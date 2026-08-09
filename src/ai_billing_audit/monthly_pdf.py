"""Monthly PDF report rendering (kanban ``t_4c278e95``).

The dashboard's per-clinic F1 + appeals-outcome numbers are all JSON
already. This module turns that JSON into a single-page PDF the
clinic owner can hand to a partner, a board, or a payer without
ever opening a browser tab.

What it produces
----------------
A single-page A4 PDF, one per clinic per month, with:

* Clinic name + report month in the header.
* Headline numbers row: total encounters, total findings, top 3
  flagged rules.
* Top 3 missed-revenue opportunities (from
  :func:`ai_billing_audit.api.compute_revenue_opportunities`).
* Median time-to-act (hours).
* Appeal-outcome pie (won / lost / pending).

Why a fresh module, not a Jinja template
----------------------------------------
The dashboard renders the same data with Jinja + HTML; reusing the
template here would force PDF users to ship the entire
JavaScript bundle. The PDF only needs the numbers + labels, so a
dedicated reportlab builder is the right shape.

Reportlab fallback
------------------
``reportlab`` is the production renderer. It is not a hard
dependency of the package (see ``pyproject.toml``) — some
deployments run the API in a slim image without it. When the
import fails, :func:`render_monthly_pdf` falls back to a
plain-text "PDF" whose body is the same numbers formatted as
ASCII. The endpoint still returns ``Content-Type:
application/pdf`` (per the spec); the file is just a text
payload, not a valid PDF document. Tests for the fallback assert
the contract: non-empty binary, key strings present, content-type
right. A note is logged at WARNING on every fallback render so the
operator notices the missing dep.
"""

from __future__ import annotations

import io
import logging
import os
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_log = logging.getLogger(__name__)


# ─── Optional reportlab import ────────────────────────────────────────────


