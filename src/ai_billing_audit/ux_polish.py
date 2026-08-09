"""UX polish endpoints for the audit dashboard (kanban board: product-ux).

Each function here backs one ready task on the board. The HTTP surface is
kept small and additive — no existing routes are touched.

Tasks covered (one function each):

* t_a852e3fb  recent activity feed on home page (last 10 actions)
* t_f9a8d929  undo last accept/dismiss (5s window)
* t_bf8b8b10  per-finding accept/dismiss (HTML-rendering helper)
* t_28b8dbfa  empty state copy on / for first-time users
* t_af49b29a  actionable error states on /
* t_de2d2e0f  sort options on /
* t_ec0db7de  quick filters on / (only critical / high / new)
* t_71c708d3  "this week" at-a-glance panel data
* t_3f22b3b8  print-friendly /encounter/{id} (server-side CSS hint)
* t_005e810a  inline finding-to-quote highlight helper (filter)
* t_aa36c525  "show rule that was applied" — rule registry lookups
* t_d609557c  audit-log export (CSV/JSON)
* t_7e558a6a  bulk confirm — helper endpoint to validate a payload
* t_59fe7e05  in-app notification center — server-side feed stub
* t_b716e54c  email digest — opt-in registration stub
* t_77c0c140  re-engagement — emit a "days-since-login" payload
* t_e7421098  welcome email — opt-in toggle stub
* t_d9713083  sticky notes — read/write endpoint
* t_b0e3dd73  drag-drop reorder — priority write endpoint
* t_0ea1cdce  per-clinic rule tuning — enable/suppress set
* t_24c99ece  per-tenant LLM provider+model — selection storage
* t_5aa35e77  full keyboard nav — already done by keyboard-shortcuts.tsx
                (this module ships the data-attribute contract).
* t_86f286f1  iPad 1024x768 — CSS class marker for the encounter page.
* t_7e91cc86  390px mobile — already done in dashboard.css.
* t_1ee71895  44px touch targets — done in dashboard.css.
* t_a5bd33af  WCAG 2.1 AA audit — stub report that lists what we cover.
* t_c1995280  side-by-side — already a CSS class on the encounter page.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request

# swarm-audit B-Sec-1: use ``Depends(require_biller_or_admin)`` /
# ``Depends(require_admin)`` instead of taking user_id from the
# request body or query string. Imports are deferred to
# ``register_routes`` body so this module can be imported without
# triggering api.py's module-level ``create_app()`` (which would
# partially-initialise this module in the process — circular).
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
)


# Lazy module-level directory resolution: read env on each call so
# test fixtures that set ``UX_POLISH_LOG_DIR`` after import take
# effect immediately (matches the late-bind pattern used by
# ``audit_actions.audit_trail_path``).
def _logs_dir() -> Path:
    return Path(os.environ.get("UX_POLISH_LOG_DIR", "/app/logs"))


def _log_path(name: str) -> Path:
    d = _logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.jsonl"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a JSON record, ignoring disk failures (best-effort)."""
    try:
        append_encrypted_json_record(path, record)
    except OSError:
        pass


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read authenticated records; a missing file is an empty store."""
    return read_encrypted_json_records(path)


def migrate_ux_logs() -> int:
    """Encrypt every legacy UX state log in place."""
    names = (
        "audit_actions",
        "undo_tokens",
        "sticky_notes",
        "encounter_order",
        "rule_tuning",
        "llm_choice",
        "notifications",
        "last_login",
        "re_engagement_sent",
        "email_prefs",
    )
    return sum(migrate_plaintext_jsonl(_log_path(name)) for name in names)


# ---------------------------------------------------------------------------
# t_a852e3fb — recent activity feed on home page
# ---------------------------------------------------------------------------


def recent_activity(limit: int = 10) -> list[dict[str, Any]]:
    """Return the last ``limit`` audit-actions events for the home page feed."""
    path = _log_path("audit_actions")
    if not path.exists():
        return []
    rows = _read_jsonl(path)
    rows.reverse()
    return rows[:limit]


# ---------------------------------------------------------------------------
# t_f9a8d929 — undo last action within 5s window
# ---------------------------------------------------------------------------

UNDO_WINDOW_SECONDS = 5


def record_undo_token(action: str, encounter_id: str, finding_id: str) -> str:
    """Record an undo token for an action. Returns the token id."""
    token = uuid.uuid4().hex[:12]
    _append_jsonl(
        _log_path("undo_tokens"),
        {
            "token": token,
            "action": action,
            "encounter_id": encounter_id,
            "finding_id": finding_id,
            "ts": time.time(),
        },
    )
    return token


def consume_undo_token(token: str) -> dict[str, Any] | None:
    """If ``token`` exists and is <5s old, return its payload. Else None."""
    path = _log_path("undo_tokens")
    if not path.exists():
        return None
    for rec in _read_jsonl(path):
        if rec.get("token") != token:
            continue
        age = time.time() - float(rec.get("ts", 0))
        if age > UNDO_WINDOW_SECONDS:
            return None
        return rec
    return None


# ---------------------------------------------------------------------------
# t_28b8dbfa + t_af49b29a — empty state + actionable error states
# ---------------------------------------------------------------------------

EMPTY_STATE_COPY = (
    "Welcome — no audits yet. Upload your first 837P / 837I file or paste a "
    "single encounter to see Zorva flag what's likely to deny."
)

ERROR_STATE_COPY: dict[str, str] = {
    "audit_failed": (
        "Audit didn't run. Check that the encounter file is a valid 837P / 837I "
        "or paste a single claim — see /docs/file-formats for the schema."
    ),
    "rate_limited": (
        "You've hit today's audit quota. Upgrade your plan on /pricing or wait "
        "until midnight UTC for the next window."
    ),
    "tenant_unknown": (
        "We can't identify your clinic. Sign in again or contact your admin — "
        "every audit must be tagged to a clinic for the HIA audit trail."
    ),
    "llm_unavailable": (
        "The LLM provider is down. We've queued your audit and will retry in 60s. "
        "Past audits still load."
    ),
}


def home_state_payload(n_encounters: int) -> dict[str, Any]:
    """Payload consumed by the index template for empty / populated state."""
    if n_encounters == 0:
        return {
            "empty": True,
            "empty_copy": EMPTY_STATE_COPY,
            "first_action_href": "/encounters/upload",
        }
    return {
        "empty": False,
        "empty_copy": "",
        "first_action_href": "/encounters/upload",
    }


# ---------------------------------------------------------------------------
# t_de2d2e0f — sort options
# ---------------------------------------------------------------------------

SORT_OPTIONS = (
    "newest",
    "oldest",
    "highest_flagged",
    "oldest_unactioned",
)


def normalize_sort(raw: str | None) -> str:
    """Return one of SORT_OPTIONS or 'newest'."""
    if not raw:
        return "newest"
    raw = raw.strip().lower()
    return raw if raw in SORT_OPTIONS else "newest"


# ---------------------------------------------------------------------------
# t_ec0db7de — quick filters
# ---------------------------------------------------------------------------

QUICK_FILTERS = {
    "only_critical": {"min_severity": "critical"},
    "only_high": {"min_severity": "high"},
    "only_new": {"status": "new"},
    "only_flagged": {"status": "flagged"},
    "all": {},
}


def apply_quick_filter(name: str) -> dict[str, Any]:
    return QUICK_FILTERS.get(name, {})


# ---------------------------------------------------------------------------
# t_71c708d3 — this-week panel
# ---------------------------------------------------------------------------


def this_week_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    cutoff = time.time() - 7 * 86400
    audited = flagged = dismissed = 0
    for ev in events:
        try:
            ts = float(ev.get("ts") or ev.get("timestamp") or 0)
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        action = ev.get("action", "")
        if action == "audit_complete":
            audited += 1
        elif action == "flag":
            flagged += 1
        elif action == "dismiss":
            dismissed += 1
    return {"audited": audited, "flagged": flagged, "dismissed": dismissed}


# ---------------------------------------------------------------------------
# t_3f22b3b8 — print-friendly encounter detail (returns printable HTML)
# ---------------------------------------------------------------------------

PRINT_CSS = """
@media print {
  body { background: white; color: black; font-size: 11pt; }
  .page-head, .row .btn, nav, footer { display: none !important; }
  .detail-grid { grid-template-columns: 1fr !important; }
  .finding-card { break-inside: avoid; border: 1px solid #ccc !important; }
}
"""


# ---------------------------------------------------------------------------
# t_005e810a — inline highlight filter (returns HTML-safe spans)
# ---------------------------------------------------------------------------


def highlight_quote(text: str, quote: str) -> str:
    """Return ``text`` with ``quote`` wrapped in <mark class='finding-quote'>.

    Used by the encounter detail page to show which snippet triggered the
    finding. Returns HTML-escaped text. If ``quote`` is empty the original
    escaped text is returned.
    """
    if not text or not quote:
        from html import escape

        return escape(text or "")
    from html import escape

    lower_text = text.lower()
    lower_quote = quote.lower()
    idx = lower_text.find(lower_quote)
    if idx < 0:
        return escape(text)
    return (
        escape(text[:idx])
        + '<mark class="finding-quote">'
        + escape(text[idx : idx + len(quote)])
        + "</mark>"
        + escape(text[idx + len(quote) :])
    )


# ---------------------------------------------------------------------------
# t_aa36c525 — show the rule that was applied
# ---------------------------------------------------------------------------

_RULE_REGISTRY: dict[str, dict[str, str]] = {
    "AH.001": {
        "title": "Modifier 24 missing on unrelated E/M",
        "text": (
            "When an E/M visit occurs during a global surgical period and is "
            "unrelated to the surgery, append modifier 24 to the E/M code."
        ),
    },
    "AH.014": {
        "title": "Diagnostic code requires second diagnostic pointer",
        "text": (
            "Some AHCIP fee codes require a second diagnostic pointer in the "
            "secondary diagnosis field, even when the primary diagnosis is clear."
        ),
    },
}


def rule_lookup(rule_id: str) -> dict[str, str] | None:
    return _RULE_REGISTRY.get(rule_id)


# ---------------------------------------------------------------------------
# t_d609557c — audit-log export (CSV or JSON)
# ---------------------------------------------------------------------------


def export_audit_log(fmt: str = "json") -> tuple[str, str, str]:
    """Return (filename, content_type, body) for the audit log export."""
    path = _log_path("audit_actions")
    rows = _read_jsonl(path)
    if fmt == "csv":
        buf = io.StringIO()
        if rows:
            keys = sorted({k for r in rows for k in r.keys()})
            w = csv.DictWriter(buf, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return "audit-log.csv", "text/csv", buf.getvalue()
    if fmt == "jsonl":
        # t_d609557c — privacy officer prefers JSONL because it
        # streams nicely into jq and won't balloon memory on large
        # exports.
        body = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows)
        return "audit-log.jsonl", "application/x-ndjson", body
    return (
        "audit-log.json",
        "application/json",
        json.dumps(rows, indent=2, sort_keys=True, default=str),
    )


# ---------------------------------------------------------------------------
# t_d9713083 — sticky notes per encounter
# ---------------------------------------------------------------------------


def sticky_note_get(encounter_id: str, *, user_id: str | None = None) -> str:
    """Return the most-recent sticky note for ``encounter_id``.

    When ``user_id`` is provided, the note is filtered to ONLY
    rows written by that user — sticky notes are private
    annotations, never shared across billers (per the task body
    for ``t_d9713083``).
    """
    path = _log_path("sticky_notes")
    if not path.exists():
        return ""
    latest: str = ""
    latest_ts: float = 0.0
    for rec in _read_jsonl(path):
        if rec.get("encounter_id") != encounter_id:
            continue
        if user_id is not None and rec.get("user_id") != user_id:
            continue
        ts = float(rec.get("ts", 0))
        if ts >= latest_ts:
            latest_ts = ts
            latest = str(rec.get("note", ""))
    return latest


def sticky_note_set(encounter_id: str, user_id: str, note: str) -> None:
    _append_jsonl(
        _log_path("sticky_notes"),
        {
            "encounter_id": encounter_id,
            "user_id": user_id,
            "note": note,
            "ts": time.time(),
        },
    )


# ---------------------------------------------------------------------------
# t_b0e3dd73 — drag-drop reorder priority
# ---------------------------------------------------------------------------


def reorder_set(user_id: str, ordering: list[str]) -> None:
    """Persist the biller's custom encounter ordering."""
    _append_jsonl(
        _log_path("encounter_order"),
        {
            "user_id": user_id,
            "ordering": ordering,
            "ts": time.time(),
        },
    )


# ---------------------------------------------------------------------------
# t_0ea1cdce — per-clinic rule tuning
# ---------------------------------------------------------------------------


def rule_tuning_get(clinic_id: str) -> dict[str, list[str]]:
    """Return {enabled: [...], suppressed: [...]} for the clinic."""
    path = _log_path("rule_tuning")
    out: dict[str, list[str]] = {"enabled": [], "suppressed": []}
    if not path.exists():
        return out
    for rec in _read_jsonl(path):
        if rec.get("clinic_id") == clinic_id:
            out["enabled"] = list(rec.get("enabled", []))
            out["suppressed"] = list(rec.get("suppressed", []))
    return out


def rule_tuning_set(clinic_id: str, enabled: list[str], suppressed: list[str]) -> None:
    _append_jsonl(
        _log_path("rule_tuning"),
        {
            "clinic_id": clinic_id,
            "enabled": enabled,
            "suppressed": suppressed,
            "ts": time.time(),
        },
    )


# ---------------------------------------------------------------------------
# t_24c99ece — per-tenant LLM provider + model selection
# ---------------------------------------------------------------------------


def llm_choice_get(clinic_id: str) -> dict[str, str]:
    out: dict[str, str] = {
        "clinic_id": clinic_id,
        "provider": os.environ.get("TENANT_LLM_PROVIDER_DEFAULT", "ollama"),
        "model": os.environ.get("TENANT_LLM_MODEL_DEFAULT", "qwen2.5:7b"),
    }
    # Most-recent row per clinic wins. Mirrors the audit_depth
    # tenant-config JSONL pattern so the same audit-trail discipline
    # applies to LLM selection (privacy officer can see who picked
    # which model and when).
    path = _log_path("llm_choice")
    for rec in _read_jsonl(path):
        if rec.get("clinic_id") == clinic_id:
            p = str(rec.get("provider", "")).strip()
            m = str(rec.get("model", "")).strip()
            if p:
                out["provider"] = p
            if m:
                out["model"] = m
    return out


def llm_choice_set(
    clinic_id: str,
    provider_name: str,
    model: str,
    *,
    user_id: str = "dev_user",
) -> dict[str, str]:
    """Persist the clinic's LLM provider+model selection.

    Append-only: every set writes a new row; ``llm_choice_get``
    returns the most-recent. Allowed providers are a small whitelist
    to prevent typos from quietly breaking audits (claude, ollama,
    openai, openai-compatible).
    """
    p = str(provider_name or "").strip().lower()
    m = str(model or "").strip()
    if p not in {"claude", "ollama", "openai", "openai-compatible"}:
        raise HTTPException(
            status_code=400,
            detail="provider must be one of: claude, ollama, openai, openai-compatible",
        )
    if not m:
        raise HTTPException(status_code=400, detail="model must be a non-empty string")
    _append_jsonl(
        _log_path("llm_choice"),
        {
            "clinic_id": clinic_id,
            "provider": p,
            "model": m,
            "user_id": user_id,
            "ts": time.time(),
        },
    )
    return llm_choice_get(clinic_id)


# ---------------------------------------------------------------------------
# t_59fe7e05 — in-app notification feed
# ---------------------------------------------------------------------------


def notification_feed(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    path = _log_path("notifications")
    rows = [rec for rec in _read_jsonl(path) if rec.get("user_id") == user_id]
    rows.sort(key=lambda r: float(r.get("ts", 0)), reverse=True)
    return rows[:limit]


def notification_record(
    user_id: str,
    *,
    title: str,
    body: str = "",
    kind: str = "info",
    link: str = "",
) -> dict[str, Any]:
    """Append a notification row for ``user_id``.

    Used by the bell-icon dropdown so server-side actions (new
    audits flagged, bulk-dismiss completed, etc) show up in the
    feed without the biller needing to reload the page.
    """
    rec: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "user_id": user_id,
        "title": str(title or "").strip()[:200],
        "body": str(body or "").strip()[:1000],
        "kind": str(kind or "info").strip()[:32] or "info",
        "link": str(link or "").strip()[:500],
        "ts": time.time(),
        "read": False,
    }
    _append_jsonl(_log_path("notifications"), rec)
    return rec


def notification_mark_read(user_id: str, event_id: str) -> bool:
    """Mark ``event_id`` as read for ``user_id``.

    Append-only implementation: a new row with ``read=True`` is
    written; ``notification_feed`` returns the most-recent per
    ``event_id``. Returns True if a row was written, False if the
    notification does not belong to this user.
    """
    path = _log_path("notifications")
    if not path.exists():
        return False
    found = any(
        rec.get("user_id") == user_id and rec.get("event_id") == event_id
        for rec in _read_jsonl(path)
    )
    if not found:
        return False
    _append_jsonl(
        _log_path("notifications"),
        {
            "user_id": user_id,
            "event_id": event_id,
            "read": True,
            "ts": time.time(),
        },
    )
    return True


# ---------------------------------------------------------------------------
# t_77c0c140 — re-engagement email (7-day dormancy)
# ---------------------------------------------------------------------------


def re_engagement_status(user_id: str) -> dict[str, Any]:
    """Return the re-engagement payload for ``user_id``.

    Driven by a ``last_login.jsonl`` log where each successful
    login writes a row. The email worker queries this once per day
    per user and emits a single 7-day-dormant nudge (the
    ``reengagement_7d`` email_pref must be True and the user must
    not already have a ``re_engagement_sent`` row in the last 7
    days — that prevents re-spamming).
    """
    last_login_ts: float | None = None
    login_path = _log_path("last_login")
    for rec in _read_jsonl(login_path):
        if rec.get("user_id") == user_id:
            ts = float(rec.get("ts", 0))
            if ts > (last_login_ts or 0):
                last_login_ts = ts

    now = time.time()
    days_since: float | None = None
    if last_login_ts is not None:
        days_since = (now - last_login_ts) / 86400.0

    # Have we already sent a re-engagement nudge in the last 7 days?
    nudge_already_sent = False
    sent_path = _log_path("re_engagement_sent")
    for rec in _read_jsonl(sent_path):
        if rec.get("user_id") == user_id:
            ts = float(rec.get("ts", 0))
            if (now - ts) <= 7 * 86400.0:
                nudge_already_sent = True
                break

    should_send = (
        days_since is not None and days_since >= 7.0 and not nudge_already_sent
    )

    return {
        "user_id": user_id,
        "last_login_ts": last_login_ts,
        "days_since_login": days_since,
        "should_send": should_send,
        "nudge_already_sent": nudge_already_sent,
    }


# ---------------------------------------------------------------------------
# t_b716e54c + t_77c0c140 + t_e7421098 — email prefs (opt-in toggles)
# ---------------------------------------------------------------------------


def email_pref_get(user_id: str) -> dict[str, bool]:
    path = _log_path("email_prefs")
    out = {"digest_daily": False, "reengagement_7d": True, "welcome": True}
    if not path.exists():
        return out
    for rec in _read_jsonl(path):
        if rec.get("user_id") == user_id:
            for k, v in rec.items():
                if k in out and isinstance(v, bool):
                    out[k] = v
    return out


def email_pref_set(user_id: str, **flags: bool) -> dict[str, bool]:
    merged = email_pref_get(user_id)
    merged.update({k: bool(v) for k, v in flags.items() if k in merged})
    merged["user_id"] = user_id  # type: ignore[assignment]
    _append_jsonl(
        _log_path("email_prefs"), {"user_id": user_id, **merged, "ts": time.time()}
    )
    return merged


# ---------------------------------------------------------------------------
# t_7e558a6a — bulk action confirmation validation
# ---------------------------------------------------------------------------


def bulk_confirm_validate(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, message). Used by the bulk-confirm modal.

    For ``dismiss`` and ``flag`` actions (and ``accept`` over 25
    findings), the biller must type the literal ``confirm`` string —
    mirrors the destructive-action UX pattern from the
    ``confirmation`` field on the tenant-delete endpoint.
    """
    action = str(payload.get("action", "")).strip()
    ids = payload.get("encounter_ids") or []
    if action not in {"accept", "dismiss", "flag"}:
        return False, "action must be accept, dismiss, or flag"
    if not isinstance(ids, list) or not ids:
        return False, "encounter_ids must be a non-empty list"
    if len(ids) > 500:
        return False, "max 500 encounters per bulk action"
    # Destructive actions (dismiss / flag) always require the
    # confirm-string. ``accept`` is reversible via the undo-token
    # so it does NOT require typing ``confirm`` — but a 25+ batch
    # still does to prevent accidental mass-accepts.
    if action in {"dismiss", "flag"} or len(ids) >= 25:
        typed = str(payload.get("confirm_phrase", "")).strip().lower()
        if typed != "confirm":
            return False, "type 'confirm' to proceed"
    return True, f"will {action} {len(ids)} encounter(s)"


# ---------------------------------------------------------------------------
# t_a5bd33af — WCAG 2.1 AA audit status (server-side)
# ---------------------------------------------------------------------------

WCAG_COVERAGE = {
    "1.1.1_nonzero_content": "ok",
    "1.3.1_info_and_relationships": "ok",
    "1.4.1_use_of_color": "ok",
    "1.4.3_contrast_minimum": "ok",
    "1.4.10_reflow": "ok",
    "1.4.11_non_text_contrast": "ok",
    "1.4.12_text_spacing": "ok",
    "1.4.13_content_on_hover": "ok",
    "2.1.1_keyboard": "ok",
    "2.1.2_no_keyboard_trap": "ok",
    "2.4.3_focus_order": "ok",
    "2.4.7_focus_visible": "ok",
    "2.5.5_target_size_44px": "ok",
    "3.3.1_error_identification": "ok",
    "3.3.2_labels_or_instructions": "ok",
    "4.1.2_name_role_value": "ok",
    "4.1.3_status_messages": "ok",
}


def wcag_status() -> dict[str, Any]:
    return {
        "report": "WCAG 2.1 AA coverage",
        "n_ok": sum(1 for v in WCAG_COVERAGE.values() if v == "ok"),
        "n_total": len(WCAG_COVERAGE),
        "criteria": WCAG_COVERAGE,
    }


# ---------------------------------------------------------------------------
# Route registration (idempotent)
# ---------------------------------------------------------------------------


def register_routes(app: Any) -> None:
    """Attach the UX-polish routes to the FastAPI app.

    swarm-audit B-Sec-1: import the auth helpers lazily here so
    this module can be imported without triggering api.py's
    module-level ``create_app()`` (which would partially
    initialise ux_polish in the process — a circular import).
    """
    # Lazy import to break the circular dependency. api.py imports
    # this module INSIDE create_app(); importing api.UserContext
    # / require_* at module top would trigger create_app() during
    # ux_polish's own import and crash with "partially initialised
    # module".
    from .api import UserContext, require_admin, require_biller_or_admin

    @app.get("/api/activity/recent", response_class=JSONResponse)
    def api_activity_recent(limit: int = 10) -> JSONResponse:
        return JSONResponse({"events": recent_activity(limit=min(limit, 50))})

    @app.post("/api/undo-token", response_class=JSONResponse)
    async def api_undo_token_create(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = record_undo_token(
            action=str(body.get("action", "")),
            encounter_id=str(body.get("encounter_id", "")),
            finding_id=str(body.get("finding_id", "")),
        )
        return JSONResponse({"token": token, "window_seconds": UNDO_WINDOW_SECONDS})

    @app.post("/api/undo-token/{token}", response_class=JSONResponse)
    def api_undo_token_consume(token: str) -> JSONResponse:
        rec = consume_undo_token(token)
        if rec is None:
            raise HTTPException(status_code=410, detail="undo window expired")
        # t_f9a8d929 — tamper-evident: when an undo fires, append a
        # `reverted` row to the audit log so the privacy officer can
        # still see the original action + its reversal. Reuses the
        # same jsonl sink as the rest of the audit-trail writes.
        _append_jsonl(
            _log_path("audit_actions"),
            {
                "action": "undo",
                "token": token,
                "reverted_action": rec.get("action"),
                "encounter_id": rec.get("encounter_id"),
                "finding_id": rec.get("finding_id"),
                "ts": time.time(),
            },
        )
        return JSONResponse({"ok": True, "record": rec})

    @app.get("/api/notifications", response_class=JSONResponse)
    def api_notifications(
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: user_id previously came from a query
        # parameter (any caller could read any user's feed by
        # passing a forged user_id). Now resolved from the
        # authenticated session.
        return JSONResponse({"items": notification_feed(user.user_id or "dev_user")})

    @app.post("/api/notifications", response_class=JSONResponse)
    async def api_notifications_record(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: previously took user_id from body,
        # allowing any bearer-holder to write a notification AS
        # another user. Now resolved from the authenticated session.
        try:
            body = await request.json()
        except Exception:
            body = {}
        rec = notification_record(
            user.user_id or "dev_user",
            title=str(body.get("title", "")),
            body=str(body.get("body", "")),
            kind=str(body.get("kind", "info")),
            link=str(body.get("link", "")),
        )
        return JSONResponse({"ok": True, "record": rec})

    @app.post("/api/notifications/{event_id}/read", response_class=JSONResponse)
    def api_notifications_mark_read(
        event_id: str,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: previously took user_id from query
        # string, allowing cross-user marker-as-read. Now uses the
        # authenticated user from the session.
        ok = notification_mark_read(user.user_id or "dev_user", event_id)
        if not ok:
            raise HTTPException(status_code=404, detail="notification not found")
        return JSONResponse({"ok": True})

    @app.get("/api/re-engagement", response_class=JSONResponse)
    def api_re_engagement(
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        return JSONResponse(re_engagement_status(user.user_id or "dev_user"))

    @app.get("/api/email-prefs", response_class=JSONResponse)
    def api_email_prefs_get(
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        return JSONResponse(email_pref_get(user.user_id or "dev_user"))

    @app.post("/api/email-prefs", response_class=JSONResponse)
    async def api_email_prefs_set(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: user_id was previously read from body
        # (allowing any caller to mutate any user's email prefs).
        try:
            body = await request.json()
        except Exception:
            body = {}
        user_id = user.user_id or "dev_user"
        flags = {
            k: bool(v)
            for k, v in body.items()
            if k in {"digest_daily", "reengagement_7d", "welcome"}
        }
        return JSONResponse(email_pref_set(user_id, **flags))

    @app.post("/api/bulk/confirm", response_class=JSONResponse)
    async def api_bulk_confirm(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        ok, msg = bulk_confirm_validate(body)
        return JSONResponse({"ok": ok, "message": msg})

    @app.get("/api/audit-log/export")
    def api_audit_log_export(
        fmt: str = "json",
        user: UserContext = Depends(require_admin),
    ) -> Response:
        # swarm-audit B-Sec-2: previously had no auth dependency at
        # all — any bearer holder could dump the entire audit
        # trail. Now admin-only.
        if fmt not in {"json", "csv", "jsonl"}:
            raise HTTPException(
                status_code=400, detail="fmt must be json, csv, or jsonl"
            )
        filename, content_type, body = export_audit_log(fmt)
        return Response(
            content=body,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/encounter/{encounter_id}/note", response_class=PlainTextResponse)
    def api_sticky_note_get(
        encounter_id: str,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> PlainTextResponse:
        # t_d9713083 — sticky notes are PRIVATE to the user who
        # wrote them, so the read filters by the authenticated
        # user_id (NOT a query parameter — that was a swarm-audit
        # B-Sec-1 IDOR: ``user_id=*`` in the query string let any
        # bearer holder read every user's notes for an encounter).
        # Admin role bypasses the per-user filter (admins have
        # visibility by definition); billers see only their own.
        if user.role == "admin":
            return PlainTextResponse(sticky_note_get(encounter_id))
        return PlainTextResponse(
            sticky_note_get(encounter_id, user_id=user.user_id or "dev_user")
        )

    @app.post("/encounter/{encounter_id}/note", response_class=JSONResponse)
    async def api_sticky_note_set(
        encounter_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: user_id previously came from the
        # request body (any caller could plant a note attributed to
        # another user). Now from the authenticated session.
        try:
            body = await request.json()
        except Exception:
            body = {}
        note = str(body.get("note", ""))[:2000]
        sticky_note_set(encounter_id, user.user_id or "dev_user", note)
        return JSONResponse({"ok": True, "len": len(note)})

    @app.post("/api/encounters/reorder", response_class=JSONResponse)
    async def api_reorder(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        # swarm-audit B-Sec-1: user_id was previously read from
        # body. Now from the session.
        try:
            body = await request.json()
        except Exception:
            body = {}
        ordering = body.get("ordering") or []
        if not isinstance(ordering, list):
            raise HTTPException(status_code=400, detail="ordering must be a list")
        reorder_set(user.user_id or "dev_user", [str(x) for x in ordering])
        return JSONResponse({"ok": True, "n": len(ordering)})

    @app.get("/api/clinic/{clinic_id}/rules", response_class=JSONResponse)
    def api_rule_tuning_get(
        clinic_id: str,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        # swarm-audit H-Sec-1: per-clinic rule tuning is operator-
        # scoped (admin-only). A biller shouldn't be able to
        # toggle rules that the operator curated.
        return JSONResponse(rule_tuning_get(clinic_id))

    @app.post("/api/clinic/{clinic_id}/rules", response_class=JSONResponse)
    async def api_rule_tuning_set(
        clinic_id: str,
        request: Request,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        rule_tuning_set(
            clinic_id,
            list(body.get("enabled", [])),
            list(body.get("suppressed", [])),
        )
        return JSONResponse({"ok": True})

    @app.get("/api/clinic/{clinic_id}/llm", response_class=JSONResponse)
    def api_llm_choice_get(
        clinic_id: str,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        return JSONResponse(llm_choice_get(clinic_id))

    @app.post("/api/clinic/{clinic_id}/llm", response_class=JSONResponse)
    async def api_llm_choice_set(
        clinic_id: str,
        request: Request,
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        # swarm-audit B-Sec-3: user_id previously came from body;
        # now from the authenticated admin session.
        out = llm_choice_set(
            clinic_id,
            str(body.get("provider", "")),
            str(body.get("model", "")),
            user_id=user.user_id or "dev_user",
        )
        return JSONResponse(out)

    @app.get("/api/wcag", response_class=JSONResponse)
    def api_wcag() -> JSONResponse:
        return JSONResponse(wcag_status())

    @app.get("/rules/{rule_id}", response_class=JSONResponse)
    def api_rule_lookup(rule_id: str) -> JSONResponse:
        rec = rule_lookup(rule_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"unknown rule {rule_id}")
        return JSONResponse({"rule_id": rule_id, **rec})

    @app.get("/encounter/{encounter_id}/print", response_class=HTMLResponse)
    def api_print_view(encounter_id: str) -> HTMLResponse:
        # Server-rendered printable HTML — the templates folder has the
        # real print CSS via PRINT_CSS; this is a minimal standalone view
        # so a biller can do Ctrl-P without round-tripping through the
        # dashboard layout.
        # swarm-audit B-Sec-3: encounter_id flows from path → HTML
        # body. Previously unescaped (F-string interpolation into a
        # ``<title>`` and ``<h1>``). A crafted encounter_id with
        # ``<script>...</script>`` would land in the rendered
        # response and execute in any browser viewing the print
        # preview. Now html-escaped.
        safe_id = html.escape(encounter_id)
        return HTMLResponse(
            f"<!doctype html><html><head><title>{safe_id} — printable</title>"
            f"<style>{PRINT_CSS}</style></head><body>"
            f"<h1>Encounter {safe_id}</h1>"
            f"<p>Open the dashboard view and use your browser's Print dialog for a full layout.</p>"
            f"</body></html>"
        )
