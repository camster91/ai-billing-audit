"""Dashboard aggregation hooks for the home page.

Lightweight module that derives summary numbers from the live encounter
store and feeds them to the dashboard templates. Kept separate from
``api.py`` so that the data-shape is testable in isolation and so that
new dashboard widgets don't keep growing the index handler.
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from .api import (
    REVENUE_OPPORTUNITY_RULES,
    _finding_dicts,
    _finding_rule_ids,
    compute_revenue_opportunities,
    list_demo_encounters,
    load_encounter_record,
)


def _month_window(now: float | None = None) -> tuple[float, float]:
    """Return ``(start_ts, end_ts)`` covering the current calendar month.

    Uses local-time semantics: the month starts at the first second of
    the 1st and ends at the next month's start (exclusive).
    """
    import datetime as _dt

    cur = _dt.datetime.fromtimestamp(now if now is not None else time.time())
    start = _dt.datetime(cur.year, cur.month, 1)
    if cur.month == 12:
        end = _dt.datetime(cur.year + 1, 1, 1)
    else:
        end = _dt.datetime(cur.year, cur.month + 1, 1)
    return start.timestamp(), end.timestamp()


def aggregate_missed_revenue_by_rule(
    *,
    now: float | None = None,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Return the top-N rules ranked by aggregate missed-revenue dollar
    impact across all encounters audited in the current calendar month.

    Each returned entry has:
        - ``rule_id``           canonical rule id (e.g. ``rule_ahcip_consultation_missed``)
        - ``rule_name``         human-readable label from
                               ``REVENUE_OPPORTUNITY_RULES``
        - ``total_dollar``      sum of ``estimated_dollar`` for this rule
        - ``encounter_count``   how many distinct encounters contributed
        - ``finding_count``     how many individual findings fired the rule

    The function is intentionally tolerant: if no encounters exist yet,
    or no findings fire within the window, it returns ``[]`` rather than
    raising — the template renders an empty-state in that case.
    """
    start_ts, end_ts = _month_window(now)
    buckets: dict[str, dict[str, Any]] = {}
    seen_encounters: set[str] = set()
    # First pass: aggregate dollar totals per rule across all demo
    # encounters whose audited_at falls in the current month. Demo
    # records that lack an audited_at timestamp are still considered
    # "this month" (they were seeded for the dashboard) so the demo
    # page isn't permanently empty.
    in_window_count = 0
    seeded_count = 0
    for demo_entry in list_demo_encounters():
        record = load_encounter_record(demo_entry.encounter_id)
        if record is None:
            continue
        audited_at = (record or {}).get("audited_at")
        if isinstance(audited_at, (int, float)):
            if audited_at < start_ts or audited_at >= end_ts:
                continue
            in_window_count += 1
        else:
            # No timestamp on record → treat as a current-month seed
            # so the chart has data to render in the demo.
            seeded_count += 1
        findings = _finding_dicts(record)
        for opp in compute_revenue_opportunities(findings):
            rid = opp.get("opportunity_rule_id")
            if not rid:
                continue
            bucket = buckets.setdefault(
                rid,
                {
                    "rule_id": rid,
                    "rule_name": opp.get("rule_name") or rid,
                    "total_dollar": 0.0,
                    "encounter_count": 0,
                    "finding_count": 0,
                },
            )
            bucket["total_dollar"] += float(opp.get("estimated_dollar") or 0.0)
            bucket["finding_count"] += 1
            seen_encounters.add(demo_entry.encounter_id)
    # encounter_count per rule: how many distinct encounters fired this rule
    rule_to_encounters: dict[str, set[str]] = {}
    for demo_entry in list_demo_encounters():
        record = load_encounter_record(demo_entry.encounter_id)
        if record is None:
            continue
        findings = _finding_dicts(record)
        for f in findings:
            for rid in _finding_rule_ids(f):
                if rid not in buckets:
                    continue
                rule_to_encounters.setdefault(rid, set()).add(demo_entry.encounter_id)
    for rid, bucket in buckets.items():
        bucket["encounter_count"] = len(rule_to_encounters.get(rid, set()))
    ranked = sorted(buckets.values(), key=lambda b: b["total_dollar"], reverse=True)
    # Round dollar values for display
    for b in ranked:
        b["total_dollar"] = round(b["total_dollar"], 2)
    return ranked[:top_n]


