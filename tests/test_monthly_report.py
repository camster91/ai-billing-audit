"""Tests for ``ai_billing_audit.monthly_report.compute_clinic_month`` (t_ca36e05d).

The function returns either:

  * an ``insufficient_data`` stub when the clinic has fewer than
    :data:`INSUFFICIENT_DATA_THRESHOLD` distinct calendar months of
    feedback in the store, or
  * the full struct described in the task body
    (``total_findings`` / ``accepted`` / ``dismissed`` / ``modified``
    / ``top_3_modified_rules`` / ``confidence_calibration`` /
    ``tuning_recommendations``).

These tests use a real ``FeedbackStore`` (tmp_path JSONL) rather than
mocking so they exercise the actual append / read chain. No LLM, no
network.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import FeedbackEntry, FeedbackStore  # noqa: E402
from ai_billing_audit.monthly_report import (  # noqa: E402
    INSUFFICIENT_DATA_THRESHOLD,
    RECOMMEND_MAINTAIN,
    RECOMMEND_RAISE_CONFIDENCE,
    RECOMMEND_REVIEW_MODIFIED,
    calibrate_confidence,
    compute_clinic_month,
    tuning_recommendation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _append_entry(
    store: FeedbackStore,
    *,
    biller_id: str,
    action: str,
    rule_id: str,
    finding_id: str,
    when: datetime,
) -> FeedbackEntry:
    """Append one FeedbackEntry signed into the chain."""
    return store.append(FeedbackEntry(
        encounter_id=f"enc-{finding_id}",
        finding_id=finding_id,
        action=action,  # type: ignore[arg-type]
        severity="medium",
        rule_id=rule_id,
        category="modifier_required",
        timestamp=_iso(when.timestamp()),
        biller_id=biller_id,
    ))


# ---------------------------------------------------------------------------
# insufficient_data branch
# ---------------------------------------------------------------------------


def test_compute_clinic_month_returns_insufficient_data_on_empty_store(
    tmp_path: Path,
) -> None:
    """A clinic with zero feedback → insufficient_data stub, no fabricated numbers.

    Pins the exact stub shape the task spec calls out: status,
    clinic_id, year, month, month_label, required_months,
    current_months.
    """
    store = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    out = compute_clinic_month("clinic-A", 2026, 6, store=store)
    assert out["status"] == "insufficient_data"
    assert out["clinic_id"] == "clinic-A"
    assert out["year"] == 2026
    assert out["month"] == 6
    assert out["month_label"] == "2026-06"
    assert out["required_months"] == INSUFFICIENT_DATA_THRESHOLD
    assert out["current_months"] == 0
    # Insufficient-data stub must NOT carry fabricated numbers.
    for forbidden_key in (
        "total_findings", "accepted", "dismissed", "modified",
        "top_3_modified_rules", "confidence_calibration",
        "tuning_recommendations",
    ):
        assert forbidden_key not in out, (
            f"insufficient_data stub must not include {forbidden_key!r}, "
            f"got keys: {sorted(out.keys())}"
        )


def test_compute_clinic_month_insufficient_with_some_feedback(
    tmp_path: Path,
) -> None:
    """Two months of feedback is still below the 3-month threshold.

    ``current_months`` must reflect the actual count (not always 0),
    and the function must not fabricate numbers for the requested
    month.
    """
    store = FeedbackStore(log_path=tmp_path / "partial.jsonl")
    base = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _append_entry(
        store, biller_id="clinic-PARTIAL",
        action="accept", rule_id="R-MOD-25", finding_id="f-1",
        when=base,
    )
    _append_entry(
        store, biller_id="clinic-PARTIAL",
        action="dismiss", rule_id="R-MOD-25", finding_id="f-2",
        when=base - timedelta(days=30),
    )
    out = compute_clinic_month("clinic-PARTIAL", 2026, 6, store=store)
    assert out["status"] == "insufficient_data"
    assert out["current_months"] == 2
    assert "total_findings" not in out


def test_compute_clinic_month_insufficient_data_ignores_other_clinics(
    tmp_path: Path,
) -> None:
    """Feedback for OTHER clinics must not bump the queried clinic's count."""
    store = FeedbackStore(log_path=tmp_path / "other.jsonl")
    base = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    for m_ago in range(1, 5):
        when = base - timedelta(days=30 * m_ago)
        _append_entry(
            store, biller_id="clinic-OTHER",
            action="accept", rule_id="R-MOD-25",
            finding_id=f"other-{m_ago}", when=when,
        )
    out = compute_clinic_month("clinic-QUERY", 2026, 6, store=store)
    assert out["status"] == "insufficient_data"
    assert out["current_months"] == 0


