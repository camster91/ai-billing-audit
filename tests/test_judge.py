"""Tests for ``ai_billing_audit.judge.FallbackGrader`` and the
``ai_billing_audit.grading.grade_with_fallback`` integration.

Coverage matrix (per the spec's acceptance criteria):

  - both trigger conditions met -> judge invoked, ``judge_used=True``
  - only one condition met (overlap in band, financial impact off;
    OR overlap off, financial impact in band) -> judge skipped,
    ``judge_used=False``, ``method="deterministic"``
  - provider-difference enforced: constructing with the same provider
    for judge and auditor raises ``SameProviderError``
  - abstain handling: judge returns blank / "?" / "I'm not sure" ->
    ``judge_used=False``, ``method="abstain_fallback"``, score is the
    deterministic overlap

In addition we cover:

  - return-shape contract: ``GradeResult(score, method, judge_used)``
  - the per-finding ``grade`` method is pure: no global env reads at
    call time (only at construction time)
  - ``grade_with_fallback`` lifts FPs to TPs only when the judge
    actually said yes (and does not regress already-matched pairs)
  - judge provider defaults are different from the auditor's
  - explicit ``judge_provider`` override is honoured
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ai_billing_audit.grading import (
    EVIDENCE_OVERLAP_THRESHOLD,
    grade_with_fallback,
    match_findings,
)
from ai_billing_audit.judge import (
    ABSTAIN_FALLBACK,
    FallbackGrader,
    GradeResult,
    JUDGE_FINANCIAL_REL_TOLERANCE,
    JUDGE_OVERLAP_LOWER,
    JUDGE_OVERLAP_UPPER,
    SameProviderError,
)
from ai_billing_audit.llm import LLMClient


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _finding(
    category: str,
    suggested_code: str,
    quote: str,
    *,
    financial_impact: float = 0.0,
    finding_id: str = "",
) -> dict[str, Any]:
    """Build a plain-dict finding. The grader accepts the
    ``clinical_evidence_quote``/``estimated_financial_impact`` names
    the data model uses."""
    return {
        "finding_id": finding_id,
        "category": category,
        "suggested_code": suggested_code,
        "clinical_evidence_quote": quote,
        "estimated_financial_impact": financial_impact,
    }


@dataclass
class TypedFinding:
    """Mirror the auditor's dataclass shape (attribute access)."""

    category: str
    suggested_code: str
    quote: str
    financial_impact: float = 0.0
    finding_id: str = ""


# Two evidence quotes that share enough tokens to land in the [0.7, 0.9]
# ambiguous band. Roughly the same length, same vocabulary, one extra
# phrase on the ground-truth side.
PRED_QUOTE = (
    "Patient reports occasional palpitations over the past two weeks. "
    "ECG performed in office shows normal sinus rhythm with isolated PACs."
)
GT_QUOTE = (
    "Patient reports occasional palpitations over the past two weeks. "
    "ECG performed in office shows normal sinus rhythm with isolated PACs; "
    "no acute ST changes."
)


# Quote pair designed to land in [0.7, 0.80] — i.e. above the lower
# band (so the judge is consulted) but BELOW the 0.80 deterministic
# matcher threshold (so the deterministic matcher rejects it as a
# paraphrase). Used by the grade_with_fallback integration tests.
PRED_QUOTE_BELOW_THRESHOLD = (
    "Patient reports occasional palpitations over the past two weeks. "
    "ECG shows normal sinus rhythm with isolated PACs."
)
# Sanity: the overlap with GT_QUOTE should land in [0.7, 0.80).


def _fake_llm(content: str) -> LLMClient:
    """Build an LLMClient whose .complete() returns a canned string.

    The shape mirrors the litellm/OpenAI response so the grader's
    ``response["choices"][0]["message"]["content"]`` extraction works.
    """

    def _complete(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {},
        }

    return LLMClient(complete=_complete)


# ---------------------------------------------------------------------------
# Return shape contract
# ---------------------------------------------------------------------------


def test_grade_returns_grade_result_dataclass() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)
    result = grader.grade(pred, gt)
    assert isinstance(result, GradeResult)
    assert hasattr(result, "score")
    assert hasattr(result, "method")
    assert hasattr(result, "judge_used")
    assert isinstance(result.score, float)
    assert 0.0 <= result.score <= 1.0
    assert result.method in {"judge", "deterministic", "abstain_fallback"}
    assert isinstance(result.judge_used, bool)


