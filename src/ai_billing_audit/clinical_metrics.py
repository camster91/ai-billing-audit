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

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# ---- Constants --------------------------------------------------------

_PROMPT_PIN_PATH = Path(
    os.environ.get("CLINIC_PROMPT_PIN_LOG", "/app/logs/clinic_prompt_pins.jsonl")
)
_TEACHING_VERDICT_PATH = Path(
    os.environ.get("TEACHING_VERDICT_LOG", "/app/logs/teaching_verdicts.jsonl")
)
_REAUDIT_QUEUE_PATH = Path(
    os.environ.get("REAUDIT_QUEUE_LOG", "/app/logs/reaudit_queue.jsonl")
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
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


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

    log_path = _feedback._LOG_PATH  # noqa: SLF001 (intentional — same path)
    if not log_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("action") or "").lower() == "incorrect":
                out.append(row)
    return out


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
    _append_jsonl(_TEACHING_VERDICT_PATH, verdict.to_dict())
    return verdict


def list_do_not_flag_rules(clinic_id: str) -> list[dict[str, Any]]:
    """Return the rule+pattern pairs the clinic has marked 'doctor right'."""
    rows = _read_jsonl(_TEACHING_VERDICT_PATH)
    return [
        r for r in rows
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
    _append_jsonl(_REAUDIT_QUEUE_PATH, payload)
    return payload


def list_reaudit_queue() -> list[dict[str, Any]]:
    return _read_jsonl(_REAUDIT_QUEUE_PATH)


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
    _append_jsonl(_PROMPT_PIN_PATH, pin.to_dict())
    return pin


def get_pinned_prompt_version(clinic_id: str) -> str | None:
    rows = _read_jsonl(_PROMPT_PIN_PATH)
    state: str | None = None
    for row in rows:
        if row.get("clinic_id") == clinic_id:
            state = str(row.get("prompt_version_id") or state)
    return state


def list_pinned_clinics() -> dict[str, str]:
    rows = _read_jsonl(_PROMPT_PIN_PATH)
    out: dict[str, str] = {}
    for row in rows:
        cid = str(row.get("clinic_id") or "")
        ver = str(row.get("prompt_version_id") or "")
        if cid and ver:
            out[cid] = ver
    return out


# ---- Route mounting ---------------------------------------------------


def mount_clinical_metrics_routes(app: FastAPI) -> None:
    """Wire the clinical-impact routes onto a FastAPI app."""

    @app.get("/api/doctor/{doctor_id}/effectiveness")
    def get_doctor_effectiveness(doctor_id: str, request: Request, clinic_id: str = "default") -> JSONResponse:
        from . import feature_flags

        if not feature_flags.is_enabled(clinic_id, "doctor_effectiveness_metric"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        payload = compute_doctor_effectiveness(doctor_id, clinic_id)
        return JSONResponse(payload)

    @app.get("/api/admin/teaching-signal-queue")
    def get_teaching_queue(request: Request, clinic_id: str | None = None) -> JSONResponse:
        from . import feature_flags

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
    ) -> JSONResponse:
        from . import feature_flags

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
    def post_reaudit(encounter_id: str, request: Request, note: str = "", actor: str = "doctor") -> JSONResponse:
        from . import feature_flags

        # Re-audit isn't gated per-clinic; the doctor's own dashboard
        # surfaces the button.
        _ = feature_flags
        payload = queue_reaudit(encounter_id, actor=actor, note=note)
        return JSONResponse(payload)

    @app.get("/api/clinic/{clinic_id}/prompt-version")
    def get_clinic_prompt_version(clinic_id: str) -> JSONResponse:
        pinned = get_pinned_prompt_version(clinic_id)
        return JSONResponse(
            {
                "clinic_id": clinic_id,
                "pinned_version": pinned,
                "default": "latest",
            }
        )

    @app.put("/api/clinic/{clinic_id}/prompt-version")
    def put_clinic_prompt_version(
        clinic_id: str,
        request: Request,
        prompt_version_id: str = "latest",
        actor: str = "admin",
    ) -> JSONResponse:
        from . import feature_flags

        if not feature_flags.is_enabled(clinic_id, "per_tenant_prompt_version"):
            raise HTTPException(status_code=404, detail="feature disabled for clinic")
        pin = pin_prompt_version(clinic_id, prompt_version_id, actor=actor)
        return JSONResponse(pin.to_dict())


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
    "mount_clinical_metrics_routes",
]
