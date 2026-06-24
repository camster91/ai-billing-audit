"""Public v1 API for EHR integrations (kanban ``t_f4f1c149``).

Why a separate module
---------------------
The existing :mod:`ai_billing_audit.api` is the operator dashboard
(HTML + bearer-token auth + RBAC). The v1 public API is a *different*
contract aimed at external EHR systems: API-key auth, JSON in/out,
machine-friendly error codes. Mixing them into the same router
would force every external endpoint to either re-implement auth
bypasses or carry the dashboard's session machinery.

This module exposes :func:`register_public_api` which the main
``create_app()`` calls once near the end to mount the v1 surface
at ``/v1/*``.

Authentication
--------------
v1 uses a single shared API key read from the ``ZORVA_API_KEY``
environment variable:

* ``Authorization: Bearer <key>`` (preferred — matches RFC 6750)
* ``X-API-Key: <key>`` (legacy / convenience header)

Behaviour matrix:

* ``ZORVA_API_KEY`` unset → every ``/v1/*`` request gets **503**
  with ``{"detail": "...ZORVA_API_KEY not configured..."}``. This
  matches the "feature present but not enabled" pattern used by the
  bearer-token middleware at the top of :mod:`ai_billing_audit.api`
  and lets operators deploy the same image to staging (no key)
  and prod (key set) without a code change.
* Key set, request missing/wrong key → **401**.
* Key matches → request proceeds.

Every request (including 401 / 503) appends one row to
``/app/logs/usage_log.jsonl`` so we can later rate-limit or audit
per-key without changing this contract. The ``ZORVA_USAGE_LOG_PATH``
env var redirects the log for tests.

Endpoints
---------
``POST /v1/audits``
    Accept an 837P claim object (JSON, parsed from the existing
    encounter-upload shape) and enqueue an audit. Returns **202**
    with ``{"audit_id", "status", "status_url"}``. ``status_url``
    is the relative path the caller polls to fetch the result.

``GET /v1/audits/{audit_id}``
    Returns the audit status (``queued`` / ``running`` / ``complete``
    / ``failed``) plus the findings once the status is ``complete``.
    **404** for unknown ids.

``POST /v1/webhooks``
    Register a webhook. See :mod:`ai_billing_audit.webhooks` for
    the registration format and storage.

The audit lifecycle (POST → 202 → poll GET → complete) deliberately
mirrors :func:`ai_billing_audit.api.encounters_audit` but is wired
straight at the v1 surface so external callers don't see the
``/encounters/{id}/audit`` RBAC / session shape.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ai_billing_audit.job_queue import JobQueue, get_default_queue
from ai_billing_audit.webhooks import (
    EVENT_AUDIT_COMPLETE,
    EVENT_FINDING_ACKNOWLEDGED,
    dispatch_event,
    register_webhook,
)

_log = logging.getLogger(__name__)


# ─── Constants ────────────────────────────────────────────────────────────


# Env var names. Centralised so tests + the readme agree on the
# exact spelling without grepping the source.
_ENV_API_KEY = "ZORVA_API_KEY"
_ENV_USAGE_LOG_PATH = "ZORVA_USAGE_LOG_PATH"
_ENV_WEBHOOK_LOG_PATH = "ZORVA_WEBHOOK_LOG_PATH"

_DEFAULT_USAGE_LOG = "/app/logs/usage_log.jsonl"
_DEFAULT_WEBHOOK_LOG = "/app/logs/webhooks.jsonl"

# Audit_id prefix so callers can distinguish public-API audits
# from operator-dashboard ones in logs / metrics dashboards.
_AUDIT_ID_PREFIX = "va_"  # v1 audit

# Polling parameters when the public API drives the auditor
# synchronously (no background worker in v1). The loop is
# bounded so a slow audit can't tie up a request thread
# indefinitely.
_SYNC_POLL_TIMEOUT_SECONDS = 30.0
_SYNC_POLL_INTERVAL_SECONDS = 0.1

# Fields the v1 surface requires on a submitted claim. We
# intentionally reuse the operator-dashboard's required-field
# vocabulary so EHRs that already talk to /encounters/upload
# don't have to remap.
_REQUIRED_CLAIM_FIELDS: tuple[str, ...] = (
    "encounter_id",
    "patient_id",
    "NPI",
    "date_of_service",
    "CPT_codes",
)


# ─── Audit-id ↔ job-id mapping ───────────────────────────────────────────


# The public API uses a stable ``audit_id`` (returned to the
# caller at POST time and used to look up the job on GET). The
# underlying :class:`JobQueue` already has its own ``job_id``;
# rather than overlap the two we keep a private mapping file
# at ``<usage_log_dir>/v1_audits.jsonl`` so the GET endpoint
# can resolve ``audit_id`` → ``job_id`` without rebuilding the
# job registry every request.
#
# Format: one JSON object per line, ``{"audit_id", "job_id",
# "submitted_at", "tenant_id"}``. The file is append-only.

def _audit_index_path() -> Path:
    """Path to the audit_id ↔ job_id index file.

    Co-located with the usage log so the operator only has to
    mount one directory. Tests override via
    ``ZORVA_USAGE_LOG_PATH`` (the same env var that selects the
    usage log path).
    """
    p = os.environ.get(_ENV_USAGE_LOG_PATH, _DEFAULT_USAGE_LOG)
    return Path(p).with_name("v1_audits.jsonl")


def _append_audit_index(audit_id: str, job_id: str, tenant_id: str) -> None:
    """Persist the ``audit_id → job_id`` mapping for later GETs."""
    path = _audit_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "audit_id": audit_id,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "submitted_at": _now_iso(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _find_audit_index(audit_id: str) -> dict[str, Any] | None:
    """Look up the most recent mapping for ``audit_id``.

    The most-recent-row-wins policy mirrors
    :meth:`JobQueue.find_by_encounter` — resubmitting the same
    encounter (or a re-issued audit_id) should point the caller
    at the freshest job.
    """
    path = _audit_index_path()
    if not path.exists():
        return None
    match: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("audit_id") == audit_id:
                match = rec
    return match


# ─── Usage log ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_audit_hex() -> str:
    """Random 12-hex audit id suffix (matches :class:`JobQueue` shape).

    The :class:`JobQueue` uses ``uuid.uuid4().hex[:12]`` for
    its ``job_id``; we mirror that length so the audit_id and
    job_id read identically in logs.
    """
    return secrets.token_hex(6)


def _append_usage_log(row: dict[str, Any]) -> None:
    """Append one row to the usage log.

    Failures are swallowed: a read-only filesystem or a full
    disk must not break the API. The warning lands in the
    application log so the operator notices on a deploy.
    """
    path = Path(os.environ.get(_ENV_USAGE_LOG_PATH, _DEFAULT_USAGE_LOG))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError as exc:  # pragma: no cover - defensive
        _log.warning("usage_log append failed: %s", exc)


def _auth_kind(request: Request) -> str:
    """One-word description of the auth header the caller used.

    For usage-log purposes only. Values:
    ``"bearer"``, ``"x-api-key"``, ``"missing"``.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return "bearer"
    if request.headers.get("x-api-key"):
        return "x-api-key"
    return "missing"


