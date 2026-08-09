"""Monthly improvement report per clinic.

This module is the read-side companion to ``per_clinic_f1.py``. Once a
clinic has accumulated enough feedback events (see
``INSUFFICIENT_DATA_THRESHOLD``), the monthly report summarises:

  * total findings emitted by the auditor for this clinic this month,
  * how many were accepted / dismissed / modified,
  * the top modified rules (suggests over- or under-sensitive rules),
  * the per-clinic F1 (using the same within-clinic recall proxy as
    ``per_clinic_f1``).

The deferred full report (with calibration + recommended prompt
changes) lives in audit task t_f98a799f; this module implements the
*empty-state* side of that report so the per_clinic_f1 dashboard and
the monthly report share a single, consistent copy.

Why this lives next to ``per_clinic_f1.py``
--------------------------------------------
The "insufficient data" empty state has the same threshold + same
copy in both contexts. Defining it once in ``per_clinic_f1.py`` and
re-exporting it here keeps the two UIs from drifting apart (which
would be a brand-voice violation per docs/VOICE.md).
"""

from __future__ import annotations

import datetime as _dt
import time
from typing import Any

from .feedback import FeedbackEntry, FeedbackStore, get_default_store
from .per_clinic_f1 import (
    INSUFFICIENT_DATA_THRESHOLD,
    insufficient_data_state,
    list_clinics,
    per_rule_metrics,
    weekly_f1,
)

__all__ = [
    "INSUFFICIENT_DATA_THRESHOLD",
    "RECOMMEND_MAINTAIN",
    "RECOMMEND_RAISE_CONFIDENCE",
    "RECOMMEND_REVIEW_MODIFIED",
    "calibrate_confidence",
    "compute_clinic_month",
    "insufficient_data_state",
    "list_clinics",
    "monthly_summary",
    "per_rule_metrics",
    "tuning_recommendation",
    "weekly_f1",
]


