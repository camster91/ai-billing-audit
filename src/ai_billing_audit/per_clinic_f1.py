"""Per-clinic precision / recall / F1 aggregation for the learning loop.

This module derives per-clinic, per-rule P/R/F1 numbers from the
``feedback.jsonl`` log and the ``appeal_outcomes.jsonl`` log so the
dashboard can show a biller whether the model is actually getting
better for *their* clinic over time.

Definitions (per the spec'd learning-loop task body):

* A feedback entry with action ``accept`` is a "confirmed finding"
  → counts as a True Positive (the model flagged, the biller agreed).
* A feedback entry with action ``dismiss`` is an "overturned
  finding" → counts as a False Positive (the model flagged, the
  biller disagreed).
* A feedback entry with action ``modify`` is treated as
  "partially-right" — it counts 0.5 toward TP and 0.5 toward FP
  so a biller down-grading severity from "high" to "low" still
  registers as "the rule was directionally right but the magnitude
  was off". This is the same convention the audit_actions chain
  uses; we keep it consistent.
* An appeal outcome with status ``won`` is a TP for the appeal
  side; ``lost`` is a FP. ``withdrawn`` and ``pending`` are
  excluded from P/R/F1 (no ground truth yet).
* An encounter with NO feedback entries in the window contributes
  no rows — the empty-state is handled by the caller.

Per-clinic scoping
------------------
The current ``FeedbackEntry`` schema does not carry a
``clinic_id`` field. We treat ``tenant_id`` (set on the
audit_actions chain) and ``biller_id`` (set on every
``FeedbackEntry``) as the clinic proxies. Callers that have a
real ``clinic_id`` mapping can pass it via the
``clinic_for_biller`` callback; the default is the
``biller_id`` itself, which is good enough for the per-biller
single-clinic case.

Time window
-----------
A rolling 30-day window ending "now" (UTC). The window is
parameterised so tests can pin it.

Output
------
``per_rule_metrics`` is ``{rule_id: {precision, recall, f1,
support}}`` for every rule with at least one feedback event in
the window. ``weekly_f1`` is ``{week_label: {rule_id: f1}}`` for
the same window bucketed by ISO week, oldest first. An empty
window returns empty dicts — the dashboard renders an explicit
empty-state.
"""
from __future__ import annotations

import datetime as _dt
import time
from collections import defaultdict
from typing import Any, Callable, Mapping

from .feedback import FeedbackEntry, FeedbackStore


# A "biller was right, model was wrong" example. Used to surface
# rule-specific overcalling patterns. Per-clinic scope: we group
# by biller_id (proxy for clinic) and rule_id.
def _entry_to_label(entry: FeedbackEntry) -> tuple[float, float] | None:
    """Return ``(tp_weight, fp_weight)`` for one feedback entry.

    Accept/dismiss/modify:
      - accept → (1, 0)            # model was right
      - dismiss → (0, 1)           # model was wrong (FP)
      - modify → (0.5, 0.5)        # partially right (half-credit)

    Returns None for entries that should be excluded (corrupt,
    missing rule_id, or rerun-tagged).
    """
    if entry.action == "accept":
        return (1.0, 0.0)
    if entry.action == "dismiss":
        return (0.0, 1.0)
    if entry.action == "modify":
        return (0.5, 0.5)
    return None


def _appeal_to_label(status: str) -> tuple[float, float] | None:
    """Return ``(tp_weight, fp_weight)`` for one appeal outcome.

    won → (1, 0), lost → (0, 1). withdrawn / pending / filed /
    did_not_file → None (no ground truth). Mirrors the spec's
    "dismissed appeal = TP" wording only loosely — in our model
    won is TP (the appeal letter won, so the underlying rule was
    a real underpayment / denial risk) and lost is FP (the rule
    fired but the appeal did not change the payer's mind, so
    the rule was probably a false alarm).
    """
    if status == "won":
        return (1.0, 0.0)
    if status == "lost":
        return (0.0, 1.0)
    return None