def _check_api_key(request: Request) -> Response | None:
    """Validate the request's API key.

    Returns ``None`` if the request is allowed, or a
    :class:`JSONResponse` to short-circuit with the appropriate
    error body. See module docstring for the auth contract.
    """
    expected = os.environ.get(_ENV_API_KEY, "").strip()
    if not expected:
        return JSONResponse(
            {
                "detail": (
                    "public API is disabled: ZORVA_API_KEY is not "
                    "configured on this server"
                ),
                "code": "api_key_not_configured",
            },
            status_code=503,
        )
    auth = request.headers.get("authorization", "")
    x_key = request.headers.get("x-api-key", "").strip()
    presented = ""
    if auth.lower().startswith("bearer "):
        presented = auth[len("Bearer "):].strip()
    elif x_key:
        presented = x_key
    if presented != expected:
        return JSONResponse(
            {"detail": "invalid or missing API key", "code": "unauthorized"},
            status_code=401,
        )
    return None


# ─── Claim validation ────────────────────────────────────────────────────


def _coerce_claim(body: dict[str, Any]) -> dict[str, Any]:
    """Normalise + validate an incoming v1 claim payload.

    Mirrors the encounter-upload shape so an EHR integration
    can lift the same JSON it already sends to the dashboard:

    * ``CPT_codes`` may be a string (comma-separated) or a list;
      we coerce to a list of strings.
    * ``NPI``, ``date_of_service``, ``patient_id``,
      ``encounter_id`` are stripped; empty values are rejected
      so a typo doesn't enqueue a job that immediately fails.
    """
    errs: list[str] = []
    out: dict[str, Any] = {}

    encounter_id = (body.get("encounter_id") or "")
    if not isinstance(encounter_id, str) or not encounter_id.strip():
        errs.append("encounter_id is required")
    else:
        out["encounter_id"] = encounter_id.strip()[:120]

    for key in ("patient_id", "NPI", "date_of_service"):
        v = body.get(key)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{key} is required")
        else:
            out[key] = v.strip()[:80]

    cpts_raw = body.get("CPT_codes")
    cpts: list[str] = []
    if isinstance(cpts_raw, list):
        cpts = [str(c).strip() for c in cpts_raw if str(c).strip()]
    elif isinstance(cpts_raw, str):
        cpts = [c.strip() for c in cpts_raw.split(",") if c.strip()]
    if not cpts:
        errs.append("CPT_codes is required and must be non-empty")
    out["CPT_codes"] = cpts

    if errs:
        raise HTTPException(status_code=400, detail={"errors": errs})
    return out


