"""Tests for the clean-rate metrics on the home page.

The clean-rate hero leads with positive signal ("94% of claims clean,
$73k confirmed this month") rather than negative signal ("2 findings").
The math must be honest: real claim counts, an industry-average claim
value, a clearly-labeled comparison baseline.

What's pinned
-------------
* Empty data -> ready=False, no hero rendered
* Single clean claim -> 100% clean rate, $190 revenue (1 * $190)
* Half-clean -> 50% clean rate, $ revenue proportional
* Old claims (60+ days) excluded from this-month
* Still-running claims (finished_at=0) excluded
* Delta is positive when this month beats last month
"""

from __future__ import annotations

from ai_billing_audit.api import (
    AVG_CLAIM_VALUE_USD,
    INDUSTRY_DENIAL_RATE,
    compute_clean_rate_metrics,
)


def test_constants_sane():
    """The constants are exported and reasonable."""
    assert AVG_CLAIM_VALUE_USD > 0
    assert 100 < AVG_CLAIM_VALUE_USD < 500
    assert 0 < INDUSTRY_DENIAL_RATE < 0.5


def test_empty_data_ready_false():
    out = compute_clean_rate_metrics([], now=1_000_000.0)
    assert out["ready"] is False
    assert out["this_month_count"] == 0
    assert out["this_month_clean_rate"] is None


def test_single_clean_claim():
    """100% clean rate, $190 revenue, ~$14 avoided denials."""
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [{"encounter_id": "E1", "findings": [], "finished_at": now - 100}],
        now=now,
    )
    assert out["ready"] is True
    assert out["this_month_count"] == 1
    assert out["this_month_clean"] == 1
    assert out["this_month_flagged"] == 0
    assert abs(out["this_month_clean_rate"] - 1.0) < 1e-9
    assert abs(out["this_month_revenue_confirmed"] - AVG_CLAIM_VALUE_USD) < 1e-9
    # Avoided denials = (1.0 - 0.925) * 1 * 190 = 14.25
    assert 14.0 < out["this_month_avoided_denials_dollar"] < 15.0


def test_half_clean():
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [
            {"encounter_id": "C1", "findings": [], "finished_at": now - 100},
            {
                "encounter_id": "C2",
                "findings": [{"severity": "high"}],
                "finished_at": now - 200,
            },
        ],
        now=now,
    )
    assert out["this_month_count"] == 2
    assert out["this_month_clean"] == 1
    assert out["this_month_flagged"] == 1
    assert abs(out["this_month_clean_rate"] - 0.5) < 1e-9
    assert abs(out["this_month_revenue_confirmed"] - AVG_CLAIM_VALUE_USD) < 1e-9


def test_old_claim_excluded():
    """A 60-day-old claim is outside this-month and last-month windows."""
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [{"encounter_id": "OLD", "findings": [], "finished_at": now - 60 * 86400}],
        now=now,
    )
    # Not enough data in either window
    assert out["this_month_count"] == 0
    assert out["this_month_clean_rate"] is None


def test_finished_at_zero_excluded():
    """finished_at=0 (still running) must not count."""
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [{"encounter_id": "RUN", "findings": [], "finished_at": 0}],
        now=now,
    )
    assert out["this_month_count"] == 0


def test_delta_positive_when_improving():
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [
            # This month: 100% clean
            {"encounter_id": "T1", "findings": [], "finished_at": now - 5 * 86400},
            # Last month: 50% clean
            {"encounter_id": "L1", "findings": [], "finished_at": now - 35 * 86400},
            {
                "encounter_id": "L2",
                "findings": [{"severity": "high"}],
                "finished_at": now - 40 * 86400,
            },
        ],
        now=now,
    )
    assert out["this_month_clean_rate"] == 1.0
    assert out["last_month_clean_rate"] == 0.5
    assert out["clean_rate_delta"] == 0.5


def test_delta_negative_when_regressing():
    now = 1_000_000.0
    out = compute_clean_rate_metrics(
        [
            # This month: 50% clean
            {"encounter_id": "T1", "findings": [], "finished_at": now - 5 * 86400},
            {
                "encounter_id": "T2",
                "findings": [{"severity": "high"}],
                "finished_at": now - 6 * 86400,
            },
            # Last month: 100% clean
            {"encounter_id": "L1", "findings": [], "finished_at": now - 35 * 86400},
        ],
        now=now,
    )
    assert out["this_month_clean_rate"] == 0.5
    assert out["last_month_clean_rate"] == 1.0
    assert out["clean_rate_delta"] == -0.5