def month_label(now: float | None = None) -> str:
    """Return a short human label for the dashboard chart caption
    (e.g. ``"June 2026"``). Kept here so the template doesn't have to
    format timestamps itself.
    """
    cur = _dt.datetime.fromtimestamp(now if now is not None else time.time())
    return cur.strftime("%B %Y")


def _parse_feedback_ts(ts: str) -> float | None:
    """Parse a feedback-log timestamp into a Unix timestamp.

    Returns ``None`` if the string is malformed so the caller can skip
    the row without aborting the whole aggregation. The feedback log
    stores ISO-8601 UTC strings (``2026-06-18T14:23:01Z``).
    """
    if not ts:
        return None
    try:
        # Python's fromisoformat in 3.11+ accepts the trailing 'Z'
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def aggregate_monthly_revenue_kpi(
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Aggregate the monthly 'revenue recovered' KPI for the dashboard hero.

    Returns a dict with:
        - ``total_dollar``       sum of ``estimated_dollar`` for every
                                 missed-revenue finding that surfaced
                                 inside the current calendar month
                                 (identified opportunities, accepted or not)
        - ``recovered_dollar``   sum of estimated_dollar for findings the
                                 biller marked *accepted* (actioned) in
                                 the same window
        - ``pending_dollar``     total_dollar − recovered_dollar, clipped
                                 at zero (a positive `accept` that
                                 outpaces identified only happens when
                                 accepts span months; clip defensively)
        - ``n_opportunities``    number of revenue findings in the window
        - ``n_accepted``         number of accepts on those findings
        - ``acceptance_ratio``   recovered / total, or 0.0 if total == 0
        - ``month_label``        human label like ``"June 2026"``
        - ``ready``              True iff at least one identified
                                 opportunity exists for the month —
                                 the template uses this to decide whether
                                 to render the hero or fall back to the
                                 empty-state copy.

    Both halves of the KPI come from different sources:

    - *Identified* opportunities are computed from the demo registry
      (and uploaded encounters with real LLM audits) the same way the
      per-rule aggregator does — see ``_finding_dicts`` and
      ``compute_revenue_opportunities``.
    - *Recovered* dollars are derived from the feedback log: every
      ``accept`` action whose timestamp falls in the month contributes
      the estimated_dollar of the finding it accepted.

    The function never raises: missing feedback log → zero recovered,
    no demo encounters → zero identified, and the template renders
    an empty-state.
    """
    start_ts, end_ts = _month_window(now)

    # ── Identified opportunities in window ──────────────────────────────
    total_dollar = 0.0
    n_opportunities = 0
    # Map finding_id → estimated_dollar so the recovered pass can look
    # up the dollar value of any finding the biller accepted this month.
    # Keys are composite "(encounter_id|finding_id)" to handle the rare
    # case where the same finding_id appears across multiple encounters.
    finding_dollars: dict[str, float] = {}
    for entry in list_demo_encounters():
        record = load_encounter_record(entry.encounter_id)
        if record is None:
            continue
        audited_at = (record or {}).get("audited_at")
        if isinstance(audited_at, (int, float)):
            if audited_at < start_ts or audited_at >= end_ts:
                continue
        # No timestamp → treat as a current-month seed (mirrors the
        # behaviour of aggregate_missed_revenue_by_rule so the demo
        # page is never permanently empty).
        findings = _finding_dicts(record)
        for opp in compute_revenue_opportunities(findings):
            dol = float(opp.get("estimated_dollar") or 0.0)
            if dol <= 0:
                continue
            total_dollar += dol
            n_opportunities += 1
            fid = opp.get("finding_id") or ""
            key = f"{entry.encounter_id}|{fid}"
            finding_dollars[key] = finding_dollars.get(key, 0.0) + dol

    # ── Recovered dollars (accept actions in window) ────────────────────
    recovered_dollar = 0.0
    n_accepted = 0
    try:
        from .feedback import get_default_store

        store = get_default_store()
        for feedback_entry in store.read_all():
            if feedback_entry.action != "accept":
                continue
            ts = _parse_feedback_ts(feedback_entry.timestamp)
            if ts is None:
                continue
            if ts < start_ts or ts >= end_ts:
                continue
            key = f"{feedback_entry.encounter_id}|{feedback_entry.finding_id}"
            recovered_value = finding_dollars.get(key)
            if recovered_value is None:
                # Accept happened this month for a finding whose
                # identified opportunity is from a different month (or
                # never priced). Fall back to the rule-level default
                # estimate so the recovered number isn't understated.
                meta = REVENUE_OPPORTUNITY_RULES.get(feedback_entry.rule_id or "")
                if meta is None:
                    recovered_value = 0.0
                else:
                    recovered_value = float(meta.get("estimated_dollar") or 0.0)
            recovered_dollar += recovered_value
            n_accepted += 1
    except Exception:
        # Feedback module unavailable or log unreadable → leave
        # recovered as zero. The hero still renders the identified
        # total in that case.
        recovered_dollar = 0.0
        n_accepted = 0

    pending_dollar = max(0.0, total_dollar - recovered_dollar)
    acceptance_ratio = (
        round(recovered_dollar / total_dollar, 4) if total_dollar > 0 else 0.0
    )
    return {
        "total_dollar": round(total_dollar, 2),
        "recovered_dollar": round(recovered_dollar, 2),
        "pending_dollar": round(pending_dollar, 2),
        "n_opportunities": n_opportunities,
        "n_accepted": n_accepted,
        "acceptance_ratio": acceptance_ratio,
        "month_label": month_label(now),
        "ready": total_dollar > 0,
    }


def aggregate_monthly_revenue_by_encounter(
    *,
    now: float | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Clinic-level monthly rollup used by ``reports/by_clinic.html``.

    Returns a dict with:
        - ``month_label``         human label like ``"June 2026"``
        - ``encounter_count``     distinct encounter count contributing
                                 at least one opportunity in the window
        - ``top_opportunities``   list of the top-N individual
                                 opportunities (not rule buckets)
                                 ordered by ``estimated_dollar``
                                 descending. Each entry has
                                 ``encounter_id``, ``rule_id``,
                                 ``rule_name``, ``suggested_code``, and
                                 ``estimated_dollar``.
        - ``ready``               True iff at least one opportunity
                                 exists for the month.

    The aggregator walks the same demo / uploaded-encounter registry
    the per-rule aggregator uses, but instead of rolling up *per rule*
    it returns per-finding rows so the biller can click through to
    the underlying encounter detail page. Same empty-state tolerance
    as the sibling aggregators.
    """
    start_ts, end_ts = _month_window(now)
    rows: list[dict[str, Any]] = []
    encounters_touched: set[str] = set()
    for entry in list_demo_encounters():
        record = load_encounter_record(entry.encounter_id)
        if record is None:
            continue
        audited_at = (record or {}).get("audited_at")
        if isinstance(audited_at, (int, float)):
            if audited_at < start_ts or audited_at >= end_ts:
                continue
        findings = _finding_dicts(record)
        for opp in compute_revenue_opportunities(findings):
            dol = float(opp.get("estimated_dollar") or 0.0)
            if dol <= 0:
                continue
            encounters_touched.add(entry.encounter_id)
            rows.append(
                {
                    "encounter_id": entry.encounter_id,
                    "rule_id": opp.get("opportunity_rule_id") or "",
                    "rule_name": opp.get("rule_name")
                    or opp.get("opportunity_rule_id")
                    or "",
                    "suggested_code": opp.get("suggested_code") or "",
                    "estimated_dollar": round(dol, 2),
                }
            )
    rows.sort(key=lambda r: r["estimated_dollar"], reverse=True)
    return {
        "month_label": month_label(now),
        "encounter_count": len(encounters_touched),
        "top_opportunities": rows[:top_n],
        "ready": len(rows) > 0,
    }
