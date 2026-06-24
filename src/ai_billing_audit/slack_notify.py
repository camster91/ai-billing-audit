"""Slack webhook notifications (kanban ``t_c9cf54f4``).

Bridges the existing webhook surface to Slack's incoming-webhook +
Block Kit format. The dashboard's :mod:`webhooks` module already
delivers JSON POSTs to any URL, so this module adds the Slack-
specific shape on top of the same dispatcher pattern.

Two concerns live here:

1. **Registration.** ``POST /api/integrations/slack`` accepts
   ``{webhook_url, channel, events}`` and persists the
   registration to ``/app/logs/slack_integrations.jsonl`` (path
   configurable via ``ZORVA_SLACK_LOG_PATH`` for tests). Each
   registration gets a stable ``slack_id`` so the caller can
   later delete or update it.

2. **Delivery.** :func:`notify_slack` looks up the registered
   Slack webhook for a tenant + event, builds a Block Kit
   payload, and POSTs it. Failures (network, timeout, non-2xx)
   are caught and logged but never raised: Slack delivery is
   best-effort and must not block the audit pipeline.

Storage layout
--------------
``slack_integrations.jsonl`` is a newline-delimited JSON file.
Each line is a single registration::

    {"slack_id": "sl_<12 hex>", "webhook_url": "https://hooks.slack.com/...",
     "channel": "#billing-audits", "events": ["audit_complete", "high_finding"],
     "clinic_id": "default", "created_at": "..."}

Delivery logs land in the same file via :func:`_append_delivery_log`
(line prefixed ``{"_kind": "delivery", ...}``). The two record
shapes are distinguishable via the ``_kind`` field on delivery
records — registrations do NOT carry a ``_kind``.

v1 simplification: there is no separate worker. ``notify_slack``
runs synchronously inside the audit / bulk-accept / bulk-dismiss
code path. The dispatcher swallows network errors so a Slack
outage can't 500 an audit completion. A background worker can
be added later by replacing ``notify_slack``'s caller with a
Celery / RQ / cron task without touching the registration
format or the Block Kit payload shape.

Why a separate module from :mod:`webhooks`
------------------------------------------
The :mod:`webhooks` module targets EHR integrations: generic
JSON, multi-tenant fan-out, no channel awareness. Slack has
its own payload contract (Block Kit ``blocks`` + ``channel``
override) and one-webhook-per-channel routing. Conflating the
two would force every webhook subscriber to opt out of Slack
quirks and vice versa. Keeping them separate means an
integration can register either kind independently.
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


# Path: defaults to /app/logs/slack_integrations.jsonl inside the
# container. Tests override via the ZORVA_SLACK_LOG_PATH env var.
_DEFAULT_LOG_PATH = "/app/logs/slack_integrations.jsonl"


# Event names the v1 Slack surface recognises. Adding a new event
# is a one-line addition to this set + whichever call site emits
# the new event; the dispatcher is event-agnostic.
EVENT_AUDIT_COMPLETE = "audit_complete"
EVENT_HIGH_FINDING = "high_finding"
_KNOWN_EVENTS: frozenset[str] = frozenset(
    {EVENT_AUDIT_COMPLETE, EVENT_HIGH_FINDING}
)


def _log_path() -> Path:
    """Resolve the Slack JSONL log path.

    Honours ``ZORVA_SLACK_LOG_PATH`` for tests; falls back to
    the production default. Returned as a :class:`Path` so the
    tests can compare against ``tmp_path`` paths.
    """
    return Path(os.environ.get("ZORVA_SLACK_LOG_PATH", _DEFAULT_LOG_PATH))


def _now_iso() -> str:
    """ISO-8601 UTC timestamp (seconds precision, trailing Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_slack_id() -> str:
    """Stable, opaque Slack-integration identifier.

    The ``sl_`` prefix makes the id self-describing in logs and
    in the JSONL file; the hex suffix is from :func:`secrets`
    so two registrations in the same microsecond still differ.
    """
    return "sl_" + secrets.token_hex(6)


# ─── Registration ─────────────────────────────────────────────────────────


def register_slack(
    *,
    webhook_url: str,
    channel: str,
    events: list[str],
    clinic_id: str | None = None,
) -> dict[str, Any]:
    """Persist a new Slack integration and return its descriptor.

    Parameters
    ----------
    webhook_url:
        The Slack incoming-webhook URL (``https://hooks.slack.com/...``).
        We don't enforce the Slack domain in v1 — a custom proxy or
        dev-channel mock (e.g. ``http://127.0.0.1:NNN/`` for tests)
        can substitute, and the operator is responsible for sanity-
        checking at registration time. Empty strings are refused.
    channel:
        Human-readable channel label (``"#billing-audits"``). The
        Block Kit ``channel`` field overrides the webhook's default
        routing so a single webhook can fan out to multiple
        channels if the operator chooses to reuse one. Stored as
        supplied so the audit log is self-describing.
    events:
        List of event names the integration wants to receive.
        Empty list is allowed (registered but disabled). Unknown
        event names are accepted (forward-compat) but logged at
        WARNING so the operator notices.
    clinic_id:
        Tenant scoping label. The portal is single-tenant today;
        the field is captured so a future multi-tenant deployment
        doesn't need a migration. Defaults to ``"default"`` when
        omitted.

    Returns
    -------
    dict with keys ``slack_id``, ``webhook_url``, ``channel``,
    ``events``, ``clinic_id``, ``created_at`` — exactly what the
    caller will receive in the HTTP response body.
    """
    if not isinstance(webhook_url, str) or not webhook_url.strip():
        raise ValueError("webhook_url must be a non-empty string")
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("channel must be a non-empty string")
    webhook_url = webhook_url.strip()
    channel = channel.strip()
    record = {
        "slack_id": _new_slack_id(),
        "webhook_url": webhook_url,
        "channel": channel,
        "events": list(events or []),
        "clinic_id": clinic_id or "default",
        "created_at": _now_iso(),
    }
    unknown = sorted(set(record["events"]) - _KNOWN_EVENTS)
    if unknown:
        _log.warning(
            "slack %s registered for unknown events %s; will never fire",
            record["slack_id"],
            unknown,
        )
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def list_integrations(*, clinic_id: str | None = None) -> list[dict[str, Any]]:
    """Return every Slack registration in the log.

    Optionally filtered by ``clinic_id``. Malformed lines are
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
                _log.warning("skipping malformed slack log row")
                continue
            # Skip delivery-log rows; they live in the same file
            # but are distinguished by the ``_kind`` key.
            if not isinstance(rec, dict) or rec.get("_kind") == "delivery":
                continue
            if clinic_id and rec.get("clinic_id") != clinic_id:
                continue
            out.append(rec)
    return out


# ─── Delivery ─────────────────────────────────────────────────────────────


def _append_delivery_log(entry: dict[str, Any]) -> None:
    """Append a delivery-attempt record to the same JSONL log.

    Storing delivery attempts in the same file as registrations
    keeps the v1 surface single-file: one path to mount, one
    path to back up. The ``_kind`` discriminator on delivery
    rows keeps :func:`list_integrations` from surfacing them.
    """
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _build_blocks(event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Render a Block Kit ``blocks`` array for ``event`` + ``payload``.

    The shape is deliberately conservative — Slack will render
    anything in the Block Kit JSON schema, but billers and
    clinic admins read these on phones between patients, so the
    message stays short and scannable. New event types should
    add a branch here; the dispatcher passes the result through
    unchanged.

    Event → headline mapping
    ------------------------
    ``audit_complete``  → "Audit complete" + summary line
    ``high_finding``    → "High-severity finding" + rule + quote
    anything else       → generic "Zorva event: <name>" + payload
    """
    if event == EVENT_AUDIT_COMPLETE:
        headline = ":white_check_mark: Audit complete"
        summary = str(payload.get("summary") or "").strip()
        findings_n = payload.get("findings_count")
        if isinstance(findings_n, int):
            sub = f"{findings_n} finding{'s' if findings_n != 1 else ''} on encounter {payload.get('encounter_id', '?')}"
        else:
            sub = f"Encounter {payload.get('encounter_id', '?')}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": sub}},
        ]
        if summary:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"> {summary[:300]}"}}
            )
        return blocks
    if event == EVENT_HIGH_FINDING:
        headline = ":rotating_light: High-severity finding actioned"
        rule = payload.get("rule_id") or payload.get("rule") or "?"
        action = payload.get("action") or "reviewed"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Encounter*\n`{payload.get('encounter_id', '?')}`"},
                    {"type": "mrkdwn", "text": f"*Rule*\n`{rule}`"},
                    {"type": "mrkdwn", "text": f"*Action*\n{action}"},
                    {"type": "mrkdwn", "text": f"*Severity*\nhigh"},
                ],
            },
        ]
        quote = payload.get("quote")
        if isinstance(quote, str) and quote.strip():
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"> {quote[:300]}"}}
            )
        return blocks
    # Fallback for unknown events: still emit *something* so the
    # operator gets a paper trail. Forward-compat friendly.
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Zorva event: `{event}`*\n```json\n{json.dumps(payload, indent=2)[:1500]}\n```"},
        }
    ]