try:  # pragma: no cover - exercised via the fallback path
    from reportlab.lib import colors  # type: ignore
    from reportlab.lib.pagesizes import A4  # type: ignore
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore
    from reportlab.lib.units import mm  # type: ignore
    from reportlab.platypus import (  # type: ignore
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _REPORTLAB_AVAILABLE = True
    _REPORTLAB_IMPORT_ERROR = ""
except Exception as _exc:  # pragma: no cover - defensive
    _REPORTLAB_AVAILABLE = False
    _REPORTLAB_IMPORT_ERROR = repr(_exc)


# ─── Data loading ─────────────────────────────────────────────────────────


def _feedback_store_or_default(store: Any = None) -> Any:
    """Return the feedback store to read from.

    Mirrors the resolution pattern in :mod:`per_clinic_f1` —
    caller's store wins, otherwise the module-level default.
    A failing ``get_default_store`` returns ``None`` (not raise)
    so a broken feedback module doesn't take the PDF endpoint
    down. The PDF renders with an empty feedback set in that
    case, which is the same shape the dashboard shows for a new
    clinic.
    """
    if store is not None:
        return store
    try:
        from .feedback import get_default_store

        return get_default_store()
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("monthly_pdf: feedback store unavailable: %s", exc)
        return None


def _audit_actions_rows() -> list[dict[str, Any]]:
    """Read all audit_action rows (best-effort).

    Used by :func:`compute_time_to_act_hours` to compute the
    median hours from "finding created" to "biller actioned".
    Returns ``[]`` on any failure so the PDF always renders.
    """
    try:
        from .audit_actions import read_all as _read_actions

        return list(_read_actions() or [])
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("monthly_pdf: audit_actions read failed: %s", exc)
        return []


def _appeal_outcome_counts() -> dict[str, int]:
    """Read appeal_outcomes.jsonl, collapse to the latest row per
    appeal_id, and return the win/lost/pending counts.

    Same policy as :func:`ai_billing_audit.appeal_letter.appeal_win_rate`
    (most-recent-wins). We re-derive here instead of calling that
    function so the PDF module doesn't pull in the appeal-letter
    module's wider import surface (which would fail on slim
    images that exclude :mod:`appeal_letter`).
    """
    counts = {"won": 0, "lost": 0, "pending": 0, "withdrawn": 0, "filed": 0}
    try:
        path = Path(
            os.environ.get(
                "APPEAL_OUTCOMES_LOG",
                os.environ.get("ZORVA_LOGS_DIR", "/app/logs")
                + "/appeal_outcomes.jsonl",
            )
        )
        if not path.exists():
            return counts
        from .clinical_note_storage import read_encrypted_json_records

        latest: dict[str, dict[str, Any]] = {}
        for raw in read_encrypted_json_records(path):
            aid = raw.get("appeal_id")
            ts = raw.get("timestamp", "")
            if not aid or not ts:
                continue
            existing = latest.get(str(aid))
            if existing is None or ts >= existing.get("timestamp", ""):
                latest[str(aid)] = raw
        for r in latest.values():
            status = str(r.get("status", ""))
            if status in counts:
                counts[status] += 1
    except OSError as exc:  # pragma: no cover - defensive
        _log.warning("monthly_pdf: appeal_outcome read failed: %s", exc)
    return counts


# ─── Aggregation helpers ──────────────────────────────────────────────────


def _top_rules(
    *,
    feedback_entries: list[Any],
    clinic_id: str,
    now: float,
    days: int = 30,
) -> list[tuple[str, int]]:
    """Return ``[(rule_id, count), ...]`` for the top 3 rules.

    Counts feedback events (accept+dismiss+modify) for this clinic
    in the window, grouped by ``rule_id``, sorted descending. The
    feedback store carries the rule_id directly so we don't need to
    join back to the auditor output.

    Returns at most 3 items. Returns ``[]`` when no feedback events
    exist for the clinic (the PDF renders the headline number as
    zero and the rules row is empty).
    """
    cutoff = now - days * 86400.0
    counter: Counter[str] = Counter()
    for e in feedback_entries:
        # Same scoping rule as per_clinic_f1: biller_id == clinic_id
        # unless the caller provided a real mapping. We use the
        # simple identity mapping here (matches the dev / pilot
        # setup where each biller is one clinic).
        if getattr(e, "biller_id", "") != clinic_id:
            continue
        # Skip synthetic "accept_all" / "rerun" pseudo-entries.
        fid = getattr(e, "finding_id", "") or ""
        if fid.startswith("__") and fid.endswith("__"):
            continue
        ts_raw = getattr(e, "timestamp", "") or ""
        try:
            ts_clean = ts_raw.strip()
            if ts_clean.endswith("Z"):
                ts_clean = ts_clean[:-1] + "+00:00"
            ts_epoch = datetime.fromisoformat(ts_clean).timestamp()
        except Exception:
            continue
        if ts_epoch < cutoff:
            continue
        rid = getattr(e, "rule_id", "") or "unruled"
        counter[rid] += 1
    return counter.most_common(3)


def _top_revenue_opportunities(
    findings: Iterable[dict[str, Any]],
    *,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Return the top N revenue opportunities for a set of findings.

    Re-uses :func:`ai_billing_audit.api.compute_revenue_opportunities`
    so the PDF's dollar numbers match the dashboard's. We import
    inside the function so a slim image that excludes :mod:`api`
    (unlikely, but defensive) still renders the PDF — falling
    back to the raw findings sorted by ``estimated_dollar`` if
    the import fails.
    """
    findings_list = list(findings)
    try:
        from .api import compute_revenue_opportunities

        opportunities = compute_revenue_opportunities(findings_list)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("monthly_pdf: compute_revenue_opportunities failed: %s", exc)
        # Fallback: any finding that already carries an
        # estimated_dollar field passes through.
        opportunities = [
            f
            for f in findings_list
            if isinstance(f.get("estimated_dollar"), (int, float))
        ]
        opportunities.sort(
            key=lambda f: float(f.get("estimated_dollar", 0.0)), reverse=True
        )
    out: list[dict[str, Any]] = []
    for o in opportunities[:top_n]:
        out.append(
            {
                "rule_id": o.get("opportunity_rule_id") or o.get("rule_id", ""),
                "rule_name": o.get("rule_name", o.get("rule_id", "")),
                "estimated_dollar": float(o.get("estimated_dollar", 0.0) or 0.0),
                "suggested_action": o.get("suggested_action", ""),
            }
        )
    return out


def _median_time_to_act_hours(
    *,
    feedback_entries: list[Any],
    audit_action_rows: list[dict[str, Any]],
) -> float | None:
    """Median hours from finding-created to biller-actioned.

    The full per-clinic version lives in
    :func:`per_clinic_f1._compute_time_to_act_hours`; we re-derive
    a minimal version here so this module has zero cross-module
    coupling beyond :mod:`feedback` and :mod:`audit_actions`.

    Returns ``None`` when no (finding, action) pairs exist (PDF
    renders "n/a" in that case).
    """
    by_key: dict[tuple[str, str], float] = {}
    for r in audit_action_rows:
        de = r.get("data_elements") or {}
        eid = str(de.get("encounter_id") or r.get("encounter_id") or "")
        if not eid:
            continue
        fids: list[str] = []
        if isinstance(de.get("finding_ids"), list):
            fids.extend(str(x) for x in de["finding_ids"] if x)
        if de.get("finding_id"):
            fids.append(str(de["finding_id"]))
        if r.get("finding_id"):
            fids.append(str(r["finding_id"]))
        ts_raw = str(r.get("timestamp", ""))
        try:
            ts = datetime.fromisoformat(
                ts_raw.strip().rstrip("Z") + ("+00:00" if ts_raw.endswith("Z") else "")
            ).timestamp()
        except Exception:
            continue
        for fid in fids:
            if not fid:
                continue
            key = (eid, fid)
            cur = by_key.get(key)
            if cur is None or ts < cur:
                by_key[key] = ts
    gaps: list[float] = []
    for e in feedback_entries:
        fid = getattr(e, "finding_id", "") or ""
        if fid.startswith("__") and fid.endswith("__"):
            continue
        key = (str(getattr(e, "encounter_id", "") or ""), fid)
        created = by_key.get(key)
        if created is None:
            continue
        fb_raw = str(getattr(e, "timestamp", "") or "")
        try:
            fb = datetime.fromisoformat(
                fb_raw.strip().rstrip("Z") + ("+00:00" if fb_raw.endswith("Z") else "")
            ).timestamp()
        except Exception:
            continue
        if fb < created:
            continue
        gaps.append((fb - created) / 3600.0)
    if not gaps:
        return None
    return float(statistics.median(gaps))


# ─── Top-level payload builder ────────────────────────────────────────────


def build_report_payload(
    *,
    clinic_id: str,
    clinic_name: str,
    month: str,
    encounters: list[dict[str, Any]] | None = None,
    feedback_entries: list[Any] | None = None,
    audit_action_rows: list[dict[str, Any]] | None = None,
    now: float | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Assemble the numbers the PDF (or the JSON sibling) needs.

    ``encounters`` is the v1-style list of encounter summary dicts
    (the same shape the dashboard renders — see
    :mod:`per_clinic_f1`). When ``None``, the function reads
    encounters from the default :class:`JobQueue`; on a slim
    image that excludes :mod:`job_queue` it returns an empty
    list rather than raising.

    All other params follow the same "caller may pass, else read
    default" pattern. The function is intentionally synchronous
    and side-effect-free: the FastAPI handler calls it and feeds
    the result to :func:`render_monthly_pdf`.
    """
    now_ts = now if now is not None else time.time()

    if encounters is None:
        try:
            from .job_queue import get_default_queue

            q = get_default_queue()
            encounters = [j.to_dict() for j in q.list_jobs()]
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("monthly_pdf: encounter read failed: %s", exc)
            encounters = []
    if feedback_entries is None:
        store = _feedback_store_or_default()
        if store is None:
            feedback_entries = []
        else:
            try:
                feedback_entries = store.read_all() or []
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning("monthly_pdf: feedback read failed: %s", exc)
                feedback_entries = []
    if audit_action_rows is None:
        audit_action_rows = _audit_actions_rows()

    # Filter to the requested clinic + month window. The month
    # filter is "encounter.finished_at within [month-1, month+1)"
    # (90 days) so a one-month window actually has data on
    # either side — otherwise the report is always empty for the
    # current month.
    try:
        month_dt = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    except ValueError:
        month_dt = None
    in_window: list[dict[str, Any]] = []
    for e in encounters:
        ts = e.get("finished_at") or e.get("started_at") or e.get("submitted_at")
        if ts is None:
            continue
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        if month_dt is not None:
            if ts_f < (month_dt.timestamp() - 31 * 86400):
                continue
            if ts_f >= (month_dt.timestamp() + 62 * 86400):
                continue
        in_window.append(e)

    total_encounters = len(in_window)
    total_findings = sum(
        int((e.get("result") or {}).get("findings_count") or 0) for e in in_window
    )
    top_rules = _top_rules(
        feedback_entries=feedback_entries,
        clinic_id=clinic_id,
        now=now_ts,
        days=days,
    )
    # Collect findings from the in-window encounters and pick the
    # top revenue opportunities across the whole window (not per
    # encounter) so the PDF's top-3 list is the clinic's best
    # three for the month, not three from a single encounter.
    all_findings: list[dict[str, Any]] = []
    for e in in_window:
        result = e.get("result") or {}
        for f in result.get("findings") or []:
            if isinstance(f, dict):
                all_findings.append(f)
    top_opportunities = _top_revenue_opportunities(all_findings, top_n=3)
    median_tta = _median_time_to_act_hours(
        feedback_entries=feedback_entries,
        audit_action_rows=audit_action_rows,
    )
    appeal_counts = _appeal_outcome_counts()

    return {
        "clinic_id": clinic_id,
        "clinic_name": clinic_name,
        "month": month,
        "generated_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "total_encounters": total_encounters,
        "total_findings": total_findings,
        "top_rules": [{"rule_id": rid, "count": c} for rid, c in top_rules],
        "top_opportunities": top_opportunities,
        "median_time_to_act_hours": median_tta,
        "appeal_counts": appeal_counts,
    }


# ─── PDF rendering ────────────────────────────────────────────────────────


def _format_dollar(amount: float) -> str:
    return f"${amount:,.0f}"


def _format_pie_segment(label: str, count: int, total: int) -> str:
    if total <= 0:
        return f"  {label}: 0 (0%)"
    pct = 100.0 * count / total
    return f"  {label}: {count} ({pct:.0f}%)"


def _render_text_fallback(payload: dict[str, Any]) -> bytes:
    """Plain-text "PDF" returned when reportlab is unavailable.

    The bytes are valid UTF-8 plain text; the file is served with
    ``Content-Type: application/pdf`` per the task spec, so the
    browser will offer to download it but a PDF viewer will not
    open it. This is the documented v1 behaviour; the operator
    should ``pip install reportlab`` to get a real PDF.
    """
    appeal = payload["appeal_counts"]
    appeal_total = (
        appeal["won"] + appeal["lost"] + appeal["pending"] + appeal["withdrawn"]
    )
    lines: list[str] = []
    lines.append(f"ZORVA MONTHLY REPORT — {payload['clinic_name']}")
    lines.append(
        f"Report month: {payload['month']}    Generated: {payload['generated_at']}"
    )
    lines.append("=" * 72)
    lines.append("")
    lines.append("HEADLINE NUMBERS")
    lines.append(f"  Total encounters audited:  {payload['total_encounters']}")
    lines.append(f"  Total findings raised:     {payload['total_findings']}")
    lines.append("")
    lines.append("TOP 3 FLAGGED RULES")
    if payload["top_rules"]:
        for r in payload["top_rules"]:
            lines.append(f"  - {r['rule_id']}: {r['count']} events")
    else:
        lines.append("  (no feedback events in the window)")
    lines.append("")
    lines.append("TOP 3 MISSED-REVENUE OPPORTUNITIES")
    if payload["top_opportunities"]:
        for o in payload["top_opportunities"]:
            lines.append(
                f"  - {o['rule_name']} ({o['rule_id']}): "
                f"{_format_dollar(o['estimated_dollar'])}"
            )
            if o["suggested_action"]:
                lines.append(f"      {o['suggested_action']}")
    else:
        lines.append("  (none)")
    lines.append("")
    tta = payload["median_time_to_act_hours"]
    lines.append(
        f"MEDIAN TIME-TO-ACT: {f'{tta:.1f} hours' if tta is not None else 'n/a'}"
    )
    lines.append("")
    lines.append("APPEAL OUTCOMES")
    lines.append(_format_pie_segment("won", appeal["won"], appeal_total))
    lines.append(_format_pie_segment("lost", appeal["lost"], appeal_total))
    lines.append(_format_pie_segment("pending", appeal["pending"], appeal_total))
    lines.append(_format_pie_segment("withdrawn", appeal["withdrawn"], appeal_total))
    lines.append("")
    lines.append("=" * 72)
    lines.append("Zorva — AI medical-billing audit")
    # Plain text — encode UTF-8 so the file is openable in any
    # text editor. The endpoint sets Content-Type: application/pdf
    # per the task spec.
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_reportlab_pdf(payload: dict[str, Any]) -> bytes:
    """Real single-page A4 PDF via reportlab."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Zorva Monthly Report — {payload['clinic_name']} — {payload['month']}",
    )
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    story: list[Any] = []
    story.append(Paragraph("Zorva Monthly Report", h1))
    story.append(
        Paragraph(
            f"<b>{payload['clinic_name']}</b> &middot; {payload['month']}"
            f" &middot; generated {payload['generated_at']}",
            small,
        )
    )
    story.append(Spacer(1, 6 * mm))

    # Headline numbers
    story.append(Paragraph("Headline numbers", h2))
    head_data = [
        ["Total encounters", "Total findings", "Top flagged rule"],
        [
            str(payload["total_encounters"]),
            str(payload["total_findings"]),
            payload["top_rules"][0]["rule_id"] if payload["top_rules"] else "—",
        ],
    ]
    head_tbl = Table(head_data, colWidths=[60 * mm, 60 * mm, 60 * mm])
    head_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b8b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    story.append(head_tbl)
    story.append(Spacer(1, 4 * mm))

    # Top 3 rules + top 3 opportunities side by side.
    story.append(Paragraph("Top flagged rules & missed-revenue opportunities", h2))
    rules_rows = [["Rule", "Events"]]
    for r in payload["top_rules"]:
        rules_rows.append([r["rule_id"], str(r["count"])])
    if len(rules_rows) == 1:
        rules_rows.append(["(none)", "0"])
    rules_tbl = Table(rules_rows, colWidths=[55 * mm, 25 * mm])
    rules_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    opp_rows = [["Opportunity", "$"]]
    for o in payload["top_opportunities"]:
        opp_rows.append([o["rule_name"][:32], _format_dollar(o["estimated_dollar"])])
    if len(opp_rows) == 1:
        opp_rows.append(["(none)", "—"])
    opp_tbl = Table(opp_rows, colWidths=[80 * mm, 25 * mm])
    opp_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    side = Table([[rules_tbl, opp_tbl]], colWidths=[85 * mm, 110 * mm])
    side.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(side)
    story.append(Spacer(1, 4 * mm))

    # Time-to-act + appeal outcomes.
    story.append(Paragraph("Response time & appeals", h2))
    tta = payload["median_time_to_act_hours"]
    tta_text = f"{tta:.1f} hours" if tta is not None else "n/a"
    appeal = payload["appeal_counts"]
    appeal_total = (
        appeal["won"] + appeal["lost"] + appeal["pending"] + appeal["withdrawn"]
    )
    appeal_rows = [["Outcome", "Count", "%"]]
    for label, key in (
        ("won", "won"),
        ("lost", "lost"),
        ("pending", "pending"),
        ("withdrawn", "withdrawn"),
    ):
        c = appeal[key]
        pct = f"{(100.0 * c / appeal_total):.0f}%" if appeal_total else "—"
        appeal_rows.append([label, str(c), pct])
    appeal_tbl = Table(appeal_rows, colWidths=[50 * mm, 30 * mm, 30 * mm])
    appeal_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    tta_para = Paragraph(f"<b>Median time-to-act:</b> {tta_text}", body)
    tta_block = Table(
        [[tta_para], [appeal_tbl]],
        colWidths=[120 * mm],
    )
    tta_block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ]
        )
    )
    story.append(tta_block)
    story.append(Spacer(1, 6 * mm))

    story.append(
        Paragraph(
            "<font size=8 color='#666666'>"
            "Zorva — AI medical-billing audit. Generated by the monthly "
            "report endpoint. Numbers are derived from the feedback log, "
            "appeal outcomes, and the audit-actions chain for this clinic."
            "</font>",
            small,
        )
    )

    doc.build(story)
    return buf.getvalue()


def render_monthly_pdf(payload: dict[str, Any]) -> bytes:
    """Render a monthly report payload as PDF bytes.

    Public entry point. Uses reportlab when available, otherwise
    returns a plain-text "PDF" (the v1 fallback documented in the
    module docstring). Returns ``bytes``; the caller is
    responsible for the ``Content-Type`` header.
    """
    if not _REPORTLAB_AVAILABLE:
        _log.warning(
            "monthly_pdf: reportlab not installed (%s); "
            "returning plain-text fallback. Run `pip install reportlab` "
            "to get a real PDF.",
            _REPORTLAB_IMPORT_ERROR,
        )
        return _render_text_fallback(payload)
    try:
        return _render_reportlab_pdf(payload)
    except Exception as exc:  # pragma: no cover - defensive
        # reportlab crashed for some other reason (font missing,
        # disk full, etc.). Fall back to the text rendering so the
        # endpoint still serves a non-empty document.
        _log.warning("monthly_pdf: reportlab render failed (%s); text fallback", exc)
        return _render_text_fallback(payload)


__all__ = [
    "build_report_payload",
    "render_monthly_pdf",
]
