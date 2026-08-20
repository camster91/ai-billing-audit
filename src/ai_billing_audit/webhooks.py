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

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
)

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
_SIGNATURE_MAX_AGE_SECONDS = 300


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


def verify_webhook_signature(
    *,
    body: bytes,
    timestamp: str,
    delivery_id: str,
    signature: str,
    secret: str,
    now: int | None = None,
    seen_delivery_ids: set[str] | None = None,
    max_age_seconds: int = _SIGNATURE_MAX_AGE_SECONDS,
    previous_secret: str | None = None,
    previous_signature: str | None = None,
) -> bool:
    """Verify a Zorva v1 callback and optionally reject replay.

    Consumers should pass the raw request body, the three ``X-Zorva-*``
    headers, and the signing secret returned once during registration. A
    caller-owned ``seen_delivery_ids`` set provides in-process replay
    protection; durable consumers should back that set with their own
    database or idempotency store.

    During a rotation overlap (issue #21), the consumer also passes
    the ``previous_secret`` it stored before the rotation and the
    ``X-Zorva-Signature-Previous`` header value. Either signature
    verifies; the replay check applies to the delivery id either way.
    """
    if not secret or not delivery_id or not isinstance(body, bytes):
        return False
    if not timestamp.isdigit() or not signature.startswith("v1="):
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    if max_age_seconds < 0 or abs(current - timestamp_int) > max_age_seconds:
        return False
    if seen_delivery_ids is not None and delivery_id in seen_delivery_ids:
        return False
    signed = timestamp.encode("ascii") + b"." + body
    expected = hmac.new(
        secret.encode("utf-8"), signed, hashlib.sha256
    ).hexdigest()
    supplied = signature[3:]
    if hmac.compare_digest(supplied, expected):
        if seen_delivery_ids is not None:
            seen_delivery_ids.add(delivery_id)
        return True
    # Try the previous (rotation-overlap) signature if supplied.
    # A well-formed value is exactly "v1=<hex>"; anything else
    # is a client bug and we reject without further work.
    if previous_secret and previous_signature and previous_signature.startswith("v1="):
        prev_expected = hmac.new(
            previous_secret.encode("utf-8"), signed, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(previous_signature[3:], prev_expected):
            if seen_delivery_ids is not None:
                seen_delivery_ids.add(delivery_id)
            return True
    return False


def _allow_private_webhook_urls() -> bool:
    """Escape hatch for hermetic tests that spin up loopback receivers.

    Production must leave this unset. Local webhook integration
    tests set ``ZORVA_WEBHOOK_ALLOW_PRIVATE=1``.
    """
    return os.environ.get("ZORVA_WEBHOOK_ALLOW_PRIVATE", "") == "1"


def validate_webhook_url(url: str) -> str:
    """Return a sanitized absolute webhook URL or raise ``ValueError``.

    SSRF controls (production):
      * scheme must be ``https`` (``http`` only when private URLs
        are explicitly allowed for tests)
      * hostname must resolve; every resolved address must be a
        public global unicast address (no loopback / link-local /
        private / multicast / unspecified / reserved)
      * literal IP hosts are checked the same way
      * userinfo (``user:pass@host``) is rejected
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    allow_private = _allow_private_webhook_urls()
    if scheme == "https":
        pass
    elif scheme == "http" and allow_private:
        pass
    else:
        raise ValueError("url must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must not contain userinfo")
    host = parsed.hostname
    if not host:
        raise ValueError("url must include a hostname")
    # Block obvious metadata / internal hostnames even before DNS.
    blocked_hosts = {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
    if host.lower() in blocked_hosts and not allow_private:
        raise ValueError("url host is not allowed")
    try:
        addrinfos = socket.getaddrinfo(
            host, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError(f"url host could not be resolved: {exc}") from exc
    if not addrinfos:
        raise ValueError("url host could not be resolved")
    for info in addrinfos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ValueError(f"url resolved to invalid address: {ip_str}") from exc
        if allow_private:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("url must not target a private or reserved address")
    # Rebuild without fragment; keep query/path as provided.
    cleaned = urllib.parse.urlunparse(
        (scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return cleaned


# ─── Registration ─────────────────────────────────────────────────────────


def register_webhook(
    *,
    url: str,
    events: list[str],
    tenant_id: str | None = None,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    """Persist a new webhook registration and return its descriptor.

    Parameters
    ----------
    url:
        Absolute https URL the dispatcher will POST event
        payloads to. Private / loopback / link-local / metadata
        targets are rejected (SSRF defence). Tests may set
        ``ZORVA_WEBHOOK_ALLOW_PRIVATE=1`` to exercise loopback
        receivers.
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
    signing_secret:
        Optional caller-supplied secret for migration. When
        supplied (and >= 16 chars) the registration uses it
        directly instead of generating a new one. This is the
        supported path for migrating a consumer from an
        out-of-band-issued secret into the Zorva-managed
        rotation flow. When omitted (the default), a fresh
        32-byte URL-safe secret is generated and returned once
        in the descriptor. The caller is responsible for
        surfacing the secret exactly once to the consumer.

    Returns
    -------
    dict with keys ``webhook_id``, ``url``, ``events``,
    ``created_at``, ``tenant_id`` — exactly what the caller
    will receive in the HTTP response body.
    """
    url = validate_webhook_url(url)
    if signing_secret is not None:
        if not isinstance(signing_secret, str) or len(signing_secret) < 16:
            raise ValueError(
                "signing_secret must be a string of >= 16 characters when supplied"
            )
        secret = signing_secret
    else:
        secret = secrets.token_urlsafe(32)
    record = {
        "webhook_id": _new_webhook_id(),
        "url": url,
        "events": list(events or []),
        "created_at": _now_iso(),
        "tenant_id": tenant_id or "default",
        "_signing_secret": secret,
    }
    unknown = sorted(set(record["events"]) - _KNOWN_EVENTS)
    if unknown:
        _log.warning(
            "webhook %s registered for unknown events %s; will never fire",
            record["webhook_id"],
            unknown,
        )
    append_encrypted_json_record(_log_path(), record)
    return record


def list_webhooks(*, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return the current state of every registration in the log.

    Optionally filtered by ``tenant_id``. Malformed lines are
    skipped (a single bad row must not break the dispatcher).

    The on-disk format is append-only: a rotation drops a new
    row next to the original. ``list_webhooks`` de-duplicates by
    ``webhook_id`` and returns the LAST row per id so callers
    see the current signing secret (and any
    ``previous_secret`` overlap) without writing a separate
    rewrite step at rotation time.
    """
    path = _log_path()
    if not path.exists():
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for rec in read_encrypted_json_records(path):
        # Skip delivery-log rows; they live in the same file
        # but are distinguished by the ``_kind`` key. (See
        # ``_append_delivery_log``.)
        if rec.get("_kind") == "delivery":
            continue
        if tenant_id and rec.get("tenant_id") != tenant_id:
            continue
        wid = rec.get("webhook_id")
        if not isinstance(wid, str):
            continue
        by_id[wid] = rec
    return list(by_id.values())


# ─── Delivery ─────────────────────────────────────────────────────────────


def _append_delivery_log(entry: dict[str, Any]) -> None:
    """Append a delivery-attempt record to the same JSONL log.

    Storing delivery attempts in the same file as registrations
    keeps the v1 surface single-file: one path to mount, one
    path to back up. The ``_kind`` discriminator on delivery
    rows keeps :func:`list_webhooks` from surfacing them.
    """
    append_encrypted_json_record(_log_path(), entry)


def migrate_webhook_log() -> int:
    """Encrypt the legacy webhook registration and delivery log."""
    return migrate_plaintext_jsonl(_log_path())


# ─── Rotation (issue #21) ─────────────────────────────────────────────────

# Maximum overlap window a consumer can request. Anything
# longer than 24h is rejected because the previous_secret +
# expires_at fields would let a stolen former secret keep
# working for too long after the operator rotates.
_MAX_ROTATION_OVERLAP_SECONDS = 24 * 60 * 60
_DEFAULT_ROTATION_OVERLAP_SECONDS = 60 * 60  # 1h


def rotate_webhook_signing_secret(
    webhook_id: str,
    *,
    new_secret: str | None = None,
    overlap_seconds: int = _DEFAULT_ROTATION_OVERLAP_SECONDS,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Rotate a webhook's signing secret with a bounded overlap window.

    Issue #21 acceptance criterion: "Rotation overlap is bounded and
    audited." This implements the v1 rotation contract:

      1. The current secret moves into ``previous_secret`` (plus
         ``previous_secret_expires_at``) so the next ``overlap_seconds``
         of deliveries are dual-signed.
      2. The new secret (auto-generated if not supplied) takes over
         as the active ``_signing_secret``. The new secret is
         returned to the caller exactly once — never logged, never
         persisted past the JSONL row, never echoed in error
         messages.
      3. After ``previous_secret_expires_at``, deliveries sign with
         the new secret only. The consumer's verify path accepts
         either signature during the overlap, then the new only.
      4. The rotation is recorded in the JSONL as a new row
         (replacing the old one) so the audit trail shows the
         rotation timestamp.

    Overlap is bounded by ``_MAX_ROTATION_OVERLAP_SECONDS`` (24h).
    A larger request is silently capped to the max so a misconfigured
    operator cannot keep a stolen secret alive indefinitely.

    The caller (a tenant admin via the public API) is responsible
    for distributing the new secret to the consumer out-of-band
    before the rotation expires. The verify side accepts either
    secret during the overlap; after the overlap only the new
    secret verifies.
    """
    if not webhook_id or not isinstance(webhook_id, str):
        raise ValueError("webhook_id is required")
    if overlap_seconds <= 0:
        raise ValueError("overlap_seconds must be positive")
    overlap = min(int(overlap_seconds), _MAX_ROTATION_OVERLAP_SECONDS)

    if new_secret is None:
        new_secret = secrets.token_urlsafe(32)
    if not isinstance(new_secret, str) or len(new_secret) < 16:
        raise ValueError(
            "new_secret must be a string of >= 16 characters when supplied"
        )

    path = _log_path()
    path = Path(path) if not isinstance(path, Path) else path
    rows = read_encrypted_json_records(path)
    target_idx = None
    for i, rec in enumerate(rows):
        if rec.get("_kind") == "delivery":
            continue
        if rec.get("webhook_id") != webhook_id:
            continue
        if tenant_id is not None and rec.get("tenant_id") != tenant_id:
            continue
        target_idx = i
        target = rec
        break
    if target_idx is None:
        raise KeyError(f"webhook {webhook_id} not found")

    # The new secret is the only field the caller needs back. The
    # caller is the public API; it must surface it once in the
    # HTTP response. The Python caller of rotate_webhook_signing_secret
    # (i.e. the API handler) is responsible for NOT logging it.
    expires_at = _now_iso_plus_seconds(overlap)
    updated = {
        **target,
        "_signing_secret": new_secret,
        "previous_secret": target.get("_signing_secret"),
        "previous_secret_expires_at": expires_at,
        "rotated_at": _now_iso(),
    }
    rows[target_idx] = updated
    # Re-append the entire file (append-only rotated, idempotent).
    # The plaintext migration helper is for legacy rows; we
    # just rewrite the current JSONL with the new row replacing
    # the old. encrypt_then_append is fine because the helper
    # dedups by webhook_id (see ``append_encrypted_json_record``).
    from ai_billing_audit.clinical_note_storage import (
        append_encrypted_json_record,
    )
    append_encrypted_json_record(path, updated)
    # Return only the new secret and the audit fields. The
    # previous_secret is NOT returned — the caller (the API
    # handler) does not need it; the verify path already
    # accepts it during the overlap window.
    return {
        "webhook_id": updated["webhook_id"],
        "signing_secret": new_secret,  # returned once
        "previous_secret_expires_at": expires_at,
        "rotated_at": updated["rotated_at"],
        "overlap_seconds": overlap,
    }


def _now_iso_plus_seconds(seconds: int) -> str:
    """Return ``now + seconds`` in ISO-8601 with ``+00:00`` offset.

    The verify path compares ``X-Zorva-Timestamp`` (a Unix integer
    of the same instant) against ``max_age_seconds``. The
    ``previous_secret_expires_at`` field is recorded in ISO for
    operator audit; the verify path does not consult it.
    """
    from datetime import timedelta

    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()


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
    # Re-validate at delivery time so a stale JSONL row that
    # somehow points at a private IP cannot SSRF either.
    try:
        target = validate_webhook_url(str(hook.get("url") or ""))
    except ValueError as exc:
        _append_delivery_log(
            {
                "_kind": "delivery",
                "webhook_id": hook.get("webhook_id"),
                "event": event,
                "url": hook.get("url"),
                "status_code": None,
                "ok": False,
                "error": f"ssrf_blocked: {exc}",
                "attempted_at": _now_iso(),
            }
        )
        return False
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    delivery_id = "dlv_" + secrets.token_hex(12)
    body = json.dumps(
        {"event": event, "delivered_at": _now_iso(), "data": payload},
        separators=(",", ":"),
    ).encode("utf-8")
    signing_secret = str(hook.get("_signing_secret") or "")
    signed_payload = timestamp.encode("ascii") + b"." + body
    signature = (
        hmac.new(
            signing_secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()
        if signing_secret
        else ""
    )
    # During a rotation overlap window, sign the same payload with
    # the previous secret too and emit the secondary signature in
    # X-Zorva-Signature-Previous. The consumer's verify path
    # accepts either signature during the overlap. After
    # previous_secret_expires_at this is dropped automatically.
    previous_secret = str(hook.get("previous_secret") or "")
    previous_expires = str(hook.get("previous_secret_expires_at") or "")
    previous_signature = ""
    if previous_secret and previous_expires:
        try:
            exp = datetime.fromisoformat(previous_expires.replace("Z", "+00:00"))
            if exp > datetime.now(timezone.utc):
                previous_signature = hmac.new(
                    previous_secret.encode("utf-8"),
                    signed_payload,
                    hashlib.sha256,
                ).hexdigest()
        except ValueError:
            # Malformed expires_at — treat as no overlap.
            previous_signature = ""
    req = urllib.request.Request(
        target,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "zorva-webhook/1",
            "X-Zorva-Event": event,
            "X-Zorva-Delivery": delivery_id,
            "X-Zorva-Timestamp": timestamp,
            "X-Zorva-Signature": f"v1={signature}",
            **(
                {"X-Zorva-Signature-Previous": f"v1={previous_signature}"}
                if previous_signature
                else {}
            ),
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
                    "url": target,
                    "status_code": resp.status,
                    "ok": ok,
                    "attempted_at": _now_iso(),
                }
            )
            return ok
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
    ) as exc:
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
    "verify_webhook_signature",
]
