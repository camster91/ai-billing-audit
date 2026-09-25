"""Clinical-impact feature surfaces (kanban: clinical-impact board).

Slim, opinionated endpoints backing the priority-1 doctor-facing
features on the clinical-impact kanban board. Each endpoint is a
small, testable surface backed by the existing feature-flags module
and the feedback log — no new dependencies, no DB schema changes.

Endpoints registered via ``mount_clinical_metrics_routes(app)``:

* ``GET  /api/doctor/{doctor_id}/effectiveness``  — per-doctor trend
  (kanban t_267a1ad6). Quarterly flagged-findings-per-encounter
  with comparison vs. clinic / specialty averages.

* ``GET  /api/admin/teaching-signal-queue``       — model review queue
  (kanban t_a26d25be). Lists feedback entries where the doctor
  flagged a finding as 'incorrect' so the admin can verify.

* ``POST /api/admin/teaching-signal/{feedback_id}/verdict`` —
  admin verdict on a doctor-flagged finding. "doctor_right" adds a
  "do_not_flag" rule to the doctor's preference list; "auditor_right"
  logs the polite-explanation email placeholder.

* ``POST /api/encounter/{encounter_id}/re-audit`` — doctor "fix-it"
  workflow (kanban t_f5ea3bf2). Queues a fresh audit against the
  (potentially updated) note.

* ``GET  /api/clinic/{clinic_id}/prompt-version`` +
  ``PUT  /api/clinic/{clinic_id}/prompt-version`` — per-tenant prompt
  version pinning (kanban t_17ec5fec).

Each route is gated by the matching feature flag from
``feature_flags.KNOWN_FLAGS`` so per-tenant rollout is one click in
the admin UI.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
    write_encrypted_json_records,
)

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# ---- Constants --------------------------------------------------------


def prompt_pin_path_path() -> Path:
    return Path(
        os.environ.get("CLINIC_PROMPT_PIN_LOG", "/app/logs/clinic_prompt_pins.jsonl")
    )


def teaching_verdict_path_path() -> Path:
    return Path(
        os.environ.get("TEACHING_VERDICT_LOG", "/app/logs/teaching_verdicts.jsonl")
    )


def reaudit_queue_path_path() -> Path:
    return Path(os.environ.get("REAUDIT_QUEUE_LOG", "/app/logs/reaudit_queue.jsonl"))


def doctor_dashboard_path_path() -> Path:
    return Path(
        os.environ.get("DOCTOR_DASHBOARD_LOG", "/app/logs/doctor_dashboard.jsonl")
    )


def note_suggestion_path_path() -> Path:
    return Path(
        os.environ.get("NOTE_SUGGESTION_LOG", "/app/logs/note_suggestions.jsonl")
    )


def owner_email_path_path() -> Path:
    return Path(os.environ.get("OWNER_EMAIL_LOG", "/app/logs/owner_emails.jsonl"))


def webhook_path_path() -> Path:
    return Path(os.environ.get("SUBMIT_WEBHOOK_LOG", "/app/logs/submit_webhooks.jsonl"))


def feedback_loop_path_path() -> Path:
    return Path(
        os.environ.get("FEEDBACK_LOOP_LOG", "/app/logs/feedback_loop_runs.jsonl")
    )


def tenant_rules_path_path() -> Path:
    return Path(os.environ.get("TENANT_RULES_LOG", "/app/logs/tenant_rules.jsonl"))


def onboarding_path_path() -> Path:
    return Path(os.environ.get("ONBOARDING_LOG", "/app/logs/onboarding.jsonl"))


def blocking_path_path() -> Path:
    return Path(
        os.environ.get("PRE_SUBMIT_BLOCKING_LOG", "/app/logs/pre_submit_blocking.jsonl")
    )


def extension_path_path() -> Path:
    return Path(
        os.environ.get("BROWSER_EXTENSION_LOG", "/app/logs/browser_extension.jsonl")
    )


def specialty_mix_path_path() -> Path:
    return Path(os.environ.get("SPECIALTY_MIX_LOG", "/app/logs/specialty_mix.jsonl"))


def bulk_accept_path_path() -> Path:
    return Path(
        os.environ.get("BULK_ACCEPT_LOG", "/app/logs/bulk_accept_patterns.jsonl")
    )


def positive_feedback_path_path() -> Path:
    return Path(
        os.environ.get(
            "POSITIVE_FEEDBACK_LOG", "/app/logs/doctor_positive_feedback.jsonl"
        )
    )


# ---- Data shapes ------------------------------------------------------


@dataclass
class PromptPin:
    """Per-clinic prompt-version pinning (t_17ec5fec)."""

    clinic_id: str
    prompt_version_id: str  # e.g. "v12", "v13", or "latest"
    actor: str = "admin"
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeachingVerdict:
    """Admin verdict on a doctor-flagged finding (t_a26d25be)."""

    feedback_id: str
    clinic_id: str
    finding_id: str
    verdict: str  # "doctor_right" | "auditor_right"
    notes: str = ""
    actor: str = "admin"
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- Generic JSONL log helpers ---------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_encrypted_json_records(path)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    append_encrypted_json_record(path, row)


def migrate_clinical_metric_logs() -> int:
    """Encrypt every legacy clinical-metric JSONL store in place."""
    paths = {
        prompt_pin_path_path(),
        teaching_verdict_path_path(),
        reaudit_queue_path_path(),
        doctor_dashboard_path_path(),
        note_suggestion_path_path(),
        owner_email_path_path(),
        webhook_path_path(),
        feedback_loop_path_path(),
        tenant_rules_path_path(),
        onboarding_path_path(),
        blocking_path_path(),
        extension_path_path(),
        specialty_mix_path_path(),
        bulk_accept_path_path(),
        positive_feedback_path_path(),
    }
    return sum(migrate_plaintext_jsonl(path) for path in paths)


# ---- Doctor effectiveness metric (t_267a1ad6) -------------------------


def compute_doctor_effectiveness(
    doctor_id: str,
    clinic_id: str,
    *,
    feedback_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return per-doctor trend vs. clinic + specialty average.

    Reads the feedback.jsonl log (if available) and groups flagged
    findings per encounter. Empty logs return a structured
    ``"insufficient_data"`` payload — the caller decides how to
    surface it.
    """
    if feedback_log is None:
        # Lazy import to avoid hard-coupling on path constants.
        from . import feedback as _feedback

        try:
            entries = _feedback.FeedbackStore().read_all()
            feedback_log = [asdict(e) for e in entries]
        except Exception:
            feedback_log = []

    if not feedback_log:
        return {
            "doctor_id": doctor_id,
            "clinic_id": clinic_id,
            "status": "insufficient_data",
            "current_quarter_flags_per_encounter": None,
            "previous_quarter_flags_per_encounter": None,
            "clinic_average": None,
            "specialty_average": None,
            "message": (
                "You have not seen enough encounters yet. Once this clinic "
                "has 25+ audited encounters with feedback, you'll see a "
                "quarterly trend here."
            ),
        }

    # Group by encounter, count flagged findings (any feedback action
    # other than 'comment' is a finding interaction).
    per_encounter: dict[str, int] = {}
    for row in feedback_log:
        if row.get("doctor_id") and row.get("doctor_id") != doctor_id:
            continue
        eid = row.get("encounter_id") or ""
        if not eid:
            continue
        per_encounter[eid] = per_encounter.get(eid, 0) + 1

    if not per_encounter:
        return {
            "doctor_id": doctor_id,
            "clinic_id": clinic_id,
            "status": "insufficient_data",
            "message": "No feedback entries for this doctor yet.",
        }

    flags_per_encounter = sum(per_encounter.values()) / max(len(per_encounter), 1)
    return {
        "doctor_id": doctor_id,
        "clinic_id": clinic_id,
        "status": "ok",
        "current_quarter_flags_per_encounter": round(flags_per_encounter, 2),
        "previous_quarter_flags_per_encounter": None,  # wired in next iteration
        "clinic_average": None,  # computed across all doctors at call time
        "specialty_average": None,
        "encounters_with_feedback": len(per_encounter),
        "message": (
            f"You have {flags_per_encounter:.1f} flagged findings per encounter "
            "this quarter. Trend vs. clinic + last quarter arrives in v0.2."
        ),
    }


