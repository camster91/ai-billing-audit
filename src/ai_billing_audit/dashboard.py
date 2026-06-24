"""Dashboard aggregation hooks for the home page.

Lightweight module that derives summary numbers from the live encounter
store and feeds them to the dashboard templates. Kept separate from
``api.py`` so that the data-shape is testable in isolation and so that
new dashboard widgets don't keep growing the index handler.
"""

from __future__ import annotations

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
    # First pass: aggregate dollar totals per rule across all demo
    # encounters whose audited_at falls in the current month. Demo
    # records that lack an audited_at timestamp are still considered
    # "this month" (they were seeded for the dashboard) so the demo
    # page isn't permanently empty.
    in_window_count = 0
    seeded_count = 0
    for entry in list_demo_encounters():
        record = load_encounter_record(entry.encounter_id)
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
            seen_encounters.add(entry.encounter_id)
    # encounter_count per rule: how many distinct encounters fired this rule
    rule_to_encounters: dict[str, set[str]] = {}
    for entry in list_demo_encounters():
        record = load_encounter_record(entry.encounter_id)
        if record is None:
            continue
        findings = _finding_dicts(record)
        for f in findings:
            for rid in _finding_rule_ids(f):
                if rid not in buckets:
                    continue
                rule_to_encounters.setdefault(rid, set()).add(entry.encounter_id)
    for rid, bucket in buckets.items():
        bucket["encounter_count"] = len(rule_to_encounters.get(rid, set()))
    ranked = sorted(
        buckets.values(), key=lambda b: b["total_dollar"], reverse=True
    )
    # Round dollar values for display
    for b in ranked:
        b["total_dollar"] = round(b["total_dollar"], 2)
    return ranked[:top_n]


def month_label(now: float | None = None) -> str:
    """Return a short human label for the dashboard chart caption
    (e.g. ``"June 2026"``). Kept here so the template doesn't have to
    format timestamps itself.
    """
    import datetime as _dt

    cur = _dt.datetime.fromtimestamp(now if now is not None else time.time())
    return cur.strftime("%B %Y")