# ---------------------------------------------------------------------------
# Provider-difference enforcement
# ---------------------------------------------------------------------------


def test_same_provider_raises_same_provider_error() -> None:
    with pytest.raises(SameProviderError):
        FallbackGrader(
            llm=_fake_llm("yes"),
            auditor_provider="openai",
            judge_provider="openai",  # same as auditor
            judge_model="gpt-4o-mini",
        )


def test_default_provider_pairs_differ() -> None:
    """The default construction picks a different provider from the auditor's."""
    grader = FallbackGrader(llm=_fake_llm("yes"))
    assert grader.auditor_provider != grader.judge_provider
    assert grader.judge_model  # non-empty


def test_different_provider_constructs_ok() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="anthropic",
        judge_provider="openai",
        judge_model="gpt-4o-mini",
    )
    assert grader.auditor_provider == "anthropic"
    assert grader.judge_provider == "openai"
    assert grader.judge_model == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Both conditions met -> judge invoked
# ---------------------------------------------------------------------------


def test_both_conditions_met_invokes_judge_yes() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)

    # Sanity: the overlap on these two quotes should land in [0.7, 0.9].
    from ai_billing_audit.grading import _jaccard, _tokenize

    overlap = _jaccard(_tokenize(PRED_QUOTE), _tokenize(GT_QUOTE))
    assert JUDGE_OVERLAP_LOWER <= overlap <= JUDGE_OVERLAP_UPPER, (
        f"fixture overlap {overlap:.3f} is outside the expected band "
        f"[{JUDGE_OVERLAP_LOWER}, {JUDGE_OVERLAP_UPPER}]; pick a different quote pair"
    )

    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.method == "judge"
    assert result.score == 1.0


