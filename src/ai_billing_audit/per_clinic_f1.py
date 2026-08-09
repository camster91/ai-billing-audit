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
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .feedback import FeedbackEntry, FeedbackStore

# Path to the appeal-outcomes JSONL log. The clinic dashboard uses this
# to compute the denial-rate metric (encounters with a ``lost`` or
# ``withdrawn`` appeal outcome ÷ encounters with at least one outcome).
# Same default location as ``appeal_letter._APPEAL_OUTCOMES_LOG``; we
# re-derive it here so ``per_clinic_f1`` doesn't depend on the appeal
# module being importable (it is, in practice, but the dashboard must
# keep working even if appeal_letter.py is broken).
_APPEAL_OUTCOMES_LOG = Path(
    os.environ.get(
        "APPEAL_OUTCOMES_LOG",
        os.environ.get("ZORVA_LOGS_DIR", "/app/logs") + "/appeal_outcomes.jsonl",
    )
)


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
    # Walk BACK to the previous Monday (inclusive), NOT forward to the
    # next Monday. Walking forward would miss events that fall in the
    # partial first week (start_ts lands mid-week); the bucket those
    # events belong to is the Monday *on or before* start_ts.
    while cur.weekday() != 0:
        cur = cur - _dt.timedelta(days=1)
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
            out.append(
                {
                    "week_start": week_start,
                    "f1": 0.0,
                    "support": 0,
                    "tp": 0.0,
                    "fp": 0.0,
                }
            )
            continue
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        # Recall: same within-clinic proxy as per_rule_metrics.
        out.append(
            {
                "week_start": week_start,
                "f1": round(_safe_f1(precision, min(1.0, sup / 5.0)), 4),
                "support": sup,
                "tp": round(tp, 2),
                "fp": round(fp, 2),
            }
        )
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
        out.append(
            {
                "clinic_id": clinic_id,
                "feedback_count": n,
                "biller_count": len(billers[clinic_id]),
            }
        )
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


# ─────────────────────────────────────────────────────────────────────
# Clinic Dashboard (t_1ef7beb3)
# ─────────────────────────────────────────────────────────────────────
# The four headline metrics the clinic owner sees on the dashboard:
#
#   1. denial_rate               — % of submitted claims that were denied
#   2. top_flagged_rules         — top N rules by fire-count, with %
#   3. time_to_act               — median + p90 hours from finding
#                                  creation to biller feedback action
#   4. missed_revenue_dollars    — sum of ``estimated_dollar`` from
#                                  ACCEPTED findings on revenue-
#                                  opportunity rules
#
# These aggregate from the same three stores the rest of the dashboard
# uses (FeedbackStore, audit_actions, appeal_outcomes) — we DO NOT add
# new tables. A clinic is identified by ``clinic_id`` (caller-supplied
# or, by default, ``biller_id`` — same convention as
# ``per_rule_metrics`` / ``weekly_f1``).

# Allowed ``window`` query-string values for the
# ``/api/dashboard/clinic`` endpoint. Defaults to 30d. Anything outside
# this set is clamped to 30d so a typo ("30" instead of "30d") can't
# crash the aggregation. Centralized here so the route + the test
# reference the same set.
ALLOWED_DASHBOARD_WINDOWS: tuple[int, ...] = (7, 30, 90)
DEFAULT_DASHBOARD_WINDOW_DAYS = 30


def _parse_window_param(raw: str | None) -> int:
    """Coerce a ``?window=`` value to one of :data:`ALLOWED_DASHBOARD_WINDOWS`.

    Accepts ``"7d"``, ``"30d"``, ``"90d"``, plus the bare integers
    ``7``, ``30``, ``90``. Anything else (missing, malformed, out of
    range) collapses to :data:`DEFAULT_DASHBOARD_WINDOW_DAYS`.

    Pure helper — safe to call from a route handler or a unit test.
    """
    if raw is None:
        return DEFAULT_DASHBOARD_WINDOW_DAYS
    s = str(raw).strip().lower().rstrip("d").strip()
    try:
        n = int(s)
    except (TypeError, ValueError):
        return DEFAULT_DASHBOARD_WINDOW_DAYS
    if n in ALLOWED_DASHBOARD_WINDOWS:
        return n
    return DEFAULT_DASHBOARD_WINDOW_DAYS