# ---------------------------------------------------------------------------
# Happy path — full struct
# ---------------------------------------------------------------------------


def _seed_three_months_of_feedback(
    store: FeedbackStore,
    *,
    biller_id: str,
    when: datetime,
) -> None:
    """Seed the store with 3 distinct months of feedback for ``biller_id``.

    The current month gets 1 accept + 1 dismiss + 2 modify events
    (on rules R-MOD-25 and R-DX-91). The two prior months each get
    1 accept so the gate passes (>=3 distinct months).
    """
    # Month -2: 1 accept
    _append_entry(
        store, biller_id=biller_id,
        action="accept", rule_id="R-MOD-25", finding_id="f-pre2",
        when=when - timedelta(days=60),
    )
    # Month -1: 1 accept
    _append_entry(
        store, biller_id=biller_id,
        action="accept", rule_id="R-MOD-25", finding_id="f-pre1",
        when=when - timedelta(days=30),
    )
    # Current month (the requested month): 1 accept + 1 dismiss + 2 modify.
    _append_entry(
        store, biller_id=biller_id,
        action="accept", rule_id="R-MOD-25", finding_id="f-acc-1",
        when=when,
    )
    _append_entry(
        store, biller_id=biller_id,
        action="dismiss", rule_id="R-DX-91", finding_id="f-dis-1",
        when=when,
    )
    _append_entry(
        store, biller_id=biller_id,
        action="modify", rule_id="R-MOD-25", finding_id="f-mod-1",
        when=when,
    )
    _append_entry(
        store, biller_id=biller_id,
        action="modify", rule_id="R-DX-91", finding_id="f-mod-2",
        when=when,
    )


def test_compute_clinic_month_full_struct_shape(
    tmp_path: Path,
) -> None:
    """Happy path: full struct contains every key the task spec calls out.

    Pins exact keys: status, clinic_id, year, month, month_label,
    total_findings, accepted, dismissed, modified,
    top_3_modified_rules, confidence_calibration,
    tuning_recommendations.
    """
    store = FeedbackStore(log_path=tmp_path / "full.jsonl")
    when = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _seed_three_months_of_feedback(store, biller_id="clinic-FULL", when=when)

    out = compute_clinic_month("clinic-FULL", 2026, 6, store=store)

    assert out["status"] == "ok"
    assert out["clinic_id"] == "clinic-FULL"
    assert out["year"] == 2026
    assert out["month"] == 6
    assert out["month_label"] == "2026-06"
    # Action counts for the requested month (June 2026):
    # 1 accept, 1 dismiss, 2 modify → total_findings = 4.
    assert out["accepted"] == 1
    assert out["dismissed"] == 1
    assert out["modified"] == 2
    assert out["total_findings"] == 4
    assert isinstance(out["top_3_modified_rules"], list)
    assert isinstance(out["confidence_calibration"], str)
    assert out["confidence_calibration"] in {"HIGH", "MEDIUM", "LOW"}
    assert isinstance(out["tuning_recommendations"], list)
    assert len(out["tuning_recommendations"]) >= 1
    assert all(isinstance(s, str) for s in out["tuning_recommendations"])


