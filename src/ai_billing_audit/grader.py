"""Deterministic LLM-based grader.

The :class:`Grader` is the LLM-judge counterpart to the deterministic
``match_findings`` function in :mod:`ai_billing_audit.grading`. Where
``match_findings`` is a pure Python F1 scorer, :class:`Grader` invokes
an LLM to grade a (predicted, ground_truth) finding pair against a
three-rule decision (category, code, evidence overlap).

Determinism contract
--------------------
The grader is configured by ``prompts/grader_config.json``. The config
fixes:

  * the judge model identifier,
  * sampling temperature = 0 (fully deterministic greedy decoding),
  * sampling seed = 42 (provider-side RNG seeded identically),
  * the prompt template (loaded from ``prompts/grader_prompt.txt``).

With these settings, the same input ALWAYS produces the same output.
This is verified by ``scripts/verify_grader_reproducibility.py``.

Public surface
--------------
``Grader``
    The grader class. Constructed from the config file (or an explicit
    ``config_path``). The default constructor reads the bundled
    ``prompts/grader_config.json`` and resolves all paths relative to
    the package's ``prompts/`` directory.

``GraderVerdict``
    Typed result: ``verdict`` (str), ``score`` (float in [0, 1]),
    ``rationale`` (str). ``as_dict()`` returns a JSON-serialisable
    representation suitable for byte-identical comparison.

``load_grader_config(path=None) -> dict``
    Load and validate the grader config. Returns the parsed dict.

``build_messages(predicted, ground_truth, *, context=None) -> list[dict]``
    Build the OpenAI-style messages list for a single grading call. Pure
    function, no I/O beyond reading the prompt template. Deterministic.

The grader never consults the process environment at call time — model
name, temperature, seed, and prompt path are all resolved from the
config at construction time. The :class:`LLMClient` it uses for
completion still reads ``LLM_API_KEY`` etc. at HTTP-request time (the
client's own contract), but no model-selection or sampling-parameter
state is read from the environment.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ai_billing_audit.llm import LLMClient

__all__ = [
    "Grader",
    "GraderVerdict",
    "GraderConfigError",
    "load_grader_config",
    "build_messages",
    "DEFAULT_CONFIG_NAME",
]

DEFAULT_CONFIG_NAME = "grader_config.json"
DEFAULT_PROMPT_NAME = "grader_prompt.txt"

# The path the default config + prompt are resolved against. We do not
# use ``resources.files("ai_billing_audit")`` here because the grader
# config and prompt live under ``prompts/`` at the project root, not
# inside the package — they are project-level artifacts, not bundled
# package data. The default constructor walks up from this module to
# the project root and then into ``prompts/``.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "prompts" / DEFAULT_CONFIG_NAME
_DEFAULT_PROMPT_PATH = _PROJECT_ROOT / "prompts" / DEFAULT_PROMPT_NAME

# Fixed seed for the Python-side RNG. The LLM judge uses temperature=0
# and provider seed=42 (set in the config), but the Python-side random
# is also seeded here for any sampling the grader helper itself does.
PYTHON_RNG_SEED = 42

# The response schema the LLM judge must conform to. Mirrors
# ``GraderVerdict`` exactly.
_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "score", "rationale"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["match", "no_match", "partial"],
        },
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale": {"type": "string"},
    },
}


class GraderConfigError(ValueError):
    """Raised when the grader config is missing or invalid."""


@dataclass(frozen=True)
class GraderVerdict:
    """The structured result of a single :meth:`Grader.grade` call."""

    verdict: str
    score: float
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable, byte-comparable dict representation.

        The dict has a fixed key order so two ``GraderVerdict`` instances
        with the same fields serialise to byte-identical JSON. Use
        ``json.dumps(v.as_dict(), sort_keys=True)`` for the strictest
        byte-comparison; the key order in ``as_dict`` is already fixed,
        so a plain ``json.dumps(v.as_dict())`` is also deterministic.
        """
        return {
            "verdict": self.verdict,
            "score": round(float(self.score), 6),
            "rationale": self.rationale,
        }


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        return _DEFAULT_CONFIG_PATH
    p = Path(path)
    if not p.is_file():
        raise GraderConfigError(f"grader config not found at {p}")
    return p


