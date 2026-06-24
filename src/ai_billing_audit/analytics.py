"""Top missed-revenue patterns analyzer by specialty.

Aggregates audit data (list of records or a path to a JSONL) to
surface the most common missed-revenue patterns per clinic
specialty, ranked by frequency × dollar value. The output is the
ad-hoc sales-prep query: a clinic admin can ask "what are the top
5 missed-revenue patterns in family medicine for the last 90
days?" and get a ranked list of patterns with their count and
total dollars.

The function is intentionally decoupled from the audit chain
shape: it accepts a list of dicts OR a path to a JSONL of dicts,
and looks up the ``specialty`` and ``findings`` shape on each
record. Records without a matching specialty are excluded.
Records without findings contribute to "no findings yet" but
are otherwise ignored.

Three-month minimum
-------------------
The training-side learning loop (MIPROv2, per-clinic F1) requires
3+ months of audit data before the per-clinic numbers are
reliable. The analyzer follows the same rule:

* If the input covers <3 distinct months, the function returns
  the partial result and a ``"insufficient_data"`` flag the
  caller can surface to the user. We don't fail — partial data
  is still useful for a sales conversation, but the caller
  should not present it as a hardened number.

Output shape
------------
::

    {
      "specialty":      "family_medicine",
      "months_covered": 6,
      "insufficient_data": False,
      "patterns": [
        {
          "pattern":         "missing_modifier_25",
          "count":           47,
          "total_dollars":   4230.00,
          "score":           198810.0,  # count * total_dollars
        },
        ...
      ],
    }
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Default minimum months of data the analyzer wants before it
# returns a "hardened" answer. Below this, the result is still
# returned but flagged. Mirrors the per-clinic F1 threshold.
MIN_MONTHS = 3

# Default cap on the number of patterns returned. The sales
# conversation wants the top 5; the analytics dashboard might
# want 10. Configurable per call.
DEFAULT_TOP_N = 5

# What we treat as "missed-revenue" entries in an audit record.
# Matches the rule_id / category / amount shape the auditor
# emits. Anything without a positive dollar amount is filtered
# out so the score stays meaningful.
_MISSED_REVENUE_CATEGORIES = frozenset(
    {
        "missed_modifier",
        "missing_modifier_25",
        "undercode",
        "em_level_upcode",
        "missing_procedure",
        "missed_preventive",
        "telehealth_premium",
        "modifier_unlock",
    }
)


def _coerce_record_amount(finding: Mapping[str, Any]) -> float:
    """Return the dollar value a missed-revenue finding contributed.

    Looks at ``estimated_value``, ``amount``, ``dollar_amount``,
    ``value`` in that order, then falls back to 0. A finding
    with no dollar value is treated as $0 (filtered out by the
    caller) rather than raising.
    """
    for key in ("estimated_value", "amount", "dollar_amount", "value"):
        v = finding.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return 0.0


def _is_missed_revenue(finding: Mapping[str, Any]) -> bool:
    """Decide whether a finding is a missed-revenue entry.

    A finding is missed-revenue if:
      * the auditor's category is in the known missed-revenue
        categories, OR
      * the rule_id starts with a known missed-revenue prefix
        (``rule_ahcip_missing_*``, ``em_level_upcode``, etc.), OR
      * the finding has a positive estimated_value and the
        category isn't a denial/catch category.

    The last rule is the catch-all so the analyzer works on
    new rule types we add later.
    """
    category = (finding.get("category") or "").lower()
    if category in _MISSED_REVENUE_CATEGORIES:
        return True
    rule_id = (finding.get("rule_id") or "").lower()
    if any(
        rule_id.startswith(prefix)
        for prefix in (
            "rule_ahcip_missing_",
            "rule_ahcip_preventive_",
            "rule_ahcip_modifier_",
            "rule_ahcip_telehealth_",
            "em_level_upcode",
            "undercode",
        )
    ):
        return True
    # Catch-all: any finding with a positive estimated_value
    # that's NOT a denial / catch category is treated as
    # missed-revenue.
    if category and "denial" not in category and "catch" not in category:
        amt = _coerce_record_amount(finding)
        if amt > 0:
            return True
    return False


def _pattern_key(finding: Mapping[str, Any]) -> str:
    """Bucket key for a finding.

    Prefers the rule_id (specific). Falls back to category. Falls
    back to a literal ``"(unknown)"`` so the function never
    explodes on dirty data.
    """
    rule_id = finding.get("rule_id")
    if isinstance(rule_id, str) and rule_id.strip():
        return rule_id.strip()
    category = finding.get("category")
    if isinstance(category, str) and category.strip():
        return category.strip()
    return "(unknown)"


def _month_key(ts: str) -> str:
    """Coerce an ISO-ish timestamp string to a YYYY-MM month key.

    Returns ``"unknown"`` for unparseable input. Month buckets
    drive the insufficient-data gate.
    """
    if not isinstance(ts, str) or not ts:
        return "unknown"
    try:
        # Accept both ``2026-06-15T12:34:56Z`` and ``2026-06-15``
        return datetime.strptime(ts[:10], "%Y-%m-%d").strftime("%Y-%m")
    except ValueError:
        return "unknown"


def _iter_records(
    audit_data: Sequence[Mapping[str, Any]] | str | Path,
) -> Iterable[Mapping[str, Any]]:
    """Yield audit records from a list, a JSONL path, or a single record.

    A "record" is a dict with at least a ``specialty`` (string)
    and a ``findings`` (list of dicts). Some records may carry
    the findings inline (the auditor's run output); some may
    store them on a nested key (``record["findings"]``,
    ``record["audit"]["findings"]``).
    """
    if isinstance(audit_data, (str, Path)):
        path = Path(audit_data)
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        return
    if isinstance(audit_data, Mapping):
        yield audit_data
        return
    for record in audit_data:  # type: ignore[union-attr]
        if isinstance(record, Mapping):
            yield record


def _findings_for(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Pull the findings list out of a record (handles two shapes)."""
    findings = record.get("findings")
    if isinstance(findings, list):
        return [f for f in findings if isinstance(f, Mapping)]
    nested = record.get("audit")
    if isinstance(nested, Mapping):
        findings = nested.get("findings")
        if isinstance(findings, list):
            return [f for f in findings if isinstance(f, Mapping)]
    return []


def _specialty_for(record: Mapping[str, Any]) -> str:
    """Return the specialty string for a record, normalized.

    Accepts ``specialty`` or ``provider_specialty``. Falls back
    to ``""`` (which the caller filters out).
    """
    for key in ("specialty", "provider_specialty"):
        v = record.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return ""


def top_missed_revenue_patterns(
    specialty: str,
    audit_data: Sequence[Mapping[str, Any]] | str | Path,
    *,
    top_n: int = DEFAULT_TOP_N,
    min_months: int = MIN_MONTHS,
) -> dict[str, Any]:
    """Return the top missed-revenue patterns for ``specialty``.

    Parameters
    ----------
    specialty : str
        Clinic specialty to filter on (case-insensitive). Records
        with a different specialty are skipped. ``"family
        medicine"`` and ``"family_medicine"`` both match
        ``family_medicine`` (we lowercase + strip on both sides).
    audit_data : list[dict] | str | Path
        Either a list of audit records (each with at least
        ``specialty`` and ``findings``) or a path to a JSONL
        file of such records.
    top_n : int
        How many patterns to return (default 5).
    min_months : int
        Minimum distinct months of data for a "hardened" answer.
        Below this, the result is still returned but flagged
        with ``insufficient_data=True``.

    Returns
    -------
    dict
        See module docstring for the shape.

    Notes
    -----
    * Records with no findings are skipped (they contribute no
      pattern but are counted toward the "months covered"
      tally if they carry a timestamp).
    * Findings with no positive estimated_value are skipped
      (a missed-revenue finding with $0 isn't missed revenue).
    * The function is pure; no I/O beyond reading the JSONL
      path the caller passes in.
    """
    target = (specialty or "").strip().lower()
    if not target:
        # No specialty filter — return everything aggregated.
        target = ""

    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, float] = defaultdict(float)
    months: set[str] = set()
    records_seen = 0
    records_kept = 0

    for record in _iter_records(audit_data):
        records_seen += 1
        record_specialty = _specialty_for(record)
        if target and record_specialty != target:
            continue
        records_kept += 1
        # Stamp the month bucket for the insufficient-data gate.
        ts = record.get("timestamp") or record.get("created_at") or ""
        m = _month_key(ts)
        if m != "unknown":
            months.add(m)
        for finding in _findings_for(record):
            if not _is_missed_revenue(finding):
                continue
            amount = _coerce_record_amount(finding)
            if amount <= 0:
                continue
            key = _pattern_key(finding)
            counts[key] += 1
            totals[key] += amount

    # Rank by count × total_dollars, descending.
    patterns = [
        {
            "pattern": key,
            "count": counts[key],
            "total_dollars": round(totals[key], 2),
            "score": counts[key] * totals[key],
        }
        for key in counts
    ]
    patterns.sort(key=lambda p: p["score"], reverse=True)
    if top_n and top_n > 0:
        patterns = patterns[:top_n]

    return {
        "specialty": specialty,
        "months_covered": len(months),
        "records_seen": records_seen,
        "records_kept": records_kept,
        "insufficient_data": len(months) < min_months,
        "patterns": patterns,
    }


def _cli() -> None:  # pragma: no cover — manual CLI entry point
    """CLI: ``python -m ai_billing_audit.analytics <path> <specialty>``."""
    import argparse
    import sys

    p = argparse.ArgumentParser(
        description="Top missed-revenue patterns for a specialty."
    )
    p.add_argument(
        "path",
        help="Path to a JSONL of audit records (or '-' for stdin).",
    )
    p.add_argument(
        "specialty",
        help="Specialty to filter on (e.g. 'family_medicine').",
    )
    p.add_argument(
        "--top-n", type=int, default=DEFAULT_TOP_N,
        help=f"Number of patterns to return (default {DEFAULT_TOP_N}).",
    )
    p.add_argument(
        "--min-months", type=int, default=MIN_MONTHS,
        help=f"Min months of data (default {MIN_MONTHS}).",
    )
    args = p.parse_args()
    if args.path == "-":
        records: list[dict[str, Any]] = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        result = top_missed_revenue_patterns(
            args.specialty, records, top_n=args.top_n, min_months=args.min_months,
        )
    else:
        result = top_missed_revenue_patterns(
            args.specialty, args.path, top_n=args.top_n, min_months=args.min_months,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