# ─── Audit status helpers ────────────────────────────────────────────────


# :class:`Job` uses ``__slots__`` so we can't attach the
# ``audit_id`` to the Job itself. This module-level dict is
# the in-process reverse lookup. The persistent copy lives
# in ``v1_audits.jsonl`` (via :func:`_append_audit_index`),
# so a server restart recovers audit_id ↔ job_id mappings
# from disk; the dict here just avoids an extra file read
# on every GET.
_audit_id_for_job_id: dict[str, str] = {}


def _audit_status_to_dict(job: Any) -> dict[str, Any]:
    """Serialise a queued Job into the v1 audit-status shape."""
    result = job.result or {}
    findings = result.get("findings") if isinstance(result, dict) else None
    audit_id = _audit_id_for_job_id.get(job.job_id) or ""
    out: dict[str, Any] = {
        "audit_id": audit_id,
        "job_id": job.job_id,
        "status": job.status,  # queued | running | done | failed
        "encounter_id": job.encounter_id,
        "submitted_at": job.submitted_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error or None,
        "has_discrepancy": bool(findings),
        "findings": findings or [],
        "summary": result.get("summary") if isinstance(result, dict) else None,
    }
    return out


# ─── Synchronous audit runner (v1) ───────────────────────────────────────


def _run_audit_synchronously(queue: JobQueue, audit_id: str) -> None:
    """Block until the queued audit reaches a terminal status.

    The default :class:`JobQueue` runs jobs in a daemon thread.
    The v1 contract is "POST → 202 with status_url, GET returns
    the result", which means the caller of POST is expected to
    poll — so we don't block the POST itself. This helper is
    invoked from the GET endpoint when the audit is still
    running: we wait up to ``_SYNC_POLL_TIMEOUT_SECONDS`` so a
    caller polling right after a POST gets the result without
    needing to loop client-side. The timeout is conservative
    because the v1 auditor (synth-stub) finishes in <1s; a real
    LLM-backed audit can exceed this, in which case we surface
    the running status and let the caller retry.
    """
    idx = _find_audit_index(audit_id)
    if idx is None:
        return
    deadline = time.time() + _SYNC_POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        job = queue.get(idx["job_id"])
        if job is None:
            return
        if job.status in ("done", "failed"):
            return
        time.sleep(_SYNC_POLL_INTERVAL_SECONDS)