def test_both_conditions_met_invokes_judge_no() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("no"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.method == "judge"
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# Only one condition met -> judge skipped, deterministic score
# ---------------------------------------------------------------------------


def test_overlap_below_lower_band_skips_judge() -> None:
    """Overlap below 0.7: condition 1 fails -> judge skipped, score is
    the deterministic token-Jaccard overlap."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    short_pred = "ECG shows PACs."
    long_gt = (
        "Patient reports occasional palpitations over the past two weeks. "
        "ECG performed in office shows normal sinus rhythm with isolated "
        "PACs; no acute ST changes; heart rate 72 bpm and regular."
    )
    pred = _finding("missing_dx", "R00.2", short_pred, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", long_gt, financial_impact=100.0)

    from ai_billing_audit.grading import _jaccard, _tokenize

    overlap = _jaccard(_tokenize(short_pred), _tokenize(long_gt))
    assert overlap < JUDGE_OVERLAP_LOWER, (
        f"fixture overlap {overlap:.3f} is not below {JUDGE_OVERLAP_LOWER}; "
        f"pick a more divergent quote pair"
    )

    result = grader.grade(pred, gt)
    assert result.judge_used is False
    assert result.method == "deterministic"
    assert result.score == pytest.approx(overlap)


def test_financial_impact_off_skips_judge() -> None:
    """Overlap in band, but financial impact diverges by more than
    20 %: condition 2 fails -> judge skipped, score is the
    deterministic overlap."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=500.0)
    # 100 vs 500: relative error = 0.80, well above the 0.20 tolerance.
    result = grader.grade(pred, gt)
    assert result.judge_used is False
    assert result.method == "deterministic"
    # The deterministic score is the token-Jaccard overlap, which is
    # in the ambiguous band — between 0.7 and 0.9.
    from ai_billing_audit.grading import _jaccard, _tokenize

    expected = _jaccard(_tokenize(PRED_QUOTE), _tokenize(GT_QUOTE))
    assert result.score == pytest.approx(expected)
    assert JUDGE_OVERLAP_LOWER < result.score < JUDGE_OVERLAP_UPPER


def test_financial_impact_zero_zero_passes() -> None:
    """Both impacts zero: relative error formula collapses, treat as pass."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=0.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=0.0)
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.method == "judge"


def test_financial_impact_zero_gt_nonzero_pred_fails() -> None:
    """GT impact is 0 but predicted is non-zero: the (0,0) pass
    condition is not met, so the judge is skipped."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=50.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=0.0)
    result = grader.grade(pred, gt)
    assert result.judge_used is False
    assert result.method == "deterministic"


def test_overlap_above_upper_band_skips_judge() -> None:
    """Overlap > 0.9: condition 1 fails -> judge skipped, score is
    the (very high) deterministic overlap."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    almost_same = (
        "Patient reports occasional palpitations over the past two weeks. "
        "ECG performed in office shows normal sinus rhythm with isolated PACs"
    )
    almost_same_with_period = almost_same + "."
    pred = _finding("missing_dx", "R00.2", almost_same, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", almost_same_with_period, financial_impact=100.0)

    from ai_billing_audit.grading import _jaccard, _tokenize

    overlap = _jaccard(_tokenize(almost_same), _tokenize(almost_same_with_period))
    assert overlap > JUDGE_OVERLAP_UPPER, (
        f"fixture overlap {overlap:.3f} is not above {JUDGE_OVERLAP_UPPER}"
    )

    result = grader.grade(pred, gt)
    assert result.judge_used is False
    assert result.method == "deterministic"
    assert result.score > JUDGE_OVERLAP_UPPER


# ---------------------------------------------------------------------------
# Abstain handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["", " ", "?", "maybe", "unsure", "I'm not sure", "I cannot determine"],
    ids=["empty", "whitespace", "question_mark", "maybe", "unsure", "not_sure", "cannot_determine"],
)
def test_abstain_responses_fall_back_to_deterministic(raw: str) -> None:
    grader = FallbackGrader(
        llm=_fake_llm(raw),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)

    from ai_billing_audit.grading import _jaccard, _tokenize

    expected_overlap = _jaccard(_tokenize(PRED_QUOTE), _tokenize(GT_QUOTE))
    result = grader.grade(pred, gt)
    assert result.judge_used is False, f"raw={raw!r}: judge should abstain"
    assert result.method == ABSTAIN_FALLBACK
    assert result.score == pytest.approx(expected_overlap)


def test_llm_transport_error_treated_as_abstain() -> None:
    """If the underlying LLM client raises, the grader abstains
    (returns the deterministic score) instead of crashing. This is
    the conservative call when we don't know the judge's answer."""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated network failure")

    grader = FallbackGrader(
        llm=LLMClient(complete=_boom),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)

    from ai_billing_audit.grading import _jaccard, _tokenize

    expected_overlap = _jaccard(_tokenize(PRED_QUOTE), _tokenize(GT_QUOTE))
    result = grader.grade(pred, gt)
    assert result.judge_used is False
    assert result.method == ABSTAIN_FALLBACK
    assert result.score == pytest.approx(expected_overlap)


def test_yes_with_prose_returns_yes() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("Yes, the evidence supports the predicted impact."),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.method == "judge"
    assert result.score == 1.0


def test_no_with_prose_returns_no() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("No, the evidence does not support that claim."),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.method == "judge"
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# Input shape flexibility
# ---------------------------------------------------------------------------


def test_accepts_dataclass_inputs() -> None:
    """The grader should accept dataclass-shaped findings, not just dicts."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = TypedFinding(
        category="missing_dx",
        suggested_code="R00.2",
        quote=PRED_QUOTE,
        financial_impact=100.0,
    )
    gt = TypedFinding(
        category="missing_dx",
        suggested_code="R00.2",
        quote=GT_QUOTE,
        financial_impact=100.0,
    )
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.score == 1.0


