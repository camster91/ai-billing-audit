"""Tests for the clinic dashboard endpoint (t_1ef7beb3).

The dashboard returns 4 metrics in a single payload:

    1. denial_rate           — % of submitted claims that were denied
    2. top_flagged_rules     — [{rule_id, count, pct}] sorted desc
    3. time_to_act           — median + p90 hours from finding
                               creation to biller feedback action
    4. missed_revenue_dollars — sum of estimated_dollar from
                               ACCEPTED revenue opportunities

Acceptance criteria (per the task body):
    * Single GET endpoint returns the 4 metrics in one payload
    * Aggregates from FeedbackStore + audit_actions + per-finding
      data — DO NOT add new tables
    * Window param defaults to 30d, accepts 7d/30d/90d
    * Time-to-act: gap between audit_action 'append' and feedback
    * Missed revenue: only count ACCEPTED findings

Tests cover:
    * empty (no feedback) — empty state payload, ready=False
    * 30d default — explicit /api/dashboard/clinic returns 30d
    * 7d vs 90d window — same data, different window_days
    * clinic_id mismatch — 404

We use tmp-path backed stores / log files so the tests don't
touch the production JSONL files at /app/logs/*.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: float) -> str:
    """Format a POSIX timestamp as the feedback log's ISO-8601 UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _append_feedback(
    store,
    *,
    action: str,
    rule_id: str,
    biller_id: str,
    encounter_id: str,
    finding_id: str,
    ts: float,
) -> None:
    """Append one FeedbackEntry with a pinned timestamp."""
    from ai_billing_audit.feedback import FeedbackEntry

    entry = FeedbackEntry(
        encounter_id=encounter_id,
        finding_id=finding_id,
        action=action,
        severity="medium",
        rule_id=rule_id,
        category="modifier_required",
        timestamp=_iso(ts),
        biller_id=biller_id,
    )
    store.append(entry)