# ─── FastAPI route registration ──────────────────────────────────────────


def register_public_api(
    app: FastAPI,
    *,
    queue: JobQueue | None = None,
    tenant_id: str | None = None,
) -> None:
    """Mount the ``/v1/*`` routes on ``app``.

    Parameters
    ----------
    app:
        The FastAPI instance to register routes on. Mounted
        directly so the v1 surface shares the existing
        middleware stack (CORS, GZip, etc.) configured by
        :func:`ai_billing_audit.api.create_app`.
    queue:
        Optional override for the audit job queue. Tests
        inject a :class:`JobQueue` with a custom runner so
        they can drive jobs to ``done`` deterministically.
    tenant_id:
        Tenant label written into the usage log and the
        audit index. Defaults to the operator's
        ``TENANT_ID`` env var, then ``"default"``.
    """
    if queue is None:
        # Look the queue up lazily per-request. Resolving it
        # once at module-import time would freeze the queue
        # at import time and defeat tests that swap in a
        # fresh queue with a custom runner via
        # ``reset_default_queue_for_tests()``.
        def _resolve_queue() -> JobQueue:
            return get_default_queue()

        queue_resolver: Any = _resolve_queue
    else:
        queue_resolver = lambda: queue  # noqa: E731 (closure capture)
    if tenant_id is None:
        tenant_id = os.environ.get("TENANT_ID", "default")

    # ── POST /v1/audits ──────────────────────────────────────────────────

    @app.post("/v1/audits", status_code=202)
    async def v1_create_audit(request: Request) -> JSONResponse:
        auth_err = _check_api_key(request)
        if auth_err is not None:
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "POST /v1/audits",
                    "status": auth_err.status_code,
                    "auth": _auth_kind(request),
                    "remote": request.client.host if request.client else "",
                    "tenant_id": tenant_id,
                }
            )
            return auth_err

        # Body parsing — we accept JSON only. Malformed JSON
        # gets a 400 with a stable shape so EHRs can branch
        # on it (rather than a stack trace).
        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "POST /v1/audits",
                    "status": 400,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                    "error": "malformed_json",
                }
            )
            raise HTTPException(
                status_code=400,
                detail={"errors": [f"malformed JSON: {exc}"]},
            )
        if not isinstance(raw, dict):
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "POST /v1/audits",
                    "status": 400,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                    "error": "body_not_object",
                }
            )
            raise HTTPException(
                status_code=400,
                detail={"errors": ["body must be a JSON object"]},
            )

        # Optional clinical note on the same body. EHRs that
        # already capture the chart can ship it; otherwise
        # the runner's stub path takes over.
        clinical_note = raw.get("clinical_note")
        if isinstance(clinical_note, str) and clinical_note.strip():
            # Persist so the runner picks it up. The runner
            # reads notes from logs/uploaded_notes/ via
            # _load_uploaded_note — see job_queue.py.
            try:
                from pathlib import Path as _P

                notes_dir = _P(__file__).resolve().parent.parent.parent / "logs" / "uploaded_notes"
                notes_dir.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.get("encounter_id") or "anon").strip("._")[:80] or "anon"
                # v1- prefix so the runner can distinguish v1
                # API notes from operator-dashboard ones when
                # it picks the most-recent note.
                (notes_dir / f"{safe}.v1.txt").write_text(clinical_note, encoding="utf-8")
            except OSError as exc:  # pragma: no cover - defensive
                _log.warning("could not persist v1 clinical note: %s", exc)

        claim = _coerce_claim(raw)
        audit_id = _AUDIT_ID_PREFIX + _new_audit_hex()
        job = queue_resolver().enqueue(
            encounter=claim,
            source="v1_api",
            source_filename=None,
            tenant_id=tenant_id,
        )
        # Track the audit_id → job_id mapping in-process so the
        # GET endpoint can surface it. The :class:`Job` uses
        # ``__slots__`` so we can't set a new attribute on it;
        # a module-level dict keyed by ``job_id`` is the
        # simplest v1-compatible alternative.
        _audit_id_for_job_id[job.job_id] = audit_id
        _append_audit_index(audit_id, job.job_id, tenant_id)
        _append_usage_log(
            {
                "ts": _now_iso(),
                "endpoint": "POST /v1/audits",
                "status": 202,
                "auth": _auth_kind(request),
                "tenant_id": tenant_id,
                "audit_id": audit_id,
                "job_id": job.job_id,
                "encounter_id": claim.get("encounter_id"),
            }
        )

        # Fire-and-forget webhook for those who opted in. We
        # dispatch ``audit_complete`` from the GET endpoint
        # (when the job transitions to done) rather than here
        # because the caller expects 202 + status_url, not
        # the final result. The ``finding_acknowledged`` event
        # is dispatched from the operator dashboard's accept /
        # dismiss endpoints (kanban task t_4496cee1 explicitly
        # lists both events).
        return JSONResponse(
            {
                "audit_id": audit_id,
                "status": "queued",
                "status_url": f"/v1/audits/{audit_id}",
                "encounter_id": claim.get("encounter_id"),
            },
            status_code=202,
        )

    # ── GET /v1/audits/{audit_id} ────────────────────────────────────────

    @app.get("/v1/audits/{audit_id}")
    async def v1_get_audit(request: Request, audit_id: str) -> JSONResponse:
        auth_err = _check_api_key(request)
        if auth_err is not None:
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "GET /v1/audits/{id}",
                    "status": auth_err.status_code,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                }
            )
            return auth_err

        idx = _find_audit_index(audit_id)
        if idx is None:
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "GET /v1/audits/{id}",
                    "status": 404,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                    "audit_id": audit_id,
                }
            )
            return JSONResponse(
                {"detail": f"audit_id {audit_id!r} not found", "code": "not_found"},
                status_code=404,
            )

        job = queue_resolver().get(idx["job_id"])
        if job is None:
            # Index says we know this id, but the in-memory
            # job was evicted (server restarted). Surface a
            # 410 Gone-style 404 so the EHR can re-submit.
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "GET /v1/audits/{id}",
                    "status": 404,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                    "audit_id": audit_id,
                    "error": "job_evicted",
                }
            )
            return JSONResponse(
                {
                    "detail": (
                        f"audit_id {audit_id!r} is no longer in the "
                        "in-memory registry; resubmit to re-audit"
                    ),
                    "code": "not_found",
                },
                status_code=404,
            )

        # If the job is still running, briefly wait so a
        # caller that polls right after POST gets the result
        # without burning round-trips.
        if job.status not in ("done", "failed"):
            _run_audit_synchronously(queue_resolver(), audit_id)
            job = queue_resolver().get(idx["job_id"]) or job

        body = _audit_status_to_dict(job)
        # External shape: status is "complete" not "done".
        body["status"] = "complete" if job.status == "done" else job.status
        # Fire audit_complete webhook on the first GET that
        # observes a transition to done. We track which audit
        # ids have been notified in-process; for v1 an
        # in-memory set is fine (a multi-replica deployment
        # would push this onto the same JSONL index).
        if job.status == "done":
            _maybe_notify_audit_complete(audit_id, body)

        _append_usage_log(
            {
                "ts": _now_iso(),
                "endpoint": "GET /v1/audits/{id}",
                "status": 200,
                "auth": _auth_kind(request),
                "tenant_id": tenant_id,
                "audit_id": audit_id,
                "job_status": body["status"],
            }
        )
        return JSONResponse(body)

    # ── POST /v1/webhooks ────────────────────────────────────────────────

    @app.post("/v1/webhooks")
    async def v1_create_webhook(request: Request) -> JSONResponse:
        auth_err = _check_api_key(request)
        if auth_err is not None:
            _append_usage_log(
                {
                    "ts": _now_iso(),
                    "endpoint": "POST /v1/webhooks",
                    "status": auth_err.status_code,
                    "auth": _auth_kind(request),
                    "tenant_id": tenant_id,
                }
            )
            return auth_err

        try:
            raw = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"errors": [f"malformed JSON: {exc}"]})
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail={"errors": ["body must be a JSON object"]})

        url = raw.get("url")
        events = raw.get("events")
        if not isinstance(url, str) or not url.strip():
            raise HTTPException(status_code=400, detail={"errors": ["url is required"]})
        if not isinstance(events, list) or not all(isinstance(e, str) for e in events):
            raise HTTPException(
                status_code=400,
                detail={"errors": ["events must be a list of strings"]},
            )

        try:
            record = register_webhook(
                url=url,
                events=events,
                tenant_id=tenant_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"errors": [str(exc)]})

        _append_usage_log(
            {
                "ts": _now_iso(),
                "endpoint": "POST /v1/webhooks",
                "status": 201,
                "auth": _auth_kind(request),
                "tenant_id": tenant_id,
                "webhook_id": record["webhook_id"],
                "events": events,
            }
        )
        return JSONResponse(record, status_code=201)