def test_accepts_quote_field_alias() -> None:
    """The spec calls the evidence field ``evidence_quote``; the
    data model calls it ``clinical_evidence_quote``; the auditor
    dataclass calls it ``quote``. All three should work."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = {"category": "missing_dx", "suggested_code": "R00.2", "quote": PRED_QUOTE, "financial_impact": 100.0}
    gt = {"category": "missing_dx", "suggested_code": "R00.2", "quote": GT_QUOTE, "financial_impact": 100.0}
    result = grader.grade(pred, gt)
    assert result.judge_used is True
    assert result.score == 1.0


# ---------------------------------------------------------------------------
# Integration with grading.grade_with_fallback
# ---------------------------------------------------------------------------


def test_grade_with_fallback_promotes_fp_to_tp_on_yes() -> None:
    """A paraphrased predicted finding that misses the 0.80 threshold
    but lands in the [0.7, 0.9] band is rescued by a judge-yes."""
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = [_finding("missing_dx", "R00.2", PRED_QUOTE_BELOW_THRESHOLD, financial_impact=100.0)]
    gt = [_finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)]

    # Sanity: the deterministic matcher rejects this pair, and the
    # overlap on the new fixture lands in the [0.7, 0.80) band.
    from ai_billing_audit.grading import _jaccard, _tokenize

    overlap = _jaccard(_tokenize(PRED_QUOTE_BELOW_THRESHOLD), _tokenize(GT_QUOTE))
    assert JUDGE_OVERLAP_LOWER <= overlap < EVIDENCE_OVERLAP_THRESHOLD, (
        f"fixture overlap {overlap:.3f} is outside the expected band "
        f"[{JUDGE_OVERLAP_LOWER}, {EVIDENCE_OVERLAP_THRESHOLD}); pick a different quote pair"
    )
    base = match_findings(pred, gt)
    assert base.tp == 0, "deterministic matcher should reject the paraphrase"
    assert base.fp == 1

    result = grade_with_fallback(pred, gt, grader)
    assert result.tp == 1
    assert result.fp == 0
    assert result.fn == 0


def test_grade_with_fallback_leaves_alone_on_judge_no() -> None:
    """When the judge says no, the FP stays an FP."""
    grader = FallbackGrader(
        llm=_fake_llm("no"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = [_finding("missing_dx", "R00.2", PRED_QUOTE_BELOW_THRESHOLD, financial_impact=100.0)]
    gt = [_finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)]

    result = grade_with_fallback(pred, gt, grader)
    assert result.tp == 0
    assert result.fp == 1
    assert result.fn == 1


def test_grade_with_fallback_no_op_on_clean_match() -> None:
    """An already-matched pair is not re-graded."""
    grader = FallbackGrader(
        llm=_fake_llm("no"),  # judge would say no; should not be consulted
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = [_finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)]
    gt = [_finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)]

    base = match_findings(pred, gt)
    assert base.tp == 1

    result = grade_with_fallback(pred, gt, grader)
    assert result.tp == 1
    assert result.fp == 0
    assert result.fn == 0


def test_grade_with_fallback_abstain_does_not_promote() -> None:
    """If the judge abstains, the FP stays an FP (and the score is
    the deterministic overlap, but grade_with_fallback does not
    surface the per-finding score)."""
    grader = FallbackGrader(
        llm=_fake_llm("unsure"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = [_finding("missing_dx", "R00.2", PRED_QUOTE_BELOW_THRESHOLD, financial_impact=100.0)]
    gt = [_finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)]

    result = grade_with_fallback(pred, gt, grader)
    assert result.tp == 0
    assert result.fp == 1
    assert result.fn == 1


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_exposes_auditor_and_judge_providers() -> None:
    grader = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    assert grader.auditor_provider == "openai"
    assert grader.judge_provider == "anthropic"
    assert grader.judge_model == "claude-haiku-4-5"


def test_threshold_constants_match_spec() -> None:
    """The trigger thresholds are part of the spec. If we accidentally
    regress one of them, this test catches it."""
    assert JUDGE_OVERLAP_LOWER == 0.7
    assert JUDGE_OVERLAP_UPPER == 0.9
    assert JUDGE_FINANCIAL_REL_TOLERANCE == 0.20
    assert EVIDENCE_OVERLAP_THRESHOLD == 0.80


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_graders_with_same_inputs_produce_same_outputs() -> None:
    """Two graders constructed identically should agree on the
    same input. The fake LLM is deterministic, so both graders
    will get the same judge answer; the overlap is also
    deterministic."""
    a = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    b = FallbackGrader(
        llm=_fake_llm("yes"),
        auditor_provider="openai",
        judge_provider="anthropic",
        judge_model="claude-haiku-4-5",
    )
    pred = _finding("missing_dx", "R00.2", PRED_QUOTE, financial_impact=100.0)
    gt = _finding("missing_dx", "R00.2", GT_QUOTE, financial_impact=100.0)
    ra = a.grade(pred, gt)
    rb = b.grade(pred, gt)
    assert ra.score == rb.score
    assert ra.method == rb.method
    assert ra.judge_used == rb.judge_used