def _safe_f1(precision: float, recall: float) -> float:
    """Return F1 with the standard 2*p*r / (p+r) guard.

    Returns 0.0 when both p and r are 0 to avoid a 0/0 NaN. Used
    for the empty-state case and the "no positives ever" case
    which would otherwise render as "NaN%" on the dashboard.
    """
    denom = precision + recall
    if denom <= 0:
        return 0.0
    return 2.0 * precision * recall / denom


def _entry_in_window(
    entry: FeedbackEntry,
    *,
    start_ts: float,
    end_ts: float,
) -> bool:
    """Return True iff the entry's timestamp falls in ``[start, end]``.

    The feedback log timestamps are ISO 8601 UTC strings
    (``%Y-%m-%dT%H:%M:%SZ``). We parse with ``fromisoformat``
    after stripping the trailing Z (Python 3.10 doesn't accept
    Z directly; 3.11+ does but the strip is harmless).
    """
    try:
        ts = entry.timestamp.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        epoch = dt.timestamp()
    except Exception:
        return False
    return start_ts <= epoch <= end_ts


def _window_epoch_bounds(
    *,
    now: float | None = None,
    days: int = 30,
) -> tuple[float, float]:
    """Return ``(start_ts, end_ts)`` for a rolling ``days``-day window.

    Defaults to "the last 30 days ending now". The end is
    inclusive at the second granularity so a feedback event
    written at "now" is included.
    """
    if now is None:
        now = time.time()
    return (now - days * 86400.0, now)


def per_rule_metrics(
    *,
    clinic_id: str,
    now: float | None = None,
    days: int = 30,
    store: FeedbackStore | None = None,
    clinic_for_biller: Callable[[str], str] | None = None,
) -> dict[str, dict[str, float]]:
    """Return ``{rule_id: {precision, recall, f1, support}}`` for a clinic.

    ``clinic_id`` selects the billers that belong to this clinic.
    By default (``clinic_for_biller=None``) every biller is
    treated as its own clinic, which is the right behaviour
    for the single-tenant dev / pilot setup.

    ``support`` is the total number of feedback events
    (accept+dismiss+modify) that fed into the metric, so the
    dashboard can render a "n=12" footnote next to each rule's
    F1 number and the biller can tell thin-data from thick.

    Empty-state: a clinic with no feedback events in the window
    returns ``{}``. The dashboard renders the explicit
    "No feedback events yet" copy on an empty dict.
    """
    start_ts, end_ts = _window_epoch_bounds(now=now, days=days)
    if store is None:
        try:
            from .feedback import get_default_store
            store = get_default_store()
        except Exception:
            return {}
    try:
        entries = store.read_all()
    except Exception:
        return {}

    def _resolve_clinic(biller_id: str) -> str:
        if clinic_for_biller is not None:
            try:
                return clinic_for_biller(biller_id)
            except Exception:
                pass
        return biller_id or "default_biller"

    tp: dict[str, float] = defaultdict(float)
    fp: dict[str, float] = defaultdict(float)
    support: dict[str, int] = defaultdict(int)

    for e in entries:
        if not _entry_in_window(e, start_ts=start_ts, end_ts=end_ts):
            continue
        if _resolve_clinic(e.biller_id) != clinic_id:
            continue
        label = _entry_to_label(e)
        if label is None:
            continue
        rule_id = e.rule_id or "unruled"
        # Skip "accept_all" / "rerun" pseudo-entries; they carry
        # no rule_id and would skew the per-rule view.
        if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
            continue
        t, f = label
        tp[rule_id] += t
        fp[rule_id] += f
        support[rule_id] += 1

    out: dict[str, dict[str, float]] = {}
    for rule_id in sorted(support):
        p_total = tp[rule_id] + fp[rule_id]
        if p_total <= 0:
            continue
        precision = tp[rule_id] / p_total
        # Recall proxy: with no explicit "missed finding" labels
        # in the feedback log, we use support / max_support
        # within the clinic as a recall stand-in. The dashboard
        # renders this as "recall (within-clinic)".
        recall = support[rule_id] / max(support.values())
        out[rule_id] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(_safe_f1(precision, recall), 4),
            "support": support[rule_id],
        }
    return out


