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
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from .claim_schema import normalize_claim

logger = logging.getLogger(__name__)

# Finished jobs older than this are dropped from the in-memory map
# (JSONL on disk remains the durable trail). Prevents unbounded
# growth of `_jobs` under sustained upload load.
_JOB_RETENTION_SECONDS = int(os.environ.get("ZORVA_JOB_RETENTION_SECONDS", "86400"))
_JOB_MAX_IN_MEMORY = int(os.environ.get("ZORVA_JOB_MAX_IN_MEMORY", "2000"))

# Stable client-facing error codes. Never ship raw exception text
# (SDK / LLM / filesystem messages) to the poll API / UI.
_CLIENT_SAFE_JOB_ERRORS: dict[str, str] = {
    "failed": "audit_job_failed",
}


def _sanitize_job_error(exc: BaseException) -> str:
    """Map an exception to a stable, non-leaky client error code.

    Full exception details are logged server-side by the caller.
    """
    name = type(exc).__name__
    # Keep a small allowlist of intentionally-safe codes for UI
    # branching; everything else collapses to audit_job_failed.
    if name in {"TimeoutError", "asyncio.TimeoutError"}:
        return "audit_job_timeout"
    if name in {"ValueError", "X12ParseError"}:
        return "audit_job_invalid_input"
    return _CLIENT_SAFE_JOB_ERRORS["failed"]


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a client/log-safe copy of a job result.

    Audit failures historically stored ``audit_error`` as the raw exception
    message. Keep the field for UI compatibility, but expose only a stable
    error code and never persist or return the original text.
    """
    public = dict(result or {})
    if "audit_error" in public:
        public["audit_error"] = "audit_job_failed"
    return public


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

    Doctor email resolution (in order):
    1. encounter.provider_email  (explicit override, e.g. from a
       custom upload form that captured it)
    2. encounter.doctor_email    (legacy field name)
    3. encounter.NPI → doctor_email_for_provider(NPI) lookup
       (queries the CMS NPI Registry; results cached on disk)
    4. None → no email sent

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
        from .doctor_email import (
            build_doctor_summary,
            doctor_email_for_provider,
            send_doctor_summary,
        )
    except ImportError:
        return 0

    # Resolve the doctor's email address. The portal paste-form
    # doesn't collect a provider_email field; the runner falls back
    # to looking up the email by NPI via the CMS public registry.
    doctor_email = (
        encounter.get("provider_email")
        or encounter.get("doctor_email")
    )
    if not doctor_email:
        npi = (encounter.get("NPI") or "").strip()
        # Skip the registry lookup for invalid NPI shapes — the
        # helper itself rejects non-10-digit values, but checking
        # here avoids the function call entirely and keeps the
        # call-site behaviour obvious from a quick read.
        if npi and npi.isdigit() and len(npi) == 10:
            try:
                doctor_email = doctor_email_for_provider(npi)
            except Exception:
                # NPI Registry unreachable (offline, rate-limited,
                # or malformed). Fall through to "no email" — the
                # audit still ran; the biller can forward it
                # manually.
                doctor_email = None
    if not doctor_email:
        logger.info(
            "no doctor email resolvable (no provider_email field, "
            "no usable NPI). Skipping doctor summary email.",
            extra={"encounter_id": encounter.get("encounter_id")},
        )
        return 0

    # Build the encounter dict the email builder expects, with the
    # resolved email injected.
    encounter_with_email = {**encounter, "doctor_email": doctor_email}

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
            encounter={**encounter_with_email, "clinical_note": clinical_note},
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
        "patient_id",
        "source",
        "source_filename",
        "tenant_id",
        "status",
        "error",
        "result",
        "submitted_at",
        "started_at",
        "finished_at",
        "dedup_hit",
    )

    def __init__(
        self,
        *,
        job_id: str,
        encounter_id: str,
        source: str,
        source_filename: str | None,
        tenant_id: str | None = None,
        patient_id: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.encounter_id = encounter_id
        self.patient_id = patient_id or ""
        self.source = source
        self.source_filename = source_filename
        self.tenant_id = tenant_id or "default"
        self.status = "queued"
        self.error = ""
        self.result: dict[str, Any] = {}
        self.submitted_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        # dedup_hit: True when enqueue() returned this Job because
        # of a recent-match dedup (NOT a fresh enqueue). Callers
        # can surface this in the upload-submit response so the
        # biller sees "already audited at <job_id>" instead of a
        # brand-new job_id.
        self.dedup_hit = False

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
            "tenant_id": self.tenant_id,
            "status": self.status,
            "stage": self.status,
            "progress": self._STATUS_PROGRESS.get(self.status, 0),
            # Never expose raw exception text to poll clients / UI.
            "error": self.public_error(),
            "result": _public_result(self.result),
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def public_error(self) -> str:
        """Client-safe error string (never raw exception text)."""
        if not self.error:
            return ""
        # Historical JSONL rows may still contain "Type: message".
        # Collapse anything that looks like a Python exception to a
        # stable code so old failed jobs don't leak on poll.
        head = self.error.split(":", 1)[0].strip()
        if head.endswith("Error") or head.endswith("Exception"):
            return "audit_job_failed"
        if self.error.startswith("audit_job_"):
            return self.error
        return "audit_job_failed"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        j = cls(
            job_id=d["job_id"],
            encounter_id=d["encounter_id"],
            source=d["source"],
            source_filename=d.get("source_filename"),
            tenant_id=d.get("tenant_id"),
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
        tenant_id: str | None = None,
        allow_duplicate: bool = False,
    ) -> Job:
        """Submit a job. Returns the freshly created Job.

        The job transitions through ``queued`` → ``running`` →
        ``done`` / ``failed`` in a background thread.

        Multi-tenant hardening: tenant_id is recorded on the Job
        so the JSONL log row carries the tenant. The
        _latest_real_audit_for API handler filters by tenant
        so one tenant's encounter can't leak to another.

        Dedup: unless ``allow_duplicate=True``, the queue
        refuses to enqueue a second job for the same
        (tenant_id, encounter_id, patient_id) tuple while an
        earlier job is still active (queued / running) or was
        completed in the last ``DEDUP_WINDOW_SECONDS``
        (default 300). The returned ``Job`` in that case is the
        existing one, and ``job.dedup_hit=True`` is set so the
        caller can surface "we already audited this" in the
        response instead of running a fresh audit.
        """
        # Normalize every new payload at the durable boundary. Legacy aliases
        # remain readable, but persisted jobs use one versioned contract.
        encounter = normalize_claim(encounter)
        jid = uuid.uuid4().hex[:12]
        encounter_id = str(encounter.get("encounter_id") or f"enc_{jid}")
        patient_id = str(encounter.get("patient_id") or "").strip()
        if not allow_duplicate:
            existing = self._find_recent_dup(
                tenant_id=tenant_id,
                encounter_id=encounter_id,
                patient_id=patient_id,
            )
            if existing is not None:
                existing.dedup_hit = True
                return existing
        job = Job(
            job_id=jid,
            encounter_id=encounter_id,
            patient_id=patient_id,
            source=source,
            source_filename=source_filename,
            tenant_id=tenant_id,
        )
        with self._lock:
            self._prune_jobs_locked()
            self._jobs[jid] = job
            self._append_log(job)
        threading.Thread(
            target=self._run_job,
            args=(job, encounter),
            name=f"audit-job-{jid}",
            daemon=True,
        ).start()
        return job

    def _find_recent_dup(
        self,
        *,
        tenant_id: str | None,
        encounter_id: str,
        patient_id: str,
    ) -> Job | None:
        """Return an existing job that matches
        ``(tenant_id, encounter_id, patient_id)`` if one was
        completed within ``DEDUP_WINDOW_SECONDS`` OR is still
        active. ``None`` if no recent match — caller should
        proceed with the enqueue.

        The window default (300s = 5 minutes) is short enough
        that a biller who genuinely wants to re-audit a claim
        after a payer-rule update can do so by waiting 5 min
        (or by passing ``allow_duplicate=True``). It's long
        enough that a doubled-click or network-retry duplicate
        gets caught.
        """
        import time as _time
        import os as _os
        window = int(_os.environ.get("DEDUP_WINDOW_SECONDS", "300"))
        now = _time.time()
        with self._lock:
            # Iterate in reverse insertion order — most-recent jobs
            # are likeliest to be the duplicate (the biller just
            # submitted this claim).
            jobs_in_order = list(self._jobs.values())[::-1]
            for j in jobs_in_order:
                if j.tenant_id != tenant_id:
                    continue
                if j.encounter_id != encounter_id:
                    continue
                # Match by patient_id when both are present (the
                # biller might have re-keyed the encounter_id with
                # a typo, but the patient_id is a stable link).
                # When patient_id is empty on BOTH the new and
                # existing job, the encounter_id alone is the
                # dedup key (matches what we have).
                job_patient = str(getattr(j, "patient_id", "") or "")
                if patient_id and job_patient and patient_id != job_patient:
                    continue
                # Active (queued / running) — definitely a dup
                if j.status in ("queued", "running"):
                    return j
                # Completed within the dedup window
                finished = getattr(j, "finished_at", None)
                if finished is None:
                    continue
                if now - finished < window:
                    return j
        return None

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
                logger.error(
                    "audit job %s failed: %s",
                    job.job_id,
                    type(exc).__name__,
                )
                with self._lock:
                    job.status = "failed"
                    job.error = _sanitize_job_error(exc)
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

    def _prune_jobs_locked(self) -> None:
        """Drop finished jobs past retention / over the in-memory cap.

        Caller MUST hold ``self._lock``. Durable history remains in
        the JSONL log on disk.
        """
        now = time.time()
        to_drop: list[str] = []
        for jid, job in self._jobs.items():
            if job.status not in ("done", "failed"):
                continue
            finished = job.finished_at or job.started_at or job.submitted_at or 0.0
            if now - finished > _JOB_RETENTION_SECONDS:
                to_drop.append(jid)
        for jid in to_drop:
            self._jobs.pop(jid, None)
        # Hard cap: if still oversized, drop oldest finished first.
        if len(self._jobs) <= _JOB_MAX_IN_MEMORY:
            return
        finished_jobs = [
            (jid, job)
            for jid, job in self._jobs.items()
            if job.status in ("done", "failed")
        ]
        finished_jobs.sort(
            key=lambda pair: pair[1].finished_at
            or pair[1].started_at
            or pair[1].submitted_at
            or 0.0
        )
        overflow = len(self._jobs) - _JOB_MAX_IN_MEMORY
        for jid, _job in finished_jobs[: max(0, overflow)]:
            self._jobs.pop(jid, None)


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
    # Hoisted so the exception-handler return at the end has
    # access.
    seed = abs(hash(encounter_id)) % (2**31)

    # Three branches, all assign ``claim`` / ``synth_out`` /
    # ``clinical_note`` before the auditor call below:
    #
    # 1. 837I short-circuit (kanban t_ca101c1c). The institutional
    #    upload route hands us a pre-built canonical claim object
    #    (with provider_npis, value_codes, facility lines, etc.)
    #    via the ``_claim_canonical`` key. We use it verbatim and
    #    skip the synth entirely so the multi-provider /
    #    inpatient shape survives end-to-end.
    # 2. Real-data path: an uploaded note + a queued claim with
    #    CPTs. Audit the user's actual claim against their actual
    #    note. See kanban t_5c741803 / t_d16db103 for context.
    # 3. Legacy demo path: synth everything (the marketing
    #    screenshots depend on this).
    canonical_claim = encounter.get("_claim_canonical")
    if canonical_claim:
        claim = dict(canonical_claim)
        cpts = [
            (li.get("cpt_code") or "").strip()
            for li in (claim.get("line_items") or [])
            if (li.get("cpt_code") or "").strip()
        ]
        icds = (
            claim.get("diagnosis_codes")
            or claim.get("icd10_codes")
            or []
        )
        # An 837I upload is the highest-fidelity data we have —
        # treat it as the hardest tier so the auditor doesn't
        # down-weight findings.
        tier = "HARD"
        variant = "flagged"
        synth_out = {
            "encounter_id": encounter_id,
            "cpt_codes": [{"code": c} for c in cpts],
            "icd10_codes": icds,
            "flagged": True,
            "difficulty_tier": tier,
            "variant": variant,
            "ran_via": "upload_portal_institutional_837i",
            "provider_note": {},
        }
        clinical_note = uploaded_note or ""
    else:
        # If we have an uploaded note AND the queued claim has CPT
        # codes (i.e. the staff user actually used the paste-form,
        # not just clicked a demo link), audit the real claim
        # against the real note.
        queued_cpts = (
            encounter.get("CPT_codes")
            or encounter.get("cpt_codes")
            or []
        )
        use_real_data = bool(uploaded_note) and bool(queued_cpts)

        if use_real_data:
            cpts = list(queued_cpts)
            # Build the line_items list from the queued CPTs. The auditor
            # only reads cpt_codes/icd10_codes so we keep the shape simple.
            line_items = [
                {
                    "line_id": i + 1,
                    "cpt_code": str(c),
                    "modifiers": [],
                    "dx_pointers": (
                        encounter.get("diagnosis_codes")
                        or encounter.get("icd10_codes")
                        or []
                    ),
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
                "diagnosis_codes": (
                    encounter.get("diagnosis_codes")
                    or encounter.get("icd10_codes")
                    or []
                ),
            }
            # Force variant=flagged so the auditor doesn't bias toward
            # "this looks clean". The real-data path always audits a
            # real claim where there could be real issues.
            variant = "flagged"
            tier = "HARD"  # treat pilot data as the hardest tier
            synth_out = {
                "encounter_id": encounter_id,
                "cpt_codes": [{"code": str(c)} for c in cpts],
                "icd10_codes": (
                    encounter.get("diagnosis_codes")
                    or encounter.get("icd10_codes")
                    or []
                ),
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
    # Persist the audit-ready claim on Job.result so the re-audit
    # endpoint can reconstruct the original claim byte-for-byte
    # (CPT codes, ICDs, NPI, date_of_service, patient_id) instead
    # of falling back to a PT_REAUDIT placeholder with empty
    # line_items. See kanban card t_10774785.
    _persisted_claim = dict(claim)
    # Add the Zorva system context to the encounter envelope. The
    # auditor doesn't see this prose — it's a structured payload that
    # downstream consumers (dashboard, appeal-letter generator, audit
    # trail) read. The auditor's prompt stays focused on rule
    # matching; we don't pollute it with vision/market text.
    from .zorva_context import build_context_for_encounter
    zorva_ctx = build_context_for_encounter(
        country_code=encounter.get("country_code"),
        payer_id=encounter.get("payer_id"),
        province=encounter.get("province"),
        health_number=encounter.get("patient_id"),
    )
    audit_encounter["zorva_context"] = zorva_ctx

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
            "zorva_context": zorva_ctx,
            # Persisted for re-audit reconstruction — see t_10774785.
            "claim": _persisted_claim,
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
            "audit_error": "audit_job_failed",
            # Persisted even on failure so re-audit can still
            # recover the originally-uploaded claim payload — see
            # t_10774785.
            "claim": _persisted_claim,
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
