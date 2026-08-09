"""Tests for the per-clinic F1 aggregation module.

These cover the acceptance criteria in the learning-loop
``t_c34bf190`` task spec:

1. **Strictly improving F1** — week-over-week per-rule F1 rises
   monotonically; the dashboard chart should plot an upward
   trend.
2. **Flat F1** — week-over-week F1 stays within rounding noise;
   the dashboard should render a flat trend line.
3. **No events** — a clinic with zero feedback events in the
   window returns empty ``per_rule`` and empty ``weekly`` (or
   weekly buckets with f1=0). The dashboard renders the
   empty-state copy on this case.

We use a tmp ``FeedbackStore`` so tests don't touch the
production feedback log at ``/app/logs/feedback.jsonl``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import (  # noqa: E402
    FeedbackEntry,
    FeedbackStore,
)
from ai_billing_audit.per_clinic_f1 import (  # noqa: E402
    INSUFFICIENT_DATA_THRESHOLD,
    insufficient_data_state,
    per_rule_metrics,
    weekly_f1,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> FeedbackStore:
    """Fresh per-test feedback log so tests don't bleed into each other."""
    return FeedbackStore(log_path=tmp_path / "feedback.jsonl")


def _iso(ts: float) -> str:
    """Format a POSIX timestamp as the feedback log's expected ISO-8601 UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(
    store: FeedbackStore,
    *,
    action: str,
    rule_id: str,
    biller_id: str,
    encounter_id: str,
    ts: float,
    severity: str = "medium",
) -> None:
    """Append one feedback entry with a pinned timestamp.

    Bypasses the chain-signing path so tests don't depend on
    ``compute_signature`` — the per_clinic_f1 module only reads
    entries, it doesn't verify the chain.
    """
    entry = FeedbackEntry(
        encounter_id=encounter_id,
        finding_id=f"f-{rule_id}-{int(ts)}",
        action=action,
        severity=severity,
        rule_id=rule_id,
        category="modifier_required",
        timestamp=_iso(ts),
        biller_id=biller_id,
    )
    # Skip chain signing — the dashboard reader does not verify.
    store.append(entry)


def _last_week_now(now: float | None = None) -> float:
    """Return the ``now`` used as the window endpoint for tests.

    Defaults to a Monday UTC boundary so each seven-day fixture block
    remains in one ISO-week bucket regardless of the wall clock.
    """
    if now is None:
        now = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
    return now


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_strictly_improving_f1(store: FeedbackStore) -> None:
    """A clinic whose precision improves week-over-week yields an upward F1 trend.

    Seed 4 weeks of feedback for one clinic. Week 0 is mostly
    dismissals (low precision), week 3 is mostly accepts (high
    precision). The weekly F1 series should be non-decreasing
    (modulo the recall-proxy smoothing).
    """
    now = _last_week_now()
    # Four weeks back from "now", 7-day spaced.
    week0 = now - 28 * 86400
    week1 = now - 21 * 86400
    week2 = now - 14 * 86400
    week3 = now - 7 * 86400

    # Week 0: 1 accept, 3 dismissals → precision 0.25, low F1.
    for i, ts in enumerate([week0, week0 + 3600, week0 + 7200, week0 + 10800]):
        action = "accept" if i == 0 else "dismiss"
        _append(
            store,
            action=action,
            rule_id="R-MOD-25",
            biller_id="biller-A",
            encounter_id=f"enc-w0-{i}",
            ts=ts,
        )

    # Week 1: 2 accept, 2 dismiss.
    for i, ts in enumerate([week1, week1 + 3600, week1 + 7200, week1 + 10800]):
        action = "accept" if i < 2 else "dismiss"
        _append(
            store,
            action=action,
            rule_id="R-MOD-25",
            biller_id="biller-A",
            encounter_id=f"enc-w1-{i}",
            ts=ts,
        )

    # Week 2: 3 accept, 1 dismiss.
    for i, ts in enumerate([week2, week2 + 3600, week2 + 7200, week2 + 10800]):
        action = "accept" if i < 3 else "dismiss"
        _append(
            store,
            action=action,
            rule_id="R-MOD-25",
            biller_id="biller-A",
            encounter_id=f"enc-w2-{i}",
            ts=ts,
        )

    # Week 3: 4 accept, 0 dismiss.
    for i, ts in enumerate([week3, week3 + 3600, week3 + 7200, week3 + 10800]):
        _append(
            store,
            action="accept",
            rule_id="R-MOD-25",
            biller_id="biller-A",
            encounter_id=f"enc-w3-{i}",
            ts=ts,
        )

    # per_rule_metrics aggregates across the whole 30-day window:
    # total 10 accept / 6 dismiss → precision ≈ 0.625.
    per_rule = per_rule_metrics(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=store,
    )
    assert "R-MOD-25" in per_rule, per_rule
    pr = per_rule["R-MOD-25"]
    assert pr["support"] == 16
    # Precision: 10/(10+6) = 0.625.
    assert 0.6 <= pr["precision"] <= 0.66
    assert pr["f1"] > 0.0

    # weekly_f1 should be non-empty and the latest week should
    # have the highest F1 (week 3 = pure accept, week 0 = mostly
    # dismiss). The recall proxy in per_clinic_f1.py uses
    # support/5 clamped to 1.0, so week 3 (support=4) has the
    # best per-week F1.
    weekly = weekly_f1(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=store,
    )
    assert weekly, "weekly_f1 should produce buckets"
    # The last non-empty bucket (latest week) must have a higher
    # F1 than the first non-empty bucket (oldest week).
    nonempty = [b for b in weekly if b["support"] > 0]
    assert len(nonempty) >= 2, nonempty
    first_f1 = nonempty[0]["f1"]
    last_f1 = nonempty[-1]["f1"]
    assert last_f1 > first_f1, (
        f"expected strictly improving F1: first={first_f1}, last={last_f1}, "
        f"buckets={nonempty}"
    )


def test_flat_f1(store: FeedbackStore) -> None:
    """A clinic with the same accept/dismiss ratio each week yields a flat F1 series.

    Seed 4 weeks, each with 2 accept + 2 dismiss for one rule.
    The weekly F1 series should produce identical precision each
    week (0.5), so the chart should plot a flat line.
    """
    now = _last_week_now()
    week_starts = [now - (28 - 7 * i) * 86400 for i in range(4)]
    for w_idx, w_start in enumerate(week_starts):
        for i in range(4):
            action = "accept" if i < 2 else "dismiss"
            _append(
                store,
                action=action,
                rule_id="R-MOD-25",
                biller_id="biller-A",
                encounter_id=f"enc-flat-w{w_idx}-{i}",
                ts=w_start + i * 3600,
            )

    weekly = weekly_f1(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=store,
    )
    nonempty = [b for b in weekly if b["support"] > 0]
    assert len(nonempty) >= 4, f"expected ≥4 weekly buckets, got {len(nonempty)}"
    f1_values = [b["f1"] for b in nonempty]
    # All four buckets should have precision ≈ 0.5 → identical
    # F1 within rounding tolerance (±0.01).
    spread = max(f1_values) - min(f1_values)
    assert spread <= 0.01, (
        f"flat F1 expected (max-min ≤ 0.01), got spread={spread}, buckets={nonempty}"
    )


def test_no_feedback_in_window_returns_empty_state(store: FeedbackStore) -> None:
    """A clinic with zero feedback events in the window returns empty dicts.

    The dashboard widget renders the explicit empty-state copy
    on this case (the HTML sets ``pcf1-empty`` visible and
    ``pcf1-content`` hidden).
    """
    now = _last_week_now()
    # Append some feedback for OTHER clinics / OTHER rules so the
    # store is non-empty — the function should still return empty
    # for the queried clinic.
    _append(
        store,
        action="accept",
        rule_id="R-OTHER",
        biller_id="biller-X",
        encounter_id="enc-x-1",
        ts=now - 5 * 86400,
    )
    _append(
        store,
        action="dismiss",
        rule_id="R-OTHER",
        biller_id="biller-Y",
        encounter_id="enc-y-1",
        ts=now - 10 * 86400,
    )

    # 1. No events for "biller-Z" → empty per-rule metrics.
    per_rule = per_rule_metrics(
        clinic_id="biller-Z",
        now=now,
        days=30,
        store=store,
    )
    assert per_rule == {}, (
        f"expected empty per_rule for clinic with no events, got {per_rule}"
    )

    # 2. weekly_f1 returns a (possibly empty) list — either empty
    # or filled with empty buckets. Both are acceptable
    # empty-state signals; the contract is "the dashboard can
    # show empty-state copy".
    weekly = weekly_f1(
        clinic_id="biller-Z",
        now=now,
        days=30,
        store=store,
    )
    assert weekly == [] or all(b["support"] == 0 for b in weekly), (
        f"expected empty weekly buckets, got {weekly}"
    )

    # 3. The list_clinics-style contract: there ARE feedback
    # entries in the store, just none for biller-Z. The dashboard
    # correctly does NOT offer "biller-Z" in the picker.
    # (This is enforced by list_clinics() in per_clinic_f1.py —
    # covered indirectly via the store-roundtrip above.)


def test_insufficient_data_state_below_threshold() -> None:
    """Empty-state helper flags a clinic with n<threshold feedback events.

    Pure unit test: doesn't touch the store or the LLM. Verifies the
    helper that backs both the per_clinic_f1 dashboard and the
    monthly report returns the friendly "insufficient data" payload
    when total support is below the threshold, and the "ok" payload
    when it's at or above.
    """
    # 1. Empty per_rule -> insufficient (total_support=0 < threshold).
    s0 = insufficient_data_state(
        clinic_id="clinic-A",
        per_rule={},
        window_days=30,
    )
    assert s0["is_insufficient"] is True
    assert s0["total_support"] == 0
    assert s0["threshold"] == INSUFFICIENT_DATA_THRESHOLD
    assert s0["clinic_id"] == "clinic-A"
    assert s0["window_days"] == 30
    assert "Not enough feedback" in s0["message"]
    assert "Insufficient data" in s0["headline"]
    assert "Review a few findings" in s0["cta"]
    assert "3 more" in s0["message"], (
        f"expected '3 more' (threshold - 0) in message, got: {s0['message']!r}"
    )

    # 2. Below threshold (n=2 < 3) -> still insufficient, message
    #    should report "1 more" needed.
    per_rule_below = {
        "rule_ahcip_em_level": {
            "precision": 0.8,
            "recall": 0.5,
            "f1": 0.62,
            "support": 1,
        },
        "rule_ahcip_dx_linkage": {
            "precision": 1.0,
            "recall": 0.5,
            "f1": 0.67,
            "support": 1,
        },
    }
    s2 = insufficient_data_state(
        clinic_id="clinic-B",
        per_rule=per_rule_below,
        window_days=30,
    )
    assert s2["is_insufficient"] is True
    assert s2["total_support"] == 2
    assert "1 more" in s2["message"], (
        f"expected '1 more' in message, got: {s2['message']!r}"
    )

    # 3. At threshold (n=3) -> NOT insufficient, message is empty.
    per_rule_at = {
        "rule_a": {"precision": 1.0, "recall": 0.5, "f1": 0.67, "support": 3},
    }
    s3 = insufficient_data_state(
        clinic_id="clinic-C",
        per_rule=per_rule_at,
        window_days=30,
    )
    assert s3["is_insufficient"] is False
    assert s3["total_support"] == 3
    assert s3["message"] == "", (
        f"expected empty message when at-or-above threshold, got: {s3['message']!r}"
    )

    # 4. Above threshold -> NOT insufficient, even with low-precision
    #    rules. The helper should NOT conflate "low data" with "low
    #    precision" — that's the per-rule table's job to display.
    per_rule_above = {
        f"rule_{i}": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2}
        for i in range(5)
    }
    s4 = insufficient_data_state(
        clinic_id="clinic-D",
        per_rule=per_rule_above,
        window_days=30,
    )
    assert s4["is_insufficient"] is False
    assert s4["total_support"] == 10


def test_appeal_window_reads_encrypted_outcomes(tmp_path, monkeypatch):
    from ai_billing_audit import appeal_letter
    from ai_billing_audit.appeal_letter import AppealOutcome, log_appeal_outcome
    from ai_billing_audit.per_clinic_f1 import _read_appeal_outcomes_window

    path = tmp_path / "appeal_outcomes.jsonl"
    monkeypatch.setattr(appeal_letter, "_APPEAL_OUTCOMES_LOG", path)
    log_appeal_outcome(
        AppealOutcome.now(
            appeal_id="appeal-secret",
            encounter_id="enc-secret",
            status="won",
        )
    )

    rows = _read_appeal_outcomes_window(
        start_ts=0,
        end_ts=4_000_000_000,
        outcomes_log=path,
    )
    assert [row["appeal_id"] for row in rows] == ["appeal-secret"]