def test_compute_clinic_month_top_modified_rules_ordering(
    tmp_path: Path,
) -> None:
    """top_3_modified_rules: descending by count, ties broken by rule_name asc.

    Seed three modify events on R-MOD-25 and one on R-DX-91, so the
    expected order is R-MOD-25 first (count=3), R-DX-91 second (count=1).
    Add a tie-break case: a second rule with count=1 named earlier
    alphabetically, then ensure it still sorts to position 2.
    """
    store = FeedbackStore(log_path=tmp_path / "top.jsonl")
    base = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    # Gate-passing baseline: 2 prior months with 1 accept each.
    _append_entry(
        store, biller_id="clinic-TOP",
        action="accept", rule_id="R-MOD-25", finding_id="g-pre2",
        when=base - timedelta(days=60),
    )
    _append_entry(
        store, biller_id="clinic-TOP",
        action="accept", rule_id="R-MOD-25", finding_id="g-pre1",
        when=base - timedelta(days=30),
    )
    # Current month: 3 modify on R-MOD-25, 1 modify on R-DX-91.
    for i in range(3):
        _append_entry(
            store, biller_id="clinic-TOP",
            action="modify", rule_id="R-MOD-25",
            finding_id=f"g-mod-{i}", when=base,
        )
    _append_entry(
        store, biller_id="clinic-TOP",
        action="modify", rule_id="R-DX-91",
        finding_id="g-mod-dx", when=base,
    )

    out = compute_clinic_month("clinic-TOP", 2026, 6, store=store)
    assert out["status"] == "ok"
    assert out["modified"] == 4
    top = out["top_3_modified_rules"]
    assert top[0] == {"rule_name": "R-MOD-25", "count": 3}
    # The single-count rule sorts by name ascending (only one entry
    # here, so just check the count).
    assert top[1] == {"rule_name": "R-DX-91", "count": 1}
    assert len(top) == 2


def test_compute_clinic_month_top_modified_rules_capped_at_three(
    tmp_path: Path,
) -> None:
    """When more than 3 rules are modified, the list is truncated to 3."""
    store = FeedbackStore(log_path=tmp_path / "cap.jsonl")
    base = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _append_entry(
        store, biller_id="clinic-CAP",
        action="accept", rule_id="R-MOD-25", finding_id="c-pre2",
        when=base - timedelta(days=60),
    )
    _append_entry(
        store, biller_id="clinic-CAP",
        action="accept", rule_id="R-MOD-25", finding_id="c-pre1",
        when=base - timedelta(days=30),
    )
    # 5 different rules, 1 modify each → top-3 should keep the first 3
    # alphabetically by tie-break.
    for rule in ["R-A", "R-B", "R-C", "R-D", "R-E"]:
        _append_entry(
            store, biller_id="clinic-CAP",
            action="modify", rule_id=rule,
            finding_id=f"c-{rule}", when=base,
        )

    out = compute_clinic_month("clinic-CAP", 2026, 6, store=store)
    assert out["status"] == "ok"
    top = out["top_3_modified_rules"]
    assert len(top) == 3
    # All have count=1; tie-break is rule_name ascending.
    assert [r["rule_name"] for r in top] == ["R-A", "R-B", "R-C"]


def test_compute_clinic_month_recommendations_non_empty_even_when_thin(
    tmp_path: Path,
) -> None:
    """tuning_recommendations must contain >=1 string even on thin data.

    Seeds exactly 3 months of feedback (the gate-passing minimum)
    with 1 accept per month and no modify events — i.e. the
    "boring" case. The function should still return at least one
    recommendation (the empty-data fallback).
    """
    store = FeedbackStore(log_path=tmp_path / "thin.jsonl")
    base = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    for m_ago in range(1, 4):
        _append_entry(
            store, biller_id="clinic-THIN",
            action="accept", rule_id="R-MOD-25",
            finding_id=f"t-{m_ago}",
            when=base - timedelta(days=30 * m_ago),
        )

    out = compute_clinic_month("clinic-THIN", 2026, 6, store=store)
    assert out["status"] == "ok"
    recs = out["tuning_recommendations"]
    assert isinstance(recs, list)
    assert len(recs) >= 1
    assert all(isinstance(s, str) and s for s in recs)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_month", [0, 13, -1, 99])
def test_compute_clinic_month_raises_for_invalid_month(
    tmp_path: Path, bad_month: int,
) -> None:
    """Out-of-range month values raise ValueError instead of silently wrapping."""
    store = FeedbackStore(log_path=tmp_path / "validate.jsonl")
    with pytest.raises(ValueError, match="month must be in 1..12"):
        compute_clinic_month("clinic-V", 2026, bad_month, store=store)


def test_compute_clinic_month_is_importable_from_module() -> None:
    """Acceptance: function is importable from the public module surface."""
    import ai_billing_audit.monthly_report as mr
    assert callable(mr.compute_clinic_month)
    assert mr.compute_clinic_month.__name__ == "compute_clinic_month"


