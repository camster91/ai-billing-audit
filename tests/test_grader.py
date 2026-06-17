"""Unit tests for the deterministic LLM-based grader.

Covers:
  * load_grader_config validates the four required keys (model,
    temperature=0, seed=42, prompt_templates).
  * Grader construction pins the judge model/temperature/seed from the
    config and pins the LLMClient with the same model.
  * build_messages is a pure function (same input -> same output).
  * Grader.grade calls the LLM with temperature=0 and seed=42 and
    validates the response into a GraderVerdict.
  * Two Graders built from the same config and same fake LLM produce
    byte-identical verdicts on the same input.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable when pytest is run from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.grader import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    Grader,
    GraderConfigError,
    GraderVerdict,
    _resolve_prompt_path,
    build_messages,
    load_grader_config,
)
from ai_billing_audit.llm import LLMClient  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "prompts" / DEFAULT_CONFIG_NAME


class FakeLLM:
    """Deterministic fake LLMClient for testing."""

    def __init__(self, canned_response: str) -> None:
        self._canned = canned_response
        self.calls: list[tuple] = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return {
            "choices": [{"message": {"content": self._canned}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


def test_config_loads_and_validates():
    config = load_grader_config()
    judge = config["judge"]
    assert judge["model"], "judge.model must be set"
    assert float(judge["temperature"]) == 0.0
    assert int(judge["seed"]) == 42
    assert "prompt_templates" in config
    assert config["prompt_templates"], "prompt_templates must be a non-empty mapping"


def test_config_path_default_resolves():
    assert CONFIG_PATH.is_file(), f"default config not found at {CONFIG_PATH}"


def test_resolve_prompt_path_rejects_missing_file(tmp_path):
    with pytest.raises(GraderConfigError):
        _resolve_prompt_path("missing.txt", config_path=tmp_path / "cfg.json")


def test_build_messages_is_deterministic():
    prompt = "You are the grader."
    pred = {"category": "missing_dx", "suggested_code": "R00.2", "quote": "palpitations"}
    gt = {"category": "missing_dx", "suggested_code": "R00.2", "quote": "palpitations reported"}
    m1 = build_messages(pred, gt, prompt=prompt, context="enc-001")
    m2 = build_messages(pred, gt, prompt=prompt, context="enc-001")
    assert m1 == m2, "build_messages must be byte-identical for the same input"
    assert m1[0]["role"] == "system"
    assert m1[0]["content"] == prompt
    assert m1[1]["role"] == "user"
    # The user content must include both finding dicts.
    user_content = m1[1]["content"]
    assert "R00.2" in user_content
    assert "enc-001" in user_content


def test_grader_pins_model_temperature_seed():
    fake = FakeLLM(json.dumps({"verdict": "match", "score": 1.0, "rationale": "ok"}))
    grader = Grader(llm=fake)
    sample_pred = {"category": "c", "suggested_code": "X", "quote": "q"}
    sample_gt = {"category": "c", "suggested_code": "X", "quote": "q"}
    grader.grade(sample_pred, sample_gt, context="ctx")

    assert len(fake.calls) == 1
    messages, kwargs = fake.calls[0]
    assert kwargs["model"] == grader.model
    assert float(kwargs["temperature"]) == 0.0
    assert int(kwargs["seed"]) == 42
    assert "response_format" in kwargs


def test_grader_grade_returns_typed_verdict():
    fake = FakeLLM(json.dumps({"verdict": "match", "score": 0.9, "rationale": "all match"}))
    grader = Grader(llm=fake)
    v = grader.grade(
        {"category": "c", "suggested_code": "X", "quote": "q"},
        {"category": "c", "suggested_code": "X", "quote": "q"},
        context="ctx",
    )
    assert isinstance(v, GraderVerdict)
    assert v.verdict == "match"
    assert v.score == pytest.approx(0.9, rel=1e-6)
    assert v.rationale == "all match"


def test_grader_rejects_bad_verdict():
    fake = FakeLLM(json.dumps({"verdict": "maybe", "score": 0.5, "rationale": "huh"}))
    grader = Grader(llm=fake)
    with pytest.raises(GraderConfigError):
        grader.grade(
            {"category": "c", "suggested_code": "X", "quote": "q"},
            {"category": "c", "suggested_code": "X", "quote": "q"},
        )


def test_grader_rejects_out_of_range_score():
    fake = FakeLLM(json.dumps({"verdict": "match", "score": 1.5, "rationale": "huh"}))
    grader = Grader(llm=fake)
    with pytest.raises(GraderConfigError):
        grader.grade(
            {"category": "c", "suggested_code": "X", "quote": "q"},
            {"category": "c", "suggested_code": "X", "quote": "q"},
        )


def test_two_graders_produce_byte_identical_verdicts():
    canned = json.dumps({"verdict": "match", "score": 1.0, "rationale": "ok"})
    sample_pred = {"category": "missing_dx", "suggested_code": "R00.2", "quote": "palpitations"}
    sample_gt = {"category": "missing_dx", "suggested_code": "R00.2", "quote": "palpitations"}
    g1 = Grader(llm=FakeLLM(canned))
    g2 = Grader(llm=FakeLLM(canned))
    v1 = g1.grade(sample_pred, sample_gt, context="ctx")
    v2 = g2.grade(sample_pred, sample_gt, context="ctx")
    # The GraderVerdict dataclass is frozen, so direct equality holds
    # only for value equality. The byte-strict comparison is via as_dict
    # JSON serialization, which is the contract the verification script
    # also uses.
    b1 = json.dumps(v1.as_dict(), ensure_ascii=False).encode("utf-8")
    b2 = json.dumps(v2.as_dict(), ensure_ascii=False).encode("utf-8")
    assert b1 == b2
    assert v1 == v2


def test_verdict_as_dict_has_fixed_key_order():
    v = GraderVerdict(verdict="match", score=0.5, rationale="x")
    d = v.as_dict()
    assert list(d.keys()) == ["verdict", "score", "rationale"]


def test_grader_uses_default_config_path_when_none():
    """Grader() with no config_path resolves the bundled default."""
    fake = FakeLLM(json.dumps({"verdict": "match", "score": 1.0, "rationale": "ok"}))
    grader = Grader(llm=fake)
    # If the default config path is wrong or missing, the constructor
    # would have raised. The model field comes from the config.
    assert grader.model
    assert grader.seed == 42


def test_grader_constructor_seeds_python_rng():
    """random.seed(42) is called at construction."""
    import random as _random

    # Pre-seed with a different value; construction should overwrite.
    _random.seed(0)
    fake = FakeLLM(json.dumps({"verdict": "match", "score": 1.0, "rationale": "ok"}))
    Grader(llm=fake)
    # After construction, the next random.random() call should be
    # deterministic from seed=42. We can't assert the exact value
    # without coupling to Python's RNG algorithm, but we can assert
    # that running the same sequence twice gives the same numbers.
    _random.seed(42)
    expected = [_random.random() for _ in range(5)]
    # The grader seeds 42 at construction; re-seeding to 42 and pulling
    # 5 values should match a fresh seed-42 sequence. (The grader's own
    # construction call consumed some RNG, but a *fresh* Grader() in
    # the same process advances the RNG identically.)
    fake2 = FakeLLM(json.dumps({"verdict": "match", "score": 1.0, "rationale": "ok"}))
    Grader(llm=fake2)
    actual = [_random.random() for _ in range(5)]
    # The grader consumes a fixed number of random.random() calls (one
    # for the seed itself, none for actual sampling) — Python's
    # random.seed(42) does not consume RNG, so the post-construction
    # state should be identical between two Graders.
    assert expected == actual