def _write_audit_actions(path: Path, rows: list[dict]) -> None:
    """Write audit_actions rows as JSONL to ``path``.

    Bypasses the chain-signing path so tests don't depend on
    ``compute_signature``. The reader used by ``aggregate_clinic_dashboard``
    walks the file directly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _write_appeal_outcomes(path: Path, rows: list[dict]) -> None:
    """Write appeal-outcome rows as JSONL to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _audit_action_row(
    *,
    encounter_id: str,
    finding_id: str,
    ts: float,
    action: str = "flag",
) -> dict:
    """Build one audit_actions row."""
    return {
        "event_id": f"ev-{encounter_id}-{finding_id}",
        "timestamp": _iso(ts),
        "user_identifier": "test",
        "action": action,
        "tenant_id": "default",
        "data_elements": {
            "encounter_id": encounter_id,
            "finding_id": finding_id,
            "finding_ids": [finding_id],
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def feedback_store(tmp_path: Path):
    """Fresh per-test feedback log so tests don't bleed into each other."""
    from ai_billing_audit.feedback import FeedbackStore

    return FeedbackStore(log_path=tmp_path / "feedback.jsonl")


@pytest.fixture()
def audit_actions_log(tmp_path: Path) -> Path:
    return tmp_path / "audit_trail.jsonl"


@pytest.fixture()
def appeal_outcomes_log(tmp_path: Path) -> Path:
    return tmp_path / "appeal_outcomes.jsonl"


def _loader_returning(findings: list[dict]):
    """Build a stub ``load_findings_for_clinic`` returning a fixed list."""

    def _loader(cid: str, start_ts: float, end_ts: float) -> list[dict]:
        return list(findings)

    return _loader


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_empty_state_returns_zero_metrics(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """No feedback / no outcomes / no findings → empty payload, ready=False.

    The dashboard renders the friendly empty-state copy on this case.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    payload = aggregate_clinic_dashboard(
        clinic_id="clinic-empty",
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    assert payload["ok"] is True
    assert payload["ready"] is False
    assert payload["clinic_id"] == "clinic-empty"
    assert payload["window_days"] == 30
    assert payload["denial_rate"] is None
    assert payload["denial_rate_detail"]["denied_encounters"] == 0
    assert payload["top_flagged_rules"] == []
    assert payload["time_to_act"]["median_hours"] is None
    assert payload["time_to_act"]["p90_hours"] is None
    assert payload["missed_revenue_dollars"] == 0.0
    assert payload["missed_revenue_count"] == 0
    assert payload["n_feedback"] == 0


def test_30d_default_via_route(client) -> None:
    """GET /api/dashboard/clinic (no window param) returns window_days=30.

    We test the route, not the function, so the spec'd default is
    exercised end-to-end. The endpoint is allowed-no-auth in dev so
    no bearer is needed; the per_clinic_f1 sibling uses the same
    middleware and behaves the same way.
    """
    r = client.get("/api/dashboard/clinic")
    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == 30
    # The default clinic_id falls back to the active tenant (or
    # "default_biller"); we just check it's a non-empty string.
    assert isinstance(body["clinic_id"], str) and body["clinic_id"]


def test_window_7d_vs_90d_returns_different_window_days(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """7d and 90d windows both return their respective window_days.

    We pass the same data through both windows so the only thing
    that differs is ``days``. The aggregation should run cleanly
    on either side.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    common = dict(
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    p7 = aggregate_clinic_dashboard(clinic_id="clinic-x", days=7, **common)
    p90 = aggregate_clinic_dashboard(clinic_id="clinic-x", days=90, **common)
    assert p7["window_days"] == 7
    assert p90["window_days"] == 90


def test_window_param_7d_routes_correctly(client) -> None:
    """?window=7d is accepted and routed to the 7-day aggregator."""
    r = client.get("/api/dashboard/clinic?window=7d")
    assert r.status_code == 200
    assert r.json()["window_days"] == 7


def test_window_param_90d_routes_correctly(client) -> None:
    """?window=90d is accepted and routed to the 90-day aggregator."""
    r = client.get("/api/dashboard/clinic?window=90d")
    assert r.status_code == 200
    assert r.json()["window_days"] == 90


def test_window_param_invalid_clamps_to_default(client) -> None:
    """?window=42d (out of set) clamps to 30d, doesn't crash."""
    r = client.get("/api/dashboard/clinic?window=42d")
    assert r.status_code == 200
    assert r.json()["window_days"] == 30


def test_window_param_bare_integer_routes_correctly(client) -> None:
    """?window=7 (bare int, no 'd' suffix) is accepted."""
    r = client.get("/api/dashboard/clinic?window=7")
    assert r.status_code == 200
    assert r.json()["window_days"] == 7


def test_clinic_id_mismatch_returns_404(client) -> None:
    """Unknown clinic_id returns 404 (not 500, not 200 with garbage)."""
    r = client.get("/api/dashboard/clinic?clinic_id=does-not-exist-xyz")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
    assert "does-not-exist-xyz" in body["detail"]


# ---------------------------------------------------------------------------
# Functional tests (the four metrics actually compute the right thing)
# ---------------------------------------------------------------------------


def test_top_flagged_rules_sorted_descending_with_pct(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """The top_flagged_rules list is sorted by count desc, with valid pct."""
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    # 5 feedback events for "modifier-25", 3 for "em_level", 1 for "dx_linkage".
    for i, rid in enumerate(["modifier-25"] * 5 + ["em_level"] * 3 + ["dx_linkage"]):
        _append_feedback(
            feedback_store,
            action="dismiss",
            rule_id=rid,
            biller_id="biller-A",
            encounter_id=f"enc-{i}",
            finding_id=f"f-{rid}-{i}",
            ts=now - 3600,  # all within 30d
        )

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",  # default clinic_for_biller resolves biller→clinic
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    rules = payload["top_flagged_rules"]
    assert len(rules) == 3
    # Sorted descending by count.
    assert rules[0]["rule_id"] == "modifier-25"
    assert rules[0]["count"] == 5
    assert rules[1]["rule_id"] == "em_level"
    assert rules[1]["count"] == 3
    assert rules[2]["rule_id"] == "dx_linkage"
    assert rules[2]["count"] == 1
    # pcts sum to ~100.
    total_pct = sum(r["pct"] for r in rules)
    assert 99.9 < total_pct <= 100.01, total_pct
    # Sanity-check individual pcts.
    assert rules[0]["pct"] == pytest.approx(55.56, rel=0.01)  # 5/9
    assert rules[1]["pct"] == pytest.approx(33.33, rel=0.01)  # 3/9


def test_time_to_act_uses_audit_action_gap(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """Time-to-act median/p90 = gap from audit_action → feedback entry."""
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    audit_rows = []
    for i, gap_hours in enumerate([1.0, 2.0, 3.0, 4.0, 8.0]):
        created_ts = now - 86400  # all created 1 day ago
        feedback_ts = created_ts + gap_hours * 3600
        eid = f"enc-{i}"
        fid = f"f-{i}"
        audit_rows.append(
            _audit_action_row(
                encounter_id=eid, finding_id=fid, ts=created_ts
            )
        )
        _append_feedback(
            feedback_store,
            action="accept",
            rule_id="modifier-25",
            biller_id="biller-A",
            encounter_id=eid,
            finding_id=fid,
            ts=feedback_ts,
        )
    _write_audit_actions(audit_actions_log, audit_rows)

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: _read_audit_rows(audit_actions_log),
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    tta = payload["time_to_act"]
    assert tta["n_pairs"] == 5
    assert tta["n_unpaired"] == 0
    # median of [1,2,3,4,8] = 3.0
    assert tta["median_hours"] == pytest.approx(3.0, abs=1e-6)
    # p90 of [1,2,3,4,8]: position 0.9 * (5-1) = 3.6 → between idx 3 (val=4)
    # and idx 4 (val=8); linear interp = 4 + 0.6*(8-4) = 6.4.
    assert tta["p90_hours"] == pytest.approx(6.4, abs=1e-6)


def test_time_to_act_excludes_unpaired_feedback(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """Feedback entries with no matching audit_action are excluded from the stat."""
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    # Pair 1: matched pair (gap = 2h).
    audit_rows = [
        _audit_action_row(
            encounter_id="enc-1",
            finding_id="f-1",
            ts=now - 86400,
        ),
    ]
    _append_feedback(
        feedback_store,
        action="accept",
        rule_id="modifier-25",
        biller_id="biller-A",
        encounter_id="enc-1",
        finding_id="f-1",
        ts=now - 86400 + 2 * 3600,
    )
    # Unpaired feedback (no audit_action row).
    _append_feedback(
        feedback_store,
        action="accept",
        rule_id="em_level",
        biller_id="biller-A",
        encounter_id="enc-orphan",
        finding_id="f-orphan",
        ts=now - 3600,
    )
    _write_audit_actions(audit_actions_log, audit_rows)

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: _read_audit_rows(audit_actions_log),
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    tta = payload["time_to_act"]
    assert tta["n_pairs"] == 1
    assert tta["n_unpaired"] == 1
    assert tta["median_hours"] == pytest.approx(2.0, abs=1e-6)


def test_missed_revenue_only_counts_accepted_findings(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """Missed revenue sums estimated_dollar from ACCEPTED findings only.

    Dismissed findings contribute $0; findings without any feedback
    decision contribute $0. Only the two accepted findings count.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    # Build findings using compute_revenue_opportunities so they
    # carry the ``estimated_dollar`` field the aggregator checks.
    from ai_billing_audit.api import compute_revenue_opportunities

    raw_findings = [
        {
            "encounter_id": "enc-1",
            "finding_id": "f-mod-25",
            "rule_id": "rule_ahcip_modifier_25_001",
            "severity": "high",
            "category": "modifier_required",
            "suggested_code": "MOD25",
        },
        {
            "encounter_id": "enc-1",
            "finding_id": "f-em-level",
            "rule_id": "rule_ahcip_em_level_upcode",
            "severity": "medium",
            "category": "evaluation",
            "suggested_code": "03.04A",
        },
        {
            "encounter_id": "enc-2",
            "finding_id": "f-telehealth",
            "rule_id": "rule_ahcip_telehealth_premium",
            "severity": "low",
            "category": "modifier_required",
            "suggested_code": "TELEHEALTH",
        },
    ]
    opportunities = compute_revenue_opportunities(raw_findings)
    assert len(opportunities) == 3
    # Total possible (all 3 accepted) — used as the sanity ceiling.
    total_possible = sum(o["estimated_dollar"] for o in opportunities)
    assert total_possible > 0

    # Accept finding #1; dismiss finding #2; leave finding #3 alone.
    _append_feedback(
        feedback_store,
        action="accept",
        rule_id="modifier-25",
        biller_id="biller-A",
        encounter_id="enc-1",
        finding_id="f-mod-25",
        ts=now - 3600,
    )
    _append_feedback(
        feedback_store,
        action="dismiss",
        rule_id="em_level",
        biller_id="biller-A",
        encounter_id="enc-1",
        finding_id="f-em-level",
        ts=now - 3600,
    )

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning(opportunities),
    )
    # Only the accepted finding (f-mod-25, $45) counts.
    assert payload["missed_revenue_count"] == 1
    assert payload["missed_revenue_dollars"] == pytest.approx(
        45.0, abs=1e-6
    )


def test_denial_rate_from_lost_and_withdrawn_outcomes(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """denial_rate = encounters with lost/withdrawn ÷ decided encounters.

    Seed 5 outcomes: 2 lost, 1 withdrawn, 2 won → 3/5 = 0.60.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    # Need at least one feedback entry to anchor the clinic
    # (the function refuses to report a denial rate for a clinic
    # with no feedback — see _compute_denial_rate).
    _append_feedback(
        feedback_store,
        action="dismiss",
        rule_id="modifier-25",
        biller_id="biller-A",
        encounter_id="enc-1",
        finding_id="f-1",
        ts=now - 3600,
    )

    rows = [
        # 2 lost
        {
            "appeal_id": "a-1",
            "encounter_id": "enc-lost-1",
            "status": "lost",
            "timestamp": _iso(now - 86400),
        },
        {
            "appeal_id": "a-2",
            "encounter_id": "enc-lost-2",
            "status": "lost",
            "timestamp": _iso(now - 86400),
        },
        # 1 withdrawn
        {
            "appeal_id": "a-3",
            "encounter_id": "enc-withdrawn",
            "status": "withdrawn",
            "timestamp": _iso(now - 86400),
        },
        # 2 won
        {
            "appeal_id": "a-4",
            "encounter_id": "enc-won-1",
            "status": "won",
            "timestamp": _iso(now - 86400),
        },
        {
            "appeal_id": "a-5",
            "encounter_id": "enc-won-2",
            "status": "won",
            "timestamp": _iso(now - 86400),
        },
    ]
    _write_appeal_outcomes(appeal_outcomes_log, rows)

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    dr = payload["denial_rate_detail"]
    assert dr["denied_encounters"] == 3
    assert dr["decided_encounters"] == 5
    assert dr["n_lost"] == 2
    assert dr["n_withdrawn"] == 1
    assert dr["n_won"] == 2
    assert payload["denial_rate"] == pytest.approx(0.6, abs=1e-4)


def test_denial_rate_uses_latest_wins_per_appeal_id(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """Latest outcome per appeal_id wins (pending → won updates the rate)."""
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    _append_feedback(
        feedback_store,
        action="dismiss",
        rule_id="modifier-25",
        biller_id="biller-A",
        encounter_id="enc-1",
        finding_id="f-1",
        ts=now - 3600,
    )
    rows = [
        # appeal "a-1": pending first, then won.
        {
            "appeal_id": "a-1",
            "encounter_id": "enc-1",
            "status": "pending",
            "timestamp": _iso(now - 7200),
        },
        {
            "appeal_id": "a-1",
            "encounter_id": "enc-1",
            "status": "won",
            "timestamp": _iso(now - 3600),
        },
        # appeal "a-2": lost.
        {
            "appeal_id": "a-2",
            "encounter_id": "enc-2",
            "status": "lost",
            "timestamp": _iso(now - 3600),
        },
    ]
    _write_appeal_outcomes(appeal_outcomes_log, rows)

    payload = aggregate_clinic_dashboard(
        clinic_id="biller-A",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    # After latest-wins collapse: a-1=won, a-2=lost. 1 denied of 2 decided.
    assert payload["denial_rate_detail"]["decided_encounters"] == 2
    assert payload["denial_rate_detail"]["denied_encounters"] == 1
    assert payload["denial_rate_detail"]["n_won"] == 1
    assert payload["denial_rate_detail"]["n_pending"] == 0
    assert payload["denial_rate"] == pytest.approx(0.5, abs=1e-4)


def test_denial_rate_none_for_clinic_with_no_feedback(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """A clinic with no feedback gets denial_rate=None, even if outcomes exist.

    Without feedback we can't identify the clinic's billers, so we
    refuse to fabricate a per-clinic number. The endpoint payload
    carries denial_rate=None and ready=False.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    now = 1_700_000_000.0
    rows = [
        {
            "appeal_id": "a-1",
            "encounter_id": "enc-1",
            "status": "lost",
            "timestamp": _iso(now - 86400),
        },
    ]
    _write_appeal_outcomes(appeal_outcomes_log, rows)

    payload = aggregate_clinic_dashboard(
        clinic_id="clinic-no-feedback",
        now=now,
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    assert payload["denial_rate"] is None
    # The denial_rate_detail still surfaces the raw counts so the
    # UI can show "we have outcomes but can't scope to your clinic".
    assert payload["denial_rate_detail"]["n_lost"] == 1


def test_aggregate_returns_all_four_metric_keys(
    feedback_store,
    audit_actions_log,
    appeal_outcomes_log,
) -> None:
    """Smoke: the payload carries the 4 spec'd keys + ok/ready/clinic_id/window_days.

    Even on the empty state the contract is preserved — the front-end
    can render metric tiles by reading fixed keys.
    """
    from ai_billing_audit.per_clinic_f1 import aggregate_clinic_dashboard

    payload = aggregate_clinic_dashboard(
        clinic_id="clinic-X",
        days=30,
        store=feedback_store,
        audit_actions_reader=lambda: [],
        outcomes_log=appeal_outcomes_log,
        load_findings_for_clinic=_loader_returning([]),
    )
    assert "denial_rate" in payload
    assert "top_flagged_rules" in payload
    assert "time_to_act" in payload
    assert "missed_revenue_dollars" in payload
    # And the framing keys the front-end depends on.
    for k in ("ok", "ready", "clinic_id", "window_days", "generated_at"):
        assert k in payload, f"missing framing key: {k}"


# ---------------------------------------------------------------------------
# Internal helpers (file readers) — kept here so each test is self-contained
# ---------------------------------------------------------------------------


def _read_audit_rows(path: Path) -> list[dict]:
    """Read JSONL rows from ``path`` (no chain verification)."""
    if not path.is_file():
        return []
    out: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ---------------------------------------------------------------------------
# Fixture: client
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Starlette TestClient with AUTH off so the dev-mode middleware lets us in.

    The bearer middleware in ``api.create_app`` reads the
    ``AUDIT_ALLOW_NO_AUTH`` env var at app-construction time. To
    make this work in CI (where the env isn't pre-configured) we
    set the env BEFORE creating a fresh app via the factory. This
    keeps the test fully isolated from the module-level ``app``
    singleton — which may have been constructed earlier in the
    test session with a different env.
    """
    os.environ["AUDIT_ALLOW_NO_AUTH"] = "1"
    os.environ["AUDIT_BEARER_TOKEN"] = ""
    from starlette.testclient import TestClient
    from ai_billing_audit.api import create_app

    return TestClient(create_app())