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

from typing import Any, Mapping

from .per_clinic_f1 import (
    INSUFFICIENT_DATA_THRESHOLD,
    insufficient_data_state,
    list_clinics,
    per_rule_metrics,
    weekly_f1,
)

__all__ = [
    "INSUFFICIENT_DATA_THRESHOLD",
    "insufficient_data_state",
    "list_clinics",
    "monthly_summary",
    "per_rule_metrics",
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