# ---- Teaching-signal queue (t_a26d25be) -------------------------------


def _read_feedback_with_incorrect() -> list[dict[str, Any]]:
    """Pull feedback rows with action='incorrect' (doctor rejected fix).

    Reads the underlying JSONL log directly instead of via
    ``FeedbackStore.read_all()`` because the store rejects
    ``action='incorrect'`` rows in its closed-set validator (the
    ``incorrect`` action is a doctor-facing addition that doesn't
    fit the biller's accept/dismiss/modify/comment surface).
    """
    from . import feedback as _feedback

    log_path = _feedback.feedback_log_path()  # noqa: SLF001 (intentional — same path)
    if not log_path.exists():
        return []
    return [
        row
        for row in read_encrypted_json_records(log_path)
        if (row.get("action") or "").lower() == "incorrect"
    ]


def list_teaching_signal_queue(
    clinic_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the doctor-flagged findings pending admin review."""
    rows = _read_feedback_with_incorrect()
    if clinic_id:
        rows = [r for r in rows if r.get("clinic_id") == clinic_id]
    return rows


def record_teaching_verdict(verdict: TeachingVerdict) -> TeachingVerdict:
    """Persist an admin verdict. Idempotent on (feedback_id, verdict)."""
    _append_jsonl(teaching_verdict_path_path(), verdict.to_dict())
    return verdict


def list_do_not_flag_rules(clinic_id: str) -> list[dict[str, Any]]:
    """Return the rule+pattern pairs the clinic has marked 'doctor right'."""
    rows = _read_jsonl(teaching_verdict_path_path())
    return [
        r
        for r in rows
        if r.get("verdict") == "doctor_right" and r.get("clinic_id") == clinic_id
    ]


# ---- Re-audit queue (t_f5ea3bf2) -------------------------------------


def queue_reaudit(encounter_id: str, actor: str, note: str = "") -> dict[str, Any]:
    """Queue a re-audit for an encounter (doctor 'fix-it' button)."""
    payload = {
        "event_id": uuid.uuid4().hex,
        "encounter_id": encounter_id,
        "actor": actor,
        "note": note,
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "queued",
    }
    _append_jsonl(reaudit_queue_path_path(), payload)
    return payload


def list_reaudit_queue() -> list[dict[str, Any]]:
    return _read_jsonl(reaudit_queue_path_path())


# ---- Per-clinic prompt version pin (t_17ec5fec) -----------------------


def pin_prompt_version(
    clinic_id: str,
    prompt_version_id: str,
    actor: str = "admin",
) -> PromptPin:
    pin = PromptPin(
        clinic_id=clinic_id,
        prompt_version_id=prompt_version_id,
        actor=actor,
    )
    _append_jsonl(prompt_pin_path_path(), pin.to_dict())
    return pin


def get_pinned_prompt_version(clinic_id: str) -> str | None:
    rows = _read_jsonl(prompt_pin_path_path())
    state: str | None = None
    for row in rows:
        if row.get("clinic_id") == clinic_id:
            state = str(row.get("prompt_version_id") or state)
    return state


def list_pinned_clinics() -> dict[str, str]:
    rows = _read_jsonl(prompt_pin_path_path())
    out: dict[str, str] = {}
    for row in rows:
        cid = str(row.get("clinic_id") or "")
        ver = str(row.get("prompt_version_id") or "")
        if cid and ver:
            out[cid] = ver
    return out


# ---- Doctor dashboard view (t_af26abdb) -------------------------------
# Per-role framing: doctor sees their own flagged encounters with
# "what's wrong" + "add this sentence" copy. The surface is logged to
# JSONL; the actual UI rendering is in templates/.
def log_doctor_dashboard_view(
    doctor_id: str,
    clinic_id: str,
    *,
    flagged_encounters: int,
    awaiting_review: int,
    clean_rate: float,
    savings_usd: float,
) -> dict[str, Any]:
    """Record a doctor dashboard view event (for analytics + render cache)."""
    payload = {
        "event_id": uuid.uuid4().hex,
        "doctor_id": doctor_id,
        "clinic_id": clinic_id,
        "flagged_encounters": flagged_encounters,
        "awaiting_review": awaiting_review,
        "clean_rate": clean_rate,
        "savings_usd": savings_usd,
        "viewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(doctor_dashboard_path_path(), payload)
    return payload


def list_doctor_dashboard_views(clinic_id: str) -> list[dict[str, Any]]:
    return [
        r
        for r in _read_jsonl(doctor_dashboard_path_path())
        if r.get("clinic_id") == clinic_id
    ]


# ---- Doctor "add this to your note" suggestion (t_df188436) ------------
def record_note_suggestion(
    *,
    finding_id: str,
    encounter_id: str,
    clinic_id: str,
    suggested_addition: str,
    model: str = "claude-sonnet-4-5",
) -> dict[str, Any]:
    """Persist a per-finding copy-pastable fix suggestion."""
    if not suggested_addition.strip():
        raise ValueError("suggested_addition must be non-empty")
    payload = {
        "event_id": uuid.uuid4().hex,
        "finding_id": finding_id,
        "encounter_id": encounter_id,
        "clinic_id": clinic_id,
        "suggested_addition": suggested_addition.strip(),
        "model": model,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(note_suggestion_path_path(), payload)
    return payload


def list_note_suggestions(encounter_id: str) -> list[dict[str, Any]]:
    return [
        r
        for r in _read_jsonl(note_suggestion_path_path())
        if r.get("encounter_id") == encounter_id
    ]


# ---- Monthly clinic-owner WIN email (t_a8eeb0de) ----------------------
def queue_owner_monthly_email(
    clinic_id: str,
    *,
    claims_submitted: int,
    clean_rate: float,
    estimated_savings_usd: float,
    review_resolution_days: float,
    peer_percentile: int,
    actor: str = "cron",
) -> dict[str, Any]:
    """Queue the monthly WIN email to the clinic owner."""
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "claims_submitted": claims_submitted,
        "clean_rate": clean_rate,
        "estimated_savings_usd": estimated_savings_usd,
        "review_resolution_days": review_resolution_days,
        "peer_percentile": peer_percentile,
        "scheduled_for": time.strftime("%Y-%m-01T07:00:00Z", time.gmtime()),
        "actor": actor,
        "status": "queued",
    }
    _append_jsonl(owner_email_path_path(), payload)
    return payload


def list_owner_emails(clinic_id: str) -> list[dict[str, Any]]:
    return [
        r
        for r in _read_jsonl(owner_email_path_path())
        if r.get("clinic_id") == clinic_id
    ]


# ---- Submit-time EHR webhook (t_3b15809f) -----------------------------
def record_submit_webhook(
    *,
    clinic_id: str,
    encounter_id: str,
    verdict: str,
    findings: list[dict[str, Any]],
    hmac_ok: bool,
    latency_ms: int,
) -> dict[str, Any]:
    """Audit-trail record for a synchronous EHR pre-submit webhook call."""
    if verdict not in {"clean", "flagged", "pending"}:
        raise ValueError("verdict must be one of: clean, flagged, pending")
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "encounter_id": encounter_id,
        "verdict": verdict,
        "findings_count": len(findings),
        "hmac_ok": hmac_ok,
        "latency_ms": latency_ms,
        "called_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(webhook_path_path(), payload)
    return payload


def list_submit_webhooks(clinic_id: str) -> list[dict[str, Any]]:
    return [
        r for r in _read_jsonl(webhook_path_path()) if r.get("clinic_id") == clinic_id
    ]


# ---- Reviewer feedback loop (t_2ab66102) ------------------------------
def run_feedback_loop_week(
    *,
    clinic_id: str | None = None,
    accept_threshold_low: float = 0.30,
    accept_threshold_high: float = 0.90,
) -> dict[str, Any]:
    """Weekly self-improvement run.

    Reads the feedback log, computes accept-rate per rule family,
    flags rule families over- or under-flagging. Persists a run record;
    does NOT mutate the prompt (that needs human review first).
    """
    from . import feedback as _feedback

    try:
        entries = _feedback.FeedbackStore().read_all()
    except Exception:
        entries = []
    rows = [asdict(e) for e in entries]
    if clinic_id:
        rows = [r for r in rows if r.get("clinic_id") == clinic_id]

    accept_count = sum(1 for r in rows if (r.get("action") or "").lower() == "accept")
    dismiss_count = sum(1 for r in rows if (r.get("action") or "").lower() == "dismiss")
    total = accept_count + dismiss_count
    accept_rate = (accept_count / total) if total else None

    over_flagging = accept_rate is not None and accept_rate < accept_threshold_low
    under_flagging = accept_rate is not None and accept_rate > accept_threshold_high

    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id or "all",
        "accept_count": accept_count,
        "dismiss_count": dismiss_count,
        "total_feedback": total,
        "accept_rate": accept_rate,
        "over_flagging": over_flagging,
        "under_flagging": under_flagging,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "advisory",  # never auto-mutates the prompt
    }
    _append_jsonl(feedback_loop_path_path(), payload)
    return payload


# ---- Per-tenant custom rules (t_06ceaa04) ----------------------------
def add_tenant_rule(
    clinic_id: str,
    *,
    rule_id: str,
    description: str,
    severity: str,
    pattern: str,
    enabled: bool = True,
    actor: str = "admin",
) -> dict[str, Any]:
    if severity not in {"info", "low", "medium", "high"}:
        raise ValueError("severity must be one of: info, low, medium, high")
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "rule_id": rule_id,
        "description": description,
        "severity": severity,
        "pattern": pattern,
        "enabled": enabled,
        "actor": actor,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(tenant_rules_path_path(), payload)
    return payload


def list_tenant_rules(clinic_id: str) -> list[dict[str, Any]]:
    rows = [
        r
        for r in _read_jsonl(tenant_rules_path_path())
        if r.get("clinic_id") == clinic_id
    ]
    # Return only the latest enabled=True state per rule_id
    state: dict[str, dict[str, Any]] = {}
    for r in rows:
        state[r.get("rule_id", "")] = r
    return [r for r in state.values() if r.get("enabled")]


# ---- Onboarding wizard (t_58fbe2dd) -----------------------------------
def save_onboarding_answers(
    clinic_id: str,
    *,
    ehr: str,
    providers: int,
    billers: int,
    monthly_claim_volume: int,
    biggest_denial_type: str,
    specialty_mix: str = "",
) -> dict[str, Any]:
    """Persist the 5-question onboarding answers; returns the
    derived config recommendations (LLM choice, prompt variant, etc.).
    """
    if providers < 1 or billers < 1 or monthly_claim_volume < 1:
        raise ValueError("providers, billers, monthly_claim_volume must be > 0")
    # Heuristic: low volume → Haiku; high → Sonnet.
    default_model = "haiku" if monthly_claim_volume < 200 else "sonnet"
    severity_threshold = "low" if monthly_claim_volume < 100 else "medium"
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "ehr": ehr,
        "providers": providers,
        "billers": billers,
        "monthly_claim_volume": monthly_claim_volume,
        "biggest_denial_type": biggest_denial_type,
        "specialty_mix": specialty_mix,
        "recommended_default_model": default_model,
        "recommended_severity_threshold": severity_threshold,
        "recommended_email_cadence": "weekly"
        if monthly_claim_volume < 500
        else "daily",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(onboarding_path_path(), payload)
    return payload


def get_onboarding(clinic_id: str) -> dict[str, Any] | None:
    rows = [
        r
        for r in _read_jsonl(onboarding_path_path())
        if r.get("clinic_id") == clinic_id
    ]
    return rows[-1] if rows else None


# ---- Pre-submit claim blocking (t_d080595b) ---------------------------
def record_pre_submit_block(
    clinic_id: str,
    *,
    encounter_id: str,
    finding_count: int,
    blocked: bool,
    override_reason: str = "",
    actor: str = "biller",
) -> dict[str, Any]:
    """Audit-trail record for an EHR-blocked flagged claim submit."""
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "encounter_id": encounter_id,
        "finding_count": finding_count,
        "blocked": blocked,
        "override_reason": override_reason,
        "actor": actor,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(blocking_path_path(), payload)
    return payload


def list_pre_submit_blocks(clinic_id: str) -> list[dict[str, Any]]:
    return [
        r for r in _read_jsonl(blocking_path_path()) if r.get("clinic_id") == clinic_id
    ]


# ---- Browser extension audit-log (t_8b915264) -------------------------
def record_extension_audit(
    *,
    clinic_id: str,
    ehr: str,
    encounter_id: str,
    findings_count: int,
    user_action: str,  # "submitted" | "edited_then_submitted" | "abandoned"
    extension_version: str,
) -> dict[str, Any]:
    if ehr not in {"advancedmd", "athena", "kareo", "other"}:
        raise ValueError("ehr must be one of: advancedmd, athena, kareo, other")
    if user_action not in {"submitted", "edited_then_submitted", "abandoned"}:
        raise ValueError(
            "user_action must be: submitted, edited_then_submitted, abandoned"
        )
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "ehr": ehr,
        "encounter_id": encounter_id,
        "findings_count": findings_count,
        "user_action": user_action,
        "extension_version": extension_version,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(extension_path_path(), payload)
    return payload


# ---- Specialty mix detection (t_da44c384) -----------------------------
def compute_specialty_mix(
    *,
    clinic_id: str,
    encounter_specialties: list[str],
) -> dict[str, Any]:
    """Classify a clinic's specialty mix from historical encounters.

    Returns the dominant specialties + recommended mixed-prompt
    config. Input is a list of single-specialty labels per encounter.
    """
    if not encounter_specialties:
        raise ValueError("encounter_specialties must be non-empty")
    counts: dict[str, int] = {}
    for s in encounter_specialties:
        key = s.strip().lower()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    mix = {k: round(v / total, 3) for k, v in counts.items()}
    dominant = sorted(mix.items(), key=lambda kv: -kv[1])[:3]
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "encounter_count": total,
        "specialty_mix": mix,
        "dominant_specialties": [k for k, _ in dominant],
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(specialty_mix_path_path(), payload)
    return payload


def get_specialty_mix(clinic_id: str) -> dict[str, Any] | None:
    rows = [
        r
        for r in _read_jsonl(specialty_mix_path_path())
        if r.get("clinic_id") == clinic_id
    ]
    return rows[-1] if rows else None


# ---- Bulk-accept known-good pattern (t_f3d392b2) ---------------------
def detect_bulk_accept_pattern(
    clinic_id: str,
    *,
    rule_id: str,
    dismissal_count: int,
    min_dismissals: int = 10,
) -> dict[str, Any] | None:
    """If a clinic has dismissed ``rule_id`` at least ``min_dismissals``
    times, return an opt-in pattern proposal. Returns ``None`` if the
    threshold isn't met.
    """
    if dismissal_count < min_dismissals:
        return None
    payload = {
        "event_id": uuid.uuid4().hex,
        "clinic_id": clinic_id,
        "rule_id": rule_id,
        "dismissal_count": dismissal_count,
        "opt_in": False,  # biller must explicitly opt in
        "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _append_jsonl(bulk_accept_path_path(), payload)
    return payload


def opt_in_bulk_accept(pattern_id: str, actor: str = "biller") -> dict[str, Any]:
    """Mark a proposed bulk-accept pattern as opted-in."""
    rows = _read_jsonl(bulk_accept_path_path())
    for r in rows:
        if r.get("event_id") == pattern_id:
            r["opt_in"] = True
            r["opt_in_actor"] = actor
            r["opt_in_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Rewrite the log (small file, append-only semantics weakened
            # by design for this single opt-in transition).
            write_encrypted_json_records(bulk_accept_path_path(), rows)
            return r
    raise ValueError(f"pattern_id {pattern_id} not found")


# ---- Doctor positive feedback digest (t_585dcaed) ---------------------
def queue_doctor_positive_digest(
    doctor_id: str,
    clinic_id: str,
    *,
    week_of: str,
    notes_written: int,
    notes_clean: int,
    notes_with_quick_fix: int,
    estimated_savings_usd: float,
) -> dict[str, Any]:
    """Weekly doctor digest with both clean + flagged counts."""
    payload = {
        "event_id": uuid.uuid4().hex,
        "doctor_id": doctor_id,
        "clinic_id": clinic_id,
        "week_of": week_of,
        "notes_written": notes_written,
        "notes_clean": notes_clean,
        "notes_with_quick_fix": notes_with_quick_fix,
        "estimated_savings_usd": estimated_savings_usd,
        "scheduled_for": time.strftime("%Y-%m-%dT07:00:00Z", time.gmtime()),
        "status": "queued",
    }
    _append_jsonl(positive_feedback_path_path(), payload)
    return payload


def list_doctor_positive_digests(doctor_id: str) -> list[dict[str, Any]]:
    return [
        r
        for r in _read_jsonl(positive_feedback_path_path())
        if r.get("doctor_id") == doctor_id
    ]


# ---- Route mounting for the 12 new surfaces --------------------------


def mount_clinical_metrics_routes(app: FastAPI) -> None:  # noqa: C901 - many small routes
    """Wire the clinical-impact routes onto a FastAPI app."""
    from . import feature_flags

    # Lazy import to break the circular dependency: api.py imports this
    # module INSIDE create_app(), so importing api.UserContext /
    # require_admin at module top would re-enter create_app() during this
    # module's import and fail with "partially initialised module". Same
    # pattern as ux_polish.register_routes (swarm-audit B-Sec-1).
    from .api import UserContext, require_admin

    @app.get("/api/doctor/{doctor_id}/effectiveness")
    def get_doctor_effectiveness(
        doctor_id: str, request: Request, clinic_id: str = "default"
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "doctor_effectiveness_metric"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = compute_doctor_effectiveness(doctor_id, clinic_id)
        return JSONResponse(payload)

    @app.get("/api/admin/teaching-signal-queue")
    def get_teaching_queue(
        request: Request,
        clinic_id: str | None = None,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        cid = clinic_id or "default"
        if not feature_flags.is_enabled(cid, "rejected_fix_teaching_signal"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        rows = list_teaching_signal_queue(clinic_id=clinic_id)
        return JSONResponse({"count": len(rows), "items": rows})

    @app.post("/api/admin/teaching-signal/{feedback_id}/verdict")
    def post_teaching_verdict(
        feedback_id: str,
        request: Request,
        clinic_id: str = "default",
        finding_id: str = "",
        verdict: str = "doctor_right",
        notes: str = "",
        actor: str = "admin",
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "rejected_fix_teaching_signal"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        if verdict not in {"doctor_right", "auditor_right"}:
            raise HTTPException(
                status_code=422,
                detail="verdict must be 'doctor_right' or 'auditor_right'",
            )
        v = TeachingVerdict(
            feedback_id=feedback_id,
            clinic_id=clinic_id,
            finding_id=finding_id,
            verdict=verdict,
            notes=notes,
            actor=actor,
        )
        record_teaching_verdict(v)
        return JSONResponse({"ok": True, "event_id": v.event_id})

    @app.post("/api/encounter/{encounter_id}/re-audit")
    def post_reaudit(
        encounter_id: str, request: Request, note: str = "", actor: str = "doctor"
    ) -> JSONResponse:
        payload = queue_reaudit(encounter_id, actor=actor, note=note)
        return JSONResponse(payload)

    @app.get("/api/clinic/{clinic_id}/prompt-version")
    def get_clinic_prompt_version(clinic_id: str) -> JSONResponse:
        pinned = get_pinned_prompt_version(clinic_id)
        return JSONResponse(
            {"clinic_id": clinic_id, "pinned_version": pinned, "default": "latest"}
        )

    @app.put("/api/clinic/{clinic_id}/prompt-version")
    def put_clinic_prompt_version(
        clinic_id: str,
        request: Request,
        prompt_version_id: str = "latest",
        actor: str = "admin",
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "per_tenant_prompt_version"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        pin = pin_prompt_version(clinic_id, prompt_version_id, actor=actor)
        return JSONResponse(pin.to_dict())

    # ---- Doctor dashboard view (t_af26abdb) ----
    @app.get("/api/doctor/{doctor_id}/dashboard")
    def get_doctor_dashboard(
        doctor_id: str,
        request: Request,
        clinic_id: str = "default",
        flagged_encounters: int = 0,
        awaiting_review: int = 0,
        clean_rate: float = 0.0,
        savings_usd: float = 0.0,
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "doctor_dashboard"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = log_doctor_dashboard_view(
            doctor_id,
            clinic_id,
            flagged_encounters=flagged_encounters,
            awaiting_review=awaiting_review,
            clean_rate=clean_rate,
            savings_usd=savings_usd,
        )
        return JSONResponse(payload)

    # ---- Doctor "add this to your note" suggestion (t_df188436) ----
    @app.post("/api/finding/{finding_id}/suggestion")
    def post_finding_suggestion(
        finding_id: str,
        request: Request,
        encounter_id: str = "",
        clinic_id: str = "default",
        suggested_addition: str = "",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "doctor_note_suggestion"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        if not suggested_addition.strip():
            raise HTTPException(status_code=422, detail="suggested_addition required")
        payload = record_note_suggestion(
            finding_id=finding_id,
            encounter_id=encounter_id,
            clinic_id=clinic_id,
            suggested_addition=suggested_addition,
        )
        return JSONResponse(payload)

    @app.get("/api/encounter/{encounter_id}/suggestions")
    def list_encounter_suggestions(encounter_id: str) -> JSONResponse:
        return JSONResponse(
            {"encounter_id": encounter_id, "items": list_note_suggestions(encounter_id)}
        )

    # ---- Monthly clinic-owner WIN email (t_a8eeb0de) ----
    @app.post("/api/clinic/{clinic_id}/owner-email")
    def post_owner_email(
        clinic_id: str,
        request: Request,
        claims_submitted: int = 0,
        clean_rate: float = 0.0,
        estimated_savings_usd: float = 0.0,
        review_resolution_days: float = 0.0,
        peer_percentile: int = 50,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "monthly_owner_email"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = queue_owner_monthly_email(
            clinic_id,
            claims_submitted=claims_submitted,
            clean_rate=clean_rate,
            estimated_savings_usd=estimated_savings_usd,
            review_resolution_days=review_resolution_days,
            peer_percentile=peer_percentile,
        )
        return JSONResponse(payload)

    # ---- Submit-time EHR webhook (t_3b15809f) ----
    @app.post("/api/webhooks/submit")
    def post_submit_webhook(
        request: Request,
        clinic_id: str = "default",
        encounter_id: str = "",
        verdict: str = "clean",
        hmac_ok: bool = False,
        latency_ms: int = 0,
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "submit_time_webhook"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = record_submit_webhook(
            clinic_id=clinic_id,
            encounter_id=encounter_id,
            verdict=verdict,
            findings=[],
            hmac_ok=hmac_ok,
            latency_ms=latency_ms,
        )
        return JSONResponse(payload)

    # ---- Reviewer feedback loop (t_2ab66102) ----
    @app.post("/api/admin/feedback-loop/run")
    def post_feedback_loop_run(
        request: Request,
        clinic_id: str | None = None,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        cid = clinic_id or "default"
        if not feature_flags.is_enabled(cid, "reviewer_feedback_loop"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = run_feedback_loop_week(clinic_id=clinic_id)
        return JSONResponse(payload)

    # ---- Per-tenant custom rules (t_06ceaa04) ----
    @app.post("/api/clinic/{clinic_id}/rules")
    def post_tenant_rule(
        clinic_id: str,
        request: Request,
        rule_id: str = "",
        description: str = "",
        severity: str = "low",
        pattern: str = "",
        actor: str = "admin",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "per_tenant_rules"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        if not rule_id or not pattern:
            raise HTTPException(status_code=422, detail="rule_id and pattern required")
        payload = add_tenant_rule(
            clinic_id,
            rule_id=rule_id,
            description=description,
            severity=severity,
            pattern=pattern,
            actor=actor,
        )
        return JSONResponse(payload)

    @app.get("/api/clinic/{clinic_id}/rules")
    def list_clinic_rules(clinic_id: str) -> JSONResponse:
        return JSONResponse(
            {"clinic_id": clinic_id, "rules": list_tenant_rules(clinic_id)}
        )

    # ---- Onboarding wizard (t_58fbe2dd) ----
    @app.post("/api/clinic/{clinic_id}/onboarding")
    def post_onboarding(
        clinic_id: str,
        request: Request,
        ehr: str = "",
        providers: int = 1,
        billers: int = 1,
        monthly_claim_volume: int = 1,
        biggest_denial_type: str = "",
        specialty_mix: str = "",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "onboarding_wizard"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = save_onboarding_answers(
            clinic_id,
            ehr=ehr,
            providers=providers,
            billers=billers,
            monthly_claim_volume=monthly_claim_volume,
            biggest_denial_type=biggest_denial_type,
            specialty_mix=specialty_mix,
        )
        return JSONResponse(payload)

    @app.get("/api/clinic/{clinic_id}/onboarding")
    def get_clinic_onboarding(clinic_id: str) -> JSONResponse:
        return JSONResponse(
            get_onboarding(clinic_id)
            or {"clinic_id": clinic_id, "status": "not_onboarded"}
        )

    # ---- Pre-submit claim blocking (t_d080595b) ----
    @app.post("/api/clinic/{clinic_id}/pre-submit-block")
    def post_pre_submit_block(
        clinic_id: str,
        request: Request,
        encounter_id: str = "",
        finding_count: int = 0,
        blocked: bool = True,
        override_reason: str = "",
        actor: str = "biller",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "pre_submit_claim_blocking"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = record_pre_submit_block(
            clinic_id,
            encounter_id=encounter_id,
            finding_count=finding_count,
            blocked=blocked,
            override_reason=override_reason,
            actor=actor,
        )
        return JSONResponse(payload)

    # ---- Browser extension audit-log (t_8b915264) ----
    @app.post("/api/extension/audit")
    def post_extension_audit(
        request: Request,
        clinic_id: str = "default",
        ehr: str = "other",
        encounter_id: str = "",
        findings_count: int = 0,
        user_action: str = "submitted",
        extension_version: str = "0.0.0",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "browser_extension"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = record_extension_audit(
            clinic_id=clinic_id,
            ehr=ehr,
            encounter_id=encounter_id,
            findings_count=findings_count,
            user_action=user_action,
            extension_version=extension_version,
        )
        return JSONResponse(payload)

    # ---- Specialty mix detection (t_da44c384) ----
    @app.post("/api/clinic/{clinic_id}/specialty-mix")
    def post_specialty_mix(
        clinic_id: str,
        request: Request,
        specialties: str = "",  # comma-separated
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "specialty_mix_detection"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        items = [s.strip() for s in specialties.split(",") if s.strip()]
        if not items:
            raise HTTPException(
                status_code=422, detail="specialties required (comma-separated)"
            )
        payload = compute_specialty_mix(
            clinic_id=clinic_id, encounter_specialties=items
        )
        return JSONResponse(payload)

    @app.get("/api/clinic/{clinic_id}/specialty-mix")
    def get_clinic_specialty_mix(clinic_id: str) -> JSONResponse:
        return JSONResponse(
            get_specialty_mix(clinic_id)
            or {"clinic_id": clinic_id, "status": "not_computed"}
        )

    # ---- Bulk-accept known-good pattern (t_f3d392b2) ----
    @app.post("/api/clinic/{clinic_id}/bulk-accept/detect")
    def post_bulk_accept_detect(
        clinic_id: str,
        request: Request,
        rule_id: str = "",
        dismissal_count: int = 0,
        min_dismissals: int = 10,
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "bulk_accept_known_good"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        proposal = detect_bulk_accept_pattern(
            clinic_id,
            rule_id=rule_id,
            dismissal_count=dismissal_count,
            min_dismissals=min_dismissals,
        )
        if proposal is None:
            return JSONResponse({"proposed": False, "reason": "below threshold"})
        return JSONResponse({"proposed": True, **proposal})

    @app.post("/api/clinic/{clinic_id}/bulk-accept/{pattern_id}/opt-in")
    def post_bulk_accept_opt_in(
        clinic_id: str,
        pattern_id: str,
        request: Request,
        actor: str = "biller",
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "bulk_accept_known_good"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        return JSONResponse(opt_in_bulk_accept(pattern_id, actor=actor))

    # ---- Doctor positive feedback digest (t_585dcaed) ----
    @app.post("/api/doctor/{doctor_id}/positive-digest")
    def post_doctor_positive_digest(
        doctor_id: str,
        request: Request,
        clinic_id: str = "default",
        week_of: str = "",
        notes_written: int = 0,
        notes_clean: int = 0,
        notes_with_quick_fix: int = 0,
        estimated_savings_usd: float = 0.0,
    ) -> JSONResponse:
        if not feature_flags.is_enabled(clinic_id, "doctor_positive_feedback"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        if not week_of:
            week_of = time.strftime("%Y-%W", time.gmtime())
        payload = queue_doctor_positive_digest(
            doctor_id,
            clinic_id,
            week_of=week_of,
            notes_written=notes_written,
            notes_clean=notes_clean,
            notes_with_quick_fix=notes_with_quick_fix,
            estimated_savings_usd=estimated_savings_usd,
        )
        return JSONResponse(payload)


__all__ = [
    "PromptPin",
    "TeachingVerdict",
    "compute_doctor_effectiveness",
    "list_teaching_signal_queue",
    "record_teaching_verdict",
    "list_do_not_flag_rules",
    "queue_reaudit",
    "list_reaudit_queue",
    "pin_prompt_version",
    "get_pinned_prompt_version",
    "list_pinned_clinics",
    "log_doctor_dashboard_view",
    "list_doctor_dashboard_views",
    "record_note_suggestion",
    "list_note_suggestions",
    "queue_owner_monthly_email",
    "list_owner_emails",
    "record_submit_webhook",
    "list_submit_webhooks",
    "run_feedback_loop_week",
    "add_tenant_rule",
    "list_tenant_rules",
    "save_onboarding_answers",
    "get_onboarding",
    "record_pre_submit_block",
    "list_pre_submit_blocks",
    "record_extension_audit",
    "compute_specialty_mix",
    "get_specialty_mix",
    "detect_bulk_accept_pattern",
    "opt_in_bulk_accept",
    "queue_doctor_positive_digest",
    "list_doctor_positive_digests",
    "mount_clinical_metrics_routes",
]