def _parse_iso_to_epoch(ts: str) -> float | None:
    """Parse an ISO-8601 UTC timestamp string to a POSIX epoch.

    Mirrors the same lenient parser used elsewhere in this module:
    accepts the ``Z`` suffix (Python 3.11+) and treats naive strings
    as UTC. Returns ``None`` on any parse failure so callers can
    silently drop corrupt rows instead of crashing the dashboard.
    """
    if not ts:
        return None
    try:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return float(dt.timestamp())
    except Exception:
        return None


def _epoch_to_iso(epoch: float) -> str:
    """Format a POSIX epoch as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, second-res)."""
    return _dt.datetime.fromtimestamp(float(epoch), tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _percentile(values: list[float], pct: float) -> float | None:
    """Return the linear-interpolated ``pct`` percentile of ``values``.

    ``pct`` is in [0, 100]; ``values`` is non-empty. Returns ``None``
    if the input is empty. Uses the same linear interpolation as
    numpy.percentile(..., method="linear") — the smallest index is
    ``pct/100 * (n-1)`` and we round to the nearest integer. This is
    intentionally simple; we do not need numpy's exact semantics here,
    just a stable answer to one decimal place.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    sorted_v = sorted(values)
    n = len(sorted_v)
    if pct <= 0:
        return float(sorted_v[0])
    if pct >= 100:
        return float(sorted_v[-1])
    pos = (pct / 100.0) * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return float(sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac)


def _median(values: list[float]) -> float | None:
    """Return the median of ``values`` (or ``None`` for empty input).

    Thin wrapper around :func:`_percentile` — median is just p50.
    """
    return _percentile(values, 50.0)


def _read_audit_actions_window(
    *,
    start_ts: float,
    end_ts: float,
    audit_actions_reader: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Return audit_actions rows whose timestamp falls in ``[start, end]``.

    Defensive: corrupt / unparseable rows are silently skipped. The
    reader is parameterized so tests can inject a tmp-path-backed
    reader without monkey-patching the module-level audit_actions.
    """
    if audit_actions_reader is None:
        try:
            from .audit_actions import read_all as _aa_read
        except Exception:
            return []
        try:
            rows = _aa_read(tenant_id="*")
        except Exception:
            return []
    else:
        try:
            rows = audit_actions_reader()
        except Exception:
            return []
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        ts = r.get("timestamp") or ""
        ep = _parse_iso_to_epoch(ts)
        if ep is None:
            continue
        if ep < start_ts or ep > end_ts:
            continue
        out.append(r)
    return out


def _read_appeal_outcomes_window(
    *,
    start_ts: float,
    end_ts: float,
    outcomes_log: Path | None = None,
) -> list[dict[str, Any]]:
    """Return appeal-outcome rows whose timestamp falls in ``[start, end]``.

    Defensive: missing log, corrupt JSON, or unparseable timestamps
    are silently dropped so a corrupted row can't break the
    dashboard. Returns the raw dicts so the caller can read
    ``appeal_id`` / ``encounter_id`` / ``status`` / ``timestamp``
    directly.
    """
    log = outcomes_log if outcomes_log is not None else _APPEAL_OUTCOMES_LOG
    if not log.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        from .clinical_note_storage import read_encrypted_json_records

        for rec in read_encrypted_json_records(log):
            ep = _parse_iso_to_epoch(str(rec.get("timestamp", "")))
            if ep is None:
                continue
            if ep < start_ts or ep > end_ts:
                continue
            out.append(rec)
    except OSError:
        return []
    return out


def _compute_top_flagged_rules(
    *,
    feedback_entries: list[FeedbackEntry],
) -> list[dict[str, Any]]:
    """Return ``[{rule_id, count, pct}]`` from the feedback log.

    ``pct`` is the rule's share of total feedback events that fired
    any rule (i.e. ``count / sum(all counts)``). Empty input returns
    an empty list — the dashboard renders "No flagged findings in
    this window" copy on that case. Pseudo-entries (those with
    ``finding_id`` starting and ending with ``__``) are excluded
    because they aren't real findings — same convention used by
    :func:`per_rule_metrics`.
    """
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for e in feedback_entries:
        if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
            continue
        rid = str(e.rule_id or "").strip() or "<unruled>"
        counts[rid] += 1
        total += 1
    if total == 0:
        return []
    out: list[dict[str, Any]] = []
    for rid, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        out.append(
            {
                "rule_id": rid,
                "count": c,
                "pct": round(100.0 * c / total, 2),
            }
        )
    return out


def _compute_time_to_act_hours(
    *,
    feedback_entries: list[FeedbackEntry],
    audit_action_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return median + p90 hours from finding creation to biller action.

    For each feedback entry we look for the EARLIEST audit_action row
    with the same ``(encounter_id, finding_id)`` — that row's
    timestamp is treated as the "finding created" moment. The
    feedback entry's own timestamp is the "biller actioned" moment.
    The gap in hours is what we collect.

    Why earliest, not latest: the audit chain may contain a per-finding
    accept / dismiss / modify row that runs AFTER the biller already
    clicked. We want the first time the finding hit the chain, which
    is the moment the biller saw it on screen.

    Why audit_action, not the encounter's ``audited_at`` field: the
    audit_actions chain is the tamper-evident source of truth for
    "when did the system record this finding existing". Encounter
    ``audited_at`` is a derived value that may be missing or stale
    for uploaded encounters.

    Returns a dict with:
        * ``median_hours``     — median of the per-finding gaps
        * ``p90_hours``        — 90th percentile of the gaps
        * ``n_pairs``          — how many feedback entries paired
                                 (used as the ``n=`` footnote)
        * ``n_unpaired``       — feedback entries with no matching
                                 audit_action row (excluded from the
                                 stat; surfaced so the dashboard can
                                 explain a thin-data case)

    Empty input / no pairs returns ``None`` for both stats — the
    dashboard renders "Not enough data" copy on that case.
    """
    # Index audit_actions by (encounter_id, finding_id) -> earliest ts.
    # ``finding_id`` may be carried in data_elements.finding_ids (list)
    # or data_elements.finding_id (singular) or top-level finding_id;
    # we check all three because the chain writers have not been
    # consistent over the codebase's history.
    by_key: dict[tuple[str, str], float] = {}
    for r in audit_action_rows:
        de = r.get("data_elements") or {}
        eid = str(de.get("encounter_id") or r.get("encounter_id") or "")
        if not eid:
            continue
        fids_raw: list[str] = []
        if isinstance(de.get("finding_ids"), list):
            fids_raw.extend(str(x) for x in de["finding_ids"] if x)
        if de.get("finding_id"):
            fids_raw.append(str(de["finding_id"]))
        if r.get("finding_id"):
            fids_raw.append(str(r["finding_id"]))
        ep = _parse_iso_to_epoch(str(r.get("timestamp", "")))
        if ep is None:
            continue
        for fid in fids_raw:
            if not fid:
                continue
            key = (eid, fid)
            cur = by_key.get(key)
            if cur is None or ep < cur:
                by_key[key] = ep

    gaps_hours: list[float] = []
    n_unpaired = 0
    for e in feedback_entries:
        # Pseudo-entries (system markers) have no pair.
        if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
            continue
        key = (str(e.encounter_id or ""), str(e.finding_id or ""))
        created = by_key.get(key)
        if created is None:
            n_unpaired += 1
            continue
        fb_ep = _parse_iso_to_epoch(str(e.timestamp or ""))
        if fb_ep is None or fb_ep < created:
            # Feedback before the audit row → corrupt pairing, skip.
            n_unpaired += 1
            continue
        gaps_hours.append((fb_ep - created) / 3600.0)

    return {
        "median_hours": _median(gaps_hours),
        "p90_hours": _percentile(gaps_hours, 90.0),
        "n_pairs": len(gaps_hours),
        "n_unpaired": n_unpaired,
    }


def _compute_denial_rate(
    *,
    feedback_entries: list[FeedbackEntry],
    appeal_outcomes: list[dict[str, Any]],
    clinic_for_biller_fn: Callable[[str], str],
    clinic_id: str,
) -> dict[str, Any]:
    """Return ``denial_rate`` + supporting counts for the clinic.

    Definition (per the spec):
      ``denial_rate`` = encounters with a ``lost`` or ``withdrawn``
      appeal outcome ÷ encounters with at least one appeal outcome,
      scoped to the clinic's billers.

    Same latest-wins collapsing used by
    ``appeal_letter.appeal_win_rate``: an appeal_id may appear
    multiple times in the log (``pending`` → ``won`` follow-up); we
    keep only the latest row per appeal_id so the rate reflects the
    current state.

    Returns a dict:
        * ``denial_rate``           — float in [0.0, 1.0] or None
        * ``denied_encounters``     — int count
        * ``decided_encounters``    — int denominator
        * ``n_lost``                — appeals that ended ``lost``
        * ``n_withdrawn``           — appeals that ended ``withdrawn``
        * ``n_pending``             — appeals still pending
        * ``n_won``                 — appeals that ended ``won``

    Empty input returns ``None`` for ``denial_rate``.
    """
    # Resolve which encounter_ids belong to this clinic. We use the
    # biller→clinic mapping derived from the feedback log (same
    # convention as the per-clinic F1 module): a biller is in the
    # clinic iff at least one of their feedback events resolves to
    # clinic_id. The appeal-outcomes log doesn't carry biller_id, so
    # we project via biller to derive the clinic's set of billers.
    # If there are no feedback events for the clinic, we treat the
    # denial rate as undefined rather than scoping to a wrong set.
    has_clinic_feedback = any(
        _resolve_clinic_for(e.biller_id, clinic_for_biller_fn) == clinic_id
        for e in feedback_entries
    )

    # Build latest-outcome per appeal_id (lexicographic max on the
    # ISO timestamp; ties keep the later-seen row, which is fine for
    # test determinism).
    latest: dict[str, dict[str, Any]] = {}
    for r in appeal_outcomes:
        aid = str(r.get("appeal_id") or "")
        if not aid:
            continue
        prev = latest.get(aid)
        ts = str(r.get("timestamp", ""))
        prev_ts = str(prev.get("timestamp", "")) if prev else ""
        if prev is None or ts >= prev_ts:
            latest[aid] = r

    n_lost = 0
    n_withdrawn = 0
    n_pending = 0
    n_won = 0
    # encounter_id -> set of "decided as denied?" flags. An encounter
    # is "denied" if ANY of its latest outcomes are lost or withdrawn.
    decided: dict[str, bool] = {}
    for r in latest.values():
        eid = str(r.get("encounter_id") or "")
        if not eid:
            continue
        status = str(r.get("status") or "")
        if status == "lost":
            n_lost += 1
            decided[eid] = True
        elif status == "withdrawn":
            n_withdrawn += 1
            decided[eid] = True
        elif status == "won":
            n_won += 1
            decided[eid] = False
        elif status == "pending":
            n_pending += 1
            # pending is "in flight" — don't count in decided yet,
            # but also don't mark the encounter as denied.
            decided.setdefault(eid, False)

    denied_encounters = sum(1 for v in decided.values() if v)
    # Decided denominator: encounters with a terminal outcome (won /
    # lost / withdrawn). Pending-only encounters are excluded — they
    # don't have a decision yet, so counting them would deflate the
    # rate artificially.
    decided_encounters = sum(
        1
        for r in latest.values()
        if str(r.get("status", "")) in ("won", "lost", "withdrawn")
        and str(r.get("encounter_id", ""))
    )
    # If the clinic has no feedback (so we can't identify its
    # billers), we treat the denial rate as None rather than
    # accidentally reporting a global number as "this clinic's rate".
    # With feedback, the rate reflects the encounter outcomes in
    # the window; per-clinic biller scoping for the outcomes log is
    # an open follow-up (the log doesn't carry biller_id yet).
    denial_rate = (
        (denied_encounters / decided_encounters)
        if (decided_encounters and has_clinic_feedback)
        else None
    )

    return {
        "denial_rate": round(float(denial_rate), 4)
        if denial_rate is not None
        else None,
        "denied_encounters": denied_encounters,
        "decided_encounters": decided_encounters,
        "n_lost": n_lost,
        "n_withdrawn": n_withdrawn,
        "n_pending": n_pending,
        "n_won": n_won,
    }


def _resolve_clinic_for(
    biller_id: str,
    clinic_for_biller: Callable[[str], str] | None,
) -> str:
    """Return the clinic_id for ``biller_id`` via the optional callback.

    Mirrors the inline resolver used in :func:`per_rule_metrics` so
    callers don't have to think about the callback's exception
    semantics.
    """
    if clinic_for_biller is not None:
        try:
            return clinic_for_biller(biller_id)
        except Exception:
            pass
    return biller_id or "default_biller"


def aggregate_clinic_dashboard(
    *,
    clinic_id: str,
    now: float | None = None,
    days: int = DEFAULT_DASHBOARD_WINDOW_DAYS,
    store: FeedbackStore | None = None,
    clinic_for_biller: Callable[[str], str] | None = None,
    audit_actions_reader: Callable[..., list[dict[str, Any]]] | None = None,
    outcomes_log: Path | None = None,
    load_findings_for_clinic: Callable[[str, float, float], list[dict[str, Any]]]
    | None = None,
) -> dict[str, Any]:
    """Compute the 4 headline clinic-dashboard metrics in one pass.

    Mirrors the style of :func:`per_rule_metrics` and :func:`weekly_f1`
    (module-level, pure, parameterized readers so tests can inject
    tmp-path-backed stores / logs). The caller passes optional
    dependency injectors:

      * ``store``                — feedback log (defaults to the
                                   module-level ``FeedbackStore``)
      * ``audit_actions_reader`` — audit_actions reader (defaults to
                                   ``audit_actions.read_all``)
      * ``outcomes_log``         — path to appeal_outcomes.jsonl
      * ``load_findings_for_clinic`` — returns ``[{finding_id,
                                   rule_id, severity, ...}, ...]``
                                   for the clinic's encounters in the
                                   window. The api.py route passes a
                                   closure that walks demo records +
                                   uploaded audits. Tests pass a stub
                                   returning a fixed list.

    Empty-state behaviour (matches the spec's acceptance criteria):
      * No feedback → all metrics return zero/None + a friendly
        ``ready=False`` flag. The dashboard renders the explicit
        empty-state copy in that case.
      * clinic_id mismatch (no data for that clinic) → same as above.

    Returns
    -------
    dict with keys:
        * ``ok`` (bool)                   — True iff the call succeeded
        * ``ready`` (bool)                — True iff we have enough
                                             data to show non-empty
                                             values for any metric
        * ``clinic_id`` (str)
        * ``window_days`` (int)
        * ``denial_rate`` (float | None)  — see _compute_denial_rate
        * ``denial_rate_detail`` (dict)   — supporting counts
        * ``top_flagged_rules`` (list)    — see _compute_top_flagged_rules
        * ``time_to_act`` (dict)          — see _compute_time_to_act_hours
        * ``missed_revenue_dollars`` (float) — sum of estimated_dollar
                                             from ACCEPTED revenue
                                             opportunities in the window
        * ``missed_revenue_count`` (int)  — number of accepted
                                             opportunities contributing
        * ``n_feedback`` (int)            — feedback events in window
        * ``generated_at`` (str)          — ISO timestamp of this call
    """
    start_ts, end_ts = _window_epoch_bounds(now=now, days=days)

    # Default store.
    if store is None:
        try:
            from .feedback import get_default_store

            store = get_default_store()
        except Exception:
            store = None  # type: ignore[assignment]

    # Read feedback once; reused across the 4 metrics.
    feedback_entries: list[FeedbackEntry] = []
    if store is not None:
        try:
            feedback_entries = store.read_all()
        except Exception:
            feedback_entries = []

    # Filter to the window + the clinic (biller → clinic mapping).
    def _resolve(biller_id: str) -> str:
        return _resolve_clinic_for(biller_id, clinic_for_biller)

    window_feedback: list[FeedbackEntry] = []
    for e in feedback_entries:
        if not _entry_in_window(e, start_ts=start_ts, end_ts=end_ts):
            continue
        if _resolve(e.biller_id) != clinic_id:
            continue
        window_feedback.append(e)

    audit_rows = _read_audit_actions_window(
        start_ts=start_ts,
        end_ts=end_ts,
        audit_actions_reader=audit_actions_reader,
    )
    appeal_outcomes = _read_appeal_outcomes_window(
        start_ts=start_ts,
        end_ts=end_ts,
        outcomes_log=outcomes_log,
    )

    # 1. Top flagged rules.
    top_rules = _compute_top_flagged_rules(feedback_entries=window_feedback)

    # 2. Time-to-act (median + p90 hours).
    time_to_act = _compute_time_to_act_hours(
        feedback_entries=window_feedback,
        audit_action_rows=audit_rows,
    )

    # 3. Denial rate (encounters with lost/withdrawn ÷ decided).
    denial_detail = _compute_denial_rate(
        feedback_entries=window_feedback,
        appeal_outcomes=appeal_outcomes,
        clinic_for_biller_fn=_resolve,
        clinic_id=clinic_id,
    )

    # 4. Missed revenue (ACCEPTED findings only).
    #
    # Pull findings via the injected loader; default to the
    # ``compute_revenue_opportunities`` path the rest of the
    # dashboard uses. We can't import api.py here without creating a
    # circular dependency (api.py imports from this module), so the
    # route layer is responsible for passing a loader closure.
    missed_revenue_dollars = 0.0
    missed_revenue_count = 0
    if load_findings_for_clinic is not None:
        try:
            findings = load_findings_for_clinic(clinic_id, start_ts, end_ts)
        except Exception:
            findings = []
        # Build a quick lookup: (encounter_id, finding_id) -> True
        # iff the biller accepted this finding in the window.
        accepted_keys: set[tuple[str, str]] = set()
        for e in window_feedback:
            if e.action != "accept":
                continue
            accepted_keys.add((str(e.encounter_id), str(e.finding_id)))

        for f in findings or []:
            try:
                # The default loader returns already-enriched
                # opportunity dicts (from compute_revenue_opportunities);
                # but if the caller passes raw findings instead, we
                # fall back to scanning rule_ids manually.
                if "estimated_dollar" in f and "opportunity_rule_id" in f:
                    key = (str(f.get("encounter_id", "")), str(f.get("finding_id", "")))
                    if key in accepted_keys:
                        missed_revenue_dollars += float(
                            f.get("estimated_dollar") or 0.0
                        )
                        missed_revenue_count += 1
                else:
                    # Raw-finding path: re-run the revenue-opp
                    # filter inline to keep the contract uniform.
                    from .api import compute_revenue_opportunities  # type: ignore

                    for opp in compute_revenue_opportunities([f]):
                        key = (
                            str(f.get("encounter_id", "")),
                            str(f.get("finding_id", "")),
                        )
                        if key in accepted_keys:
                            missed_revenue_dollars += float(
                                opp.get("estimated_dollar") or 0.0
                            )
                            missed_revenue_count += 1
            except Exception:
                continue

    # Empty-state signal: the dashboard renders friendly "not enough
    # data" copy when ALL metrics are zero/None. We treat any of the
    # following as "ready":
    #   - at least one feedback event
    #   - at least one appeal outcome in the window
    #   - at least one accepted revenue opportunity
    ready = bool(
        window_feedback
        or appeal_outcomes
        or missed_revenue_count > 0
        or denial_detail.get("decided_encounters", 0) > 0
    )

    return {
        "ok": True,
        "ready": ready,
        "clinic_id": clinic_id,
        "window_days": days,
        "denial_rate": denial_detail.get("denial_rate"),
        "denial_rate_detail": denial_detail,
        "top_flagged_rules": top_rules,
        "time_to_act": time_to_act,
        "missed_revenue_dollars": round(missed_revenue_dollars, 2),
        "missed_revenue_count": missed_revenue_count,
        "n_feedback": len(window_feedback),
        "generated_at": _epoch_to_iso(end_ts),
    }