# ─── In-process deduplication for audit_complete ─────────────────────────


# Track audit_ids we've already notified so the GET endpoint
# doesn't fire the webhook on every poll after completion.
# Module-level set + lock because the request handler runs on
# a worker thread (TestClient + uvicorn both share this state).
_notified_lock = threading.Lock()
_already_notified: set[str] = set()


def _maybe_notify_audit_complete(audit_id: str, body: dict[str, Any]) -> None:
    """Fire ``audit_complete`` webhook once per audit_id.

    Idempotent within the lifetime of the process; a server
    restart re-fires the webhook on the next GET, which is the
    documented behaviour for at-least-once delivery.
    """
    with _notified_lock:
        if audit_id in _already_notified:
            return
        _already_notified.add(audit_id)
    try:
        dispatch_event(
            EVENT_AUDIT_COMPLETE,
            {
                "audit_id": audit_id,
                "encounter_id": body.get("encounter_id"),
                "has_discrepancy": body.get("has_discrepancy"),
                "findings": body.get("findings") or [],
                "summary": body.get("summary"),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        # dispatch_event itself catches network errors; this
        # is a last-resort guard so a misbehaving webhook
        # subscriber can't 500 the GET response.
        _log.warning("audit_complete dispatch failed for %s: %s", audit_id, exc)


def emit_finding_acknowledged(
    *,
    audit_id: str | None,
    encounter_id: str,
    finding_id: str,
    action: str,
    tenant_id: str = "default",
) -> dict[str, int]:
    """Public helper for the operator dashboard's accept/dismiss endpoints.

    Called from ``encounters/{id}/finding/{fid}/accept`` and
    ``.../dismiss`` so EHRs subscribed to the
    ``finding_acknowledged`` event get notified when a biller
    acknowledges a finding. Lives in :mod:`public_api` rather
    than in :mod:`webhooks` because the audit_id field is a
    v1-API concept; the dispatcher itself is event-agnostic.

    Best-effort: never raises (see :func:`webhooks.dispatch_event`).
    """
    payload = {
        "audit_id": audit_id,
        "encounter_id": encounter_id,
        "finding_id": finding_id,
        "action": action,
        "tenant_id": tenant_id,
    }
    # Look the dispatcher up via the live module each call
    # so monkeypatching ``webhooks_module.dispatch_event`` in
    # tests affects this path. Importing it at module top
    # would freeze the reference and bypass test patches.
    from ai_billing_audit import webhooks as _webhooks

    return _webhooks.dispatch_event(EVENT_FINDING_ACKNOWLEDGED, payload)


__all__ = [
    "emit_finding_acknowledged",
    "register_public_api",
]