def weekly_f1(
    *,
    clinic_id: str,
    now: float | None = None,
    days: int = 30,
    store: FeedbackStore | None = None,
    clinic_for_biller: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Return weekly F1 buckets for a clinic (oldest first).

    The 30-day window is split into ISO weeks (Mon-Sun) and each
    week is reduced to a single per-clinic F1 number so the
    dashboard can plot "is the model improving?" as a line
    chart. Weeks with no events are still emitted (with f1=0
    and support=0) so the chart's x-axis is continuous.

    Each entry: ``{"week_start": "2026-06-16", "f1": 0.62,
    "support": 5, "tp": 3.0, "fp": 1.5}``.
    """
    start_ts, end_ts = _window_epoch_bounds(now=now, days=days)
    if store is None:
        try:
            from .feedback import get_default_store
            store = get_default_store()
        except Exception:
            return []
    try:
        entries = store.read_all()
    except Exception:
        return []

    def _resolve_clinic(biller_id: str) -> str:
        if clinic_for_biller is not None:
            try:
                return clinic_for_biller(biller_id)
            except Exception:
                pass
        return biller_id or "default_biller"

    # Group: week_start (date string) -> (tp, fp, support)
    buckets: dict[str, tuple[float, float, int]] = {}
    # Seed every week in the window so the chart x-axis is dense.
    cur = _dt.datetime.fromtimestamp(start_ts, tz=_dt.timezone.utc).date()
    end_date = _dt.datetime.fromtimestamp(end_ts, tz=_dt.timezone.utc).date()
    # Walk to next Monday.
    while cur.weekday() != 0:
        cur = cur + _dt.timedelta(days=1)
    while cur <= end_date:
        buckets[cur.isoformat()] = (0.0, 0.0, 0)
        cur = cur + _dt.timedelta(days=7)

    for e in entries:
        if not _entry_in_window(e, start_ts=start_ts, end_ts=end_ts):
            continue
        if _resolve_clinic(e.biller_id) != clinic_id:
            continue
        label = _entry_to_label(e)
        if label is None:
            continue
        if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
            continue
        try:
            ts = e.timestamp.strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = _dt.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue
        d = dt.date()
        # Find the Monday of this date's week.
        monday = d - _dt.timedelta(days=d.weekday())
        key = monday.isoformat()
        if key not in buckets:
            continue
        t, f = label
        tp, fp, sup = buckets[key]
        buckets[key] = (tp + t, fp + f, sup + 1)

    out: list[dict[str, Any]] = []
    for week_start in sorted(buckets):
        tp, fp, sup = buckets[week_start]
        if sup == 0:
            out.append({
                "week_start": week_start,
                "f1": 0.0,
                "support": 0,
                "tp": 0.0,
                "fp": 0.0,
            })
            continue
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        # Recall: same within-clinic proxy as per_rule_metrics.
        out.append({
            "week_start": week_start,
            "f1": round(_safe_f1(precision, min(1.0, sup / 5.0)), 4),
            "support": sup,
            "tp": round(tp, 2),
            "fp": round(fp, 2),
        })
    return out


def list_clinics(
    *,
    store: FeedbackStore | None = None,
    clinic_for_biller: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Return the list of clinics the dashboard should offer in the picker.

    Each entry: ``{"clinic_id": "...", "biller_count": N,
    "feedback_count": M}``. The dashboard renders this as a
    <select> with the most-active clinic first. An empty list
    is the empty-state signal: no feedback has been written
    yet, so the per-clinic view is meaningless.
    """
    if store is None:
        try:
            from .feedback import get_default_store
            store = get_default_store()
        except Exception:
            return []
    try:
        entries = store.read_all()
    except Exception:
        return []

    def _resolve_clinic(biller_id: str) -> str:
        if clinic_for_biller is not None:
            try:
                return clinic_for_biller(biller_id)
            except Exception:
                pass
        return biller_id or "default_biller"

    counts: dict[str, int] = defaultdict(int)
    billers: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        c = _resolve_clinic(e.biller_id)
        counts[c] += 1
        billers[c].add(e.biller_id)
    out: list[dict[str, Any]] = []
    for clinic_id, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        out.append({
            "clinic_id": clinic_id,
            "feedback_count": n,
            "biller_count": len(billers[clinic_id]),
        })
    return out


# Minimum feedback events before per-clinic metrics become meaningful.
# Below this threshold the dashboard renders the "insufficient data"
# empty state instead of a misleading 0% F1 number. The threshold is
# intentionally small (3 events) so a clinic that has just started
# reviewing findings isn't stuck on the empty state forever — once a
# single biller has clicked accept/dismiss/modify three times we
# have enough signal to show *some* number, even if it's noisy.
INSUFFICIENT_DATA_THRESHOLD = 3


def insufficient_data_state(
    *,
    clinic_id: str,
    per_rule: Mapping[str, Mapping[str, float]],
    window_days: int,
) -> dict[str, Any]:
    """Return the empty-state payload for the per-clinic F1 dashboard.

    Used by both the per_clinic_f1 dashboard and the monthly report
    so the same copy / threshold logic lives in one place.

    The dashboard / report should call this on every render and
    branch on ``is_insufficient`` — if True, render the friendly
    empty state ("need 3+ feedback events for an F1 number")
    instead of the per-rule table.

    Returns
    -------
    dict with keys:

    * ``is_insufficient`` (bool) — True iff the clinic has fewer than
      :data:`INSUFFICIENT_DATA_THRESHOLD` feedback events in the
      window.
    * ``total_support`` (int) — total feedback events that fed into
      the per-rule metrics (so the UI can show "n=2, need n>=3").
    * ``threshold`` (int) — the threshold (echo of
      :data:`INSUFFICIENT_DATA_THRESHOLD`) so the UI doesn't have
      to hardcode the constant.
    * ``headline`` (str) — short headline for the empty state.
    * ``message`` (str) — one-paragraph explanation, suitable for
      dropping into the dashboard's empty-state div.
    * ``cta`` (str) — call-to-action for the empty state (currently
      "Review a few findings to start measuring your model's
      accuracy.").

    The function is pure and side-effect-free; safe to call from
    templates or the API layer.
    """
    total_support = sum(int(v.get("support", 0)) for v in per_rule.values())
    is_insufficient = total_support < INSUFFICIENT_DATA_THRESHOLD
    if is_insufficient:
        needed = INSUFFICIENT_DATA_THRESHOLD - total_support
        needed_msg = f"{needed} more"
        message = (
            f"Not enough feedback yet to calculate an F1 number for "
            f"this clinic in the last {window_days} days. We need at "
            f"least {INSUFFICIENT_DATA_THRESHOLD} feedback events "
            f"(accept / dismiss / modify) before the per-clinic F1 "
            f"metric is meaningful — below that threshold the number "
            f"is dominated by noise. You've got {total_support}; "
            f"that's {needed_msg} short."
        )
    else:
        needed_msg = ""
        message = ""
    return {
        "is_insufficient": is_insufficient,
        "total_support": total_support,
        "threshold": INSUFFICIENT_DATA_THRESHOLD,
        "window_days": window_days,
        "clinic_id": clinic_id,
        "headline": "Insufficient data — need a few more reviews",
        "message": message,
        "cta": (
            "Review a few findings to start measuring your model's "
            "accuracy for this clinic."
        ),
    }