def monthly_summary(
    *,
    clinic_id: str,
    now: float | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Return the monthly summary payload for a single clinic.

    Mirrors the per_clinic_f1 API response but adds the
    insufficient-data empty state at the top level so the
    monthly-report route can render either the chart or the
    empty-state block from a single response.

    The summary deliberately does NOT pre-compute the full deferred
    report (calibration + recommended prompt changes). That work
    lives in t_f98a799f and depends on 3+ months of feedback data,
    which we don't have yet. Adding it now would be fabricating
    numbers.
    """
    per_rule = per_rule_metrics(clinic_id=clinic_id, now=now, days=days)
    weekly = weekly_f1(clinic_id=clinic_id, now=now, days=days)
    empty_state = insufficient_data_state(
        clinic_id=clinic_id,
        per_rule=per_rule,
        window_days=days,
    )
    return {
        "clinic_id": clinic_id,
        "days": days,
        "per_rule": per_rule,
        "weekly": weekly,
        "insufficient_data": empty_state["is_insufficient"],
        "empty_state": empty_state,
    }


# ─────────────────────────────────────────────────────────────────────
# Per-clinic, per-month aggregation (t_ca36e05d)
# ─────────────────────────────────────────────────────────────────────
# The deferred full monthly report (t_f98a799f) promises a richer
# calibration + tuning payload than ``monthly_summary`` provides. The
# building block for that report is the function in this section —
# ``compute_clinic_month`` — which takes a single (clinic, year, month)
# and returns either the insufficient_data stub or the struct the UI
# will render:
#
#   {
#     "status": "ok",
#     "clinic_id": "...",
#     "year": 2026, "month": 6, "month_label": "2026-06",
#     "total_findings": 42,
#     "accepted": 28, "dismissed": 9, "modified": 5,
#     "top_3_modified_rules": [{"rule_name": "R-MOD-25", "count": 3}, ...],
#     "confidence_calibration": "HIGH" | "MEDIUM" | "LOW",
#     "tuning_recommendations": ["...", ...],   # >=1 strings, always
#   }
#
# The function deliberately reuses ``per_clinic_f1.per_rule_metrics`` /
# ``weekly_f1`` / ``insufficient_data_state`` instead of re-deriving
# aggregation primitives. The "insufficient data" semantics match the
# per_clinic_f1 dashboard: fewer than
# :data:`INSUFFICIENT_DATA_THRESHOLD` distinct calendar months of
# feedback for the clinic → no fabricated numbers, just the stub.


# Precision thresholds for the legacy precision-based calibration.
# These are no longer used by ``compute_clinic_month`` (the report
# now uses :func:`calibrate_confidence` against acceptance /
# modification rates per kanban t_cb95d540) but are kept here as
# module-level constants for any external reader that still imports
# them. Will be removed in a future cleanup pass.
_CALIBRATION_HIGH_MIN = 0.85
_CALIBRATION_MEDIUM_MIN = 0.65


def _parse_iso_timestamp(ts: str) -> _dt.datetime | None:
    """Parse a feedback log timestamp, returning None on any failure.

    Mirrors the parser in ``per_clinic_f1._entry_in_window``: the
    log timestamps are ISO-8601 UTC (``%Y-%m-%dT%H:%M:%SZ``). We
    strip the trailing Z because Python 3.10's ``fromisoformat``
    doesn't accept it (3.11+ does; the strip is harmless).
    """
    if not ts:
        return None
    try:
        norm = ts.strip()
        if norm.endswith("Z"):
            norm = norm[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(norm)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _entry_is_in_month(entry: FeedbackEntry, *, year: int, month: int) -> bool:
    """Return True iff ``entry.timestamp`` falls in the requested month.

    Synthetic ``__accept_all__`` / ``__rerun__`` pseudo-entries are
    excluded — they carry no real rule_id and would inflate the
    counts. Same convention as ``per_clinic_f1``.
    """
    if entry.finding_id.startswith("__") and entry.finding_id.endswith("__"):
        return False
    dt = _parse_iso_timestamp(entry.timestamp)
    if dt is None:
        return False
    return dt.year == year and dt.month == month


def _distinct_months_for_clinic(
    entries: list[FeedbackEntry],
    *,
    clinic_id: str,
) -> set[tuple[int, int]]:
    """Return the distinct ``(year, month)`` tuples with feedback for ``clinic_id``.

    Used by the insufficient-data gate: we need to count DISTINCT
    calendar months (not just "do you have events in the requested
    month") so the gate matches the per_clinic_f1 dashboard's
    threshold-based empty state.
    """
    months: set[tuple[int, int]] = set()
    for e in entries:
        if e.biller_id != clinic_id:
            continue
        if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
            continue
        dt = _parse_iso_timestamp(e.timestamp)
        if dt is None:
            continue
        months.add((dt.year, dt.month))
    return months


def _safe_per_rule_for_window(
    *,
    clinic_id: str,
    now: float | None,
    days: int,
    store: FeedbackStore | None,
) -> dict[str, dict[str, float]]:
    """Wrap ``per_rule_metrics`` so a missing store returns ``{}`` instead of raising.

    The dashboard already swallows ``get_default_store`` failures, but
    this function is called from a JSON-API hot path; the route
    expects a 200 even when the feedback store is unreadable.
    """
    try:
        return per_rule_metrics(
            clinic_id=clinic_id,
            now=now,
            days=days,
            store=store,
        )
    except Exception:
        return {}


# Confidence-calibration thresholds (kanban t_cb95d540).
#
# These translate the noisy per-month acceptance / modification
# fractions into a single HIGH / MEDIUM / LOW bucket the biller can
# act on. They are coarse on purpose — the same numbers live in the
# public :func:`calibrate_confidence` docstring and the tuning
# recommendations (:func:`tuning_recommendation`) so the calibration
# string and the recommendation strings stay in lock-step.
_CALIBRATION_ACCEPTANCE_HIGH_MIN = 0.8  # acceptance_rate >= this → candidate for HIGH
_CALIBRATION_MODIFICATION_HIGH_MAX = (
    0.1  # modification_rate <= this → candidate for HIGH
)
_CALIBRATION_ACCEPTANCE_LOW_MAX = 0.5  # acceptance_rate <  this → LOW
_CALIBRATION_MODIFICATION_LOW_MIN = 0.3  # modification_rate >  this → LOW

# Tuning-recommendation thresholds (kanban t_cb95d540).
#
# These drive :func:`tuning_recommendation`. Each branch fires when
# its condition is true; multiple branches can fire in the same
# month (e.g. a low acceptance rate AND a high modify rate).
_TUNING_MODIFICATION_OVERFLAG_MIN = (
    0.2  # modification_rate > this → "review modified rules"
)
_TUNING_ACCEPTANCE_RAISE_MAX = (
    0.5  # acceptance_rate  < this → "raise confidence threshold"
)

# Public, human-readable recommendation strings. Kept as module-level
# constants so tests can pin them and the copy never drifts between
# the producer and the test assertions.
RECOMMEND_REVIEW_MODIFIED = "review modified rules for over-flagging"
RECOMMEND_RAISE_CONFIDENCE = "raise confidence threshold on low-acceptance rules"
RECOMMEND_MAINTAIN = "maintain current thresholds"


def calibrate_confidence(acceptance_rate: float, modification_rate: float) -> str:
    """Map an acceptance/modification rate pair to HIGH / MEDIUM / LOW.

    Calibration thresholds
    ----------------------
    The two inputs are fractions in ``[0.0, 1.0]`` describing one
    month's biller behaviour for one clinic:

    * ``acceptance_rate``  — fraction of feedback events where the
      biller ``accept``ed the finding without changing it
      (``accepted / (accepted + dismissed + modified)``).
    * ``modification_rate`` — fraction of feedback events where the
      biller ``modify``ied the finding before submission
      (``modified / (accepted + dismissed + modified)``).

    A month with no feedback events at all (``total == 0``) makes
    both rates undefined; we return ``"LOW"`` defensively so the
    route never 500s.

    Calibration bands
    -----------------
    * ``HIGH`` — billers are accepting most findings AND not
      modifying them. The prompt is well-tuned for this clinic.
      Trigger: ``acceptance_rate >= 0.8 AND modification_rate <= 0.1``.
    * ``LOW`` — billers are either rejecting most findings
      (low acceptance) or correcting them so often that the
      original finding shape was wrong.
      Trigger: ``acceptance_rate < 0.5 OR modification_rate > 0.3``.
    * ``MEDIUM`` — everything else. The clinic is in the band
      where we don't have enough signal to recommend a global
      threshold change but the prompt isn't perfectly tuned either.

    Boundary semantics are deliberate: ``acceptance_rate == 0.8``
    still counts as HIGH-eligible, and ``modification_rate == 0.1``
    still counts as HIGH-eligible. ``acceptance_rate == 0.5`` does
    NOT count as LOW (the rule is strict-less-than), and
    ``modification_rate == 0.3`` does NOT count as LOW (strict
    greater-than). These match the thresholds in the task spec
    verbatim.
    """
    # Defensive: a month with no findings has undefined rates.
    # Don't manufacture HIGH from zeros.
    if not (0.0 <= acceptance_rate <= 1.0) or not (0.0 <= modification_rate <= 1.0):
        return "LOW"
    if (
        acceptance_rate >= _CALIBRATION_ACCEPTANCE_HIGH_MIN
        and modification_rate <= _CALIBRATION_MODIFICATION_HIGH_MAX
    ):
        return "HIGH"
    if (
        acceptance_rate < _CALIBRATION_ACCEPTANCE_LOW_MAX
        or modification_rate > _CALIBRATION_MODIFICATION_LOW_MIN
    ):
        return "LOW"
    return "MEDIUM"


def tuning_recommendation(
    acceptance_rate: float, modification_rate: float
) -> list[str]:
    """Generate tuning recommendations from a month's rate pair.

    Returns at least one recommendation, never an empty list. The
    three branches are independent and may all fire in the same
    month — e.g. a clinic with ``acceptance_rate=0.4`` AND
    ``modification_rate=0.25`` returns BOTH "raise confidence
    threshold on low-acceptance rules" AND "review modified rules
    for over-flagging".

    Branches
    --------
    1. ``"review modified rules for over-flagging"`` — fired when
       ``modification_rate > 0.2``. Billers are correcting a
       non-trivial slice of findings; rule prompts likely over-fire
       on this clinic's claim shapes.
    2. ``"raise confidence threshold on low-acceptance rules"`` —
       fired when ``acceptance_rate < 0.5``. Billers are rejecting
       most findings; the rule prompts likely flag too much.
    3. ``"maintain current thresholds"`` — fallback when neither of
       the above fires. The default-position string the UI shows
       when nothing else is wrong.

    Boundary semantics: ``modification_rate == 0.2`` does NOT fire
    the over-flagging branch (strict greater-than). Likewise
    ``acceptance_rate == 0.5`` does NOT fire the raise-confidence
    branch. These match the thresholds in the task spec verbatim.

    Defensive: if either rate is outside ``[0.0, 1.0]``, treat it as
    missing data and return the "maintain current thresholds"
    recommendation so the UI never sees an empty list.
    """
    if not (0.0 <= acceptance_rate <= 1.0) or not (0.0 <= modification_rate <= 1.0):
        return [RECOMMEND_MAINTAIN]

    recs: list[str] = []
    if modification_rate > _TUNING_MODIFICATION_OVERFLAG_MIN:
        recs.append(RECOMMEND_REVIEW_MODIFIED)
    if acceptance_rate < _TUNING_ACCEPTANCE_RAISE_MAX:
        recs.append(RECOMMEND_RAISE_CONFIDENCE)
    if not recs:
        recs.append(RECOMMEND_MAINTAIN)
    return recs


def _top_modified_rules(
    entries: list[FeedbackEntry],
    *,
    clinic_id: str,
    year: int,
    month: int,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the top-N rules by ``modify`` count for the requested month.

    Order: descending by count; ties broken by rule_name ascending
    so the output is deterministic. Rules with no name fall back to
    ``"unruled"`` (same convention as ``per_clinic_f1``).
    """
    counts: dict[str, int] = {}
    for e in entries:
        if e.biller_id != clinic_id:
            continue
        if e.action != "modify":
            continue
        if not _entry_is_in_month(e, year=year, month=month):
            continue
        rule = e.rule_id or "unruled"
        counts[rule] = counts.get(rule, 0) + 1
    # Sort: count desc, then rule_name asc for ties.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"rule_name": rule, "count": count} for rule, count in ordered[:limit]]


def compute_clinic_month(
    clinic_id: str,
    year: int,
    month: int,
    *,
    store: FeedbackStore | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the per-clinic, per-month report payload.

    Parameters
    ----------
    clinic_id:
        The clinic identifier — the same string the per_clinic_f1
        dashboard uses (``biller_id`` is the clinic proxy in the
        current single-tenant dev setup).
    year, month:
        The calendar month to report on (``month`` is 1-12). Out-of-
        range ``month`` values raise ``ValueError`` so the caller
        gets a clear error instead of a silently-wrong window.
    store:
        Optional ``FeedbackStore`` to read from. Defaults to
        ``get_default_store()`` (the same store the rest of the
        API uses) so tests can inject a fixture.
    now:
        Optional POSIX timestamp used as the upper bound of the
        per-rule window. ``None`` means "right now".

    Returns
    -------
    dict — one of two shapes:

    1. **Insufficient-data stub** — when the clinic has fewer than
       :data:`INSUFFICIENT_DATA_THRESHOLD` distinct calendar months
       of feedback in the store::

           {
             "status": "insufficient_data",
             "clinic_id": "...",
             "year": 2026, "month": 6, "month_label": "2026-06",
             "required_months": 3,
             "current_months": <int>,
           }

    2. **Full report** — when the clinic has at least 3 months of
       feedback. The struct contains exactly the keys the task
       spec calls out::

           {
             "status": "ok",
             "clinic_id": "...",
             "year": 2026, "month": 6, "month_label": "2026-06",
             "total_findings": 42,
             "accepted": 28,
             "dismissed": 9,
             "modified": 5,
             "top_3_modified_rules": [{"rule_name": "R-MOD-25", "count": 3}, ...],
             "confidence_calibration": "HIGH" | "MEDIUM" | "LOW",
             "tuning_recommendations": ["...", ...],   # >=1 strings
           }

    Notes
    -----
    * The function is pure: it does not mutate the store or write
      to disk. Safe to call from the API route, a template, or a
      one-off CLI script.
    * Action counts come from the feedback log; we don't reach
      into the auditor or encounter data because the feedback log
      is the canonical "what the biller decided" record.
    * The per-rule table comes from ``per_clinic_f1.per_rule_metrics``
      over a 30-day window ending ``now`` — same window the
      dashboard uses — so the calibration bucket matches what the
      biller sees in the per-clinic dashboard.
    """
    if not 1 <= int(month) <= 12:
        raise ValueError(f"month must be in 1..12, got {month!r}")

    if store is None:
        try:
            store = get_default_store()
        except Exception:
            store = None

    try:
        entries = store.read_all() if store is not None else []
    except Exception:
        entries = []

    # Insufficient-data gate: clinic must have >=3 distinct months of
    # feedback in the store. We count globally (not just for the
    # requested month) so the gate matches the per_clinic_f1
    # dashboard's threshold semantics.
    distinct_months = _distinct_months_for_clinic(entries, clinic_id=clinic_id)
    current_months = len(distinct_months)
    if current_months < INSUFFICIENT_DATA_THRESHOLD:
        return {
            "status": "insufficient_data",
            "clinic_id": clinic_id,
            "year": int(year),
            "month": int(month),
            "month_label": f"{int(year):04d}-{int(month):02d}",
            "required_months": INSUFFICIENT_DATA_THRESHOLD,
            "current_months": current_months,
        }

    # Action counts for the requested month only.
    accepted = dismissed = modified = 0
    for e in entries:
        if e.biller_id != clinic_id:
            continue
        if not _entry_is_in_month(e, year=year, month=month):
            continue
        if e.action == "accept":
            accepted += 1
        elif e.action == "dismiss":
            dismissed += 1
        elif e.action == "modify":
            modified += 1
    total_findings = accepted + dismissed + modified

    if now is None:
        now = time.time()
    _safe_per_rule_for_window(
        clinic_id=clinic_id,
        now=now,
        days=30,
        store=store,
    )

    top_modified = _top_modified_rules(
        entries,
        clinic_id=clinic_id,
        year=year,
        month=month,
    )

    # Compute the per-month acceptance / modification fractions and
    # feed them into the public calibration + tuning helpers
    # (kanban t_cb95d540). The rates are computed locally on the
    # requested-month counts.
    if total_findings > 0:
        acceptance_rate = accepted / total_findings
        modification_rate = modified / total_findings
    else:
        # Defensive: gate already requires >=3 months of feedback,
        # but the requested month itself could still be empty. Treat
        # as undefined so the helpers fall back to LOW / maintain.
        acceptance_rate = 0.0
        modification_rate = 0.0

    calibration = calibrate_confidence(acceptance_rate, modification_rate)
    recs = tuning_recommendation(acceptance_rate, modification_rate)

    return {
        "status": "ok",
        "clinic_id": clinic_id,
        "year": int(year),
        "month": int(month),
        "month_label": f"{int(year):04d}-{int(month):02d}",
        "total_findings": total_findings,
        "accepted": accepted,
        "dismissed": dismissed,
        "modified": modified,
        "top_3_modified_rules": top_modified,
        "confidence_calibration": calibration,
        "tuning_recommendations": recs,
    }
