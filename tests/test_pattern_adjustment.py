"""Tests for the per-clinic pattern adjustment module.

Covers the four required behaviours from the
``zorva-learning-loop`` kanban task ``t_a3f27093``:

1. ``compute_clinic_pattern_adjustments`` flags a (clinic, rule,
   signature) bucket that has enough dismissals and returns a weight
   < 1.0 for that clinic only.
2. Rules without sufficient dismissal history are returned with weight
   1.0 (i.e. they are simply absent from the weights map, which the
   auditor interprets as no change).
3. ``apply_weights`` down-weights findings whose rule is in the
   clinic's weight map; a test confirms a down-weighted rule produces
   a finding with ``pattern_weight < 1.0`` and is dropped when the
   weight falls below the floor.
4. One run without enough data does not produce phantom adjustments.

Idempotency: ``compute_clinic_pattern_adjustments`` is a pure function
over its inputs; calling it twice with the same entries yields the
same report.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import FeedbackEntry  # noqa: E402
from ai_billing_audit.pattern_adjustment import (  # noqa: E402
    PatternAdjustmentConfig,
    apply_weights,
    compute_clinic_pattern_adjustments,
)


def _dismiss(
    biller: str, rule: str, category: str = "missing-dx", severity: str = "HIGH"
) -> FeedbackEntry:
    return FeedbackEntry(
        encounter_id="enc_x",
        finding_id=f"f_{rule}",
        action="dismiss",
        rule_id=rule,
        category=category,
        severity=severity,
        biller_id=biller,
    )


def _accept(
    biller: str, rule: str, category: str = "missing-dx", severity: str = "HIGH"
) -> FeedbackEntry:
    return FeedbackEntry(
        encounter_id="enc_x",
        finding_id=f"f_{rule}",
        action="accept",
        rule_id=rule,
        category=category,
        severity=severity,
        biller_id=biller,
    )


def test_flags_over_called_pattern_with_weight_below_one() -> None:
    """6 of 7 dismissals of em_level_upcode at clinic A → weight < 1.0."""
    entries = [_dismiss("clinic_a", "rule_ahcip_em_level_upcode") for _ in range(6)]
    entries.append(_accept("clinic_a", "rule_ahcip_em_level_upcode"))
    report = compute_clinic_pattern_adjustments(entries)
    assert "clinic_a" in report.weights
    assert "rule_ahcip_em_level_upcode" in report.weights["clinic_a"]
    weight = report.weights["clinic_a"]["rule_ahcip_em_level_upcode"]
    assert 0.0 <= weight < 1.0
    # And only that clinic was adjusted.
    assert set(report.weights.keys()) == {"clinic_a"}


def test_rule_without_history_is_unchanged() -> None:
    """A rule with zero dismissals is absent from the weights map (== 1.0)."""
    entries = [_accept("clinic_a", "rule_ahcip_modifier_25") for _ in range(10)]
    report = compute_clinic_pattern_adjustments(entries)
    assert "clinic_a" not in report.weights


def test_insufficient_data_produces_no_phantom_adjustments() -> None:
    """3 dismissals (below min_occurrences=5) → no adjustment."""
    entries = [_dismiss("clinic_a", "rule_ahcip_em_level_upcode") for _ in range(3)]
    report = compute_clinic_pattern_adjustments(entries)
    assert report.weights == {}
    assert report.adjusted == []


def test_threshold_filtering_dismissal_rate_below_cutoff() -> None:
    """5 entries with 40% dismissals (below 60% threshold) → no adjustment."""
    entries = [_dismiss("clinic_a", "rule_x") for _ in range(2)] + [
        _accept("clinic_a", "rule_x") for _ in range(3)
    ]
    assert len(entries) == 5
    report = compute_clinic_pattern_adjustments(entries)
    assert report.weights == {}


def test_multiple_clinics_independent() -> None:
    """Clinic A's over-called rule does not leak into Clinic B's weights."""
    # Clinic A: 7/7 dismissals → strongly over-called.
    # Clinic B: 7/10 dismissals → mildly over-called.
    entries = [_dismiss("clinic_a", "rule_em") for _ in range(7)] + (
        [_dismiss("clinic_b", "rule_em") for _ in range(7)]
        + [_accept("clinic_b", "rule_em") for _ in range(3)]
    )
    report = compute_clinic_pattern_adjustments(entries)
    assert "rule_em" in report.weights["clinic_a"]
    assert "rule_em" in report.weights["clinic_b"]
    # Clinic A's weight is lower (100% dismissals vs. 70%).
    assert report.weights["clinic_a"]["rule_em"] < report.weights["clinic_b"]["rule_em"]


def test_apply_weights_attaches_pattern_weight_and_can_drop() -> None:
    """apply_weights annotates findings and drops those below the floor."""
    weights = {"rule_a": 0.3, "rule_b": 0.7}
    findings = [
        {"rule_id": "rule_a", "severity": "HIGH", "msg": "a"},
        {"rule_id": "rule_b", "severity": "LOW", "msg": "b"},
        {"rule_id": "rule_c", "severity": "LOW", "msg": "c"},  # unchanged
    ]
    out = apply_weights(findings, weights, min_weight_to_emit=0.0)
    assert len(out) == 3
    by_rule = {f["rule_id"]: f for f in out}
    assert by_rule["rule_a"]["pattern_weight"] == 0.3
    assert by_rule["rule_b"]["pattern_weight"] == 0.7
    assert by_rule["rule_c"]["pattern_weight"] == 1.0  # absent == 1.0

    # Floor at 0.5 → drop rule_a, keep rule_b and rule_c.
    out_strict = apply_weights(findings, weights, min_weight_to_emit=0.5)
    rules_kept = {f["rule_id"] for f in out_strict}
    assert rules_kept == {"rule_b", "rule_c"}


def test_idempotent_repeated_calls() -> None:
    """Calling the function twice with the same entries yields the same report."""
    entries = [_dismiss("clinic_a", "rule_x") for _ in range(6)]
    r1 = compute_clinic_pattern_adjustments(entries)
    r2 = compute_clinic_pattern_adjustments(entries)
    assert r1.weights == r2.weights
    assert r1.adjusted == r2.adjusted


def test_clinic_for_biller_callback_used() -> None:
    """When a clinic_for_biller callback is provided, the report groups by clinic_id."""
    entries = [_dismiss("biller_42", "rule_x") for _ in range(6)]
    # biller_42 → clinic_z (e.g. an organization that owns multiple billers).
    report = compute_clinic_pattern_adjustments(
        entries, clinic_for_biller=lambda b: {"biller_42": "clinic_z"}.get(b, b)
    )
    assert "clinic_z" in report.weights
    assert "biller_42" not in report.weights


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        PatternAdjustmentConfig(min_occurrences=0)
    with pytest.raises(ValueError):
        PatternAdjustmentConfig(min_dismissal_rate=1.5)
    with pytest.raises(ValueError):
        PatternAdjustmentConfig(min_weight=-0.1)
