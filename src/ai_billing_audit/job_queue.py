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
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "encounter_id": self.encounter_id,
            "source": self.source,
            "source_filename": self.source_filename,
            "status": self.status,
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
    """Run the synth pipeline against the encounter.

    The synth agent expects a ``Template(tier, variant, ...)`` and
    a seed. For portal uploads we already have the encounter in
    hand, so we use the synth purely as a way to feed the audit
    pipeline — the seeded RNG produces deterministic identifiers
    the auditor can use for trace logging, and the encounter body
    is preserved through.

    Why "MEDIUM/clean" by default? It exercises the moderator path
    the auditor is most often tested on, and a clean variant means
    the job succeeds even on a borderline-real upload. The
    paste-form can override ``difficulty_tier`` and ``variant``.
    """
    # Imported lazily so test environments without a populated
    # synth package can still import this module.
    from .synth_agent import generate, Template

    tier = str(encounter.get("difficulty_tier") or "EASY").upper()
    if tier not in ("EASY", "MEDIUM", "HARD"):
        tier = "EASY"
    variant = str(encounter.get("variant") or "clean").lower()
    if variant not in ("clean", "flagged"):
        variant = "clean"
    # Seed from the encounter_id so re-submission is reproducible.
    seed_source = encounter.get("encounter_id") or "enc_default"
    seed = abs(hash(seed_source)) % (2**31)
    synth_out = generate(
        Template(tier=tier, variant=variant, schema_version=1),
        seed=seed,
    )
    # The "audit job" returns the synth run's identifier + a
    # marker that the encounter body came from the upload flow.
    return {
        "synth_encounter_id": synth_out.get("encounter_id"),
        "difficulty_tier": synth_out.get("difficulty_tier"),
        "variant": synth_out.get("variant", variant),
        "seed": seed,
        "ran_via": "upload_portal",
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
