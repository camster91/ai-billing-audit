"""Doctor-side view, suggestions, positive feedback, and effectiveness metrics.

Kanban boards covered:

* t_af26abdb — Doctor dashboard view (separate from biller's)
* t_df188436 — Doctor-side 'add this to your note' suggestion
* t_f5ea3bf2 — Doctor 'fix-it' workflow (re-audit on note update)
* t_585dcaed — Doctor sees BOTH the flag and the positive feedback
* t_267a1ad6 — Doctor effectiveness metric ("12% better than last quarter")

The doctor-facing experience is intentionally different from the
biller's. Billers see counts ("14 findings, 4 awaiting review").
Doctors see personalised narratives ("you have 3 notes this week
that need a quick fix", "you wrote 47 clean notes, saved $9,200").

This module owns the data shaping:

* ``doctor_encounters_for(provider_npi, audit_log, *, lookback_days=14)``
  — encounters where this provider is the rendering provider,
  with only the doctor-relevant facts: 1-sentence what's-wrong,
  copy-pastable fix, severity. NO billing codes, NO dollar amounts
  on the finding-detail (positive framing only).

* ``suggest_fix_for(finding)`` — the exact "add this sentence to
  your note" copy-pastable line. Builds on the
  ``doctor_email.specialty_fix_suggestion`` heuristic but
  surfaces the text directly so the doctor can paste it.

* ``fixit_reaudit_payload(encounter_id, updated_note_text)`` —
  the re-audit job the "note updated, please re-audit" button
  queues. Returns the payload, doesn't call the queue.

* ``doctor_weekly_digest(provider_npi, audit_log, ...)`` —
  positive + negative framing for the weekly email.

* ``doctor_effectiveness(provider_npi, audit_log, *, prior_window_days=90)``
  — the "your notes are 12% better than last quarter" metric.

All functions are pure: they take data in, return dicts out. No
side effects, no I/O. The FastAPI surface wires them up.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

# ---------------------------------------------------------------------------
# Doctor-encounter view
# ---------------------------------------------------------------------------


def doctor_encounters_for(
    provider_npi: str,
    audit_log: Iterable[dict[str, Any]],
    *,
    lookback_days: int = 14,
    now_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Return doctor-shaped encounters for ``provider_npi``.

    Filters to encounters where this provider is the rendering
    provider. For each encounter, returns:

    * ``encounter_id``
    * ``date_of_service``
    * ``patient_label`` — anonymised ("the patient", never name)
    * ``what_wrong`` — 1 sentence or "" if clean
    * ``fix_suggestion`` — copy-pastable line or "" if clean
    * ``severity`` — "high" | "medium" | "low"
    * ``needs_fix`` — bool

    Encounters with zero findings appear too — but with empty
    ``what_wrong`` / ``fix_suggestion`` and ``needs_fix=False``.
    That way the doctor sees "you wrote 8 clean notes this week"
    just by counting rows.
    """
    if not provider_npi:
        return []
    now = now_ts if now_ts is not None else time.time()
    cutoff = now - (lookback_days * 86_400)
    out: list[dict[str, Any]] = []
    for enc in audit_log:
        if enc.get("provider_npi") != provider_npi:
            continue
        # Date filter — fall back to last_modified if DOS missing
        date_ref = enc.get("date_of_service") or enc.get("last_modified") or ""
        try:
            from_ts = _parse_iso(date_ref)
        except ValueError:
            from_ts = 0.0
        if from_ts and from_ts < cutoff:
            continue
        findings = enc.get("findings") or []
        if findings:
            top = _worst_finding(findings)
            what_wrong = _one_sentence_what_wrong(top)
            fix = _one_sentence_fix(top)
            severity = str(top.get("severity", "medium"))
            needs_fix = True
        else:
            what_wrong = ""
            fix = ""
            severity = ""
            needs_fix = False
        out.append(
            {
                "encounter_id": str(enc.get("encounter_id", "")),
                "date_of_service": str(enc.get("date_of_service", "")),
                "patient_label": enc.get("patient_label", "the patient"),
                "what_wrong": what_wrong,
                "fix_suggestion": fix,
                "severity": severity,
                "needs_fix": needs_fix,
            }
        )
    # Most-recent first
    out.sort(key=lambda r: r["date_of_service"], reverse=True)
    return out