# ---------------------------------------------------------------------------
# calibrate_confidence + tuning_recommendation (kanban t_cb95d540)
# ---------------------------------------------------------------------------
#
# The spec pins the calibration bands on (acceptance_rate,
# modification_rate) directly, so we test the pure functions on
# fixture rate pairs rather than going through the full
# ``compute_clinic_month`` plumbing. The integration test at the
# bottom of this section confirms the wiring.


def test_calibrate_confidence_high_band_clear_case() -> None:
    """Acceptance 0.9 + modification 0.05 → HIGH (well inside the band)."""
    assert calibrate_confidence(acceptance_rate=0.9, modification_rate=0.05) == "HIGH"


def test_calibrate_confidence_high_band_at_boundary() -> None:
    """Acceptance == 0.8 AND modification == 0.1 → HIGH (boundary inclusive)."""
    # Spec wording: HIGH if acceptance_rate >= 0.8 AND modification_rate <= 0.1
    assert calibrate_confidence(acceptance_rate=0.8, modification_rate=0.1) == "HIGH"


def test_calibrate_confidence_high_band_demoted_by_modification() -> None:
    """Acceptance high but modification > 0.1 → not HIGH.

    Pins that the modification_rate branch is AND-joined with the
    acceptance branch — we don't return HIGH just because acceptance
    is great while billers are still rewriting findings.
    """
    assert calibrate_confidence(acceptance_rate=0.95, modification_rate=0.11) != "HIGH"


def test_calibrate_confidence_low_band_low_acceptance() -> None:
    """Acceptance < 0.5 → LOW regardless of modification rate."""
    assert calibrate_confidence(acceptance_rate=0.4, modification_rate=0.0) == "LOW"
    assert calibrate_confidence(acceptance_rate=0.0, modification_rate=0.0) == "LOW"
    # Acceptance just below the threshold should also be LOW.
    assert calibrate_confidence(acceptance_rate=0.499, modification_rate=0.0) == "LOW"


def test_calibrate_confidence_low_band_high_modification() -> None:
    """Modification > 0.3 → LOW regardless of acceptance rate."""
    assert calibrate_confidence(acceptance_rate=1.0, modification_rate=0.31) == "LOW"
    assert calibrate_confidence(acceptance_rate=0.9, modification_rate=0.5) == "LOW"


def test_calibrate_confidence_low_band_boundary_acceptance_is_not_low() -> None:
    """Acceptance exactly == 0.5 with low modification → not LOW.

    Pins that the LOW rule is strict-less-than (acceptance_rate < 0.5).
    """
    assert calibrate_confidence(acceptance_rate=0.5, modification_rate=0.05) != "LOW"


def test_calibrate_confidence_low_band_boundary_modification_is_not_low() -> None:
    """Modification exactly == 0.3 with high acceptance → not LOW.

    Pins that the LOW rule is strict-greater-than (modification_rate > 0.3).
    """
    assert calibrate_confidence(acceptance_rate=0.95, modification_rate=0.3) != "LOW"


def test_calibrate_confidence_medium_band_between_bands() -> None:
    """All non-HIGH, non-LOW cases → MEDIUM.

    Spec: MEDIUM otherwise. These fixtures sit strictly between the
    HIGH and LOW bands (acceptance in [0.5, 0.8) and modification in
    (0.1, 0.3]).
    """
    assert calibrate_confidence(acceptance_rate=0.7, modification_rate=0.15) == "MEDIUM"
    assert calibrate_confidence(acceptance_rate=0.6, modification_rate=0.2) == "MEDIUM"
    assert calibrate_confidence(acceptance_rate=0.5, modification_rate=0.15) == "MEDIUM"


def test_calibrate_confidence_defensive_invalid_rates_return_low() -> None:
    """Out-of-range rates fall back to LOW so the route never 500s."""
    assert calibrate_confidence(acceptance_rate=-0.1, modification_rate=0.0) == "LOW"
    assert calibrate_confidence(acceptance_rate=0.5, modification_rate=1.5) == "LOW"
    assert calibrate_confidence(acceptance_rate=2.0, modification_rate=-0.3) == "LOW"


