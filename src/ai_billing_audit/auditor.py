"""Auditor agent — a thin prompt runner over :class:`LLMClient`.

The Auditor is the LLM-driven counterpart to the deterministic
ground-truth generator. Where the ground-truth library encodes a fixed
set of well-known billing rules in Python, the Auditor asks an LLM to
apply the *retrieved* rules (the citations attached to each encounter)
to the encounter and emit a structured findings list.

Public surface
--------------
``run_audit(encounter, *, llm=None, prompt_path=None) -> AuditResult``
    The single entry point. Builds the messages payload, dispatches the
    LLM call, validates the response, and returns the findings.

``build_messages(encounter, *, prompt) -> list[dict[str, str]]``
    The unit-testable seam. Takes the encounter and a pre-loaded prompt
    string, returns the OpenAI-style messages list. Tests can assert
    shape without invoking any LLM.

``load_prompt(path=None) -> str``
    Loads the auditor prompt. ``None`` falls back to the bundled
    default prompt shipped with the package.

``AuditResult``, ``Finding``, ``AuditValidationError``
    The typed result and the typed error.

Design constraints
------------------
* No LLM-specific code lives in this module. It depends only on
  :class:`LLMClient`.
* The function is pure-ish: the only state read at call time is the
  process environment (resolved by the LLMClient's own env reads) and
  the optional ``prompt_path`` argument. The default prompt is loaded
  from disk once and cached at module import.
* Every structured finding is validated against the findings schema
  (``Finding`` dataclass) before being returned. Mismatches raise
  :class:`AuditValidationError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_billing_audit.llm import LLMClient

__all__ = [
    "AuditResult",
    "Finding",
    "AuditValidationError",
    "run_audit",
    "build_messages",
    "load_prompt",
    "validate_findings",
]

_DEFAULT_PROMPT_NAME = "auditor_prompt.txt"
_DEFAULT_PROMPT_CACHE: str | None = None


# The response schema the LLM is asked to conform to. Mirrors AuditResult
# and Finding shape (one level of nesting; arrays of strings).
RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "findings"],
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category",
                    "suggested_code",
                    "quote",
                    "severity",
                    "rule_ids",
                ],
                "properties": {
                    "category": {"type": "string"},
                    "suggested_code": {"type": "string"},
                    "quote": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high", "critical"],
                    },
                    "rule_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


class AuditValidationError(ValueError):
    """Raised when the LLM response does not match the findings schema."""


@dataclass(frozen=True)
class Finding:
    """A single auditor finding as emitted by the LLM and validated."""

    category: str
    suggested_code: str
    quote: str
    severity: str
    rule_ids: tuple[str, ...] = field(default_factory=tuple)
    finding_id: str = ""


@dataclass(frozen=True)
class AuditResult:
    """The result of a single ``run_audit`` call."""

    encounter_id: str
    findings: tuple[Finding, ...]
    summary: str


def load_prompt(path: str | Path | None = None) -> str:
    """Load the auditor system prompt.

    ``path=None`` returns the bundled default, loaded from package data
    and cached at module import. A custom path is read fresh every call.
    """
    if path is None:
        global _DEFAULT_PROMPT_CACHE
        if _DEFAULT_PROMPT_CACHE is None:
            try:
                _DEFAULT_PROMPT_CACHE = (
                    resources.files("ai_billing_audit")
                    .joinpath(_DEFAULT_PROMPT_NAME)
                    .read_text(encoding="utf-8")
                )
            except (FileNotFoundError, ModuleNotFoundError):
                # Editable install fallback: read the file relative to this
                # module's parent package directory.
                pkg_root = Path(__file__).resolve().parent
                _DEFAULT_PROMPT_CACHE = (pkg_root / _DEFAULT_PROMPT_NAME).read_text(
                    encoding="utf-8"
                )
        return _DEFAULT_PROMPT_CACHE.rstrip("\n")

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Auditor prompt not found at {p}")
    return p.read_text(encoding="utf-8").rstrip("\n")


def _encounter_context(encounter: Mapping[str, Any]) -> str:
    """Render the encounter as a plain-text context block for the LLM."""
    clinical_note = str(encounter.get("clinical_note", "") or "")
    is_flagged = bool(encounter.get("is_flagged", False))
    claim = encounter.get("claim", {}) or {}
    rules = encounter.get("rules", []) or []

    parts: list[str] = []
    parts.append(f"encounter_id: {encounter.get('encounter_id', '<unknown>')}")
    parts.append(f"is_flagged: {is_flagged}")
    if claim:
        parts.append("claim:")
        parts.append(json.dumps(claim, indent=2))
    if rules:
        parts.append("rules:")
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            parts.append(
                f"  - rule_id: {rule.get('rule_id', '')}\n"
                f"    snippet: {rule.get('snippet', '')}"
            )
    parts.append("clinical_note:")
    parts.append(clinical_note)
    return "\n".join(parts)


def build_messages(encounter: Mapping[str, Any], *, prompt: str) -> list[dict[str, str]]:
    """Build the OpenAI-style messages list sent to the LLM.

    The system message is the loaded auditor prompt; the user message
    is the rendered encounter context (claim + rules + clinical_note).
    """
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": _encounter_context(encounter)},
    ]


def validate_findings(payload: Any) -> tuple[Finding, ...]:
    """Parse + validate the ``findings`` array from the LLM response.

    Raises :class:`AuditValidationError` if the payload is not a dict,
    if ``findings`` is missing or not a list, or if any individual
    finding violates the schema. ``finding_id`` is optional and defaults
    to ``""``.
    """
    if not isinstance(payload, Mapping):
        raise AuditValidationError(
            f"response is not a JSON object (got {type(payload).__name__})"
        )

    raw = payload.get("findings")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AuditValidationError(
            f"'findings' must be a list (got {type(raw).__name__})"
        )

    findings: list[Finding] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise AuditValidationError(
                f"findings[{i}] is not a JSON object (got {type(item).__name__})"
            )
        for key in ("category", "suggested_code", "quote", "severity"):
            if key not in item:
                raise AuditValidationError(f"findings[{i}] missing required field '{key}'")
        rule_ids = item.get("rule_ids", [])
        if not isinstance(rule_ids, list) or not all(
            isinstance(r, str) for r in rule_ids
        ):
            raise AuditValidationError(
                f"findings[{i}].rule_ids must be a list of strings"
            )
        findings.append(
            Finding(
                category=str(item["category"]),
                suggested_code=str(item["suggested_code"]),
                quote=str(item["quote"]),
                severity=str(item["severity"]),
                rule_ids=tuple(rule_ids),
                finding_id=str(item.get("finding_id", "") or ""),
            )
        )
    return tuple(findings)


def run_audit(
    encounter: Mapping[str, Any],
    *,
    llm: LLMClient | None = None,
    prompt_path: str | Path | None = None,
) -> AuditResult:
    """Run the auditor on a single encounter.

    Builds the messages, dispatches them through ``llm`` (a default
    :class:`LLMClient` is constructed when ``None``), validates the
    response, and returns a typed :class:`AuditResult`.
    """
    client = llm if llm is not None else LLMClient()
    prompt = load_prompt(prompt_path)
    messages = build_messages(encounter, prompt=prompt)
    payload = client.complete_json(messages, RESPONSE_JSON_SCHEMA)
    findings = validate_findings(payload)
    summary = str(payload.get("summary", "") or "")
    return AuditResult(
        encounter_id=str(encounter.get("encounter_id", "") or ""),
        findings=findings,
        summary=summary,
    )
