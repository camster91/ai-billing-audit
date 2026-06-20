"""In-process job queue for the encounter-upload portal.

The audit pipeline the portal feeds runs the synth agent (see
:mod:`ai_billing_audit.synth_agent`) per accepted file. Until the
real EHR ingestion lands, we model the audit job as a thin wrapper
around the synth call so the UI has a pollable status and the
accepted files leave a durable trail.

Why in-process + JSONL
----------------------

* The portal lives in a single FastAPI process. A thread-safe dict
  covers the "pollable from the same process" requirement.
* We append a JSONL line to ``jobs.jsonl`` on every status change
  so a process restart can rebuild the dict from disk. The
  JSONL is a log, not a database — the latest line per ``job_id``
  is the source of truth.
* No external broker. This matches the project's
  "self-hosted / minimal-infra" stance (see
  ``AGENTS.md``). A future card can swap this for Celery / RQ
  when the audit pipeline moves off the FastAPI process.

State machine
-------------

::

    queued ──> running ──> done
                       └─> failed

There is no "cancel" — the upload flow rejects before submit, and
the synth agent is fast enough that we never need to interrupt.

The synth call uses the encounter's normalised fields to build a
``Template`` (EASY by default; the upload form can override
``difficulty_tier`` in the paste-form mode). For 837P uploads,
``difficulty_tier`` defaults to ``EASY`` so the resulting
``encounter_id`` is unique within ``enc_<>`` namespace.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

# Local copy of _PKG_DIR — the runner is a module-level function
# (the default closure for JobQueue), so it can't see the closure
# variable defined in api.py's create_app(). Re-derive it here.
_PKG_DIR = Path(__file__).resolve().parent

# Where uploaded clinical notes live on disk. Same path resolution
# as api.py: project_root/logs/uploaded_notes/. The runner reads
# this to detect real-data uploads vs synth-only demo uploads.
_UPLOADED_NOTES_DIR = _PKG_DIR.parent.parent / "logs" / "uploaded_notes"


def _load_uploaded_note(encounter_id: str) -> str | None:
    """Return the most recent uploaded clinical note for an encounter_id.

    Notes are saved as ``<encounter_id>.<note_id>.txt`` by the
    /encounters/upload/text-note endpoint. We pick the most
    recently-modified one when there are multiple (the staff user
    may have re-uploaded).

    Returns None if the dir doesn't exist or there are no matching
    files. Returns "" if the file is empty (caller decides whether
    empty notes count as "uploaded").
    """
    if not encounter_id:
        return None
    safe_match = re.sub(r"[^A-Za-z0-9_.-]+", "_", encounter_id).strip("._")[:80]
    if not safe_match:
        return None
    if not _UPLOADED_NOTES_DIR.is_dir():
        return None
    try:
        candidates = sorted(
            _UPLOADED_NOTES_DIR.glob(f"{safe_match}.*.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        return candidates[0].read_text(encoding="utf-8")
    except OSError:
        return None


def _send_doctor_emails(
    encounter: dict[str, Any],
    clinical_note: str,
    findings: list[dict[str, Any]],
    synth_out: dict[str, Any],
) -> int:
    """Send one doctor-summary email per high-severity finding.

    Skips:
    - The legacy synth/demo path (no real doctor to email).
    - Findings without a finding_id or rule_id (we can't generate
      a useful "fix" without those).
    - Doctors with email in the opt-out list.

    Returns the number of emails actually sent (or written to the
    dev fallback mailbox).

    Lazy-imports ai_billing_audit.doctor_email so the module isn't
    required for tests that only exercise the synth path.
    """
    # No emails from the synth/demo path. Real-data path is the
    # only time the doctor is a real person who needs to know.
    ran_via = synth_out.get("ran_via", "")
    if ran_via != "upload_portal_with_user_note":
        return 0
    if not findings:
        return 0
    try:
        from .doctor_email import build_doctor_summary, send_doctor_summary
    except ImportError:
        return 0

    sent = 0
    # Email the doctor about the most severe finding only. Sending
    # one email per audit keeps the doctor from feeling spammed.
    # The biller sees all findings on the dashboard; the doctor
    # sees the one that needs their attention.
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    ranked = sorted(
        findings,
        key=lambda f: severity_rank.get(str(f.get("severity", "info")).lower(), 0),
        reverse=True,
    )
    for finding in ranked[:1]:
        summary = build_doctor_summary(
            finding=finding,
            encounter={**encounter, "clinical_note": clinical_note},
        )
        if summary is None:
            continue
        try:
            if send_doctor_summary(summary):
                sent += 1
        except Exception:
            # Don't fail the whole audit job if the email pipeline
            # errors out. The finding is still in the result dict
            # for the dashboard to display.
            continue
    return sent


__all__ = [
    "Job",
    "JobQueue",
    "get_default_queue",
]


class Job:
    """A single in-flight audit job.

    Attributes:
        job_id: short hex id assigned at queue time.
        encounter_id: the encounter this job will audit.
        source: what produced the encounter — ``"837p"``,
            ``"paste"``, or ``"zip"`` (a bulk-upload expansion).
        source_filename: original filename, when the source is a
            file upload. ``None`` for paste-form.
        status: one of ``"queued"``, ``"running"``, ``"done"``,
            ``"failed"``.
        error: human-readable error when status is ``"failed"``;
            otherwise empty.
        result: a small dict the synth call returns (currently
            the synth-generated encounter's ``encounter_id`` and
            ``difficulty_tier``). Empty for failures.
        submitted_at / started_at / finished_at: epoch seconds
            (float) for each transition; ``None`` until the
            transition happens.
    """

    __slots__ = (
        "job_id",
        "encounter_id",
        "source",
        "source_filename",
        "status",
        "error",
        "result",
        "submitted_at",
        "started_at",
        "finished_at",
    )

    def __init__(
        self,
        *,
        job_id: str,
        encounter_id: str,
        source: str,
        source_filename: str | None,
    ) -> None:
        self.job_id = job_id
        self.encounter_id = encounter_id
        self.source = source
        self.source_filename = source_filename
        self.status = "queued"
        self.error = ""
        self.result: dict[str, Any] = {}
        self.submitted_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None

    # Status -> progress-percent map used by the upload portal's
    # progress indicator. The portal polls /jobs/{id} every second;
    # the status text is fine-grained, but the bar wants a number.
    # 0/15/90/100 mirrors what users see: queued sits at the start,
    # running has started but not finished, done is complete, failed
    # sits at 0 (the bar should re-render the error state, not
    # pretend it succeeded).
    _STATUS_PROGRESS: dict[str, int] = {
        "queued": 0,
        "running": 15,
        "done": 100,
        "failed": 0,
    }

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "encounter_id": self.encounter_id,
            "source": self.source,
            "source_filename": self.source_filename,
            "status": self.status,
            "stage": self.status,
            "progress": self._STATUS_PROGRESS.get(self.status, 0),
            "error": self.error,
            "result": self.result,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        j = cls(
            job_id=d["job_id"],
            encounter_id=d["encounter_id"],
            source=d["source"],
            source_filename=d.get("source_filename"),
        )
        j.status = d.get("status", "queued")
        j.error = d.get("error", "")
        j.result = d.get("result", {}) or {}
        j.submitted_at = d.get("submitted_at") or time.time()
        j.started_at = d.get("started_at")
        j.finished_at = d.get("finished_at")
        return j


class JobQueue:
    """Thread-safe in-process job store with a JSONL audit log.

    The queue is intentionally synchronous: enqueue() submits and
    starts a job in a background thread so the HTTP request can
    return immediately. A small worker pool (default size 2) is
    enough for the upload portal's traffic and keeps the synth
    agent's deterministic output from being shared across jobs.
    """

    def __init__(
        self,
        log_path: Path,
        *,
        worker_count: int = 2,
        runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._worker_count = max(1, int(worker_count))
        self._sem = threading.BoundedSemaphore(self._worker_count)
        self._runner: Callable[[dict[str, Any]], dict[str, Any]] = (
            runner if runner is not None else _default_runner
        )
        self._load_from_log()

    # --- persistence -----------------------------------------------------

    def _load_from_log(self) -> None:
        """Rebuild the in-memory dict from the JSONL log on startup.

        If the log does not exist yet, this is a no-op. The last
        line per ``job_id`` wins — earlier lines are an audit
        trail of state transitions.
        """
        if not self._log_path.exists():
            return
        try:
            with self._log_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        # Corrupted line; skip it. A production
                        # system would quarantine these to a
                        # separate file; this is a portal, not
                        # a database.
                        continue
                    jid = d.get("job_id")
                    if not jid:
                        continue
                    self._jobs[jid] = Job.from_dict(d)
        except OSError:
            # Log file unreadable; start empty. Surfacing the
            # error to the caller would block startup, which
            # is the wrong tradeoff for a demo portal.
            self._jobs.clear()

    def _append_log(self, job: Job) -> None:
        """Append the job's current state to the JSONL log.

        No-op if the path's parent cannot be written — the
        in-memory dict is still authoritative for the running
        process.
        """
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(job.to_dict(), sort_keys=True))
                fh.write("\n")
        except OSError:
            pass

    # --- public API -------------------------------------------------------

    def enqueue(
        self,
        *,
        encounter: dict[str, Any],
        source: str,
        source_filename: str | None = None,
    ) -> Job:
        """Submit a job. Returns the freshly created Job.

        The job transitions through ``queued`` → ``running`` →
        ``done`` / ``failed`` in a background thread.
        """
        jid = uuid.uuid4().hex[:12]
        encounter_id = str(encounter.get("encounter_id") or f"enc_{jid}")
        job = Job(
            job_id=jid,
            encounter_id=encounter_id,
            source=source,
            source_filename=source_filename,
        )
        with self._lock:
            self._jobs[jid] = job
            self._append_log(job)
        threading.Thread(
            target=self._run_job,
            args=(job, encounter),
            name=f"audit-job-{jid}",
            daemon=True,
        ).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def find_by_encounter(
        self,
        encounter_id: str,
        *,
        status: str | None = "done",
        most_recent: bool = True,
    ) -> Job | None:
        """Return the cached job for ``encounter_id``, if any.

        Used by the ``POST /encounters/{id}/audit`` route to recover
        the audit-ready claim + clinical note that the upload flow
        stored. The most recent job (by ``finished_at`` or
        ``submitted_at`` if still queued) wins when multiple jobs
        exist for the same encounter — the upload portal can be
        re-submitted, and only the latest run reflects current
        payer-rule state.

        Parameters
        ----------
        encounter_id:
            The encounter id string to look up. Matches on
            ``Job.encounter_id`` exactly.
        status:
            Optional filter. ``"done"`` (default) returns only
            completed jobs. ``"running"`` returns in-flight jobs
            so a re-audit during a long run does not silently
            hit a 404. ``None`` returns any status.
        most_recent:
            When ``True`` (default), return the latest job by
            timestamp. When ``False``, return the earliest.
        """
        with self._lock:
            matches = [
                j for j in self._jobs.values()
                if j.encounter_id == encounter_id
                and (status is None or j.status == status)
            ]
        if not matches:
            return None
        matches.sort(
            key=lambda j: (j.finished_at or j.started_at or j.submitted_at or 0.0),
            reverse=bool(most_recent),
        )
        return matches[0]

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    # --- internals --------------------------------------------------------

    def _run_job(self, job: Job, encounter: dict[str, Any]) -> None:
        self._sem.acquire()
        try:
            with self._lock:
                job.status = "running"
                job.started_at = time.time()
                self._append_log(job)
            try:
                result = self._runner(encounter)
            except Exception as exc:  # noqa: BLE001 (deliberately broad)
                with self._lock:
                    job.status = "failed"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.finished_at = time.time()
                    self._append_log(job)
                return
            with self._lock:
                job.status = "done"
                job.result = result
                job.finished_at = time.time()
                self._append_log(job)
        finally:
            self._sem.release()


# --- default runner --------------------------------------------------------


def _default_runner(encounter: dict[str, Any]) -> dict[str, Any]:
    """Run the synth pipeline + the real auditor on the seeded encounter.

    The synth agent expects a ``Template(tier, variant, ...)`` and
    a seed. For portal uploads we already have the encounter_id in
    hand, so we use the synth to materialize a deterministic
    clinical_note + claim + rules, then call the real auditor (which
    hits minimax-m3:cloud via Ollama, per the live .env config).

    Why this layout: the live demo doesn't have a clinical-note
    capture UI yet. The synth provides a reproducible encounter
    body keyed on the uploaded encounter_id, so re-submitting the
    same 837P always audits the same synth encounter. Once a
    clinical-note upload path exists, this runner can be swapped
    to use the uploaded note directly.

    Real-data path (used by the pilot clinic):
    When the staff user uploaded BOTH a clinical note (via
    /encounters/upload/text-note) AND a claim with CPT codes (via
    the paste-form), we audit their actual claim against their
    actual note. The synth is skipped entirely. The audit finds
    real issues in real claims, the biller sees real findings, and
    the doctor gets a real email.

    When neither is present we fall back to the synth (legacy
    demo behaviour, retained for the marketing screenshots).
    """
    from .synth_agent import generate, Template

    encounter_id = encounter.get("encounter_id") or "enc_default"
    uploaded_note = _load_uploaded_note(encounter_id)

    # If we have an uploaded note AND the queued claim has CPT codes
    # (i.e. the staff user actually used the paste-form, not just
    # clicked a demo link), audit the real claim against the real note.
    queued_cpts = (
        encounter.get("CPT_codes")
        or encounter.get("cpt_codes")
        or []
    )
    use_real_data = bool(uploaded_note) and bool(queued_cpts)

    # Hoisted so the exception-handler return at the end has access.
    seed = abs(hash(encounter_id)) % (2**31)

    if use_real_data:
        cpts = list(queued_cpts)
        # Build the line_items list from the queued CPTs. The auditor
        # only reads cpt_codes/icd10_codes so we keep the shape simple.
        line_items = [
            {
                "line_id": i + 1,
                "cpt_code": str(c),
                "modifiers": [],
                "dx_pointers": encounter.get("icd10_codes") or [],
                "charge_amount": 150.00,
                "units": 1,
            }
            for i, c in enumerate(cpts)
        ]
        claim = {
            "encounter_id": encounter_id,
            "patient_id": encounter.get("patient_id") or "PT_REAL",
            "rendering_provider_npi": encounter.get("NPI") or "",
            "billing_provider_tax_id": "",
            "date_of_service": encounter.get("date_of_service") or "",
            "payer_id": "",
            "payer_name": "",
            "line_items": line_items,
            "diagnosis_codes": encounter.get("icd10_codes") or [],
        }
        # Force variant=flagged so the auditor doesn't bias toward
        # "this looks clean". The real-data path always audits a
        # real claim where there could be real issues.
        variant = "flagged"
        tier = "HARD"  # treat pilot data as the hardest tier
        synth_out = {
            "encounter_id": encounter_id,
            "cpt_codes": [{"code": str(c)} for c in cpts],
            "icd10_codes": encounter.get("icd10_codes") or [],
            "flagged": True,
            "difficulty_tier": tier,
            "variant": variant,
            "ran_via": "upload_portal_with_user_note",
            "provider_note": {},  # not used; clinical_note is the uploaded one
        }
        clinical_note = uploaded_note
    else:
        # Legacy demo path: synth everything.
        tier = str(encounter.get("difficulty_tier") or "EASY").upper()
        if tier not in ("EASY", "MEDIUM", "HARD"):
            tier = "EASY"
        variant = str(encounter.get("variant") or "clean").lower()
        if variant not in ("clean", "flagged"):
            variant = "clean"
        synth_out = generate(
            Template(tier=tier, variant=variant, schema_version=1),
            seed=seed,
        )

        provider_note = synth_out.get("provider_note", {}) or {}
        clinical_note = "\n\n".join(
            v for v in [
                provider_note.get("hpi", ""),
                provider_note.get("exam", ""),
                provider_note.get("mdm", ""),
            ] if v
        )
        cpts = synth_out.get("cpt_codes", []) or []
        icds = synth_out.get("icd10_codes", []) or []
        claim = {
            "encounter_id": synth_out.get("encounter_id"),
            "patient_id": "PT_DEMO",
            "rendering_provider_npi": "1992039481",
            "billing_provider_tax_id": "XX-XXX1234",
            "date_of_service": "2026-06-15",
            "payer_id": "PAYER-DEMO-001",
            "payer_name": "Demo Payer",
            "line_items": [
                {"line_id": i + 1, "cpt_code": c.get("code", ""), "modifiers": [],
                 "dx_pointers": icds, "charge_amount": 150.00, "units": 1}
                for i, c in enumerate(cpts)
            ],
            "diagnosis_codes": icds,
        }
        if uploaded_note:
            clinical_note = uploaded_note
            synth_out["ran_via"] = "upload_portal_with_user_note"
    audit_encounter = {
        "encounter_id": synth_out.get("encounter_id"),
        "is_flagged": bool(synth_out.get("flagged", False)),
        "clinical_note": clinical_note,
        "claim": claim,
        "rules": [],
        "ground_truth": [],
    }

    # Call the real auditor. LLMClient reads LLM_PROVIDER / LLM_BASE_URL /
    # LLM_MODEL / OLLAMA_API_KEY from env (set by the docker-compose env_file).
    try:
        from .auditor import run_audit, AuditValidationError
        result = run_audit(audit_encounter)
        findings = []
        for f in result.findings:
            # rule_ids is a tuple in the Finding dataclass; flatten
            # for the JSON response. The scorer (scripts/run_7x.py)
            # keys on the FIRST rule_id in the list.
            rule_ids = list(f.rule_ids) if f.rule_ids else []
            findings.append(
                {
                    "finding_id": f.finding_id,
                    "category": f.category,
                    "severity": f.severity,
                    "rule_id": rule_ids[0] if rule_ids else "",
                    "rule_ids": rule_ids,
                    "suggested_code": f.suggested_code,
                    "quote": f.quote,
                    "explanation": f.explanation,
                }
            )
        return {
            "synth_encounter_id": synth_out.get("encounter_id"),
            "difficulty_tier": synth_out.get("difficulty_tier"),
            "variant": synth_out.get("variant", variant),
            "seed": seed,
            "ran_via": synth_out.get("ran_via", "upload_portal"),
            "used_uploaded_note": synth_out.get("ran_via") == "upload_portal_with_user_note",
            "audit_status": "ok",
            "has_findings": bool(findings),
            "findings_count": len(findings),
            "findings": findings,
            "summary": result.summary,
            "doctor_emails_sent": _send_doctor_emails(
                encounter, clinical_note, findings, synth_out
            ),
        }
    except Exception as e:
        # Don't fail the whole job for a single LLM hiccup. Return
        # the synth metadata + an audit_status="failed" marker so
        # the dashboard can surface the error.
        return {
            "synth_encounter_id": synth_out.get("encounter_id"),
            "difficulty_tier": synth_out.get("difficulty_tier"),
            "variant": synth_out.get("variant", variant),
            "seed": seed,
            "ran_via": "upload_portal",
            "audit_status": "failed",
            "audit_error": str(e)[:500],
        }


# --- module-level singleton ------------------------------------------------

_DEFAULT_QUEUE: JobQueue | None = None
_DEFAULT_QUEUE_LOCK = threading.Lock()


def get_default_queue() -> JobQueue:
    """Return the process-wide JobQueue, creating it lazily.

    The log path lives under the project root's ``logs/`` so it
    ships in the same directory the rest of the run artefacts use.
    Tests inject their own queue by monkeypatching the returned
    object's ``enqueue`` / ``get`` methods.
    """
    global _DEFAULT_QUEUE
    if _DEFAULT_QUEUE is not None:
        return _DEFAULT_QUEUE
    with _DEFAULT_QUEUE_LOCK:
        if _DEFAULT_QUEUE is None:
            # Resolve from this file's location so the log lives
            # under <project>/logs/, the same directory the rest
            # of the run artefacts use. tests/test_encounters_upload.py
            # monkeypatches the queue directly, so this path is
            # only relevant for the live server.
            pkg_root = Path(__file__).resolve().parent
            log_path = pkg_root.parent.parent / "logs" / "upload_jobs.jsonl"
            _DEFAULT_QUEUE = JobQueue(log_path=log_path)
        return _DEFAULT_QUEUE


def reset_default_queue_for_tests() -> None:
    """Drop the cached singleton. Tests call this in fixtures.

    Not part of the public surface — see ``tests/test_encounters_upload.py``.
    """
    global _DEFAULT_QUEUE
    with _DEFAULT_QUEUE_LOCK:
        _DEFAULT_QUEUE = None