def test_tuning_recommendation_branch_review_modified_rules() -> None:
    """modification_rate > 0.2 fires the review-modified branch.

    Uses acceptance_rate in the safe middle (0.7) so the
    raise-confidence branch does NOT also fire — this isolates the
    review-modified branch.
    """
    recs = tuning_recommendation(acceptance_rate=0.7, modification_rate=0.25)
    assert RECOMMEND_REVIEW_MODIFIED in recs
    assert RECOMMEND_RAISE_CONFIDENCE not in recs
    assert RECOMMEND_MAINTAIN not in recs


def test_tuning_recommendation_branch_raise_confidence() -> None:
    """acceptance_rate < 0.5 fires the raise-confidence branch.

    Uses modification_rate in the safe middle (0.1) so the
    review-modified branch does NOT also fire — this isolates the
    raise-confidence branch.
    """
    recs = tuning_recommendation(acceptance_rate=0.3, modification_rate=0.1)
    assert RECOMMEND_RAISE_CONFIDENCE in recs
    assert RECOMMEND_REVIEW_MODIFIED not in recs
    assert RECOMMEND_MAINTAIN not in recs


def test_tuning_recommendation_branch_maintain_default() -> None:
    """Neither branch fires → 'maintain current thresholds'.

    Both rates in their safe middle: acceptance in [0.5, 1.0) and
    modification in (0.0, 0.2]. Falls back to the default string.
    """
    recs = tuning_recommendation(acceptance_rate=0.7, modification_rate=0.1)
    assert recs == [RECOMMEND_MAINTAIN]


def test_tuning_recommendation_both_branches_can_fire_together() -> None:
    """Both conditions can hold in the same month → both strings returned.

    acceptance=0.4 (< 0.5) AND modification=0.25 (> 0.2). The
    function should return BOTH recommendations, with maintain
    absent. Order: review-modified first (the modification-rate
    branch is checked first in the function).
    """
    recs = tuning_recommendation(acceptance_rate=0.4, modification_rate=0.25)
    assert RECOMMEND_REVIEW_MODIFIED in recs
    assert RECOMMEND_RAISE_CONFIDENCE in recs
    assert RECOMMEND_MAINTAIN not in recs
    # 'maintain' is a fallback, not an additional entry.
    assert len(recs) == 2


def test_tuning_recommendation_boundary_modification_does_not_fire() -> None:
    """modification_rate == 0.2 does NOT fire review-modified.

    Pins that the rule is strict greater-than (modification_rate > 0.2).
    """
    recs = tuning_recommendation(acceptance_rate=0.7, modification_rate=0.2)
    assert RECOMMEND_REVIEW_MODIFIED not in recs


def test_tuning_recommendation_boundary_acceptance_does_not_fire() -> None:
    """acceptance_rate == 0.5 does NOT fire raise-confidence.

    Pins that the rule is strict less-than (acceptance_rate < 0.5).
    """
    recs = tuning_recommendation(acceptance_rate=0.5, modification_rate=0.1)
    assert RECOMMEND_RAISE_CONFIDENCE not in recs


def test_tuning_recommendation_invalid_rates_fall_back_to_maintain() -> None:
    """Out-of-range rates → single 'maintain' recommendation."""
    recs = tuning_recommendation(acceptance_rate=-0.1, modification_rate=0.1)
    assert recs == [RECOMMEND_MAINTAIN]
    recs = tuning_recommendation(acceptance_rate=0.7, modification_rate=1.5)
    assert recs == [RECOMMEND_MAINTAIN]


# ---------------------------------------------------------------------------
# End-to-end integration: compute_clinic_month wires the new helpers
# ---------------------------------------------------------------------------