def _resolve_prompt_path(prompt_path_str: str, *, config_path: Path) -> Path:
    """Resolve a prompt-template path from the config.

    Resolution order:
      1. Absolute path → used as-is.
      2. Path relative to the config file's directory.
      3. Path relative to the project root (where the package lives).

    The config's ``prompt_templates`` paths are written relative to the
    project root (e.g. ``prompts/grader_prompt.txt``) so they remain
    valid no matter where the config file is moved to. The
    config-relative fallback is kept for tests that drop a config in
    ``tmp_path``.
    """
    p = Path(prompt_path_str)
    if p.is_absolute():
        if not p.is_file():
            raise GraderConfigError(f"grader prompt not found at {p}")
        return p
    # Try the config's own directory first (test-friendly), then the
    # project root.
    candidates = [
        config_path.resolve().parent / p,
        _PROJECT_ROOT / p,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise GraderConfigError(
        "grader prompt not found at any of: " + ", ".join(str(c) for c in candidates)
    )


def load_grader_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and minimally validate the grader config JSON.

    Raises :class:`GraderConfigError` if the file is missing, malformed,
    or missing any of the four required keys: ``judge.model``,
    ``judge.temperature`` (= 0), ``judge.seed`` (= 42), and a prompt
    template path.
    """
    p = _resolve_config_path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise GraderConfigError(f"grader config at {p} is not valid JSON: {e}") from e

    if not isinstance(raw, Mapping):
        raise GraderConfigError(
            f"grader config at {p} must be a JSON object (got {type(raw).__name__})"
        )

    judge = raw.get("judge")
    if not isinstance(judge, Mapping):
        raise GraderConfigError(f"grader config at {p} missing 'judge' object")
    if "model" not in judge:
        raise GraderConfigError(f"grader config at {p} missing 'judge.model'")
    if "temperature" not in judge:
        raise GraderConfigError(f"grader config at {p} missing 'judge.temperature'")
    if float(judge["temperature"]) != 0.0:
        raise GraderConfigError(
            f"grader config at {p} requires judge.temperature == 0 "
            f"(got {judge['temperature']!r})"
        )
    if "seed" not in judge:
        raise GraderConfigError(f"grader config at {p} missing 'judge.seed'")
    if int(judge["seed"]) != 42:
        raise GraderConfigError(
            f"grader config at {p} requires judge.seed == 42 (got {judge['seed']!r})"
        )
    prompt_templates = raw.get("prompt_templates")
    if not isinstance(prompt_templates, Mapping) or not prompt_templates:
        raise GraderConfigError(
            f"grader config at {p} must include a non-empty 'prompt_templates' mapping"
        )
    return dict(raw)


def _render_prompt(
    prompt_template: str,
    *,
    predicted: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    context: str,
) -> str:
    """Render the user-message body for a single grading call.

    Pure function: same input -> same output. No timestamps, no thread
    identifiers, no environment values. Only the prompt template (loaded
    once at construction) and the three input fields are consulted.
    """
    pred_json = json.dumps(dict(predicted), sort_keys=True, ensure_ascii=False)
    gt_json = json.dumps(dict(ground_truth), sort_keys=True, ensure_ascii=False)
    return (
        f"{prompt_template}\n\n"
        f"---\n"
        f"PREDICTED FINDING (from the auditor):\n"
        f"{pred_json}\n\n"
        f"GROUND-TRUTH FINDING (from the rule encoder):\n"
        f"{gt_json}\n\n"
        f"CONTEXT (informational only; do not base the verdict on this):\n"
        f"{context}"
    )


def build_messages(
    predicted: Mapping[str, Any],
    ground_truth: Mapping[str, Any],
    *,
    prompt: str,
    context: str = "",
) -> list[dict[str, str]]:
    """Build the OpenAI-style messages list for a single grading call.

    The system message is the loaded grader prompt; the user message is
    the rendered finding pair + context. Pure function — same input
    produces the same output, byte for byte.
    """
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": _render_prompt(
                prompt,
                predicted=predicted,
                ground_truth=ground_truth,
                context=context,
            ),
        },
    ]


class Grader:
    """Deterministic LLM-based grader.

    Construction reads the config file and the prompt template, builds a
    fixed :class:`LLMClient` (with a ``complete=`` closure that pins
    ``model``, ``temperature``, and ``seed``), and seeds the Python
    RNG. No state is read from the environment at call time.

    Parameters
    ----------
    config_path:
        Optional path to a grader config JSON file. ``None`` loads the
        bundled default (``prompts/grader_config.json``).
    llm:
        Optional :class:`LLMClient` to use for completions. When
        ``None``, the grader builds a default client that pins
        ``model``, ``temperature``, and ``seed`` from the config. Tests
        can inject a fake.
    """

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        # Seed Python RNG once at construction. The LLM judge itself is
        # already deterministic (temperature=0, seed=42), but any
        # sampling the helper does (e.g. shuffling candidate lists) is
        # also pinned.
        random.seed(PYTHON_RNG_SEED)

        self._config_path = _resolve_config_path(config_path)
        self._config = load_grader_config(self._config_path)
        self._judge_cfg = self._config["judge"]

        # Resolve and load the prompt template once.
        templates = self._config["prompt_templates"]
        prompt_path_str = (
            templates.get("grader_prompt")
            or templates.get("system")
            or templates.get("default")
        )
        if not prompt_path_str:
            raise GraderConfigError(
                f"grader config at {self._config_path} has no usable "
                f"prompt_templates key (expected one of: grader_prompt, system, default)"
            )
        self._prompt_path = _resolve_prompt_path(
            prompt_path_str, config_path=self._config_path
        )
        self._prompt = self._prompt_path.read_text(encoding="utf-8").rstrip("\n")

        # Build the LLM client. The default-constructed client would
        # resolve the model from LLM_MODEL on every call, which would
        # make the grader's behavior dependent on a process env var. We
        # pin the model in the client constructor.
        self._judge_model = str(self._judge_cfg["model"])
        self._judge_temperature = float(self._judge_cfg["temperature"])
        self._judge_seed = int(self._judge_cfg["seed"])
        self._judge_max_tokens = int(self._judge_cfg.get("max_tokens", 1024))
        self._llm = llm if llm is not None else LLMClient(model=self._judge_model)

    @property
    def config(self) -> dict[str, Any]:
        """The loaded config dict (read-only view)."""
        return self._config

    @property
    def prompt(self) -> str:
        """The loaded prompt template (read-only view)."""
        return self._prompt

    @property
    def model(self) -> str:
        """The judge model identifier (from the config)."""
        return self._judge_model

    @property
    def seed(self) -> int:
        """The judge seed (from the config)."""
        return self._judge_seed

    def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Dispatch a single grading call to the LLM client.

        Pins model, temperature, and seed from the config. The response
        is parsed as JSON and validated against ``_VERDICT_SCHEMA``.
        """
        response = self._llm.complete(
            messages,
            model=self._judge_model,
            temperature=self._judge_temperature,
            seed=self._judge_seed,
            max_tokens=self._judge_max_tokens,
            response_format=_VERDICT_SCHEMA,
        )
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)

    @staticmethod
    def _validate_payload(payload: Any) -> GraderVerdict:
        if not isinstance(payload, Mapping):
            raise GraderConfigError(
                f"grader response is not a JSON object (got {type(payload).__name__})"
            )
        verdict = payload.get("verdict")
        if verdict not in ("match", "no_match", "partial"):
            raise GraderConfigError(f"grader response has invalid verdict {verdict!r}")
        score = payload.get("score")
        if not isinstance(score, (int, float)):
            raise GraderConfigError(f"grader response has non-numeric score {score!r}")
        score = float(score)
        if not (0.0 <= score <= 1.0):
            raise GraderConfigError(f"grader response score {score} is out of [0, 1]")
        rationale = payload.get("rationale")
        if not isinstance(rationale, str):
            raise GraderConfigError(
                f"grader response has non-string rationale {rationale!r}"
            )
        return GraderVerdict(verdict=verdict, score=score, rationale=rationale)

    def grade(
        self,
        predicted: Mapping[str, Any],
        ground_truth: Mapping[str, Any],
        *,
        context: str = "",
    ) -> GraderVerdict:
        """Grade a single (predicted, ground_truth) finding pair.

        Returns a :class:`GraderVerdict`. The call is fully deterministic:
        the same (predicted, ground_truth, context) tuple always returns
        the same :class:`GraderVerdict`, byte for byte.
        """
        messages = build_messages(
            predicted,
            ground_truth,
            prompt=self._prompt,
            context=context,
        )
        payload = self._call_llm(messages)
        return self._validate_payload(payload)
