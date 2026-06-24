"""Webhook registration + delivery (kanban ``t_4496cee1``).

Two concerns live here:

1. **Registration.** ``POST /v1/webhooks`` accepts a body with
   ``{url, events}`` and persists it to an append-only JSONL log
   at ``/app/logs/webhooks.jsonl`` (path configurable via the
   ``ZORVA_WEBHOOK_LOG_PATH`` env var so tests can point at
   ``tmp_path``). Each registration gets a stable ``webhook_id``
   so the caller can later delete or update it.

2. **Delivery.** :func:`dispatch_event` walks every registered
   webhook and POSTs the event payload to each ``url`` whose
   ``events`` list contains the event name. Failures (network,
   timeout, non-2xx) are caught and logged but never raised:
   webhook delivery is best-effort and must not block the
   audit pipeline.

v1 simplification: there is no separate worker. The public API
fires ``dispatch_event("audit_complete", {...})`` synchronously
right after an audit finishes. This is intentionally simple —
the webhook contract is exercised end-to-end on every call,
no queues or schedulers needed. A background worker can be
added later by replacing :func:`dispatch_event`'s caller with
a Celery / RQ / cron task without touching the registration
format or the event payload shape.

Storage layout
--------------
``webhooks.jsonl`` is a newline-delimited JSON file. Each line is
a single registration::

    {"webhook_id": "wh_<12 hex>", "url": "https://...", "events": ["audit_complete"], "created_at": "...", "tenant_id": "default"}

Delivery logs land in the same file via :func:`_append_delivery_log`
(line prefixed ``{"_kind": "delivery", ...}``). The two record
shapes are distinguishable via the ``_kind`` field on delivery
records — registrations do NOT carry a ``_kind``.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# Path: defaults to /app/logs/webhooks.jsonl inside the container
# (matches the deployment layout used by upload_jobs.jsonl). Tests
# override via the ZORVA_WEBHOOK_LOG_PATH env var.
_DEFAULT_LOG_PATH = "/app/logs/webhooks.jsonl"


# Event names the v1 public API recognises. Adding a new event
# is a one-line addition to this set + whichever endpoint emits
# the new event; the delivery / storage code is event-agnostic.
EVENT_AUDIT_COMPLETE = "audit_complete"
EVENT_FINDING_ACKNOWLEDGED = "finding_acknowledged"
_KNOWN_EVENTS: frozenset[str] = frozenset(
    {EVENT_AUDIT_COMPLETE, EVENT_FINDING_ACKNOWLEDGED}
)


def _log_path() -> Path:
    """Resolve the webhook JSONL log path.

    Honours ``ZORVA_WEBHOOK_LOG_PATH`` for tests; falls back to
    the production default. Returned as a :class:`Path` so the
    tests can compare against ``tmp_path`` paths.
    """
    return Path(os.environ.get("ZORVA_WEBHOOK_LOG_PATH", _DEFAULT_LOG_PATH))


def _now_iso() -> str:
    """ISO-8601 UTC timestamp (seconds precision, trailing Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_webhook_id() -> str:
    """Stable, opaque webhook identifier.

    The ``wh_`` prefix makes the id self-describing in logs and
    in the JSONL file; the hex suffix is from :func:`secrets`
    so two registrations in the same microsecond still differ.
    """
    return "wh_" + secrets.token_hex(6)


# ─── Registration ─────────────────────────────────────────────────────────


def register_webhook(
    *,
    url: str,
    events: list[str],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Persist a new webhook registration and return its descriptor.

    Parameters
    ----------
    url:
        Absolute http(s) URL the dispatcher will POST event
        payloads to. We don't enforce a schema or a domain in
        v1 — the operator is responsible for sanity-checking
        the URL at registration time. (We do refuse empty
        strings so a typo'd ``""`` doesn't register a webhook
        that will silently 404 every dispatch.)
    events:
        List of event names the webhook wants to receive.
        Empty list is allowed (the webhook exists but never
        fires — useful for "registered but disabled" state).
        Unknown event names are accepted (forward-compat)
        but logged at WARNING so the operator notices.
    tenant_id:
        Optional scoping label. The portal is single-tenant
        today; the field is captured so a future multi-tenant
        deployment doesn't need a migration.

    Returns
    -------
    dict with keys ``webhook_id``, ``url``, ``events``,
    ``created_at``, ``tenant_id`` — exactly what the caller
    will receive in the HTTP response body.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    url = url.strip()
    record = {
        "webhook_id": _new_webhook_id(),
        "url": url,
        "events": list(events or []),
        "created_at": _now_iso(),
        "tenant_id": tenant_id or "default",
    }
    unknown = sorted(set(record["events"]) - _KNOWN_EVENTS)
    if unknown:
        _log.warning(
            "webhook %s registered for unknown events %s; will never fire",
            record["webhook_id"],
            unknown,
        )
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def list_webhooks(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return every registration in the log.

    Optionally filtered by ``tenant_id``. Malformed lines are
    skipped (a single bad row must not break the dispatcher).
    """
    path = _log_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                _log.warning("skipping malformed webhook log row")
                continue
            # Skip delivery-log rows; they live in the same file
            # but are distinguished by the ``_kind`` key. (See
            # ``_append_delivery_log``.)
            if not isinstance(rec, dict) or rec.get("_kind") == "delivery":
                continue
            if tenant_id and rec.get("tenant_id") != tenant_id:
                continue
            out.append(rec)
    return out


# ─── Delivery ─────────────────────────────────────────────────────────────


def _append_delivery_log(entry: dict[str, Any]) -> None:
    """Append a delivery-attempt record to the same JSONL log.

    Storing delivery attempts in the same file as registrations
    keeps the v1 surface single-file: one path to mount, one
    path to back up. The ``_kind`` discriminator on delivery
    rows keeps :func:`list_webhooks` from surfacing them.
    """
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _deliver_one(
    hook: dict[str, Any],
    event: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> bool:
    """POST ``payload`` to one webhook URL.

    Returns ``True`` on a 2xx response, ``False`` otherwise
    (network error, timeout, non-2xx). Never raises — webhook
    delivery failures must never bubble up into the audit
    pipeline. The :mod:`urllib` stdlib is used instead of
    ``requests`` to keep the public API self-contained
    (no third-party runtime deps).
    """
    body = json.dumps(
        {"event": event, "delivered_at": _now_iso(), "data": payload},
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        hook["url"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "zorva-webhook/1",
            "X-Zorva-Event": event,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
            _append_delivery_log(
                {
                    "_kind": "delivery",
                    "webhook_id": hook.get("webhook_id"),
                    "event": event,
                    "url": hook.get("url"),
                    "status_code": resp.status,
                    "ok": ok,
                    "attempted_at": _now_iso(),
                }
            )
            return ok
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        _log.warning(
            "webhook %s delivery to %s failed: %s",
            hook.get("webhook_id"),
            hook.get("url"),
            exc,
        )
        _append_delivery_log(
            {
                "_kind": "delivery",
                "webhook_id": hook.get("webhook_id"),
                "event": event,
                "url": hook.get("url"),
                "status_code": None,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "attempted_at": _now_iso(),
            }
        )
        return False


def dispatch_event(event: str, payload: dict[str, Any]) -> dict[str, int]:
    """Deliver ``payload`` to every webhook subscribed to ``event``.

    Walks :func:`list_webhooks`, filters by event name, and
    sequentially POSTs to each subscribed URL. Returns a
    summary dict ``{"delivered": N, "failed": M}`` so callers
    can log a single rollup line per event.

    Sequential (not parallel) by design: v1 has at most a
    handful of registered webhooks and parallelising would
    complicate error handling without a measurable latency
    win. A background poller / worker can introduce
    concurrency later without changing this contract.
    """
    subs = [h for h in list_webhooks() if event in (h.get("events") or [])]
    delivered = 0
    failed = 0
    for hook in subs:
        if _deliver_one(hook, event, payload):
            delivered += 1
        else:
            failed += 1
    if subs:
        _log.info(
            "webhook dispatch %s: delivered=%d failed=%d subscribers=%d",
            event,
            delivered,
            failed,
            len(subs),
        )
    return {"delivered": delivered, "failed": failed, "subscribers": len(subs)}


__all__ = [
    "EVENT_AUDIT_COMPLETE",
    "EVENT_FINDING_ACKNOWLEDGED",
    "dispatch_event",
    "list_webhooks",
    "register_webhook",
]