def _seed_month_with_action_counts(
    store: FeedbackStore,
    *,
    biller_id: str,
    when: datetime,
    accepted: int,
    dismissed: int,
    modified: int,
) -> None:
    """Seed the store with 3 distinct months of feedback, then in the
    requested month (``when``) write exactly ``accepted`` accepts,
    ``dismissed`` dismisses, and ``modified`` modifies. Two prior
    months get 1 accept each so the insufficient-data gate passes.
    """
    # Gate-passing baseline: 2 prior months, 1 accept each.
    _append_entry(
        store, biller_id=biller_id,
        action="accept", rule_id="R-MOD-25", finding_id="pre2",
        when=when - timedelta(days=60),
    )
    _append_entry(
        store, biller_id=biller_id,
        action="accept", rule_id="R-MOD-25", finding_id="pre1",
        when=when - timedelta(days=30),
    )
    # Current month: exactly the requested counts.
    counter = 0
    for _ in range(accepted):
        _append_entry(
            store, biller_id=biller_id,
            action="accept", rule_id="R-MOD-25",
            finding_id=f"a-{counter}", when=when,
        )
        counter += 1
    for _ in range(dismissed):
        _append_entry(
            store, biller_id=biller_id,
            action="dismiss", rule_id="R-MOD-25",
            finding_id=f"d-{counter}", when=when,
        )
        counter += 1
    for _ in range(modified):
        _append_entry(
            store, biller_id=biller_id,
            action="modify", rule_id="R-MOD-25",
            finding_id=f"m-{counter}", when=when,
        )
        counter += 1


def test_compute_clinic_month_uses_new_calibration_high(
    tmp_path: Path,
) -> None:
    """End-to-end: HIGH band when acceptance=0.9 and modification=0.0.

    Seed: 10 accepted, 0 dismissed, 0 modified → acceptance_rate=1.0
    but we want the band not HIGH because of the modification
    being 0. So instead seed 9 accept / 1 modify → acceptance=0.9,
    modification=0.1 → exactly on the HIGH boundary.
    """
    store = FeedbackStore(log_path=tmp_path / "high.jsonl")
    when = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _seed_month_with_action_counts(
        store, biller_id="clinic-HIGH", when=when,
        accepted=9, dismissed=0, modified=1,
    )

    out = compute_clinic_month("clinic-HIGH", 2026, 6, store=store)
    assert out["status"] == "ok"
    assert out["confidence_calibration"] == "HIGH"
    # 1 modified out of 10 → modification_rate = 0.1 → review-modified
    # branch (strict > 0.2) does NOT fire. acceptance=0.9 → not LOW.
    # So the only recommendation is "maintain".
    assert out["tuning_recommendations"] == [RECOMMEND_MAINTAIN]


def test_compute_clinic_month_uses_new_calibration_low(
    tmp_path: Path,
) -> None:
    """End-to-end: LOW band when acceptance=0.3 and modification=0.6.

    Seed: 3 accept / 1 dismiss / 6 modify → total=10,
    acceptance=0.3 (< 0.5 → LOW-eligible), modification=0.6
    (> 0.3 → LOW-eligible). Both LOW triggers fire.
    """
    store = FeedbackStore(log_path=tmp_path / "low.jsonl")
    when = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _seed_month_with_action_counts(
        store, biller_id="clinic-LOW", when=when,
        accepted=3, dismissed=1, modified=6,
    )

    out = compute_clinic_month("clinic-LOW", 2026, 6, store=store)
    assert out["status"] == "ok"
    assert out["confidence_calibration"] == "LOW"
    recs = out["tuning_recommendations"]
    # acceptance=0.3 fires raise-confidence, modification=0.6 fires
    # review-modified. maintain must NOT appear.
    assert RECOMMEND_REVIEW_MODIFIED in recs
    assert RECOMMEND_RAISE_CONFIDENCE in recs
    assert RECOMMEND_MAINTAIN not in recs


def test_compute_clinic_month_uses_new_calibration_medium(
    tmp_path: Path,
) -> None:
    """End-to-end: MEDIUM band when acceptance=0.7 and modification=0.15.

    Seed: 7 accept / 2 dismiss / 1 modify → total=10,
    acceptance=0.7 (in [0.5, 0.8)), modification=0.1
    (in (0.0, 0.2]) → MEDIUM. The maintenance fallback is the only
    recommendation.
    """
    store = FeedbackStore(log_path=tmp_path / "medium.jsonl")
    when = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    _seed_month_with_action_counts(
        store, biller_id="clinic-MED", when=when,
        accepted=7, dismissed=2, modified=1,
    )

    out = compute_clinic_month("clinic-MED", 2026, 6, store=store)
    assert out["status"] == "ok"
    assert out["confidence_calibration"] == "MEDIUM"
    assert out["tuning_recommendations"] == [RECOMMEND_MAINTAIN]