def _build_slack_payload(
    event: str,
    payload: dict[str, Any],
    *,
    channel: str | None = None,
) -> dict[str, Any]:
    """Wrap the Block Kit blocks + metadata in a top-level Slack body.

    Slack's incoming-webhook contract accepts JSON with at least
    ``text`` (fallback for clients that don't render blocks) and
    optionally ``blocks`` / ``channel`` / ``attachments``.
    """
    body: dict[str, Any] = {
        "text": f"Zorva: {event}",
        "blocks": _build_blocks(event, payload),
    }
    if channel:
        body["channel"] = channel
    return body


def _deliver_one(
    hook: dict[str, Any],
    event: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> bool:
    """POST a Block Kit body to one Slack integration.

    Returns ``True`` on a 2xx response, ``False`` otherwise
    (network error, timeout, non-2xx). Never raises — Slack
    delivery failures must never bubble up into the audit
    pipeline. The :mod:`urllib` stdlib is used instead of
    ``requests`` to keep the public API self-contained
    (no third-party runtime deps).
    """
    body = json.dumps(
        _build_slack_payload(
            event,
            payload,
            channel=hook.get("channel"),
        ),
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        hook["webhook_url"],
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "zorva-slack/1",
            "X-Zorva-Event": event,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
            _append_delivery_log(
                {
                    "_kind": "delivery",
                    "slack_id": hook.get("slack_id"),
                    "event": event,
                    "webhook_url": hook.get("webhook_url"),
                    "status_code": resp.status,
                    "ok": ok,
                    "attempted_at": _now_iso(),
                }
            )
            return ok
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        _log.warning(
            "slack %s delivery to %s failed: %s",
            hook.get("slack_id"),
            hook.get("webhook_url"),
            exc,
        )
        _append_delivery_log(
            {
                "_kind": "delivery",
                "slack_id": hook.get("slack_id"),
                "event": event,
                "webhook_url": hook.get("webhook_url"),
                "status_code": None,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "attempted_at": _now_iso(),
            }
        )
        return False


def notify_slack(
    clinic_id: str,
    event: str,
    payload: dict[str, Any],
) -> dict[str, int]:
    """Deliver ``payload`` to every Slack integration for ``clinic_id``.

    Walks :func:`list_integrations`, filters by ``clinic_id`` and
    ``event``, and sequentially POSTs to each subscribed URL.
    Returns a summary dict ``{"delivered": N, "failed": M,
    "subscribers": K}`` so callers can log a single rollup line
    per event.

    Best-effort: never raises. A Slack outage is logged at WARNING
    and surfaced via the ``failed`` counter, but it cannot bubble
    up to break the audit / bulk-accept / bulk-dismiss code paths
    that call this function.

    Sequential (not parallel) by design: v1 has at most a handful
    of registered integrations and parallelising would complicate
    error handling without a measurable latency win. A background
    poller / worker can introduce concurrency later without
    changing this contract.
    """
    subs = [
        h
        for h in list_integrations()
        if (h.get("clinic_id") == clinic_id)
        and (event in (h.get("events") or []))
    ]
    delivered = 0
    failed = 0
    for hook in subs:
        if _deliver_one(hook, event, payload):
            delivered += 1
        else:
            failed += 1
    if subs:
        _log.info(
            "slack dispatch event=%s clinic=%s delivered=%d failed=%d subscribers=%d",
            event,
            clinic_id,
            delivered,
            failed,
            len(subs),
        )
    return {"delivered": delivered, "failed": failed, "subscribers": len(subs)}


__all__ = [
    "EVENT_AUDIT_COMPLETE",
    "EVENT_HIGH_FINDING",
    "list_integrations",
    "notify_slack",
    "register_slack",
]