def _worst_finding(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the worst (highest severity) finding."""
    order = {"high": 3, "medium": 2, "low": 1}
    return max(findings, key=lambda f: order.get(str(f.get("severity", "low")).lower(), 0))


def _one_sentence_what_wrong(finding: dict[str, Any]) -> str:
    """Plain-English 1-sentence reason. No CPT / ICD jargon."""
    rule = str(finding.get("rule_id", ""))
    body = str(finding.get("body_site") or finding.get("anatomic_site") or "").strip()
    if rule == "MOD-25":
        return "Today's visit and procedure need a 1-line modifier so the payer doesn't bundle them."
    if rule == "MOD-59":
        return "Two services on the same day need a 1-line modifier so the payer doesn't bundle them."
    if rule == "E/M-LEVEL":
        return "The visit level doesn't match what the note supports."
    if rule == "NCCI":
        return "Two procedures on the same day conflict on the payer's edit list."
    if rule == "TIME":
        return "The note needs the start time and total minutes for the prolonged service."
    if rule == "MED-NEC":
        return "The diagnosis doesn't clearly support the procedure."
    if body:
        return f"Documentation on the {body} part of the note is incomplete."
    return "The note needs one more sentence to support the claim."


def _one_sentence_fix(finding: dict[str, Any]) -> str:
    """The copy-pastable 'add this sentence to your note' suggestion."""
    rule = str(finding.get("rule_id", ""))
    if rule in ("MOD-25", "MOD-59"):
        return "The E/M service is significant and separately identifiable from today's procedure."
    if rule == "E/M-LEVEL":
        return "Medical decision making: [problems], [data reviewed], [risk]. Total time: [X] minutes."
    if rule == "TIME":
        return "Total time on this encounter: [X] minutes, from [start] to [end]."
    if rule == "MED-NEC":
        return "[Brief sentence linking the diagnosis to the medical necessity of the procedure]."
    if rule == "NCCI":
        return "These procedures are performed at different anatomic sites or for distinct clinical reasons."
    return "[One sentence documenting the medical decision making]."


def suggest_fix_for(finding: dict[str, Any]) -> str:
    """Public alias for the copy-pastable fix line.

    Used by ``/doctor`` route and the doctor email builder.
    """
    return _one_sentence_fix(finding)


# ---------------------------------------------------------------------------
# Fix-it workflow: re-audit on note update
# ---------------------------------------------------------------------------


def fixit_reaudit_payload(
    *,
    encounter_id: str,
    updated_note_text: str,
    provider_npi: str,
    actor: str = "doctor",
) -> dict[str, Any]:
    """Build the payload for the 'note updated, please re-audit' button.

    The FastAPI endpoint receives this and pushes a job onto
    ``job_queue``. We return a payload, not a side effect.
    """
    note_hash = hashlib.sha256((updated_note_text or "").encode("utf-8")).hexdigest()
    return {
        "job_id": f"fixit_{uuid.uuid4().hex[:12]}",
        "job_type": "re_audit",
        "encounter_id": str(encounter_id),
        "provider_npi": str(provider_npi),
        "actor": actor,
        "trigger": "doctor_fixit",
        "updated_note_sha256": note_hash,
        "updated_note_chars": len(updated_note_text or ""),
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # The re-audit uses the same model as the original audit;
        # depth follows ``audit_depth.audit_depth_for`` so a
        # tenant-config override is honoured automatically.
        "depth_strategy": "tenant_default_or_global",
    }


# ---------------------------------------------------------------------------
# Doctor weekly digest: flags + positive feedback (the WIN email)
# ---------------------------------------------------------------------------


@dataclass
class DoctorWeeklyDigest:
    """The weekly positive + negative framing for one doctor."""

    provider_npi: str
    to_email: str
    subject: str
    body_text: str
    clean_count: int = 0
    flagged_count: int = 0
    saved_usd: float = 0.0
    week_label: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queued_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "provider_npi": self.provider_npi,
            "to_email": self.to_email,
            "subject": self.subject,
            "body_text": self.body_text,
            "clean_count": self.clean_count,
            "flagged_count": self.flagged_count,
            "saved_usd": self.saved_usd,
            "week_label": self.week_label,
            "queued_at": self.queued_at,
        }


def doctor_weekly_digest(
    provider_npi: str,
    audit_log: Iterable[dict[str, Any]],
    *,
    to_email: str | None = None,
    saved_per_clean_usd: float = 200.0,
    lookback_days: int = 7,
    now_ts: float | None = None,
) -> DoctorWeeklyDigest:
    """Build the weekly positive + negative framing for one doctor.

    * ``clean_count`` = encounters with zero findings
    * ``flagged_count`` = encounters with ≥ 1 finding
    * ``saved_usd`` = clean_count * saved_per_clean_usd
      (conservative: $200 per clean note = avg denied-claim cost)
    * Subject: "Your week in notes: 45 clean, 2 flagged"
    * Body: positive-first, then the 1-2 sentences per flagged note.

    Returns ``DoctorWeeklyDigest`` with all fields populated. The
    caller (FastAPI or the worker) decides whether to actually
    send via Mailgun.
    """
    encs = doctor_encounters_for(
        provider_npi,
        audit_log,
        lookback_days=lookback_days,
        now_ts=now_ts,
    )
    clean = [e for e in encs if not e["needs_fix"]]
    flagged = [e for e in encs if e["needs_fix"]]
    saved = round(len(clean) * saved_per_clean_usd, 2)
    week_label = time.strftime("%Y-W%V", time.gmtime(now_ts) if now_ts else time.gmtime())
    subject = f"Your week in notes: {len(clean)} clean, {len(flagged)} flagged"
    body_lines = [
        "Hi,",
        "",
        f"This week you wrote {len(encs)} notes.",
        f"  {len(clean)} were clean (saved ${saved:,.0f}).",
        f"  {len(flagged)} had a quick fix.",
        "",
    ]
    if flagged:
        body_lines.append("Notes needing a quick fix:")
        for e in flagged[:5]:  # cap so we don't send a wall of text
            body_lines.append(f"  - {e['date_of_service']}: {e['what_wrong']}")
            body_lines.append(f"      Add: \"{e['fix_suggestion']}\"")
        if len(flagged) > 5:
            body_lines.append(f"  ... and {len(flagged) - 5} more.")
        body_lines.append("")
    body_lines.append(
        "Open the dashboard to see the full list and re-audit after each fix."
    )
    body_lines.append("")
    body_lines.append("— Zorva pre-bill audit")
    body = "\n".join(body_lines)
    return DoctorWeeklyDigest(
        provider_npi=provider_npi,
        to_email=to_email or "",
        subject=subject,
        body_text=body,
        clean_count=len(clean),
        flagged_count=len(flagged),
        saved_usd=saved,
        week_label=week_label,
    )


# ---------------------------------------------------------------------------
# Doctor effectiveness metric ("12% better than last quarter")
# ---------------------------------------------------------------------------


def doctor_effectiveness(
    provider_npi: str,
    audit_log: Iterable[dict[str, Any]],
    *,
    prior_window_days: int = 90,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Return the doctor's clean-note effectiveness metric.

    Compares the doctor's clean-note rate in the most-recent
    ``prior_window_days`` window to the prior window of the same
    length. Returns:

    * ``provider_npi``
    * ``clean_rate_recent`` — fraction in [0, 1] for recent window
    * ``clean_rate_prior`` — fraction in [0, 1] for prior window
    * ``delta_pct_points`` — recent − prior in percentage points
    * ``relative_change_pct`` — % change vs prior
    * ``n_recent`` — total encounters in recent window
    * ``n_prior`` — total encounters in prior window
    * ``headline`` — human-readable summary

    Doctors who only see flags resent the system. Doctors who
    see "your notes are 12% better than last quarter" are fans.
    """
    if not provider_npi:
        return _empty_effectiveness(provider_npi)
    now = now_ts if now_ts is not None else time.time()
    recent_cutoff = now - (prior_window_days * 86_400)
    prior_cutoff = recent_cutoff - (prior_window_days * 86_400)
    recent_total = 0
    recent_clean = 0
    prior_total = 0
    prior_clean = 0
    for enc in audit_log:
        if enc.get("provider_npi") != provider_npi:
            continue
        ts = _parse_iso(enc.get("date_of_service") or enc.get("last_modified") or "")
        if not ts:
            continue
        is_clean = not (enc.get("findings") or [])
        if ts >= recent_cutoff:
            recent_total += 1
            if is_clean:
                recent_clean += 1
        elif ts >= prior_cutoff:
            prior_total += 1
            if is_clean:
                prior_clean += 1
    recent_rate = (recent_clean / recent_total) if recent_total else 0.0
    prior_rate = (prior_clean / prior_total) if prior_total else 0.0
    delta_pts = (recent_rate - prior_rate) * 100.0
    rel_pct = ((recent_rate - prior_rate) / prior_rate * 100.0) if prior_rate > 0 else 0.0
    if recent_total == 0 and prior_total == 0:
        headline = "Not enough notes yet to measure."
    elif prior_total == 0:
        headline = f"You wrote {recent_clean} clean notes in the last {prior_window_days} days."
    elif delta_pts > 0:
        headline = f"Your notes are {delta_pts:.1f}% better than the prior {prior_window_days} days."
    elif delta_pts < 0:
        headline = f"Your notes are {abs(delta_pts):.1f}% worse than the prior {prior_window_days} days."
    else:
        headline = f"Your clean-note rate is steady at {recent_rate * 100:.1f}%."
    return {
        "provider_npi": provider_npi,
        "clean_rate_recent": round(recent_rate, 4),
        "clean_rate_prior": round(prior_rate, 4),
        "delta_pct_points": round(delta_pts, 2),
        "relative_change_pct": round(rel_pct, 2),
        "n_recent": recent_total,
        "n_prior": prior_total,
        "headline": headline,
        "window_days": prior_window_days,
    }


def _empty_effectiveness(provider_npi: str) -> dict[str, Any]:
    return {
        "provider_npi": provider_npi,
        "clean_rate_recent": 0.0,
        "clean_rate_prior": 0.0,
        "delta_pct_points": 0.0,
        "relative_change_pct": 0.0,
        "n_recent": 0,
        "n_prior": 0,
        "headline": "Not enough notes yet to measure.",
        "window_days": 90,
    }


def _parse_iso(value: str) -> float:
    """Parse an ISO-8601 date to a unix timestamp. 0.0 on failure."""
    if not value:
        return 0.0
    from datetime import datetime
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0