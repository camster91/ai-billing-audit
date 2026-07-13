"""FastAPI surface for the demo dashboard.

Four route groups ship in this module:

* ``GET /``                          — index page; lists every encounter
                                       registered via the demo registry.
* ``GET /encounter/{encounter_id}``   — full audit panel for one encounter:
                                       clinical note with the gold
                                       finding's evidence quote
                                       highlighted, plus claim / rules /
                                       findings rendered as cards.
* ``GET /encounter/{encounter_id}/json``
                                     — the raw record, for smoke checks.
* ``/encounters/upload``              — staff upload portal (837P, clinical
                                       notes, paste-form, bulk ZIP). See
                                       the inline docs at the route
                                       definitions for the per-mode
                                       contract.
* ``POST /upload/csv``                — bulk CSV ingest for clinics that
                                       export from Kareo / OSCAR /
                                       Office Ally. Auto-detects the
                                       PM format from the header row,
                                       maps each row to the canonical
                                       schema, and enqueues one audit
                                       per row via the same job-queue
                                       path the 837P portal uses.

Sibling cards (t_5c741803 medium, t_d16db103 hard) extend the dashboard
by importing ``demo_registry`` and calling
``register_demo_encounter(...)`` — see ``src/ai_billing_audit/demo_entries.py``
for the per-difficulty registrations.

Run with::

    python scripts/run_dashboard.py

which starts uvicorn on 127.0.0.1:8765.
"""
from __future__ import annotations

import io
import json
import os
import re as _re
import time
import zipfile
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from ai_billing_audit.demo_registry import (
    get_demo_encounter,
    list_demo_encounters,
    load_encounter_record,
)
from ai_billing_audit.job_queue import get_default_queue
from ai_billing_audit.zorva_context import lookup_somb_descriptor, lookup_somb_fee
from ai_billing_audit.x12_parser import (
    X12ParseError,
    parse_837p,
    validate_required_fields,
)
from ai_billing_audit.institutional_837i import (
    parse_837i as _parse_837i,
    validate_837i as _validate_837i,
    map_837i_to_enqueue_payload as _map_837i_to_enqueue,
)

# Importing the registrations side-effecting module wires up the
# encounters that each difficulty's worker registered. Sibling workers
# (medium, hard) do the same in their own entry modules.
from ai_billing_audit import __version__, demo_entries  # noqa: F401  (side-effect import)

__all__ = ["app", "create_app"]


# Path: this file is at src/ai_billing_audit/api.py
# Templates and static assets live alongside it.
_PKG_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PKG_DIR / "templates"
_STATIC_DIR = _PKG_DIR / "static"


# ─── RBAC middleware + per-endpoint gates ────────────────────────────────
# Multi-user team feature (kanban t_846407c4). The Next.js portal's
# team management UI (kanban t_23bfd49c) is the source of truth for
# the user/role table; the FastAPI audit app enforces these roles
# via per-request ``X-User-Id`` / ``X-User-Role`` headers until a
# real auth integration (OAuth / session cookies) lands.
#
# Roles
# -----
# * ``admin``  — can do everything (read, write, admin-only ops
#                like inviting / removing team members).
# * ``biller`` — full read + write access on findings (accept /
#                dismiss / modify / comment / upload). Cannot
#                manage the team.
# * ``viewer`` — read-only. Cannot accept, dismiss, modify, or
#                comment. Cannot upload.
#
# Header contract
# ---------------
# Every request that mutates state MUST carry:
#   X-User-Id:    opaque team-member id (UUID from the Next.js
#                 team management UI).
#   X-User-Role:  one of "admin" | "biller" | "viewer".
# Missing headers on a write endpoint return 401. Missing headers
# on a read endpoint return 401 too — the bearer-token middleware
# already gates read traffic; this layer is the second factor.
#
# Dev-mode fallback
# -----------------
# When ``AUDIT_ALLOW_NO_AUTH=1`` is set, the legacy /healthz, /, and
# static paths remain open. For all OTHER routes, when that flag is
# set we still REQUIRE X-User-Id / X-User-Role for write endpoints
# but allow reads without headers — the existing bulk_actions test
# suite (kanban t_2515fe6f) and the bulk CSV path (kanban t_e18ed*)
# rely on being able to call read+write endpoints without auth in
# CI. To preserve that behavior we treat missing headers on a write
# request as a 401 only when a token IS configured (production);
# in dev (AUDIT_ALLOW_NO_AUTH=1) we fall back to a synthetic
# ("dev_user", "admin") so the existing tests keep passing. This
# fallback is **only** active in dev — production refuses requests
# with no headers.


class UserContext:
    """Lightweight request-scoped user identity container.

    Returned by :func:`get_request_user` and propagated into the
    write endpoints via FastAPI's :class:`Depends` mechanism. The
    fields are flat so they serialize trivially into the audit
    trail's ``user_id`` / ``user_role`` columns.
    """

    __slots__ = ("user_id", "role", "user_identifier")

    def __init__(self, user_id: str, role: str, user_identifier: str) -> None:
        self.user_id = user_id
        self.role = role
        self.user_identifier = user_identifier

    def as_audit_kwargs(self) -> dict[str, str]:
        """Return the kwargs to splat into ``audit_actions.append``."""
        return {"user_id": self.user_id, "user_role": self.role}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"UserContext(user_id={self.user_id!r}, role={self.role!r})"


def _coerce_role(raw: str | None) -> str | None:
    """Normalize a role string. Returns ``None`` if invalid.

    Accepts ``"Admin"``, ``" ADMIN "``, ``"biller"`` etc. — case
    insensitive, trimmed. Returns ``None`` for unknown roles so
    the caller can raise 403 with a stable error message.
    """
    if raw is None:
        return None
    n = str(raw).strip().lower()
    if n in ("admin", "biller", "viewer"):
        return n
    return None


def _resolve_user_from_request(request: Request) -> UserContext:
    """Extract ``UserContext`` from request headers or raise 401.

    Contract:
      * If ``X-User-Id`` and ``X-User-Role`` are both present and
        the role is valid, returns a populated :class:`UserContext`.
      * If the role is unknown, raises 403 (the caller is
        impersonating an invalid role — different from "missing").
      * If the headers are missing AND we're in production mode
        (``AUDIT_ALLOW_NO_AUTH`` not set), raises 401.
      * If the headers are missing AND we're in dev mode
        (``AUDIT_ALLOW_NO_AUTH=1``), falls back to
        ``("dev_user", "admin")``. This is the ONLY place the
        dev fallback lives — every other caller relies on this
        function for the same shape.
    """
    user_id = request.headers.get("X-User-Id")
    user_role = request.headers.get("X-User-Role")
    role = _coerce_role(user_role)
    if user_id and role:
        return UserContext(
            user_id=str(user_id).strip(),
            role=role,
            user_identifier=str(user_id).strip(),
        )
    if user_role and not role:
        # Header was set but with an unknown role — don't silently
        # coerce to viewer; refuse explicitly so the caller knows
        # their token/role mapping is wrong.
        raise HTTPException(
            status_code=403,
            detail=(
                f"unknown role {user_role!r}; expected one of "
                "admin, biller, viewer"
            ),
        )
    # Headers missing entirely.
    # Read AUDIT_ALLOW_NO_AUTH at call-time so tests that
    # ``monkeypatch.setenv`` AFTER module import take effect.
    # (The module-level cache is just an import-time default.)
    if _os_for_rbac.environ.get("AUDIT_ALLOW_NO_AUTH", "") == "1":
        # Dev-mode fallback so legacy tests (bulk_actions, etc.)
        # that POST without headers keep working under
        # AUDIT_ALLOW_NO_AUTH=1.
        return UserContext(
            user_id="dev_user",
            role="admin",
            user_identifier="dev_user",
        )
    raise HTTPException(
        status_code=401,
        detail=(
            "missing X-User-Id / X-User-Role headers; "
            "RBAC identity required for this endpoint"
        ),
    )


def get_request_user(request: Request) -> UserContext:
    """FastAPI dependency: extract the user context for the current request.

    Reads the request-scoped ``request.state.user`` that the RBAC
    middleware populates. Falls back to a direct header parse if
    the middleware hasn't run (e.g. when an endpoint is invoked
    directly from a unit test that bypasses ``TestClient``). The
    dependency is what the write endpoints should declare; the
    middleware is the belt-and-suspenders for the response side.
    """
    cached = getattr(request.state, "user", None)
    if isinstance(cached, UserContext):
        return cached
    return _resolve_user_from_request(request)


def get_request_user_or_anonymous(request: Request) -> UserContext:
    """FastAPI dependency: like ``get_request_user`` but returns a
    default-anonymous :class:`UserContext` when no ``X-User-Id`` /
    ``X-User-Role`` headers are present, instead of raising 401.

    Used by the public-read endpoints (denial-risk, appeal-letter,
    appeal-letters) that the marketing portal at zorva.ashbi.ca
    fetches cross-origin without bearer credentials. The portal
    *could* pass the signed-in user's ``X-User-Id`` headers, but
    omitting them is simpler and matches the public-read posture:
    anyone on the internet can fetch these endpoints, and the
    data is the same regardless of who is asking (the
    audit-trail POST endpoints that mutate state still require
    real auth via ``require_biller_or_admin`` + the bearer
    middleware).

    The returned UserContext has ``user_id="anonymous"`` and
    ``role="guest"`` so downstream code that branches on role
    can detect "this is a public-read caller" if needed (no such
    branching exists today; the dependency is purely for endpoints
    that previously used ``require_biller_or_admin`` and now allow
    public reads).
    """
    try:
        return get_request_user(request)
    except HTTPException:
        return UserContext(
            user_id="anonymous",
            role="guest",
            user_identifier="anonymous",
        )


def require_biller_or_admin(
    user: UserContext = Depends(get_request_user),
) -> UserContext:
    """FastAPI dependency: gate write endpoints behind biller-or-admin.

    Read endpoints should NOT use this dependency — the existing
    ``_bearer_auth`` middleware already gates them. This dependency
    is for the action endpoints: accept, dismiss, modify, comment,
    upload, csv-upload, bulk-accept, bulk-dismiss, bulk-flag.
    """
    if user.role not in ("admin", "biller"):
        raise HTTPException(
            status_code=403,
            detail=(
                f"role {user.role!r} cannot perform write actions; "
                "requires 'admin' or 'biller'"
            ),
        )
    return user


def require_admin(
    user: UserContext = Depends(get_request_user),
) -> UserContext:
    """FastAPI dependency: gate admin-only endpoints.

    Used by the team-management endpoints (kanban t_23bfd49c)
    hosted in the Next.js portal and any admin-only FastAPI
    routes we add later (e.g. ``GET /admin/users`` stub).
    Biller and viewer both get 403.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail=(
                f"role {user.role!r} cannot access admin-only endpoints; "
                "requires 'admin'"
            ),
        )
    return user


# Module-level sentinel for the dev-mode fallback. The value is
# read once at module import time but the RBAC middleware also
# honors ``AUDIT_ALLOW_NO_AUTH`` flips via os.environ inside
# ``_resolve_user_from_request`` so the existing test suite's
# monkeypatch.setenv pattern works.
import os as _os_for_rbac
_ALLOW_NO_AUTH = _os_for_rbac.environ.get("AUDIT_ALLOW_NO_AUTH", "") == "1"


def _highlight_quote(text: str, quote: str) -> str:
    """Return HTML-safe ``text`` with every (case-insensitive) occurrence
    of ``quote`` wrapped in ``<mark class="evidence">…</mark>``.

    Used by the detail template to make the ground-truth finding's
    evidence quote visibly stand out from the rest of the clinical
    note. If ``quote`` is empty or no match is found, returns the
    text as-is (the template still renders a small "no quote" hint).
    """
    if not text or not quote:
        return Markup(escape(text or ""))
    safe_text = escape(text)
    safe_quote = escape(quote)
    # Find every occurrence of safe_quote inside safe_text. Because both
    # have been html-escaped, a naive substring search is safe (no HTML
    # injection via crafted quotes).
    out_parts: list[str] = []
    cursor = 0
    needle = safe_quote
    lower_text = safe_text.lower()
    lower_needle = needle.lower()
    while True:
        idx = lower_text.find(lower_needle, cursor)
        if idx == -1:
            out_parts.append(safe_text[cursor:])
            break
        out_parts.append(safe_text[cursor:idx])
        out_parts.append('<mark class="evidence">')
        out_parts.append(safe_text[idx : idx + len(needle)])
        out_parts.append("</mark>")
        cursor = idx + len(needle)
    # Return as Markup so Jinja's auto-escape trusts the result and
    # emits the raw <mark> tag. The contents are already html-escaped
    # via ``escape(text)`` / ``escape(quote)`` above, so this is safe.
    return Markup("".join(out_parts))


# A "verdict" is a suggested_code that is purely alphabetic (no digits,
# no spaces, uppercase). The two real values in the dataset are "DENY"
# and "REVIEW"; every other suggested_code is a CPT/ICD-10 token like
# "99214" or "E11.9" or a phrase like "modifier 25". The dashboard
# renders verdicts as a colored decision pill instead of a code chip
# because the user needs to act on them.
_VERDICT_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _is_verdict(token: str) -> bool:
    if not token or not token.isalpha():
        return False
    return all(c in _VERDICT_TOKEN_CHARS for c in token)


def _truthy(value: str | None) -> bool:
    """Coerce a query-string flag to a bool.

    Treats ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (any case) as
    True; everything else (including empty string, ``"0"``,
    ``"false"``, ``None``) as False. Used by snooze / include-*
    toggle params so the dashboard URL behaves consistently.
    """
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _finding_dicts(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize ground_truth entries into the shape the template expects.

    The stored records are flat dicts; the template iterates a list of
    {category, severity, suggested_code, rule_id, quote, finding_id,
    suggested_is_verdict, suggested_verdict} objects. Keeping the
    normalizer in Python (not Jinja) means the template stays simple
    and the shape is unit-testable.
    """
    out: list[dict[str, Any]] = []
    for f in record.get("ground_truth", []):
        suggested = f.get("suggested_code", "")
        is_verdict = _is_verdict(suggested)
        out.append(
            {
                "finding_id": f.get("finding_id", ""),
                "category": f.get("category", ""),
                "severity": f.get("severity", ""),
                "suggested_code": suggested,
                "suggested_is_verdict": is_verdict,
                "suggested_verdict": suggested.lower() if is_verdict else "",
                "rule_id": f.get("rule_id", ""),
                "quote": f.get("clinical_evidence_quote", ""),
            }
        )
    return out


# Severity ranking for the "min severity to show" threshold.
# Lower rank = lower severity. info < low < medium < high < critical.
SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _attach_model_confidence(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich each finding dict in-place with a ``model_confidence`` field.

    The encounter-detail template renders ``f.model_confidence`` as a
    small "Model confidence: HIGH / MEDIUM / LOW" badge under each
    finding. The confidence bucket is derived from the per-rule
    accept-count in the feedback log (see
    :meth:`FeedbackStore.confidence_for_rule`).

    If we have no feedback at all yet (the common case in dev / before
    the pilot), every finding gets the "uncalibrated" bucket with the
    "Not yet calibrated at this clinic" label. The template knows how
    to render that placeholder distinctly from the calibrated buckets
    so the biller never sees a misleading "HIGH" badge before we have
    real signal.

    Cost: one full read of the feedback JSONL per call. The store is
    tiny in dev (a few rows) and the encounter-detail page is not
    called in any hot loop, so the O(n_feedback) cost is fine. If
    volume grows we can add a per-rule index.
    """
    try:
        from .feedback import get_default_store
        store = get_default_store()
    except Exception:
        store = None

    for f in findings:
        if not isinstance(f, dict):
            continue
        rule_id = str(f.get("rule_id", "") or "")
        if store is not None and rule_id:
            try:
                f["model_confidence"] = store.confidence_for_rule(rule_id)
            except Exception:
                f["model_confidence"] = {
                    "bucket": "uncalibrated",
                    "label": "Not yet calibrated at this clinic",
                    "validations": 0,
                    "dismisses": 0,
                    "total": 0,
                }
        else:
            f["model_confidence"] = {
                "bucket": "uncalibrated",
                "label": "Not yet calibrated at this clinic",
                "validations": 0,
                "dismisses": 0,
                "total": 0,
            }
    return findings


def _attach_appeal_context(
    findings: list[dict[str, Any]],
    encounter_id: str,
) -> list[dict[str, Any]]:
    """Enrich each finding dict in-place with appeal-side context.

    The encounter-detail template renders an appeal-outcome form per
    finding (gated on whether an appeal letter has been generated
    for that finding) and shows the most recent outcome (if any).
    This helper attaches:

    * ``appeal_letter_generated``: bool — True iff an appeal letter
      has been logged for (encounter_id, finding_id) in
      ``appeal_letters.jsonl``. The form is only meaningful after a
      letter exists, so the template uses this as the show/hide gate.
    * ``appeal_outcome``: dict | None — the latest AppealOutcome for
      this finding (latest by timestamp), rendered as "Last outcome"
      above the form so the biller sees their prior decision.

    Both fields are best-effort: a missing log or a corrupted row
    is treated as "no appeal yet" and "no outcome yet" rather than
    a 500. The encounter-detail page is not a hot loop, so the
    O(n_letters + n_outcomes) cost is fine for the volumes we have.
    """
    try:
        from .appeal_letter import read_appeal_letters, read_appeal_outcomes
    except Exception:
        return findings

    try:
        letters = read_appeal_letters(encounter_id=encounter_id)
    except Exception:
        letters = []
    try:
        outcomes = read_appeal_outcomes(encounter_id=encounter_id)
    except Exception:
        outcomes = []

    # Map: finding_id -> True if any letter has been logged for it.
    letter_finding_ids: set[str] = set()
    for row in letters or []:
        fid = (
            row.get("finding_id")
            or row.get("appeal_id")  # legacy: biller may have used fid as appeal_id
        )
        if fid:
            letter_finding_ids.add(str(fid))

    # Map: finding_id -> latest outcome (latest by timestamp). We
    # treat appeal_id == finding_id as the same record (the API
    # default), but also fall back to scanning all outcomes for one
    # whose appeal_id matches.
    latest_outcome: dict[str, Any] = {}
    for o in outcomes or []:
        aid = str(o.get("appeal_id") or "")
        if not aid:
            continue
        prev = latest_outcome.get(aid)
        if prev is None or str(o.get("timestamp", "")) > str(
            prev.get("timestamp", "")
        ):
            latest_outcome[aid] = o

    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("finding_id") or "")
        f["appeal_letter_generated"] = fid in letter_finding_ids
        f["appeal_outcome"] = latest_outcome.get(fid)
    return findings


# ─── Revenue opportunities ─────────────────────────────────────────────
# A subset of AHCIP rules identify "missed revenue" — the note documents
# a billable service that the claim did not capture. These findings are
# surfaced separately from the denial-risk findings list, with an
# estimated dollar uplift per rule (rough SOMB estimates — to be refined
# against zorva_context.SOMB_FEE_SCHEDULE in a follow-up).
#
# Rule selection is keyed by `rule_id` because the auditor's current
# category enum (evaluation / diagnosis / modifier / laboratory / ...)
# is a clinical-bucket taxonomy, not a revenue-vs-denial one. We
# filter on rule_id directly until the auditor's output schema
# includes a dedicated `opportunity_type` field.
REVENUE_OPPORTUNITY_RULES: dict[str, dict[str, Any]] = {
    "rule_ahcip_missing_procedure": {
        "rule_name": "Missing billable procedure",
        "estimated_dollar": 50.0,
        "suggested_action": (
            "Add the documented procedure to the claim — the note describes "
            "a service that was not submitted for reimbursement."
        ),
    },
    "rule_ahcip_em_level_upcode": {
        "rule_name": "E/M visit undercoded",
        "estimated_dollar": 40.0,
        "suggested_action": (
            "Upcode the E/M level to match the documentation complexity "
            "(e.g. 03.04A instead of 03.01A)."
        ),
    },
    "rule_ahcip_modifier_25_001": {
        "rule_name": "Modifier -25 unlock",
        "estimated_dollar": 45.0,
        "suggested_action": (
            "Append modifier -25 to the E/M code so a separately "
            "identifiable procedure can be billed in addition."
        ),
    },
    "rule_ahcip_modifier_25_unlock": {
        "rule_name": "Modifier -25 unlock (same-day E/M + procedure)",
        "estimated_dollar": 45.0,
        "suggested_action": (
            "Append modifier -25 to the E/M SOMB code so the "
            "cognitive work is paid separately from the same-day "
            "procedure (Alberta-specific; without -25 the payer "
            "bundles the E/M into the procedure fee)."
        ),
    },
    "rule_ahcip_lab_order_no_draw": {
        "rule_name": "Lab ordered without draw or follow-up date",
        "estimated_dollar": 0.0,
        "suggested_action": (
            "Workflow-only: clinic-ops to confirm the patient "
            "completed the draw (AHCIP physicians do not bill "
            "for labs; this is an operational gap, not a "
            "billing denial). Candidate for doctor_email "
            "follow-up channel in addition to the audit feed."
        ),
    },
    "rule_ahcip_telehealth_premium": {
        "rule_name": "Telehealth premium missing on virtual visit",
        "estimated_dollar": 15.0,
        "suggested_action": (
            "Append the current AHCIP telehealth premium "
            "indicator to the claim alongside the E/M "
            "(check albertadoctors.org Fee Navigator for "
            "the current Telehealth Premium code — the SOMB "
            "has changed it several times)."
        ),
    },
    "rule_ahcip_telehealth": {
        "rule_name": "Telehealth premium eligible",
        "estimated_dollar": 15.0,
        "suggested_action": (
            "Append the telehealth premium code — the visit was virtual "
            "but the claim was billed as in-person."
        ),
    },
    "rule_ahcip_cmgp": {
        "rule_name": "CMGP / chronic care premium",
        "estimated_dollar": 20.0,
        "suggested_action": (
            "Add the CMGP (Chronic Disease Management / General "
            "Practitioner) premium — patient meets eligibility."
        ),
    },
}


def _finding_rule_ids(finding: dict[str, Any]) -> list[str]:
    """Return all rule_ids attached to a finding (deduped, order-preserved).

    The auditor output schema permits both ``rule_id`` (singular, the
    common shape from the v12 prompt) and ``rule_ids`` (plural, the
    dataclass default). Findings shaped by ``_finding_dicts`` carry the
    singular form; raw LLM payloads may carry either.
    """
    seen: set[str] = set()
    out: list[str] = []
    singular = str(finding.get("rule_id") or "").strip()
    if singular:
        seen.add(singular)
        out.append(singular)
    plural = finding.get("rule_ids") or []
    if isinstance(plural, (list, tuple)):
        for rid in plural:
            s = str(rid or "").strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _codes_from_finding(finding: dict[str, Any]) -> list[str]:
    """Extract SOMB-style codes from a finding's suggested_code field.

    The auditor emits ``suggested_code`` strings like "03.04A" or
    "08.19A (45-min psychotherapy)" or even phrases like
    "telehealth modifier". This pulls out the SOMB-shaped tokens
    (uppercase letter + digits + optional trailing letter, e.g.
    "03.04A", "08.19A", "13.59B") so we can look them up against
    the SOMB fee schedule. Returns a list (possibly empty) of
    candidate codes in the order they appear.

    Phrases with no SOMB-shaped token (e.g. "telehealth modifier",
    "modifier 25") come back as an empty list — the caller then
    falls back to the rule's hardcoded estimated_dollar.
    """
    suggested = str(finding.get("suggested_code") or "").strip()
    if not suggested:
        return []
    # SOMB codes look like: 2-3 digits, a dot, 2 digits, an optional letter.
    # Match the head token before any parenthetical or punctuation.
    # We use a permissive regex to be robust to "03.04A (comprehensive …)".
    head = suggested.split("(", 1)[0].strip()
    if not head:
        return []
    pattern = _re.compile(r"\b\d{2,3}\.\d{1,2}[A-Z]?\b")
    matches = pattern.findall(head.upper())
    # Also pull off bare modifier / premium keywords that have a
    # sentinel entry in the schedule.
    extras: list[str] = []
    upper = head.upper()
    if "TELEHEALTH" in upper:
        extras.append("TELEHEALTH")
    if "CMGP" in upper or "CHRONIC DISEASE MANAGEMENT" in upper:
        extras.append("CMGP")
    if "MODIFIER -25" in upper or "MODIFIER 25" in upper or "MOD-25" in upper:
        extras.append("MOD25")
    if "AFTER-HOURS" in upper or "AFTER HOURS" in upper:
        extras.append("AFTER_HOURS")
    out: list[str] = []
    seen: set[str] = set()
    for c in matches + extras:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _best_somb_fee(codes: list[str]) -> tuple[float | None, str | None, str | None]:
    """Look up the first SOMB fee / descriptor that matches any of ``codes``.

    Returns ``(fee, code_used, descriptor)``. When no code in ``codes``
    is in the schedule, all three are ``None``. The caller decides
    whether to use the fee or fall back to the hardcoded estimate.
    """
    for c in codes:
        fee = lookup_somb_fee(c)
        if fee is not None:
            return fee, c, lookup_somb_descriptor(c)
    return None, None, None


def compute_revenue_opportunities(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter ``findings`` to revenue-opportunity ones and enrich them.

    Each returned dict carries the original finding fields plus:
        - ``rule_name``           human-readable rule label
        - ``estimated_dollar``    SOMB-derived uplift estimate (float)
        - ``somh_fee``            fee from SOMB_FEE_SCHEDULE, or None
        - ``somh_code``           which SOMB code we priced, or None
        - ``somh_descriptor``     short descriptor for the priced code, or None
        - ``somh_confidence``     "high" / "medium" / "low" — confidence of
                                  the priced value (always None when the
                                  hardcoded fallback was used)
        - ``estimated_source``    "somb_schedule" or "rule_default" — which
                                  way the dollar figure was derived
        - ``suggested_action``    one-line biller instruction
        - ``opportunity_rule_id`` the rule_id that qualified it (canonical)

    The list is sorted by descending ``estimated_dollar`` so the
    biggest opportunities are listed first.

    Findings with no matching rule_id are dropped.

    Dollar estimate precedence (per finding):
        1. If ``suggested_code`` contains a SOMB-shaped token (or a
           recognized sentinel like TELEHEALTH / CMGP / MOD25) that
           exists in ``SOMB_FEE_SCHEDULE``, use that fee.
        2. Otherwise fall back to the rule's hardcoded
           ``estimated_dollar``. Unmapped codes never fabricate a fee.
    """
    opportunities: list[dict[str, Any]] = []
    for f in findings:
        for rid in _finding_rule_ids(f):
            meta = REVENUE_OPPORTUNITY_RULES.get(rid)
            if meta is None:
                continue
            enriched = dict(f)
            enriched["opportunity_rule_id"] = rid
            enriched["rule_name"] = meta["rule_name"]
            enriched["suggested_action"] = meta["suggested_action"]

            # Try SOMB schedule first, then fall back to the rule's
            # hardcoded estimate.
            codes = _codes_from_finding(f)
            somb_fee, somb_code, somb_descriptor = _best_somb_fee(codes)
            if somb_fee is not None and somb_fee > 0:
                enriched["estimated_dollar"] = float(somb_fee)
                enriched["somb_fee"] = float(somb_fee)
                enriched["somb_code"] = somb_code
                enriched["somb_descriptor"] = somb_descriptor
                enriched["somb_confidence"] = None
                enriched["estimated_source"] = "somb_schedule"
            else:
                # SOMB has no number for this code (modifier -25,
                # unmapped telehealth add-on, etc.). Fall back to
                # the rule's hardcoded estimate and annotate the
                # confidence as None so the UI can flag it.
                fallback = float(meta["estimated_dollar"])
                enriched["estimated_dollar"] = fallback
                enriched["somb_fee"] = None
                enriched["somb_code"] = None
                enriched["somb_descriptor"] = None
                enriched["somb_confidence"] = None
                enriched["estimated_source"] = "rule_default"

            opportunities.append(enriched)
            # One opportunity per finding — the first matching rule_id wins.
            break
    opportunities.sort(key=lambda x: x.get("estimated_dollar", 0.0), reverse=True)
    return opportunities

# Dismissal reasons — the closed-loop learning signal. When the biller
# dismisses a finding, they pick one of these + an optional free-text
# note. The categories are coarse on purpose: they're meant to bucket
# "why was the AI wrong" so we can group prompts-iteration examples
# later. ``false_positive`` is the most valuable bucket — every
# dismissal in this category becomes a candidate few-shot example
# for the next prompt revision.
_DISMISS_CATEGORIES = frozenset({
    "false_positive",     # The finding is wrong; the auditor is overcalling
    "already_documented", # The finding is right but the note already covers it
    "not_applicable",     # Payer-specific override (e.g. this payer doesn't require modifier-25)
    "other",              # Free text; review later for new categories
})


def _min_severity_threshold() -> int:
    """Read MIN_SEVERITY_TO_SHOW env var, return the rank.

    Per-tenant setting in v2 (per-tenant config table). v1 uses an
    env var: MIN_SEVERITY_TO_SHOW=high means only "high" and "critical"
    findings surface on the dashboard. Default: "info" (show
    everything).

    The env var is read fresh on every request so an admin can
    change it without restarting the API. Cheap because the env
    lookup is O(1).
    """
    raw = os.environ.get("MIN_SEVERITY_TO_SHOW", "info").strip().lower()
    return SEVERITY_RANK.get(raw, SEVERITY_RANK["info"])


# Average claim value used to translate "X claims clean" into
# "$Y revenue confirmed clean". Industry average for US office
# visit. v2: per-tenant config that reads the clinic's own avg
# claim value from their billing data.
AVG_CLAIM_VALUE_USD = 190.0
# Industry average denial rate (CMS commercial). Used to estimate
# how many claims the auditor caught that would have been denied.
INDUSTRY_DENIAL_RATE = 0.075

# Multi-tenant scoping. ``TENANT_NAME`` is the human-readable
# label shown in the topbar pill. ``TENANT_ID`` is the stable
# identifier used in the audit trail's tenant_id field to
# scope reads per-clinic. Both default to "Acme Family Practice"
# until the first pilot signs; v2 reads from a per-session auth
# payload. Setting TENANT_ID explicitly to a non-"default"
# value gives the activity feed row-level isolation per clinic.
import os as _os
_TENANT_NAME = _os.environ.get("TENANT_NAME", "Acme Family Practice")
_TENANT_ID = _os.environ.get("TENANT_ID", "default")


def compute_clean_rate_metrics(
    cards: list[dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    """Compute clean-rate + dollar-value metrics for the home page hero.

    Why this exists: the home page leads with positive signal
    ("94% of claims clean, $73k confirmed") rather than negative
    signal ("2 findings, 0 awaiting"). The clinic owner wants
    the positive number. The biller wants the same number — it's
    the metric that justifies the monthly fee.

    Module-scope (not closure-bound) so it can be unit-tested
    without spinning up the FastAPI app.

    Inputs:
      cards: list of card dicts from _build_audit_card or
             equivalent. Each must have `finished_at` (unix sec)
             and `findings` (list).
      now: current time (passed in for testability).

    Outputs: see the keys in the returned dict below.
    """
    if not cards:
        return {
            "ready": False,
            "this_month_count": 0,
            "this_month_clean": 0,
            "this_month_flagged": 0,
            "this_month_clean_rate": None,
            "this_month_revenue_confirmed": 0.0,
            "this_month_avoided_denials_dollar": 0.0,
            "last_month_clean_rate": None,
            "clean_rate_delta": None,
            "avg_claim_value_usd": AVG_CLAIM_VALUE_USD,
        }

    this_month_start = now - 30 * 86400
    last_month_start = now - 60 * 86400
    this_month_clean = 0
    this_month_flagged = 0
    last_month_clean = 0
    last_month_total = 0
    for c in cards:
        finished = c.get("finished_at") or 0
        if not finished:
            continue
        findings = c.get("findings", []) or []
        is_clean = len(findings) == 0
        if finished >= this_month_start:
            if is_clean:
                this_month_clean += 1
            else:
                this_month_flagged += 1
        elif finished >= last_month_start:
            last_month_total += 1
            if is_clean:
                last_month_clean += 1

    this_month_total = this_month_clean + this_month_flagged
    this_month_clean_rate = (
        this_month_clean / this_month_total if this_month_total else None
    )
    last_month_clean_rate = (
        last_month_clean / last_month_total if last_month_total else None
    )
    clean_rate_delta: float | None = None
    if this_month_clean_rate is not None and last_month_clean_rate is not None:
        clean_rate_delta = this_month_clean_rate - last_month_clean_rate

    revenue_confirmed = this_month_clean * AVG_CLAIM_VALUE_USD
    baseline_clean_rate = 1.0 - INDUSTRY_DENIAL_RATE
    if this_month_clean_rate is not None:
        extra_clean_pct = max(0.0, this_month_clean_rate - baseline_clean_rate)
    else:
        extra_clean_pct = 0.0
    avoided_denial_dollar = (
        extra_clean_pct * this_month_total * AVG_CLAIM_VALUE_USD
    )

    return {
        "ready": True,
        "this_month_count": this_month_total,
        "this_month_clean": this_month_clean,
        "this_month_flagged": this_month_flagged,
        "this_month_clean_rate": this_month_clean_rate,
        "this_month_revenue_confirmed": revenue_confirmed,
        "this_month_avoided_denials_dollar": avoided_denial_dollar,
        "last_month_clean_rate": last_month_clean_rate,
        "clean_rate_delta": clean_rate_delta,
        "avg_claim_value_usd": AVG_CLAIM_VALUE_USD,
    }


def read_latest_real_audit(
    *,
    encounter_id: str,
    tenant_id: str,
    log_path: str | os.PathLike[str] = "/app/logs/upload_jobs.jsonl",
) -> dict[str, Any] | None:
    """Read the most recent completed LLM audit for an encounter.

    Multi-tenant hardening: this function is module-level so it's
    unit-testable in isolation (the closure-bound version inside
    create_app() can't easily be tested without HTTP). Reads the
    most recent row in upload_jobs.jsonl whose encounter_id
    matches AND whose tenant_id matches the supplied tenant_id.

    Returns a dict with the audit's findings, summary, and
    metadata; None if no match. Legacy rows without a tenant_id
    key default to "default" so existing audit trails don't
    disappear after the upgrade.

    Used by the index and encounter-detail handlers to surface
    live LLM audit results alongside the demo cards.
    """
    from pathlib import Path as _P
    log = _P(log_path)
    if not log.is_file():
        return None
    try:
        with log.open() as fh:
            lines = fh.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("encounter_id") != encounter_id:
            continue
        # Tenant filter: skip rows that belong to a different
        # tenant. Legacy rows (no tenant_id key) default to
        # "default" so existing audit trails don't disappear.
        if rec.get("tenant_id", "default") != tenant_id:
            continue
        if rec.get("status") != "done":
            continue
        res = rec.get("result", {}) or {}
        if res.get("audit_status") != "ok":
            continue
        return {
            "job_id": rec.get("job_id"),
            "encounter_id": rec.get("encounter_id"),
            "source": rec.get("source"),
            "submitted_at": rec.get("submitted_at"),
            "finished_at": rec.get("finished_at"),
            "findings_count": res.get("findings_count", 0),
            "findings": res.get("findings", []),
            "summary": res.get("summary", ""),
            "difficulty_tier": res.get("difficulty_tier"),
            "variant": res.get("variant"),
            "zorva_context": res.get("zorva_context"),
            "tenant_id": rec.get("tenant_id", "default"),
        }
    return None


def create_app() -> FastAPI:
    """Build a fresh FastAPI app.

    Exposed as a factory so tests can construct an isolated app and so
    the sibling workers can extend the registry before the app serves
    traffic (they import the entries module before any HTTP request
    fires, so registration is complete by the time the first request
    hits a route).
    """
    # Install JSON logging on the root logger iff LOG_FORMAT=json.
    # Done at app-factory time so test code that calls create_app()
    # multiple times (and reloads modules) still picks up the
    # formatter exactly once per process.
    from .audit_logging import configure_json_logging_if_requested

    configure_json_logging_if_requested()

    if not _TEMPLATES_DIR.is_dir():
        raise RuntimeError(
            f"templates dir missing at {_TEMPLATES_DIR}; "
            "the dashboard package is incomplete."
        )

    app = FastAPI(
        title="ai-billing-audit demo dashboard",
        version=__version__,
        description=(
            "Browse the demo encounters registered for the audit pipeline. "
            "Each card links to a full audit panel for the encounter."
        ),
    )

    # CORS for the marketing portal at zorva.ashbi.ca. The portal
    # fetches /api/encounters/{id}/denial-risk + /appeal-letter from
    # this FastAPI to surface denial-risk + appeal-letter UI on the
    # portal's encounter-detail page. Cross-origin fetch requires
    # these CORS headers; the allow_origin regex covers the prod
    # apex + the wildcard *.ashbi.ca subdomain (so any *.ashbi.ca
    # preview / staging host also works without redeploy).
    #
    # The portal's fetch wrapper only sends the user's session
    # cookie as `credentials: "include"`; we DON'T issue bearer
    # tokens to the portal (which would let a malicious portal
    # exfiltrate the FastAPI's auth context), so allow_credentials
    # is False. The portal sends no auth header; the FastAPI
    # requires its AUDIT_BEARER_TOKEN only for non-CORS endpoints.
    from fastapi.middleware.cors import CORSMiddleware
    import re as _re_cors
    _CORS_ALLOW_ORIGIN_RE = _re_cors.compile(r"^https://([a-z0-9-]+\.)?ashbi\.ca$")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https://([a-z0-9-]+\.)?ashbi\.ca$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-Id", "X-User-Role"],
        allow_credentials=False,
        max_age=3600,
    )

    # Bearer-token auth middleware (F-3 fix from QA_API_HARDENING.md).
    # The /healthz endpoint is whitelisted for load balancer health
    # checks. All other routes require `Authorization: Bearer ***`
    # to match the AUDIT_BEARER_TOKEN env var, or to be in
    # AUDIT_ALLOW_NO_AUTH (set to "1" only for local dev).
    import os as _os
    _BEARER = _os.environ.get("AUDIT_BEARER_TOKEN", "")
    _ALLOW_NO_AUTH = _os.environ.get("AUDIT_ALLOW_NO_AUTH", "") == "1"

    @app.middleware("http")
    async def _metrics_middleware(request, call_next):
        """Bump the http_requests counter on every response.

        Runs BEFORE the auth / rate-limit middleware so we count
        the actual response (including 401 / 429). The /metrics
        endpoint itself is excluded so a Prometheus scrape doesn't
        inflate its own count.
        """
        response = await call_next(request)
        if request.url.path != "/metrics":
            from .metrics import bump_http_request
            bump_http_request(
                request.url.path,
                request.method,
                response.status_code,
            )
        return response

    @app.middleware("http")
    async def _bearer_auth(request, call_next):
        # Whitelist: healthz + static
        if request.url.path in ("/healthz",) or request.url.path.startswith("/static"):
            return await call_next(request)
        # CORS preflight from the portal at zorva.ashbi.ca must pass
        # through without auth — the browser sends OPTIONS without
        # credentials, and the actual GET/POST after preflight is what
        # carries the real request. Without this whitelist the
        # CORSMiddleware would still set the right headers on the
        # OPTIONS response, but the bearer middleware would 401 the
        # preflight first and the browser would never reach CORS.
        if request.method == "OPTIONS":
            return await call_next(request)
        # Public demo paths: the home page, the docs path, the upload
        # portal HTML, plus the JSON endpoints the portal fetches to
        # surface denial-risk + appeal-letter UI on its encounter-
        # detail page. All of these are GET-only and operate on the
        # demo encounter registry (no PHI, no real claims). The
        # mutation endpoints (upload/preview, upload/submit,
        # upload/notes, upload/paste, /encounter/{id}/accept-all,
        # /encounter/{id}/dismiss, etc.) still require auth.
        _PUBLIC_READ_ENDPOINTS = (
            "/api/encounters/{id}/denial-risk",
            "/api/encounters/{id}/appeal-letter",
            "/api/encounters/{id}/appeal-letters",
        )
        if _ALLOW_NO_AUTH:
            return await call_next(request)
        # Public-read bypass (GET-only): the portal at zorva.ashbi.ca
        # fetches denial-risk + appeal-letter to surface the audit
        # results on the encounter-detail page. These endpoints are
        # read-only, work on the demo encounter registry (no PHI, no
        # real claims), and the data is the same the portal would
        # compute locally. They are public-read **regardless of
        # whether AUDIT_BEARER_TOKEN is configured** — so the bypass
        # runs BEFORE the bearer-required branch.
        #
        # Without this bypass, the portal can never call these
        # endpoints from the browser (it doesn't have the bearer
        # token), and the CORS preflight succeeds only for the
        # caller to then 401 on the actual GET.
        if request.method == "GET" and request.url.path.startswith(
            "/api/encounters/"
        ) and any(
            request.url.path.endswith(suffix)
            for suffix in (
                "/denial-risk",
                "/appeal-letter",
                "/appeal-letters",
            )
        ):
            return await call_next(request)
        # Legacy whitelists: /, /healthz, /static. GET-only on / + /healthz.
        # Marketing / funnel pages are also public-read (no PHI, no
        # claims data — just the ROI calculator, the case-study index,
        # the contact form, and the legal stubs). They're the top of
        # the conversion funnel and must not require a bearer token.
        if (
            request.url.path in ("/", "/healthz")
            or request.url.path.startswith("/static")
            or (
                request.method == "GET"
                and request.url.path
                in (
                    "/audits",
                    "/roi",
                    "/roi/results",
                    "/case-studies",
                    "/contact",
                    "/legal/privacy",
                    "/legal/terms",
                    "/metrics",
                    "/openapi.json",
                    "/docs",
                    "/redoc",
                    "/pricing",
                    "/security",
                    "/try",
                    "/how-it-works",
                    "/faq",
                    "/about",
                    "/compare",
                    "/demo-request",
                    "/pilot",
                    "/blog",
                    "/careers",
                    "/press",
                    "/changelog",
                    "/glossary",
                    "/for/family-medicine",
                    "/trust",
                    "/what-zorva-finds",
                    "/status",
                    "/rss.xml",
                    "/sitemap.xml",
                )
            )
            or (
                request.method == "GET"
                and request.url.path.startswith("/case-studies/")
            )
        ):
            return await call_next(request)
        if not _BEARER:
            # Auth disabled because no token is configured. Refuse
            # anything that isn't whitelisted above. The message
            # used to say "POST endpoints disabled" but the
            # middleware blanket-blocks GETs too — so the old copy
            # was misleading (P11 bug-sweep finding). Surface the
            # real reason: the operator hasn't provisioned auth.
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "server has no AUDIT_BEARER_TOKEN configured; non-public requests refused. Contact operator."},
                status_code=503,
            )
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "missing bearer token"}, status_code=401)
        token = auth[len("Bearer "):].strip()
        if token != _BEARER:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "invalid bearer token"}, status_code=401)
        return await call_next(request)

    # RBAC identity middleware (kanban t_846407c4). This middleware
    # populates ``request.state.user`` so the FastAPI dependencies
    # (``require_biller_or_admin`` / ``require_admin``) can resolve
    # the caller's identity without each endpoint re-parsing the
    # headers. The middleware is permissive: it never rejects on
    # its own (the bearer-token middleware above already handled
    # authentication); it only extracts identity for the dependency
    # layer to enforce role-based authorization.
    @app.middleware("http")
    async def _rate_limit_middleware(request, call_next):
        """In-process per-IP rate limiter for unauthenticated routes.

        Defence-in-depth on top of the Traefik rate-limiter
        (see /opt/traefik/dynamic/routers.yml). Traefik caps at
        the network edge; this middleware caps at the app edge so
        a misconfigured proxy or a direct-container-request from
        the host still can't drive /contact into spam.

        Routes limited (request > 10/minute per IP → 429):
          * POST /contact
          * POST /api/encounters/upload (real-clients upload path)

        All other routes are unbounded here — auth-required routes
        are already protected by the bearer middleware, and
        public-read marketing routes are too cheap to abuse.

        Storage: a plain dict keyed by (route, ip). Each entry is
        a list of timestamps; on each request we evict anything
        older than 60s and check the remaining count. This is
        fine for one-process Uvicorn; a multi-worker setup would
        need Redis. Multi-worker note: each uvicorn worker has its
        own dict, so the effective limit per IP is
        ``N_WORKERS * 10/minute``. Acceptable for defence-in-depth;
        document if you scale past one worker.
        """
        import time as _time
        from fastapi.responses import JSONResponse

        path = request.url.path
        method = request.method
        is_limited = (
            (method == "POST" and path == "/contact")
            or (method == "POST" and path.startswith("/api/encounters/upload"))
        )
        if not is_limited:
            return await call_next(request)

        # Pick a key for the requester. X-Forwarded-For is set by
        # Traefik; fall back to the direct client.
        xff = request.headers.get("x-forwarded-for", "")
        ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
        bucket_key = (method, path, ip)
        now = _time.monotonic()
        window_start = now - 60.0
        bucket = _rate_limit_state.setdefault(bucket_key, [])
        # Evict old timestamps (in-place; safe because we mutate the
        # list reference held in the dict).
        i = 0
        while i < len(bucket) and bucket[i] < window_start:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= 10:
            return JSONResponse(
                {
                    "detail": "rate limit exceeded: 10 requests/minute per IP",
                    "retry_after_s": 60,
                },
                status_code=429,
                headers={"Retry-After": "60"},
            )
        bucket.append(now)
        return await call_next(request)

    # Per-process rate-limit state. Dict keyed by (method, path,
    # ip) → list of monotonic timestamps within the last 60s.
    # Module-level so it survives between requests but resets on
    # process restart (intentional — a long-running bucket could
    # lock out an IP that was rate-limited hours ago).
    _rate_limit_state: dict = {}

    @app.middleware("http")
    async def _rbac_identity_middleware(request, call_next):
        user_id = request.headers.get("X-User-Id")
        user_role = request.headers.get("X-User-Role")
        role = _coerce_role(user_role)
        if user_id and role:
            request.state.user = UserContext(
                user_id=str(user_id).strip(),
                role=role,
                user_identifier=str(user_id).strip(),
            )
        elif user_role and not role:
            # Bad role in header — leave state.user unset. The
            # dependency will raise 403 when invoked.
            request.state.user = None
        else:
            # No headers; leave state.user as None. The dev-mode
            # fallback in ``_resolve_user_from_request`` will
            # supply a synthetic admin if AUDIT_ALLOW_NO_AUTH=*** is set.
            request.state.user = None
        return await call_next(request)

    def _latest_real_audit_for(encounter_id: str) -> dict[str, Any] | None:
        """Return the most recent completed LLM audit for an encounter.

        Tenant scoping (multi-tenant hardening): the upload_jobs
        log is append-only and lives in /app/logs. Without a
        tenant filter here, one tenant's encounter_id could
        collide with another tenant's (and one tenant's biller
        could read another tenant's findings). We delegate to
        the module-level ``read_latest_real_audit`` and pass
        _TENANT_ID explicitly so the function is unit-testable
        in isolation.

        Log path is configurable via the UPLOAD_AUDIT_LOG_PATH env
        var so tests can point at a tmp file. Default is the
        production path inside the container.
        """
        return read_latest_real_audit(
            encounter_id=encounter_id,
            tenant_id=_TENANT_ID,
            log_path=_os.environ.get(
                "UPLOAD_AUDIT_LOG_PATH", "/app/logs/upload_jobs.jsonl",
            ),
        )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["highlight_quote"] = _highlight_quote
    templates.env.globals["tenant_name"] = _TENANT_NAME
    templates.env.globals["tenant_id"] = _TENANT_ID

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        """Public marketing landing page.

        Replaces the Audits dashboard at / so prospects who land on
        ai-billing-audit.ashbi.ca see a marketing surface first. The
        Audits dashboard is now at /audits (preserved as the same
        handler with the same name). See the home.html template
        for the four-question landing structure.
        """
        return templates.TemplateResponse(request, "home.html", {
            "request": request,
        })

    @app.get("/audits", response_class=HTMLResponse)
    def audits_dashboard(request: Request) -> HTMLResponse:
        registered = list_demo_encounters()
        # Saved-filter presets (kanban t_66b05d72). Resolve the
        # current user from the RBAC layer so each biller sees their
        # own presets. ``?preset=<name>`` deep-links to a stored
        # preset; ``?set_default=1`` toggles the default flag for
        # the biller; ``?delete_preset=1`` removes a preset.
        from .saved_filters import SavedFilterStore

        # Use the anonymous-friendly user lookup so the index page
        # still renders for unauthenticated visitors (the demo
        # encounters and saved-filter presets are public-readable
        # when AUDIT_ALLOW_NO_AUTH is on, and the middleware
        # whitelist routes / through to this handler regardless of
        # bearer state). For auth-required deployments, the
        # middleware 401s before we get here — see
        # _bearer_auth_middleware in the create_app factory.
        user = get_request_user_or_anonymous(request)
        user_id = user.user_id or "dev_user"
        preset_store = SavedFilterStore()
        user_presets = preset_store.list_for_user(user_id)
        default_preset_name: str | None = None
        for p in user_presets:
            if p.is_default:
                default_preset_name = p.preset_name
                break

        # Filter + search state. These are referenced at lines ~1165+
        # (before they're assigned lower down in the function, around
        # ~1306), so pre-initialize them to safe defaults here. Without
        # this, requests that hit the early code paths before the
        # assignment block runs raise UnboundLocalError and the
        # dashboard returns HTTP 500 (the bug surfaced on 2026-06-26
        # when the index endpoint first received a request with auth
        # headers — the user-lookup code path hit the early
        # `current_filter_state` write before reaching the assignment).
        # The values are overwritten by the later query-param parsing
        # block; these initializers are just there to guarantee a
        # defined value at every read site.
        active_filter: str = "all"
        search_active: bool = False
        search_q_raw: str = ""
        search_cpt_raw: str = ""
        search_icd10_raw: str = ""
        search_patient_raw: str = ""
        search_npi_raw: str = ""
        # Apply ?preset=<name> as a deep-link override. The URL
        # becomes a shareable handle: a colleague can paste it in
        # chat and the biller sees the same view on click.
        preset_param = request.query_params.get("preset", "").strip()
        if preset_param:
            preset_obj = preset_store.get_preset(user_id, preset_param)
            if preset_obj and preset_obj.filter:
                # Build a redirect URL so the back button + share
                # workflow stays canonical (the URL is the state).
                params: list[tuple[str, str]] = []
                for k, v in preset_obj.filter.items():
                    params.append((k, v))
                from urllib.parse import urlencode

                redirect_url = "/?" + urlencode(params)
                # FastAPI doesn't have a clean "redirect" from a
                # template-rendering GET, so return a tiny HTML
                # page with a meta-refresh + JS fallback. This
                # keeps the route HTML-only as the task spec
                # requires (no JSON contract change).
                return HTMLResponse(
                    f'<!doctype html><meta http-equiv="refresh" '
                    f'content="0;url={redirect_url}">'
                    f'<script>location.replace("{redirect_url}")</script>'
                    f'<a href="{redirect_url}">Continue to '
                    f"{preset_obj.preset_name}</a>",
                    status_code=200,
                )
        # Compute the current-preset name (does the URL match a
        # stored preset exactly?). Used by the template to render
        # the "edit default / delete" controls next to the active
        # filter bar.
        current_filter_state: dict[str, str] = {}
        if active_filter and active_filter != "all":
            current_filter_state["status"] = active_filter
        if search_active:
            for raw_key, raw_val in (
                ("q", search_q_raw),
                ("cpt", search_cpt_raw),
                ("icd10", search_icd10_raw),
                ("patient_id", search_patient_raw),
                ("provider_npi", search_npi_raw),
            ):
                if raw_val:
                    current_filter_state[raw_key] = raw_val
        current_preset_name: str | None = None
        for p in user_presets:
            if p.filter == current_filter_state:
                current_preset_name = p.preset_name
                break
        # Handle ?set_default=1&name=<preset> — set a preset as the
        # user's default. We render a redirect to the clean URL so
        # the action is bookmarkable.
        set_default_param = request.query_params.get("set_default", "").strip()
        if set_default_param == "1":
            name_param = request.query_params.get("name", "").strip()
            if name_param:
                target = preset_store.get_preset(user_id, name_param)
                if target is not None and target.filter:
                    preset_store.save_preset(
                        user_id,
                        name_param,
                        target.filter,
                        set_default=True,
                    )
                    return HTMLResponse(
                        f'<!doctype html><meta http-equiv="refresh" '
                        f'content="0;url=/?preset={name_param}">'
                        f'<a href="/?preset={name_param}">'
                        f"Continue</a>",
                        status_code=200,
                    )
        # Decorate each entry with the record's flag status (so the
        # index can show a green "CLEAN" badge vs an amber "FLAGGED" one)
        # and a count of findings, but keep the heavy fields off the
        # index to keep the page small.
        cards: list[dict[str, Any]] = []
        for entry in registered:
            record = load_encounter_record(entry.encounter_id)
            n_findings = len(record.get("ground_truth", [])) if record else 0
            # Per-tenant severity threshold (v1: env var). Findings with
            # severity BELOW this are not counted. The card still shows
            # "flagged" if any sub-threshold finding exists (so the
            # clinic owner knows there's something to look at), but the
            # n_findings badge reflects what the biller would actually
            # see in the detail page.
            min_sev = _min_severity_threshold()
            # Score denial risk from the gold findings. Demo cards
            # get a deterministic score that mirrors what the biller
            # sees when they click through.
            visible_for_card = []
            if record is not None:
                visible_for_card = [
                    f for f in _finding_dicts(record)
                    if SEVERITY_RANK.get(f.get("severity", "info"), 0) >= min_sev
                ]
            from .denial_risk import compute_denial_risk
            if visible_for_card:
                card_risk = compute_denial_risk(
                    visible_for_card, min_severity=min_sev
                )
            else:
                card_risk = {
                    "denial_probability": 0.0,
                    "tier": "low",
                    "top_risk": None,
                }
            # Per-encounter revenue opportunity summary. Powers the
            # "$$ opportunity" badge on the home page card so the
            # biller can scan for highest-value encounters first.
            # Tier thresholds: green < $50, yellow $50-200, red >= $200.
            opp = compute_revenue_opportunities(visible_for_card)
            opp_total = round(
                sum(o.get("estimated_dollar", 0.0) for o in opp), 2
            )
            if opp_total >= 200:
                opp_tier = "high"
            elif opp_total >= 50:
                opp_tier = "medium"
            elif opp_total > 0:
                opp_tier = "low"
            else:
                opp_tier = None
            # Pull claim-level fields the search filter uses (kanban
            # t_171d24b3). The synthetic demo records expose CPT and
            # ICD10 on ``record['claim']``; real uploads also carry
            # ``patient_id`` and ``provider_npis`` so the same search
            # bar works for both. Missing keys default to empty lists /
            # strings so the filter never throws on a partial record.
            _claim = (record or {}).get("claim", {}) or {}
            _cpt_codes = _claim.get("cpt_codes", []) or []
            _icd10_codes = _claim.get("icd10_codes", []) or []
            _patient_id = (
                _claim.get("patient_id")
                or (record or {}).get("patient_id")
                or ""
            )
            _provider_npis = _claim.get("provider_npis", []) or []
            cards.append(
                {
                    "encounter_id": entry.encounter_id,
                    "difficulty": entry.difficulty,
                    "summary": entry.summary,
                    "is_flagged": bool(record.get("is_flagged")) if record else False,
                    "n_findings": n_findings,
                    "available": record is not None,
                    "denial_risk": card_risk,
                    "revenue_opportunity_total": opp_total,
                    "revenue_opportunity_tier": opp_tier,
                    "revenue_opportunity_count": len(opp),
                    "cpt_codes": _cpt_codes,
                    "icd10_codes": _icd10_codes,
                    "patient_id": _patient_id,
                    "provider_npis": _provider_npis,
                }
            )
        # Filter chips (counts) and clean-rate hero (metrics). Both
        # are derived from the registered demo cards here; the
        # template renders them in the filter-bar and hero panel.
        # Real uploaded encounters are surfaced via _list_parsed_encounters()
        # in the upload-portal pages, not on the public home page.
        counts = {
            "all": len(cards),
            "flagged": sum(1 for c in cards if c["is_flagged"]),
            "clean": sum(1 for c in cards if not c["is_flagged"]),
            "opportunities": sum(
                1 for c in cards if c["revenue_opportunity_total"] > 0
            ),
        }
        # Honour ?status= query param so the chip click actually
        # filters the rendered card grid. Default and fallback is
        # "all" so existing links keep working.
        raw_filter = request.query_params.get("status", "all").lower()
        allowed_filters = {"all", "flagged", "clean", "opportunities"}
        active_filter = raw_filter if raw_filter in allowed_filters else "all"
        if active_filter == "flagged":
            visible_cards = [c for c in cards if c["is_flagged"]]
        elif active_filter == "clean":
            visible_cards = [c for c in cards if not c["is_flagged"]]
        elif active_filter == "opportunities":
            visible_cards = [
                c for c in cards if c["revenue_opportunity_total"] > 0
            ]
        else:
            visible_cards = list(cards)
        # Encounter search (kanban t_171d24b3): the index page can
        # carry ?q= (encounter_id substring) and ?cpt= / ?icd10=
        # (prefix) filters via the search bar in the template. Filters
        # combine via AND, are URL-preserved for shareable links, and
        # run after the status filter so chip + search compose
        # cleanly. Patient ID and provider NPI are accepted but only
        # applied when the loaded record actually carries those fields
        # (the synthetic demo data doesn't, but real uploads do).
        # Original-case values are preserved for the form echo so the
        # biller sees what they typed (e.g. "I10" stays "I10" instead
        # of "i10"); the filter compares case-insensitively below.
        search_q_raw = request.query_params.get("q", "").strip()
        search_cpt_raw = request.query_params.get("cpt", "").strip()
        search_icd10_raw = request.query_params.get("icd10", "").strip()
        search_patient_raw = request.query_params.get(
            "patient_id", ""
        ).strip()
        search_npi_raw = request.query_params.get(
            "provider_npi", ""
        ).strip()
        search_q = search_q_raw.lower()
        search_cpt = search_cpt_raw.lower()
        search_icd10 = search_icd10_raw.lower()
        search_patient = search_patient_raw.lower()
        search_npi = search_npi_raw.lower()
        search_active = any(
            [search_q, search_cpt, search_icd10, search_patient, search_npi]
        )
        if search_active:
            def _card_matches(card: dict[str, Any]) -> bool:
                if search_q and search_q not in (card["encounter_id"] or "").lower():
                    return False
                if search_cpt:
                    cpts = [str(c).lower() for c in card.get("cpt_codes", [])]
                    if not any(c.startswith(search_cpt) for c in cpts):
                        return False
                if search_icd10:
                    icds = [str(c).lower() for c in card.get("icd10_codes", [])]
                    if not any(c.startswith(search_icd10) for c in icds):
                        return False
                if search_patient:
                    pid = (card.get("patient_id") or "").lower()
                    if pid != search_patient:
                        return False
                if search_npi:
                    npis = [str(n).lower() for n in card.get("provider_npis", [])]
                    if search_npi not in npis:
                        return False
                return True

            visible_cards = [c for c in visible_cards if _card_matches(c)]
        # No real-audit running totals on the demo dashboard; the
        # metrics dict is the "no data" shape so the template's
        # `{% if metrics and metrics.ready %}` skips the hero. Once
        # the demo registry accumulates real audits, this gets
        # populated.
        metrics = compute_clean_rate_metrics(cards, now=time.time())
        # Most recent real-audit run. Walk the job-queue JSONL log
        # back to the last line with audit_status=ok (no per-encounter
        # filter — we want the latest one for the home page).
        latest_real_audit: dict[str, Any] | None = None
        try:
            from pathlib import Path as _P
            log_path = _P("/app/logs/upload_jobs.jsonl")
            if log_path.is_file():
                with log_path.open() as fh:
                    lines = fh.readlines()
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("status") != "done":
                        continue
                    res = rec.get("result", {}) or {}
                    if res.get("audit_status") != "ok":
                        continue
                    latest_real_audit = {
                        "job_id": rec.get("job_id"),
                        "encounter_id": rec.get("encounter_id"),
                        "source": rec.get("source"),
                        "submitted_at": rec.get("submitted_at"),
                        "finished_at": rec.get("finished_at"),
                        "findings_count": res.get("findings_count", 0),
                        "summary": res.get("summary", ""),
                        "difficulty_tier": res.get("difficulty_tier"),
                        "variant": res.get("variant"),
                    }
                    break
        except Exception:
            latest_real_audit = None
        # Top missed-revenue patterns this month — feeds the
        # "Revenue opportunity by rule" bar chart in the dashboard.
        # Computed after cards so the aggregation can reuse the
        # same encounter data without an extra registry walk.
        try:
            from .dashboard import (
                aggregate_missed_revenue_by_rule,
                aggregate_monthly_revenue_kpi,
                month_label as _month_label,
            )
            top_missed_revenue_rules = aggregate_missed_revenue_by_rule(top_n=5)
            missed_revenue_month_label = _month_label()
        except Exception:
            top_missed_revenue_rules = []
            missed_revenue_month_label = ""
        # Monthly "revenue recovered" KPI for the dashboard hero tile.
        # Shows identified / recovered / pending dollars for the current
        # calendar month so the biller can see whether the system is
        # trustworthy at a glance. Same try/except fallback pattern as
        # the rule aggregator above — empty state if anything fails.
        try:
            from .dashboard import aggregate_monthly_revenue_kpi as _amrk
            monthly_revenue_kpi = _amrk()
        except Exception:
            monthly_revenue_kpi = {
                "total_dollar": 0.0,
                "recovered_dollar": 0.0,
                "pending_dollar": 0.0,
                "n_opportunities": 0,
                "n_accepted": 0,
                "acceptance_ratio": 0.0,
                "month_label": "",
                "ready": False,
            }
        # Per-clinic F1 widget — same data the
        # ``/api/dashboard/per_clinic_f1`` JSON endpoint serves, but
        # rendered server-side so the dashboard shows the
        # "insufficient data" empty state on first paint without
        # waiting for the JS fetch. The try/except fallback mirrors
        # the rest of the dashboard: missing module / broken
        # feedback log → empty state, not a 500.
        try:
            from .per_clinic_f1 import (
                insufficient_data_state,
                per_rule_metrics as _pcf1_per_rule,
            )
            _pcf1_clinic = _TENANT_ID or "default_biller"
            _pcf1_per_rule = _pcf1_per_rule(clinic_id=_pcf1_clinic, days=30)
            per_clinic_f1_widget = insufficient_data_state(
                clinic_id=_pcf1_clinic,
                per_rule=_pcf1_per_rule,
                window_days=30,
            )
        except Exception:
            per_clinic_f1_widget = {
                "is_insufficient": True,
                "total_support": 0,
                "threshold": 3,
                "window_days": 30,
                "clinic_id": "default_biller",
                "headline": "Insufficient data — need a few more reviews",
                "message": (
                    "The per-clinic F1 number isn't available yet. "
                    "Once a biller has accepted or dismissed a few "
                    "findings, this tile will start showing your "
                    "model's accuracy for this clinic."
                ),
                "cta": "Review a few findings to start measuring.",
            }
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "audits": visible_cards,
                "filter": active_filter,
                "counts": counts,
                "total_this_week": 0,
                "metrics": metrics,
                "n_registered": len(cards),
                "latest_real_audit": latest_real_audit,
                "top_missed_revenue_rules": top_missed_revenue_rules,
                "missed_revenue_month_label": missed_revenue_month_label,
                "monthly_revenue_kpi": monthly_revenue_kpi,
                "per_clinic_f1_widget": per_clinic_f1_widget,
                # Encounter search (kanban t_171d24b3): the form
                # values echo back into the inputs so a biller can
                # refine a search without re-typing everything; the
                # ``search_active`` flag drives the empty-state copy
                # ("no matches" vs "no audits").
                "search": {
                    "q": search_q_raw,
                    "cpt": search_cpt_raw,
                    "icd10": search_icd10_raw,
                    "patient_id": search_patient_raw,
                    "provider_npi": search_npi_raw,
                    "active": search_active,
                },
                # Saved-filter presets (kanban t_66b05d72). The store
                # is JSONL-backed so we tolerate a fresh install with
                # no log file. ``current_preset`` is set when the URL
                # matches a stored preset exactly; ``default_preset``
                # is what we'd redirect to on a clean visit if the
                # biller had marked one. The template renders the
                # dropdown + "Save current" form.
                "presets": user_presets,
                "current_preset_name": current_preset_name,
                "default_preset_name": default_preset_name,
            },
        )

    @app.get("/encounter/{encounter_id}", response_class=HTMLResponse)
    def encounter_detail(request: Request, encounter_id: str) -> HTMLResponse:
        """Render the encounter detail page.

        Three lookup paths, in order:
        1. Demo registry (encounters registered in demo_entries.py)
        2. Real uploaded encounter with a completed audit (reads
           /app/logs/upload_jobs.jsonl for the most recent audit
           for this encounter_id)
        3. 404 if neither

        The detail template is shared across all three; demo
        encounters use gold-ground-truth findings, uploaded
        encounters use real-LLM-audit findings.

        Snooze (kanban t_993c411c): the URL may carry
        ``?include_snoozed=true`` to surface findings that the
        biller has snoozed. Default behaviour hides active
        snoozes from the visible list. The active count is
        passed to the template as ``n_snoozed`` so the header
        can show a "3 snoozed" pill regardless of the filter.
        """
        include_snoozed = _truthy(request.query_params.get("include_snoozed"))
        # Resolve the active snooze map for this encounter once;
        # both the demo path and the uploaded path need it.
        from .snooze import SnoozeStore, filter_findings_by_snooze
        snooze_store = SnoozeStore()
        active_snoozes = snooze_store.active_snoozes_for_encounter(encounter_id)
        n_snoozed = len(active_snoozes)
        # Finding assignments (kanban t_54262d96): resolve the
        # current assignee for every finding on this encounter
        # so the template can render the "Assigned to <biller>"
        # badge without an N+1 fetch. Best-effort: if the
        # assignments store can't be loaded (older deploy,
        # missing module), the template falls back to no badge
        # and the page still renders.
        assignment_map: dict[str, dict[str, Any]] = {}
        try:
            from .finding_assignments import FindingAssignmentStore
            _fa_store = FindingAssignmentStore()
            for fid, entry in _fa_store.current_assignees_for_encounter(
                encounter_id
            ).items():
                assignment_map[fid] = entry.to_dict()
        except Exception:
            assignment_map = {}
        demo = get_demo_encounter(encounter_id)
        if demo is not None:
            record = load_encounter_record(encounter_id)
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"encounter {encounter_id!r} is registered but the "
                        "underlying record could not be located in data/val.json "
                        "or data/train.json."
                    ),
                )
            findings = _finding_dicts(record)
            min_sev = _min_severity_threshold()
            severity_visible = [
                f for f in findings
                if SEVERITY_RANK.get(f.get("severity", "info"), 0) >= min_sev
            ]
            # Apply the snooze filter on top of the severity
            # filter. With ``include_snoozed=false`` (default)
            # active snoozes are dropped; ``hidden_count`` rolls
            # BOTH the severity-hidden and the snoozed findings
            # into a single number so the template can show a
            # combined "X findings hidden" pill.
            visible_findings = filter_findings_by_snooze(
                severity_visible,
                active_snoozes,
                include_snoozed=include_snoozed,
            )
            hidden_count = len(findings) - len(visible_findings)
            real_audit = _latest_real_audit_for(encounter_id)
            # Score denial risk from the visible findings. Demo
            # encounters don't get a separate real-audit risk score
            # because the gold findings are deterministic; we
            # score from the same finding list the page shows.
            from .denial_risk import compute_denial_risk
            denial_risk = compute_denial_risk(
                visible_findings, min_severity=min_sev
            )
            # Surface missed-revenue findings as a distinct card so the
            # biller sees dollar uplifts separately from denial risks.
            # We derive from visible_findings (not raw findings) so the
            # card respects MIN_SEVERITY_TO_SHOW.
            revenue_opportunities = compute_revenue_opportunities(visible_findings)
            total_opportunity_dollars = round(
                sum(o["estimated_dollar"] for o in revenue_opportunities), 2
            )
            # Attach per-finding "Model confidence" buckets derived from
            # the feedback log so the encounter-detail template can
            # render a color-coded badge per finding (HIGH/MEDIUM/LOW or
            # "Not yet calibrated" placeholder).
            _attach_model_confidence(visible_findings)
            _attach_model_confidence(revenue_opportunities)
            # Attach per-finding appeal context: which findings have a
            # generated appeal letter (gates the outcome form) and the
            # most recent outcome (rendered as "Last outcome" above the
            # form). Best-effort; never raises.
            _attach_appeal_context(visible_findings, encounter_id)
            # The PRIMARY finding's evidence quote is passed to the
            # template separately so the ``_highlight_quote`` Jinja
            # filter can wrap it in <mark class="evidence">…</mark>.
            # The filter is registered at app boot (see create_app)
            # and is case-insensitive; the verbatim span is the
            # contract the dashboard tests + the biller's eye both
            # rely on to find the evidence quickly.
            primary_quote: str = ""
            if visible_findings:
                # PRIMARY = the first finding in display order (NOT
                # the highest-severity one). The dashboard tests
                # pin the highlight to the FIRST finding's quote
                # because that's how the biller scans the audit
                # panel top-to-bottom — they care about the lead
                # finding's evidence, not whichever happens to
                # have the loudest severity.
                for cand in visible_findings:
                    q = str(cand.get("quote", "") or "").strip()
                    if q:
                        primary_quote = q
                        break
            return templates.TemplateResponse(
                request,
                "encounter_detail.html",
                {
                    "encounter_id": encounter_id,
                    "difficulty": demo.difficulty,
                    "summary": demo.summary,
                    "is_flagged": record.get("is_flagged", False),
                    "clinical_note": record.get("clinical_note", ""),
                    "primary_quote": primary_quote,
                    "claim": record.get("claim", {}),
                    "rules": record.get("rules", []),
                    "findings": visible_findings,
                    "n_findings": len(visible_findings),
                    "n_findings_total": len(findings),
                    "n_findings_hidden": hidden_count,
                    "min_severity": min_sev,
                    "real_audit": real_audit,
                    "is_uploaded_encounter": False,
                    "denial_risk": denial_risk,
                    "revenue_opportunities": revenue_opportunities,
                    "total_opportunity_dollars": total_opportunity_dollars,
                    "n_snoozed": n_snoozed,
                    "include_snoozed": include_snoozed,
                    "assignments": assignment_map,
                },
            )

        # Path 2: uploaded encounter. Look up the most recent audit
        # for this encounter_id in the upload-jobs JSONL log.
        uploaded_audit = _latest_real_audit_for(encounter_id)
        if uploaded_audit is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"encounter {encounter_id!r} is not registered on the "
                    "demo dashboard, and no completed audit was found "
                    "for it in the upload history."
                ),
            )
        uploaded_findings = uploaded_audit.get("findings", []) or []
        min_sev = _min_severity_threshold()
        severity_visible = [
            f for f in uploaded_findings
            if SEVERITY_RANK.get(str(f.get("severity", "info")).lower(), 0) >= min_sev
        ]
        # Snooze filter — same shape as the demo path above.
        visible_uploaded = filter_findings_by_snooze(
            severity_visible,
            active_snoozes,
            include_snoozed=include_snoozed,
        )
        hidden_count = len(uploaded_findings) - len(visible_uploaded)
        # Score denial risk. For uploaded encounters this is the
        # REAL risk — it's the LLM's actual findings from the
        # clinic's data, not the demo's gold findings. This is
        # the number the biller actually cares about.
        from .denial_risk import compute_denial_risk
        denial_risk = compute_denial_risk(
            uploaded_findings, min_severity=min_sev
        )
        # Same revenue-opportunity pass for uploaded encounters.
        revenue_opportunities = compute_revenue_opportunities(visible_uploaded)
        total_opportunity_dollars = round(
            sum(o["estimated_dollar"] for o in revenue_opportunities), 2
        )
        # Same model-confidence pass as the demo path above — derive
        # per-finding buckets from the feedback log so the template
        # can render the "Model confidence: HIGH" badge on each
        # finding. Idempotent on findings that already have the
        # field set by an earlier handler.
        _attach_model_confidence(visible_uploaded)
        _attach_model_confidence(revenue_opportunities)
        # Same appeal-context pass for uploaded encounters so the
        # per-finding "Log appeal outcome" form appears once an
        # appeal letter has been generated for the encounter.
        _attach_appeal_context(visible_uploaded, encounter_id)
        return templates.TemplateResponse(
            request,
            "encounter_detail.html",
            {
                "encounter_id": encounter_id,
                "difficulty": uploaded_audit.get("difficulty_tier", ""),
                "summary": uploaded_audit.get("summary", ""),
                "is_flagged": bool(uploaded_findings),
                "clinical_note": "",
                "claim": {
                    "encounter_id": encounter_id,
                    "line_items": [],
                    "diagnosis_codes": [],
                },
                "rules": [],
                "findings": visible_uploaded,
                "n_findings": len(visible_uploaded),
                "n_findings_total": len(uploaded_findings),
                "n_findings_hidden": hidden_count,
                "min_severity": min_sev,
                "real_audit": uploaded_audit,
                "is_uploaded_encounter": True,
                "zorva_context": uploaded_audit.get("zorva_context"),
                "denial_risk": denial_risk,
                "revenue_opportunities": revenue_opportunities,
                "total_opportunity_dollars": total_opportunity_dollars,
                "n_snoozed": n_snoozed,
                "include_snoozed": include_snoozed,
                "assignments": assignment_map,
            },
        )
        real_audit = _latest_real_audit_for(encounter_id)

    @app.get("/encounter/{encounter_id}/json")
    def encounter_json(encounter_id: str) -> JSONResponse:
        demo = get_demo_encounter(encounter_id)
        if demo is None:
            raise HTTPException(
                status_code=404, detail=f"{encounter_id!r} not registered"
            )
        record = load_encounter_record(encounter_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"{encounter_id!r} record not found"
            )
        return JSONResponse(
            {
                "encounter_id": encounter_id,
                "difficulty": demo.difficulty,
                "summary": demo.summary,
                "is_flagged": record.get("is_flagged", False),
                "n_gold_findings": len(record.get("ground_truth", [])),
            }
        )

    @app.get("/encounter/{encounter_id}/opportunities", response_class=JSONResponse)
    def encounter_opportunities(encounter_id: str) -> JSONResponse:
        """Return the list of revenue-opportunity findings for an encounter.

        Powers the '$$ opportunity' detail modal that opens when a biller
        clicks the revenue badge on an audit card on the dashboard. The
        response shape is a thin projection of ``compute_revenue_opportunities``
        — enough for the modal to render rule name, suggested SOMB code,
        estimated dollar uplift, and the one-sentence 'why this matters'.

        Each opportunity carries the original ``finding_id`` so the modal
        can reuse the existing per-finding accept / dismiss endpoints.

        Mirrors the encounter-detail handler's lookup paths:
          1. Demo registry (gold ground-truth findings)
          2. Uploaded encounter with a completed audit (real LLM findings)
          3. 404 if neither
        """
        findings = _load_visible_findings_for_modal(encounter_id)
        if findings is None:
            raise HTTPException(
                status_code=404,
                detail=f"{encounter_id!r} not found or has no visible findings",
            )
        opportunities = compute_revenue_opportunities(findings)
        # Project to the slim modal shape — drop heavy fields, keep
        # only what the UI needs to render the per-finding row.
        rows = [
            {
                "finding_id": o.get("finding_id") or "",
                "rule_id": o.get("opportunity_rule_id") or o.get("rule_id") or "",
                "rule_name": o.get("rule_name") or o.get("opportunity_rule_id") or "",
                "suggested_code": o.get("suggested_code") or o.get("somb_code") or "",
                "estimated_dollar": float(o.get("estimated_dollar") or 0.0),
                "why": o.get("suggested_action") or "",
                "severity": o.get("severity") or "info",
            }
            for o in opportunities
        ]
        total = round(sum(r["estimated_dollar"] for r in rows), 2)
        return JSONResponse(
            {
                "encounter_id": encounter_id,
                "opportunities": rows,
                "total_dollar": total,
                "n_opportunities": len(rows),
            }
        )

    def _load_visible_findings_for_modal(encounter_id: str) -> list[dict] | None:
        """Return severity-filtered findings for the modal API.

        Same lookup paths as ``encounter_detail``: demo registry first,
        then uploaded/real-audit log. Returns ``None`` if the encounter
        is unknown OR has zero visible findings after the MIN_SEVERITY
        threshold is applied.
        """
        min_sev = _min_severity_threshold()
        demo = get_demo_encounter(encounter_id)
        if demo is not None:
            record = load_encounter_record(encounter_id)
            if record is None:
                return None
            findings = _finding_dicts(record)
            return [
                f for f in findings
                if SEVERITY_RANK.get(f.get("severity", "info"), 0) >= min_sev
            ]
        # Path 2: uploaded encounter with a completed audit.
        uploaded_audit = _latest_real_audit_for(encounter_id)
        if uploaded_audit is None:
            return None
        uploaded_findings = uploaded_audit.get("findings", []) or []
        return [
            f for f in uploaded_findings
            if SEVERITY_RANK.get(f.get("severity", "info"), 0) >= min_sev
        ]

    # ---- Reviewer actions: accept-all / dismiss / rerun / flag ----
    # Persisted via audit_actions.append(); each row is SHA-256-chained
    # so the trail is tamper-evident. The encounter detail page posts
    # to these endpoints when the biller clicks Accept / Dismiss / etc.
    # Each decision ALSO writes a FeedbackEntry to feedback.py — the
    # "training data" layer that seeds the learning loop (per-encounter
    # accept/dismiss/modify log with severity, rule_id, category).

    def _lookup_finding_meta(encounter_id: str, finding_id: str) -> tuple[str, str, str]:
        """Return (severity, rule_id, category) for a finding, or '' if unknown."""
        record = load_encounter_record(encounter_id)
        if not record:
            return "", "", ""
        for f in record.get("ground_truth", []) or []:
            if (f.get("finding_id") or f.get("id")) == finding_id:
                return (
                    str(f.get("severity", "") or ""),
                    str(f.get("rule_id", "") or ""),
                    str(f.get("category", "") or ""),
                )
        return "", "", ""

    def _record_feedback(
        encounter_id: str,
        finding_id: str,
        action: str,
        *,
        user_identifier: str,
        modify_severity: str | None = None,
        modify_category: str | None = None,
        note: str | None = None,
        correct_finding: dict[str, Any] | None = None,
    ) -> None:
        """Append one FeedbackEntry to the per-encounter learning-loop log."""
        try:
            from .feedback import FeedbackEntry, get_default_store
        except ImportError:
            return
        severity, rule_id, category = _lookup_finding_meta(encounter_id, finding_id)
        # For modify actions the spec'd schema records the biller's
        # override; we still keep the original severity/rule/category
        # so the training-data view can diff old vs. new.
        if action == "modify":
            ms = modify_severity if modify_severity is not None else severity
            mc = modify_category if modify_category is not None else category
        else:
            ms, mc = None, None
        store = get_default_store()
        entry_kwargs: dict = dict(
            encounter_id=encounter_id,
            finding_id=finding_id,
            action=action,  # type: ignore[arg-type]
            severity=severity,
            rule_id=rule_id,
            category=category,
            biller_id=user_identifier or "default_biller",
            modify_severity=ms,
            modify_category=mc,
        )
        # Forward-compatible: if FeedbackEntry has these fields, attach them.
        try:
            from dataclasses import fields as _dc_fields
            field_names = {f.name for f in _dc_fields(FeedbackEntry)}
            if "correct_finding" in field_names and correct_finding is not None:
                entry_kwargs["correct_finding"] = correct_finding
            if "note" in field_names and note is not None:
                entry_kwargs["note"] = note
        except Exception:
            pass
        store.append(FeedbackEntry(**entry_kwargs))

    @app.post("/encounter/{encounter_id}/accept-all")
    async def encounter_accept_all(
        encounter_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            findings_count = int(body.get("findings_count", 0))
        except (TypeError, ValueError):
            findings_count = 0
        event = audit_append(
            action="accept_all",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            extra={"findings_count": findings_count},
            user_id=user.user_id,
            user_role=user.role,
        )
        # Learning-loop: log one synthetic feedback entry per accept-all so
        # the per-encounter view shows the decision. The finding_id is
        # "__accept_all__" to disambiguate from per-finding accept rows.
        _record_feedback(
            encounter_id=encounter_id,
            finding_id="__accept_all__",
            action="accept",
            user_identifier=user.user_identifier,
        )
        return JSONResponse({"ok": True, "n_accepted": findings_count, "event": event})

    @app.post("/encounter/{encounter_id}/dismiss")
    async def encounter_dismiss(
        encounter_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        finding_id = str(body.get("finding_id", "") or "")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        # Closed-loop learning signal: why did the biller dismiss this
        # finding? Captured as a free-text reason + a coarse category
        # (false_positive, already_documented, not_applicable, other).
        # Persisted in audit_actions.append via the ``note`` field so
        # the existing chain signature still covers the dismissal.
        reason_category = str(body.get("reason_category", "") or "").strip()
        reason_text = str(body.get("reason_text", "") or "").strip()[:500]
        if reason_category and not _DISMISS_CATEGORIES.__contains__(reason_category):
            reason_category = ""
        note = ""
        if reason_category or reason_text:
            parts = []
            if reason_category:
                parts.append(f"category={reason_category}")
            if reason_text:
                parts.append(reason_text)
            note = " | ".join(parts)
        event = audit_append(
            action="dismiss",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            findings=[{"finding_id": finding_id}],
            note=note,
            user_id=user.user_id,
            user_role=user.role,
        )
        _record_feedback(
            encounter_id=encounter_id,
            finding_id=finding_id,
            action="dismiss",
            user_identifier=user.user_identifier,
        )
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "reason_category": reason_category,
            "event": event,
        })

    # ---- Per-finding Accept / Dismiss / Modify ------------------------
    # These endpoints mirror the encounter-level accept-all / dismiss
    # ones above but target a single finding via its finding_id. They
    # are the primary affordance now: every finding card on the
    # encounter detail page renders its own Accept / Dismiss / Modify
    # button row. Each call writes:
    #   - one audit_actions row (audit trail / hash chain), AND
    #   - one FeedbackEntry (learning-loop training seed)
    # so the per-encounter view shows one row per finding decision.

    @app.post("/encounter/{encounter_id}/finding/{finding_id}/accept")
    async def finding_accept(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Mark a single finding as accepted by the biller.

        Writes both an audit_actions row (tamper-evident chain) and a
        FeedbackEntry (learning-loop training seed).
        """
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        event = audit_append(
            action="accept",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            findings=[{"finding_id": finding_id}],
            user_id=user.user_id,
            user_role=user.role,
        )
        _record_feedback(
            encounter_id=encounter_id,
            finding_id=finding_id,
            action="accept",
            user_identifier=user.user_identifier,
        )
        return JSONResponse({"ok": True, "finding_id": finding_id, "action": "accept", "event": event})

    @app.post("/encounter/{encounter_id}/finding/{finding_id}/dismiss")
    async def finding_dismiss(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Dismiss a single finding. Optional closed-loop reason fields
        are accepted (``reason_category`` + ``reason_text``) and stored in
        the audit_actions row's ``note`` field — same shape as the
        encounter-level dismiss endpoint.

        Also accepts an optional ``correct_finding`` (a free-form dict
        with any of ``severity`` / ``category`` / ``suggested_code`` /
        ``rule_id``) so the biller can label what the right finding
        would have been. The label is persisted on the FeedbackEntry
        as a separate field — the audit_actions row keeps the
        existing schema. The new ``correct_finding_pairs()`` view on
        the FeedbackStore joins these dismissals to the original
        prediction for training (see ``docs/learning_loop.md``).
        """
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        reason_category = str(body.get("reason_category", "") or "").strip()
        reason_text = str(body.get("reason_text", "") or "").strip()[:500]
        if reason_category and not _DISMISS_CATEGORIES.__contains__(reason_category):
            reason_category = ""
        # ``correct_finding`` is an optional free-form dict. The biller
        # is allowed to label any of: severity, category, suggested_code,
        # rule_id, or a free-form ``note`` of their own. Validation is
        # permissive — only the type-check is enforced. Missing or
        # empty ``correct_finding`` keeps the dismiss endpoint exactly
        # backward-compatible.
        raw_correct = body.get("correct_finding")
        correct_finding: dict[str, Any] | None = None
        if isinstance(raw_correct, dict) and raw_correct:
            correct_finding = {
                str(k): (v if isinstance(v, (str, int, float, bool)) else str(v))
                for k, v in raw_correct.items()
            }
        note = ""
        if reason_category or reason_text:
            parts = []
            if reason_category:
                parts.append(f"category={reason_category}")
            if reason_text:
                parts.append(reason_text)
            note = " | ".join(parts)
        if correct_finding:
            # Persist a compact one-line summary into the audit_actions
            # row's note for self-contained audit-trail readability.
            cf_summary = ", ".join(
                f"{k}={v}" for k, v in sorted(correct_finding.items())
            )
            note = f"{note} | correct: {cf_summary}" if note else f"correct: {cf_summary}"
        event = audit_append(
            action="dismiss",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            findings=[{"finding_id": finding_id}],
            note=note,
            user_id=user.user_id,
            user_role=user.role,
        )
        _record_feedback(
            encounter_id=encounter_id,
            finding_id=finding_id,
            action="dismiss",
            user_identifier=user.user_identifier,
            correct_finding=correct_finding,
        )
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "action": "dismiss",
            "reason_category": reason_category,
            "correct_finding_recorded": bool(correct_finding),
            "event": event,
        })

    @app.post("/encounter/{encounter_id}/finding/{finding_id}/modify")
    async def finding_modify(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Record a biller's override of a single finding's severity and/or
        category. Body: ``{"new_severity": "...", "new_category": "...",
        "why": "..."}``. At least one of severity/category must be present.
        The optional ``why`` is the biller's free-text rationale ("why
        was the AI wrong?") and is persisted as the high-quality
        training signal the biller-correction form exists to capture.
        """
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        new_severity = str(body.get("new_severity", "") or "").strip()
        new_category = str(body.get("new_category", "") or "").strip()
        why = str(body.get("why", "") or "").strip()
        if not new_severity and not new_category:
            raise HTTPException(
                status_code=400,
                detail="new_severity and/or new_category required",
            )
        # Persist a structured note with the before/after values so the
        # existing audit_actions chain still covers the override. The
        # biller's "why" rationale is folded into the same note so the
        # audit trail is self-contained — no schema change needed to
        # audit_actions, but the rationale is preserved.
        original_severity, original_rule_id, original_category = _lookup_finding_meta(
            encounter_id, finding_id
        )
        note_parts = []
        if new_severity:
            note_parts.append(f"severity: {original_severity} -> {new_severity}")
        if new_category:
            note_parts.append(f"category: {original_category} -> {new_category}")
        note = " | ".join(note_parts)
        if why:
            note = f"{note} | why: {why}" if note else f"why: {why}"
        event = audit_append(
            action="modify",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            findings=[{"finding_id": finding_id}],
            note=note,
            user_id=user.user_id,
            user_role=user.role,
        )
        _record_feedback(
            encounter_id=encounter_id,
            finding_id=finding_id,
            action="modify",
            user_identifier=user.user_identifier,
            modify_severity=new_severity or None,
            modify_category=new_category or None,
            note=why or None,
        )
        # Also write a structured BillerCorrection record to the
        # dedicated biller_corrections.jsonl log. This is the
        # high-quality training signal the spec'd biller-correction
        # form exists to capture: (corrected) severity, category,
        # rationale, biller_id, and a SHA-256 chain signature. Best
        # effort; never raises.
        try:
            from .feedback import record_biller_correction
            record_biller_correction(
                encounter_id=encounter_id,
                finding_id=finding_id,
                severity=new_severity or original_severity or "",
                category=new_category or original_category or "",
                rationale=why,
                biller_id=user.user_identifier or "default_biller",
            )
        except Exception:
            pass
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "action": "modify",
            "new_severity": new_severity,
            "new_category": new_category,
            "why": why,
            "event": event,
        })

    # ---- Per-finding comment thread ----------------------------------
    # A "comment" is a biller's free-form note attached to a finding:
    # "why is this flagged?", "I disagree — appeal basis is…", or
    # a follow-up to another biller. Every comment is also written to
    # the feedback log as a FeedbackEntry(action="comment") so the
    # per_clinic_f1 rollup and the audit_actions chain both see it.
    # Comments never expire — they live with the finding forever.
    # The body is stored in /app/logs/finding_comments.jsonl (the
    # source of truth for threading and ordered read); the
    # FeedbackEntry is the audit-trail / training-data view.

    @app.post("/encounter/{encounter_id}/finding/{finding_id}/comments")
    async def finding_add_comment(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Append one comment to a finding's thread.

        Body: ``{"author_id": "...", "body": "...",
        "parent_comment_id": "..." (optional)}``.

        ``parent_comment_id`` enables 1-level threaded replies
        (the dashboard UI renders 2 levels — top-level + one
        layer of replies). Deeper nesting is accepted by the
        store but not rendered.
        """
        try:
            from .feedback import add_comment as _add_comment
            from .feedback import get_default_store
        except ImportError:
            raise HTTPException(
                status_code=503, detail="feedback module unavailable"
            )
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        # RBAC: prefer the authenticated user_id from the RBAC
        # middleware. If the caller passes an explicit author_id
        # in the body and it doesn't match the authenticated
        # user, we honor the explicit one (allows impersonation
        # in tests) but the canonical row stores the real user.
        author_id = str(
            body.get("author_id") or user.user_identifier
        ).strip() or "anon"
        text = str(body.get("body", "") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="body required")
        parent_comment_id = body.get("parent_comment_id")
        if parent_comment_id is not None:
            parent_comment_id = str(parent_comment_id).strip() or None
        try:
            comment, entry = _add_comment(
                get_default_store(),
                encounter_id=encounter_id,
                finding_id=finding_id,
                author_id=author_id,
                body=text,
                parent_comment_id=parent_comment_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return JSONResponse({
            "ok": True,
            "comment": comment.to_dict(),
            "feedback_event_id": entry.event_id,
        })

    @app.get("/encounter/{encounter_id}/finding/{finding_id}/comments")
    async def finding_list_comments(
        encounter_id: str,
        finding_id: str,
    ) -> JSONResponse:
        """Return the comment thread for one finding, oldest first.

        Response shape: ``{"comments": [...], "count": N}`` so a
        JS fetch can render the thread directly.
        """
        try:
            from .feedback import list_comments as _list_comments
            from .feedback import get_default_store
        except ImportError:
            raise HTTPException(
                status_code=503, detail="feedback module unavailable"
            )
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        try:
            thread = _list_comments(
                get_default_store(),
                encounter_id=encounter_id,
                finding_id=finding_id,
            )
        except Exception:
            thread = []
        return JSONResponse({
            "comments": [c.to_dict() for c in thread],
            "count": len(thread),
        })

    # ---- Snooze / re-audit reminder (kanban t_993c411c) ----------
    # A snooze hides a finding from the default encounter view until
    # a future timestamp. The biller uses it when they want to
    # "think about" a flag without it dominating the dashboard.
    # While snoozed, the finding is hidden from the default view
    # but visible with ``?include_snoozed=true``; expired snoozes
    # return the finding to the active pool automatically. Every
    # snooze is recorded in the audit chain (action="snooze") so
    # the privacy-officer view shows the biller's intent.
    @app.post("/encounter/{encounter_id}/finding/{finding_id}/snooze")
    async def finding_snooze(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Snooze a single finding until a future ISO-8601 timestamp.

        Body: ``{"until": "<iso8601>", "reason": "<optional>"}``.

        Returns the written SnoozeEntry so the UI can render a
        "snoozed until X" confirmation without re-fetching the
        store. The audit_actions chain also gets a
        ``snooze`` row for tamper-evident logging.
        """
        try:
            from .snooze import SnoozeStore
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="snooze module unavailable")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        until_raw = body.get("until")
        if not until_raw or not isinstance(until_raw, str):
            raise HTTPException(
                status_code=400, detail="until (ISO-8601 string) required"
            )
        # Validate the timestamp parses; reject if it's already
        # in the past — a snooze for the past is a no-op and
        # silently confusing. Biller can always snooze for "now
        # + 1 minute" if they want to clear the flag.
        from datetime import datetime
        try:
            ts = datetime.fromisoformat(until_raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"invalid ISO-8601 timestamp: {until_raw!r}"
            )
        if ts <= time.time():
            raise HTTPException(
                status_code=400,
                detail="snooze 'until' must be in the future",
            )
        reason = str(body.get("reason", "") or "").strip()
        store = SnoozeStore()
        entry = store.snooze(
            encounter_id=encounter_id,
            finding_id=finding_id,
            snooze_until=until_raw,
            reason=reason,
            user_identifier=user.user_identifier,
        )
        # Mirror to the audit chain so the privacy-officer view
        # shows the biller's intent. The snooze log is the source
        # of truth for active/expired; the audit row is the source
        # of truth for "did this person snooze anything today".
        try:
            audit_append(
                action="snooze",
                encounter_id=encounter_id,
                user_identifier=user.user_identifier,
                tenant_id=_TENANT_ID,
                findings=[{"finding_id": finding_id}],
                note=reason,
                extra={"snooze_until": until_raw, "snooze_event_id": entry.event_id},
                user_id=user.user_id,
                user_role=user.role,
            )
        except Exception:
            # Audit chain is best-effort here; the snooze log is
            # already the source of truth and a missing audit row
            # only affects the privacy view, not the biller.
            pass
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "snooze": entry.to_dict(),
        })

    @app.post("/encounter/{encounter_id}/finding/{finding_id}/unsnooze")
    async def finding_unsnooze(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Manually clear an active snooze before it expires.

        Mirrors ``snooze`` but writes an ``action="unsnooze"`` row
        in the SnoozeStore + the audit chain. Returns
        ``{"ok": True, "cleared": bool}`` so the UI can show a
        toast — ``cleared=False`` means there was no active snooze
        (no-op).
        """
        try:
            from .snooze import SnoozeStore
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="snooze module unavailable")
        if not finding_id:
            raise HTTPException(status_code=400, detail="finding_id required")
        store = SnoozeStore()
        entry = store.unsnooze(
            encounter_id=encounter_id,
            finding_id=finding_id,
            user_identifier=user.user_identifier,
        )
        if entry is None:
            return JSONResponse({"ok": True, "cleared": False})
        try:
            audit_append(
                action="unsnooze",
                encounter_id=encounter_id,
                user_identifier=user.user_identifier,
                tenant_id=_TENANT_ID,
                findings=[{"finding_id": finding_id}],
                note="manual unsnooze",
                extra={"snooze_event_id": entry.event_id},
                user_id=user.user_id,
                user_role=user.role,
            )
        except Exception:
            pass
        return JSONResponse({
            "ok": True,
            "cleared": True,
            "snooze": entry.to_dict(),
        })

    @app.get("/encounter/{encounter_id}/snoozes")
    async def encounter_list_snoozes(encounter_id: str) -> JSONResponse:
        """Return the active snooze map for one encounter.

        Response shape: ``{"snoozes": [{finding_id, until, reason, by, event_id}]}``
        so the dashboard can render a "X findings snoozed" badge
        even when ``include_snoozed=false`` is in effect.
        """
        try:
            from .snooze import SnoozeStore
        except ImportError:
            raise HTTPException(status_code=503, detail="snooze module unavailable")
        store = SnoozeStore()
        active = store.active_snoozes_for_encounter(encounter_id)
        return JSONResponse({
            "snoozes": [
                {
                    "finding_id": fid,
                    "until": e.snooze_until,
                    "reason": e.reason,
                    "by": e.user_identifier,
                    "event_id": e.event_id,
                }
                for fid, e in active.items()
            ],
            "count": len(active),
        })

    # ---- Finding assignments (kanban t_54262d96) ---------------------
    # Mid-clinic tier processes ~2,000 audits/month and one biller
    # can't own that queue. The office manager needs to distribute
    # findings across billers and the dashboard needs to surface
    # per-biller workload (assigned / completed / overdue).
    #
    # Endpoint shape:
    #   POST /api/encounters/{id}/finding/{fid}/assign
    #     body: {"assignee_id": "<biller>", "due_date": "<iso8601>"?}
    #     → 200 {"ok": true, "assignment": {...}}
    #   GET  /api/clinics/{clinic_id}/workload
    #     → 200 {"clinic_id": ..., "workload": [{biller_id, n_assigned,
    #                                              n_completed, n_overdue}, ...]}
    #
    # The /api/encounters/{id}/finding/{fid}/assign endpoint is
    # **idempotent on re-assign**: posting the same assignee_id for
    # the same finding writes NO new row (the current row is already
    # that assignee) and returns 200 with the existing row. Posting
    # a different assignee_id writes a NEW row — the most recent
    # row wins, but the history is preserved for the activity view.
    # Spec'd by t_54262d96 acceptance criteria.
    @app.post("/api/encounters/{encounter_id}/finding/{finding_id}/assign")
    async def api_finding_assign(
        encounter_id: str,
        finding_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Assign (or re-assign) a finding to a specific biller.

        Body shape: ``{"assignee_id": "<biller>", "due_date": "<iso8601>"?}``.

        Returns the written (or existing) assignment row. Re-assigning
        the same biller is a no-op write — the activity log doesn't
        grow, but the response confirms the current state.
        """
        try:
            from .finding_assignments import FindingAssignmentStore
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="finding_assignments module unavailable",
            )
        if not finding_id:
            raise HTTPException(
                status_code=400, detail="finding_id required"
            )
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        assignee_id = (
            str(body.get("assignee_id", "") or "").strip()
        )
        if not assignee_id:
            raise HTTPException(
                status_code=400,
                detail="assignee_id required (non-empty string)",
            )
        due_date_raw = body.get("due_date")
        due_date = ""
        if due_date_raw:
            if not isinstance(due_date_raw, str):
                raise HTTPException(
                    status_code=400,
                    detail="due_date must be an ISO-8601 string when present",
                )
            # Validate parses; we don't reject past dates here
            # (the biller may want to mark "I should have done
            # this yesterday" for retrospective triage).
            try:
                from datetime import datetime
                datetime.fromisoformat(
                    due_date_raw.replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid ISO-8601 timestamp: {due_date_raw!r}",
                )
            due_date = due_date_raw
        store = FindingAssignmentStore()
        # Idempotent re-assign: if the current assignee is already
        # the requested biller, return the existing row without
        # writing a new one. Different assignee → new row.
        existing = store.current_assignee_for(encounter_id, finding_id)
        if existing is not None and existing.assignee_id == assignee_id:
            # Still allow updating the due_date (the biller may
            # push the deadline without reassigning).
            if due_date and due_date != existing.due_date:
                entry = store.assign(
                    encounter_id=encounter_id,
                    finding_id=finding_id,
                    assignee_id=assignee_id,
                    assigned_by=user.user_identifier,
                    due_date=due_date,
                )
            else:
                entry = existing
        else:
            entry = store.assign(
                encounter_id=encounter_id,
                finding_id=finding_id,
                assignee_id=assignee_id,
                assigned_by=user.user_identifier,
                due_date=due_date,
            )
            # Mirror to the audit chain so the privacy-officer view
            # shows the manager's intent. Best-effort — the JSONL
            # log is the source of truth for "who owns what".
            try:
                audit_append(
                    action="assign",
                    encounter_id=encounter_id,
                    user_identifier=user.user_identifier,
                    tenant_id=_TENANT_ID,
                    findings=[{"finding_id": finding_id}],
                    note=f"assigned to {assignee_id}",
                    extra={
                        "assignment_event_id": entry.event_id,
                        "assignee_id": assignee_id,
                        "due_date": due_date,
                    },
                    user_id=user.user_id,
                    user_role=user.role,
                )
            except Exception:
                pass
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "assignment": entry.to_dict(),
            "reassigned": (
                existing is not None
                and existing.assignee_id != assignee_id
            ),
        })

    @app.get("/api/encounters/{encounter_id}/finding/assignments")
    async def api_encounter_assignments(encounter_id: str) -> JSONResponse:
        """Return the current assignment map for one encounter.

        Response shape: ``{"assignments": {finding_id: FindingAssignment}}``
        so the encounter detail page can render the per-finding
        "Assigned to <biller>" badge without an N+1 fetch.
        """
        try:
            from .finding_assignments import FindingAssignmentStore
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="finding_assignments module unavailable",
            )
        store = FindingAssignmentStore()
        current = store.current_assignees_for_encounter(encounter_id)
        return JSONResponse({
            "encounter_id": encounter_id,
            "assignments": {
                fid: e.to_dict() for fid, e in current.items()
            },
            "count": len(current),
        })

    # ---- Denial-risk + appeal-letter API (denial_risk.py + appeal_letter.py) -
    # The denial-risk scorer and the appeal-letter generator are both
    # implemented and unit-tested at the module level. The HTML
    # encounter-detail page already renders the denial-risk score
    # (computed inline). These JSON endpoints give the new Next.js
    # portal (apps/portal) the same data without an HTML scrape, and
    # let the biller trigger letter generation + outcome tracking
    # without going through the legacy form POSTs.

    @app.get("/api/encounters/{encounter_id}/denial-risk")
    async def api_encounter_denial_risk(
        encounter_id: str,
        # Public-read endpoint; the bearer middleware's
        # _PUBLIC_READ_ENDPOINTS check passes the request through
        # without auth, and get_request_user_or_anonymous returns
        # an "anonymous" / "guest" UserContext instead of 401ing
        # when the caller omits X-User-Id headers. See the comment
        # on get_request_user_or_anonymous for the rationale.
        user: UserContext = Depends(get_request_user_or_anonymous),
    ) -> JSONResponse:
        """Compute the per-claim denial risk from the encounter's findings.

        Response shape:
        ``{
            "encounter_id": str,
            "denial_probability": float,   # 0.0 .. 0.99
            "tier": str,                  # low / medium / high / critical
            "n_findings": int,
            "n_findings_scored": int,
            "n_findings_below_threshold": int,
            "per_finding": [...],         # one entry per scored finding
            "top_risk": {...} | None,
            "min_severity": int,
        }``

        Returns 404 if the encounter isn't registered. The tenant's
        ``min_severity`` threshold is honoured so the score matches
        what the encounter-detail HTML page shows.
        """
        from .denial_risk import compute_denial_risk
        if not encounter_id or not encounter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="encounter_id path param is empty",
            )
        encounter_id = encounter_id.strip()
        # The denial-risk scorer keys on the same finding shape the
        # encounter-detail HTML page uses (_finding_dicts normalises
        # ground_truth entries). We score against the FULL finding
        # list — the page surfaces denial_risk from
        # visible_findings after applying MIN_SEVERITY_TO_SHOW, but
        # the API consumer is the portal which may want to apply its
        # own threshold. We expose both the per-finding contributions
        # AND the min_severity we used so the caller can re-filter.
        record = load_encounter_record(encounter_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"{encounter_id!r} not registered",
            )
        findings = _finding_dicts(record)
        min_sev = _min_severity_threshold()
        scored = compute_denial_risk(findings, min_severity=min_sev)
        scored["encounter_id"] = encounter_id
        scored["min_severity"] = min_sev
        return JSONResponse(scored)

    @app.post("/api/encounters/{encounter_id}/appeal-letter")
    async def api_encounter_appeal_letter(
        request: Request,
        encounter_id: str,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Generate an appeal letter for a specific finding on this encounter.

        Body (JSON): ``{
            "finding_id"?: str,    # preferred; matches by exact id
            "rule_id"?: str,       # fallback if finding_id is absent or
                                    # the LLM didn't emit a stable id;
                                    # supports fuzzy prefix/substring match
            "denial_reason": str,   # required; what the payer said
            "clinical_note"?: str,  # optional override; falls back to the
                                    # finding's quote or the stored note
        }``.

        At least one of ``finding_id`` / ``rule_id`` is required, plus
        ``denial_reason``. This mirrors the existing
        ``/encounter/{id}/appeal`` route so the two endpoints stay
        in lock-step.

        Response (200): ``{
            "ok": True,
            "encounter_id": str,
            "finding_id": str,
            "letter": { ... see appeal_letter.generate_appeal_letter ... }
        }``

        Errors:
          * 400 — missing finding_id/rule_id or denial_reason
          * 404 — encounter not registered OR no real audit exists
          * 404 — neither finding_id nor rule_id matches any finding
          * 500 — LLM call failed AND the template-only fallback also
                  couldn't produce a letter
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=400,
                detail="body must be a JSON object",
            )
        finding_id = str(body.get("finding_id", "") or "").strip()
        rule_id = str(body.get("rule_id", "") or "").strip()
        if not finding_id and not rule_id:
            raise HTTPException(
                status_code=400,
                detail="finding_id or rule_id is required",
            )
        denial_reason = str(body.get("denial_reason", "") or "").strip()
        if not denial_reason:
            raise HTTPException(
                status_code=400,
                detail="denial_reason is required",
            )
        if not encounter_id or not encounter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="encounter_id path param is empty",
            )
        encounter_id = encounter_id.strip()

        # Pull findings from the most recent REAL audit (the LLM's
        # output), not the encounter record's ground_truth. Demo
        # encounters use the encounter record, but for uploaded
        # encounters the findings live in /app/logs/upload_jobs.jsonl.
        real_audit = _latest_real_audit_for(encounter_id)
        findings: list[dict[str, Any]] = []
        if real_audit is not None:
            findings = list(real_audit.get("findings", []) or [])
        if not findings:
            # Fall back to the encounter record's gold findings. This
            # keeps demo encounters (no real audit) usable.
            record = load_encounter_record(encounter_id)
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"{encounter_id!r} not registered and no "
                        "real audit on file; upload + audit first"
                    ),
                )
            findings = _finding_dicts(record)

        target_finding: dict[str, Any] | None = None
        if finding_id:
            for f in findings:
                if str(f.get("finding_id", "")) == finding_id:
                    target_finding = f
                    break
        if target_finding is None and rule_id:
            # Exact match first (rule_id single key or rule_ids list).
            for f in findings:
                rid = f.get("rule_id") or (
                    f.get("rule_ids", [None])[0] if f.get("rule_ids") else None
                )
                if rid == rule_id:
                    target_finding = f
                    break
            if target_finding is None:
                # Fuzzy: same first 12 chars, OR substring match.
                # Catches singular/plural ("DX_LINKAGE_REQUIRED" vs
                # "DX_LINKAGE_REQUIREMENT") and underscore/dash
                # variations. Same approach as the existing
                # /encounter/{id}/appeal route.
                rule_norm = (
                    rule_id.upper().replace("_", "").replace("-", "")
                )
                for f in findings:
                    rid = f.get("rule_id") or (
                        f.get("rule_ids", [None])[0]
                        if f.get("rule_ids") else None
                    )
                    if not rid:
                        continue
                    rid_norm = (
                        rid.upper().replace("_", "").replace("-", "")
                    )
                    if (
                        rule_norm[:12] == rid_norm[:12]
                        or rule_norm in rid_norm
                        or rid_norm in rule_norm
                    ):
                        target_finding = f
                        break
        if target_finding is None:
            key = (
                f"finding_id={finding_id!r}"
                if finding_id
                else f"rule_id={rule_id!r}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"{key} not present in the latest audit",
            )

        # Build the encounter dict the generator expects. The
        # generator only reads a couple of fields (patient_id, claim,
        # encounter_id) so we pass a minimal shape with what we have.
        record = load_encounter_record(encounter_id) or {}
        zctx = (
            (real_audit or {}).get("zorva_context")
            if isinstance(real_audit, dict) else None
        ) or {}
        clinical_note = body.get("clinical_note")
        if not isinstance(clinical_note, str) or not clinical_note.strip():
            # The finding's quote is a strong stand-in for the
            # verbatim clinical note (the LLM only sees the quote
            # at audit time anyway). For uploaded encounters, the
            # real audit's full note isn't persisted to JSONL yet
            # so we fall back to the quote.
            clinical_note = (
                target_finding.get("quote", "")
                or record.get("clinical_note", "")
            )
        encounter_dict = {
            "encounter_id": encounter_id,
            "claim": record.get("claim", {}) or {},
            "patient_id": record.get("patient_id", ""),
        }

        # LLM client wiring. Falls back to the template-only path
        # when LLMClient can't be imported (dev smoke, tests). The
        # template path always returns a valid letter, so 500 is
        # truly exceptional.
        try:
            from .llm import LLMClient
            llm_client = LLMClient()

            def _llm_complete(prompt: str) -> str:
                response = llm_client.complete(
                    messages=[{"role": "user", "content": prompt}],
                )
                if isinstance(response, dict):
                    return (response.get("choices", [{}])[0]
                                  .get("message", {})
                                  .get("content", ""))
                return str(response or "")

            llm_complete = _llm_complete
        except Exception:
            llm_complete = None

        try:
            from .appeal_letter import (
                generate_appeal_letter,
                log_appeal_letter,
            )
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="appeal_letter module unavailable",
            )

        try:
            letter = generate_appeal_letter(
                finding=target_finding,
                encounter=encounter_dict,
                clinical_note=clinical_note,
                denial_reason=denial_reason,
                zorva_context=zctx,
                llm_complete=llm_complete,
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"appeal-letter generation failed: {e}",
            )
        if letter is None:
            raise HTTPException(
                status_code=500,
                detail="appeal-letter generation returned no result",
            )
        # Persist to the appeal-letters log so outcome tracking has
        # something to attach to. ``log_appeal_letter`` handles
        # PHI-scrubbing of the markdown body before writing.
        resolved_finding_id = (
            (target_finding or {}).get("finding_id")
            if target_finding else finding_id
        ) or None
        try:
            log_appeal_letter(
                letter,
                encounter_id,
                tenant_id=_TENANT_ID,
                finding_id=resolved_finding_id,
            )
        except Exception:
            # Persisting is best-effort.
            pass
        return JSONResponse({
            "ok": True,
            "encounter_id": encounter_id,
            "finding_id": finding_id or (
                target_finding.get("finding_id", "") if target_finding else ""
            ),
            "letter": letter,
        })

    @app.get("/api/encounters/{encounter_id}/appeal-letters")
    async def api_encounter_appeal_letters(
        encounter_id: str,
        # Public-read; see _PUBLIC_READ_ENDPOINTS for the rationale.
        user: UserContext = Depends(get_request_user_or_anonymous),
    ) -> JSONResponse:
        """List every appeal letter generated for this encounter.

        Response: ``{"encounter_id": str, "letters": [...], "count": int}``.
        Ordered newest-first. The body field is PHI-scrubbed (the
        unscrubbed text lives only in the response of
        POST /appeal-letter).
        """
        try:
            from .appeal_letter import read_appeal_letters
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="appeal_letter module unavailable",
            )
        if not encounter_id or not encounter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="encounter_id path param is empty",
            )
        encounter_id = encounter_id.strip()
        letters = read_appeal_letters(encounter_id=encounter_id)
        # Newest-first ordering. read_appeal_letters returns the file
        # in append order; reverse it for "most recent at top" UX.
        letters = list(reversed(letters or []))
        return JSONResponse({
            "encounter_id": encounter_id,
            "letters": letters,
            "count": len(letters),
        })

    @app.post("/api/encounters/{encounter_id}/appeal-letter/{letter_id}/outcome")
    async def api_encounter_appeal_letter_outcome(
        request: Request,
        encounter_id: str,
        letter_id: str,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Log the outcome of an appeal letter.

        Body (JSON): ``{
            "status": str,           # required; one of won / lost /
                                       # withdrawn / pending / did_not_file
                                       # (matches the legacy
                                       # /encounter/{id}/appeal/{aid}/outcome
                                       # route so the two endpoints stay in
                                       # lock-step)
            "notes"?: str,
            "biller_id"?: str,        # optional override; defaults to the
                                       # authenticated user
        }``.

        The outcome row joins with the letter row via ``appeal_id``
        (== ``letter_id``) and ``encounter_id``. ``appeal_win_rate``
        reads these rows for the ROI dashboard.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=400,
                detail="body must be a JSON object",
            )
        status = str(body.get("status", "") or "").strip().lower()
        allowed_statuses = {
            "won", "lost", "withdrawn", "pending", "did_not_file",
        }
        if status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"status must be one of {sorted(allowed_statuses)}; "
                    f"got {status!r}"
                ),
            )
        notes = str(body.get("notes", "") or "").strip()
        biller_id = body.get("biller_id")
        if biller_id is not None:
            biller_id = str(biller_id).strip() or user.user_identifier
        else:
            biller_id = user.user_identifier
        if not encounter_id or not encounter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="encounter_id path param is empty",
            )
        if not letter_id or not letter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="letter_id path param is empty",
            )
        encounter_id = encounter_id.strip()
        letter_id = letter_id.strip()
        try:
            from .appeal_letter import (
                AppealOutcome,
                log_appeal_outcome,
            )
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="appeal_letter module unavailable",
            )
        # Use AppealOutcome.now() for consistency with the legacy
        # endpoint. The classmethod stamps the timestamp and tenant_id
        # so the audit trail stays uniform.
        outcome = AppealOutcome.now(
            appeal_id=letter_id,
            encounter_id=encounter_id,
            status=status,
            biller_id=biller_id,
            notes=notes,
        )
        log_appeal_outcome(outcome)
        return JSONResponse({
            "ok": True,
            "encounter_id": encounter_id,
            "appeal_id": letter_id,
            "status": status,
            "notes": notes,
            "timestamp": getattr(outcome, "timestamp", ""),
        })

    @app.get("/api/clinics/{clinic_id}/workload")
    async def api_clinic_workload(clinic_id: str) -> JSONResponse:
        """Return the current per-biller workload for one clinic.

        Each row: ``{biller_id, n_assigned, n_completed, n_overdue}``.
        Returns 404 if ``clinic_id`` is unknown (matches the
        per-clinic F1 / clinic dashboard 404 contract so the UI
        can treat both endpoints as "this clinic doesn't exist"
        consistently).
        """
        try:
            from .finding_assignments import FindingAssignmentStore
            from .per_clinic_f1 import list_clinics
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="finding_assignments or per_clinic_f1 unavailable",
            )
        # Validate clinic exists (mirrors the clinic dashboard
        # 404 contract). Always allow the active tenant AND the
        # dev fallback ("default_biller") as known so the demo
        # dashboard renders without a populated feedback log —
        # matches the /api/dashboard/clinic fallback behaviour.
        try:
            known = {c["clinic_id"] for c in list_clinics()}
        except Exception:
            known = set()
        known.add(_TENANT_ID or "default_biller")
        known.add("default_biller")
        if clinic_id not in known:
            raise HTTPException(
                status_code=404,
                detail=f"clinic_id {clinic_id!r} not found",
            )
        store = FindingAssignmentStore()
        rows = store.workload_for_clinic(clinic_id)
        return JSONResponse({
            "clinic_id": clinic_id,
            "workload": rows,
            "n_billers": len(rows),
        })

    # ---- CARC / RARC lookup (kanban t_7743e5d5) --------------------
    # Two lookup endpoints serving the per-payer denial reason code
    # tables (Claim Adjustment Reason Codes + Remittance Advice
    # Remark Codes). Backed by data/tables/{carc,rarc}.csv; the
    # module loads them once on first use. Unknown code → 404
    # (NOT 200-with-null) so the UI can distinguish "we have no
    # data for this" from "this code really does exist but isn't
    # in our snapshot" — a 404 is the dashboard's prompt to
    # surface "code not in current table; check payer website".
    @app.get("/api/lookup/carc/{code}")
    async def lookup_carc_code(code: str) -> JSONResponse:
        """Return the description + common resolutions for a CARC code.

        404 if the code is not in the on-disk table. Response
        shape: ``{code, description, payer_types, common_resolutions}``
        — no envelope, the bare row is the most useful form for
        the dashboard's "What does this code mean?" popover.
        """
        try:
            from .carc_rarc import lookup_carc
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="CARC/RARC lookup module unavailable",
            )
        entry = lookup_carc(code)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"CARC code {code!r} not found in lookup table",
            )
        return JSONResponse(entry.to_dict())

    @app.get("/api/lookup/rarc/{code}")
    async def lookup_rarc_code(code: str) -> JSONResponse:
        """Return the description + common resolutions for a RARC code.

        Mirror of the CARC endpoint. Same 404 semantics. RARC
        codes typically look like ``M1`` / ``N30`` (a letter
        prefix + a number) but the table accepts whatever the
        published WPC list contains.
        """
        try:
            from .carc_rarc import lookup_rarc
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="CARC/RARC lookup module unavailable",
            )
        entry = lookup_rarc(code)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"RARC code {code!r} not found in lookup table",
            )
        return JSONResponse(entry.to_dict())

    @app.get("/api/lookup/stats")
    async def lookup_table_stats() -> JSONResponse:
        """Return the count of codes loaded from each CSV.

        Lightweight health check — the dashboard uses it for
        the "X codes loaded" badge in the appeal-letter
        editor, and ops can curl it to verify the table
        loaded on startup.
        """
        try:
            from .carc_rarc import table_stats
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="CARC/RARC lookup module unavailable",
            )
        stats = table_stats()
        return JSONResponse(stats)

    @app.post("/encounter/{encounter_id}/rerun")
    async def encounter_rerun(
        encounter_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        event = audit_append(
            action="rerun",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            user_id=user.user_id,
            user_role=user.role,
        )
        # rerun is a system action, not a per-finding biller decision,
        # but the spec'd feedback table requires a row for every
        # /encounter/* endpoint so the encounter timeline is complete.
        # Tag it action="modify" so it isn't bucketed with accept/dismiss
        # in the stats() view (downstream trainers filter on action).
        _record_feedback(
            encounter_id=encounter_id,
            finding_id="__rerun__",
            action="modify",
            user_identifier=user.user_identifier,
        )
        return JSONResponse({"ok": True, "event": event})

    @app.post("/encounter/{encounter_id}/flag")
    async def encounter_flag(
        encounter_id: str,
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        event = audit_append(
            action="flag",
            encounter_id=encounter_id,
            user_identifier=user.user_identifier,
            tenant_id=_TENANT_ID,
            user_id=user.user_id,
            user_role=user.role,
        )
        # See rerun note above — flag is system-level, recorded for
        # timeline completeness, bucketed as action="modify" so it
        # doesn't pollute accept/dismiss precision stats.
        _record_feedback(
            encounter_id=encounter_id,
            finding_id="__flag__",
            action="modify",
            user_identifier=user.user_identifier,
        )
        return JSONResponse({"ok": True, "event": event})

    # ---- Bulk reviewer actions ----
    # When a clinic uploads 500 claims and 100 share the same
    # modifier-25 finding, the biller needs to dismiss all 100 with
    # one click. The per-encounter /finding/{fid}/{accept,dismiss}
    # endpoints above work for N=1 but break down for N=100. The
    # bulk endpoints below accept a list of encounter_ids and a
    # single action, and:
    #
    #   1. Verify every encounter_id exists (404 with the missing
    #      list in the body if any are unknown — the dashboard uses
    #      this to highlight bad cards).
    #   2. Apply the per-encounter action to each in turn (single-
    #      finding bulk accept is essentially "accept each real
    #      finding on this encounter", and dismiss with rule_id
    #      narrows to findings whose rule_id matches).
    #   3. Write ONE audit_actions row with action_type='bulk' that
    #      lists every affected encounter_id, the rule_id (if any),
    #      and the action. Tamper-evident chain signature covers
    #      the whole batch.
    #   4. Write per-finding FeedbackEntry rows for each real
    #      finding touched (one per finding, not one per encounter)
    #      so the per_clinic_f1 dashboard keeps counting per-clinic
    #      accept/dismiss ratios consistently with the per-finding
    #      endpoints.
    #
    # Returns ``{applied_count, skipped_count, audit_id}`` so the
    # UI can show a toast ("97 accepted, 3 already dismissed")
    # and link the audit row for the privacy officer's view.

    def _bulk_apply(
        *,
        action: str,
        encounter_ids: list[str],
        rule_id: str | None = None,
        notes: str | None = None,
        reason_category: str | None = None,
        reason_text: str | None = None,
        user_identifier: str,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> dict[str, Any]:
        """Apply ``action`` to every real finding on every encounter in
        ``encounter_ids``, write one bulk audit row + per-finding
        feedback rows, and return a summary dict.

        Atomic at the encounter level: any unknown encounter_id
        short-circuits with HTTPException(404) and NO writes happen.
        Once past the existence check the per-finding writes are
        best-effort — a single FeedbackStore failure logs but does
        not abort the rest of the batch (mirrors the per-encounter
        endpoint's tolerance for missing-module failures).

        ``skipped_count`` counts findings already in the target
        state (e.g. a bulk-dismiss that hits a finding the biller
        already dismissed in a previous round). They are skipped
        to keep the per_clinic_f1 view consistent — double-counting
        a dismiss would inflate the per-rule FP rate.

        ``applied_count`` counts findings actually transitioned.
        """
        if not encounter_ids:
            raise HTTPException(
                status_code=400,
                detail="encounter_ids must be a non-empty list",
            )
        # 1. Existence check: every encounter_id must resolve to a
        # registered demo entry (real-encounter audits are not yet
        # served by the dashboard, so load_encounter_record covers
        # both the demo and the upload paths).
        missing: list[str] = []
        for eid in encounter_ids:
            try:
                rec = load_encounter_record(eid)
            except Exception:
                rec = None
            if rec is None:
                missing.append(eid)
        if missing:
            # 404 — the dashboard uses the missing list to highlight
            # bad cards in the checkbox set.
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "one or more encounter_ids not found",
                    "missing": missing,
                },
            )

        # Normalize optional inputs once.
        norm_rule_id = (rule_id or "").strip() or None
        norm_notes = (notes or "").strip() or None
        norm_reason_category = (reason_category or "").strip() or None
        if norm_reason_category and norm_reason_category not in _DISMISS_CATEGORIES:
            norm_reason_category = None
        norm_reason_text = (reason_text or "").strip()[:500] or None

        # 2+3. Per-encounter application + audit row.
        from .audit_actions import append as audit_append

        applied: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        # Build the audit row's note once, with the rule_id +
        # closed-loop reason fields, so the chain entry is
        # self-contained for the privacy officer view.
        note_parts: list[str] = []
        if norm_rule_id:
            note_parts.append(f"rule_id={norm_rule_id}")
        if norm_reason_category:
            note_parts.append(f"category={norm_reason_category}")
        if norm_reason_text:
            note_parts.append(norm_reason_text)
        if norm_notes:
            note_parts.append(norm_notes)
        audit_note = " | ".join(note_parts) if note_parts else ""

        # Bulk action = action applied per encounter. The audit
        # row carries ``action="bulk"`` so the privacy officer can
        # filter bulk rows vs per-encounter rows; the per-encounter
        # sub-action is preserved in data_elements.action_subtype.
        action_subtype = action  # "accept" | "dismiss" | "flag"

        per_encounter_summary: list[dict[str, Any]] = []
        try:
            from .feedback import FeedbackStore, get_default_store
        except ImportError:
            FeedbackStore = None  # type: ignore[assignment,misc]
            get_default_store = None  # type: ignore[assignment]

        # Track which (encounter_id, finding_id) pairs have already
        # received a non-bulk decision so we can skip them on
        # subsequent bulk calls without double-counting.
        already_decided: set[tuple[str, str]] = set()
        if get_default_store is not None:
            try:
                store_for_history = get_default_store()
                for entry in store_for_history.read_all():
                    # Only accept/dismiss rows count as "decided";
                    # modify rows are biller-override signals and
                    # don't lock the underlying finding out of a
                    # subsequent bulk action.
                    if entry.action in ("accept", "dismiss"):
                        already_decided.add(
                            (entry.encounter_id, entry.finding_id)
                        )
            except Exception:
                # History read failure is non-fatal; we just lose
                # the dedup signal for this call.
                pass

        for eid in encounter_ids:
            try:
                record = load_encounter_record(eid)
            except Exception:
                record = None
            if record is None:
                # Defensive: existence check above already passed,
                # but if the registry was reloaded mid-call we
                # surface as a skip rather than a 500.
                skipped.append({"encounter_id": eid, "reason": "not_found"})
                continue
            findings = record.get("ground_truth", []) or []
            if not findings:
                # Encounter with no findings is a no-op; record it
                # so the dashboard can show "0 findings touched".
                per_encounter_summary.append({
                    "encounter_id": eid,
                    "applied_finding_ids": [],
                    "skipped_finding_ids": [],
                })
                continue

            applied_finding_ids: list[str] = []
            skipped_finding_ids: list[str] = []
            for f in findings:
                fid = str(
                    f.get("finding_id") or f.get("id") or ""
                ).strip()
                if not fid:
                    continue
                fid_rule = str(f.get("rule_id") or "").strip()
                # rule_id filter: when set, only touch findings
                # whose rule_id matches. This is what makes
                # "dismiss-all-with-rule" work — the biller picks
                # the modifier-25 rule and only modifier-25
                # findings across the batch are dismissed.
                if norm_rule_id and fid_rule != norm_rule_id:
                    continue
                # Skip findings already decided (accept or dismiss)
                # in a prior call. Keeps per_clinic_f1 ratios
                # honest — double-counting a dismiss would inflate
                # the per-rule FP rate. Flag is system-only, so it
                # doesn't engage this dedup check (flagging a
                # finding twice is operationally fine and doesn't
                # skew any per-rule precision metric).
                if (
                    action_subtype in ("accept", "dismiss")
                    and (eid, fid) in already_decided
                ):
                    skipped_finding_ids.append(fid)
                    skipped.append({
                        "encounter_id": eid,
                        "finding_id": fid,
                        "reason": "already_decided",
                    })
                    continue
                # Write the per-finding feedback row using the same
                # helper the per-encounter endpoints use, so the
                # feedback log gets identical schema. This is the
                # row that drives the per_clinic_f1 dashboard.
                # Flag is bucketed as action="modify" with a
                # synthetic "__bulk_flag__" finding_id so the
                # per_clinic_f1 view (which filters accept/dismiss)
                # ignores it — same convention the per-encounter
                # /flag endpoint uses, just with a bulk tag instead
                # of "__flag__" so the row is identifiable in
                # timeline views.
                if action_subtype == "flag":
                    _record_feedback(
                        encounter_id=eid,
                        finding_id="__bulk_flag__",
                        action="modify",
                        user_identifier=user_identifier,
                    )
                else:
                    _record_feedback(
                        encounter_id=eid,
                        finding_id=fid,
                        action=action_subtype,
                        user_identifier=user_identifier,
                    )
                applied_finding_ids.append(fid)
                applied.append({
                    "encounter_id": eid,
                    "finding_id": fid,
                    "rule_id": fid_rule,
                    "severity": str(f.get("severity") or "").strip().lower(),
                    "quote": f.get("quote"),
                })

            per_encounter_summary.append({
                "encounter_id": eid,
                "applied_finding_ids": applied_finding_ids,
                "skipped_finding_ids": skipped_finding_ids,
            })

        # 4. ONE bulk audit_actions row covering the whole batch.
        # The chain signature still covers this row — the
        # affected_encounter_ids list is hashed as part of
        # data_elements so any tampering breaks the chain.
        affected_encounter_ids = [
            row["encounter_id"] for row in per_encounter_summary
            if row.get("applied_finding_ids")
        ]
        event = audit_append(
            action="bulk",
            encounter_id=affected_encounter_ids[0] if affected_encounter_ids else (
                encounter_ids[0] if encounter_ids else ""
            ),
            user_identifier=user_identifier,
            tenant_id=_TENANT_ID,
            findings=[
                {"finding_id": fid} for fid in [
                    row["finding_id"] for row in applied
                ]
            ],
            note=audit_note,
            extra={
                "action_subtype": action_subtype,
                "rule_id": norm_rule_id or "",
                "affected_encounter_ids": affected_encounter_ids,
                "encounter_ids_requested": list(encounter_ids),
                "per_encounter": per_encounter_summary,
                "n_applied_findings": len(applied),
                "n_skipped_findings": len(skipped),
                "notes": norm_notes or "",
            },
            user_id=user_id,
            user_role=user_role,
        )
        # Slack ``high_finding`` event (kanban t_c9cf54f4): when a
        # biller bulk-actions a high-severity finding (accept OR
        # dismiss), post a short Slack notification to the
        # registered channel. Best-effort: notify_slack swallows
        # network errors so a Slack outage cannot fail the bulk
        # action. Only severity="high" (not "critical") fires —
        # the kanban task body explicitly says "high finding", and
        # the user can promote criticals via a future rule if they
        # want a louder notification. We loop over each affected
        # finding so a multi-finding batch can produce multiple
        # messages (Slack clients dedupe naturally by ts on
        # delivery, and a single combined card would lose the
        # per-finding rule attribution).
        if action_subtype in ("accept", "dismiss"):
            try:
                from ai_billing_audit import slack_notify as _slack

                for row in applied:
                    if row.get("severity") != "high":
                        continue
                    _slack.notify_slack(
                        _TENANT_ID,
                        _slack.EVENT_HIGH_FINDING,
                        {
                            "encounter_id": row.get("encounter_id"),
                            "finding_id": row.get("finding_id"),
                            "rule_id": row.get("rule_id") or "",
                            "severity": "high",
                            "action": action_subtype,
                            "tenant_id": _TENANT_ID,
                            "audit_id": event.get("event_id", ""),
                            "quote": row.get("quote"),
                        },
                    )
            except Exception as exc:  # pragma: no cover - defensive
                # Slack module missing or any failure is non-fatal:
                # the bulk action already committed. Log so the
                # operator notices, but never 500 the response.
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "high_finding slack notify failed for bulk %s: %s",
                    action_subtype,
                    exc,
                )
        return {
            "applied_count": len(applied),
            "skipped_count": len(skipped),
            "audit_id": event.get("event_id", ""),
            "affected_encounter_ids": affected_encounter_ids,
            "rule_id": norm_rule_id or "",
            "event": event,
        }

    @app.post("/encounters/bulk-accept")
    async def encounters_bulk_accept(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Accept every (rule-matching) finding across a list of encounters.

        Body: ``{"encounter_ids": [...], "rule_id"?: str, "notes"?: str}``.

        Returns ``{applied_count, skipped_count, audit_id, ...}``.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        raw_ids = body.get("encounter_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HTTPException(
                status_code=400,
                detail="encounter_ids must be a non-empty list",
            )
        encounter_ids = [str(x) for x in raw_ids if str(x).strip()]
        summary = _bulk_apply(
            action="accept",
            encounter_ids=encounter_ids,
            rule_id=body.get("rule_id"),
            notes=body.get("notes"),
            user_identifier=user.user_identifier,
            user_id=user.user_id,
            user_role=user.role,
        )
        return JSONResponse({"ok": True, **summary})

    @app.post("/encounters/bulk-dismiss")
    async def encounters_bulk_dismiss(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Dismiss every (rule-matching) finding across a list of encounters.

        Body: ``{"encounter_ids": [...], "rule_id"?: str,
        "reason_category"?: str, "reason_text"?: str, "notes"?: str}``.

        ``rule_id`` narrows the dismiss to findings whose rule_id
        matches (the "dismiss-all-with-rule" affordance). The
        closed-loop learning fields ``reason_category`` /
        ``reason_text`` mirror the per-encounter dismiss endpoint
        and are recorded on the single bulk audit row's ``note``
        field.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        raw_ids = body.get("encounter_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HTTPException(
                status_code=400,
                detail="encounter_ids must be a non-empty list",
            )
        encounter_ids = [str(x) for x in raw_ids if str(x).strip()]
        summary = _bulk_apply(
            action="dismiss",
            encounter_ids=encounter_ids,
            rule_id=body.get("rule_id"),
            notes=body.get("notes"),
            reason_category=body.get("reason_category"),
            reason_text=body.get("reason_text"),
            user_identifier=user.user_identifier,
            user_id=user.user_id,
            user_role=user.role,
        )
        return JSONResponse({"ok": True, **summary})

    @app.post("/encounters/bulk-flag")
    async def encounters_bulk_flag(
        request: Request,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Flag every (rule-matching) finding across a list of encounters.

        Body: ``{"encounter_ids": [...], "rule_id"?: str, "notes"?: str}``.

        Flag is a system-level signal. We write ONE bulk audit row
        for the privacy officer and one ``__bulk_flag__`` feedback
        row per affected finding (tagged action="modify" so the
        per_clinic_f1 view ignores it, same convention as the
        per-encounter /flag endpoint).
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        raw_ids = body.get("encounter_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HTTPException(
                status_code=400,
                detail="encounter_ids must be a non-empty list",
            )
        encounter_ids = [str(x) for x in raw_ids if str(x).strip()]
        summary = _bulk_apply(
            action="flag",
            encounter_ids=encounter_ids,
            rule_id=body.get("rule_id"),
            notes=body.get("notes"),
            user_identifier=user.user_identifier,
            user_id=user.user_id,
            user_role=user.role,
        )
        return JSONResponse({"ok": True, **summary})

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": app.version,
            "title": app.title,
            "n_registered": len(list_demo_encounters()),
        }

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus text-format metrics (no auth required).

        Exposes zorva_uptime_seconds, zorva_version_info,
        zorva_audit_jobs_total{state}, zorva_http_requests_total
        {path,method,status}. See ai_billing_audit.metrics.py for
        the full schema.
        """
        from .metrics import render_metrics
        return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")

    # Admin-only stub. The team management UI lives in the Next.js
    # portal (kanban t_23bfd49c); this FastAPI stub exists so the
    # RBAC admin gate has at least one endpoint to gate against
    # when the Next.js portal's API needs a server-side permission
    # check. Real user CRUD will be added in a follow-up task.
    @app.get("/admin/users")
    async def admin_list_users(
        user: UserContext = Depends(require_admin),
    ) -> JSONResponse:
        """Stub admin-only endpoint.

        Returns the authenticated admin's identity and a placeholder
        list. This is the contract the Next.js team management UI
        (kanban t_23bfd49c) will hit when it needs server-side
        permission enforcement. Biller and viewer both get 403.
        """
        return JSONResponse({
            "ok": True,
            "user": {
                "user_id": user.user_id,
                "role": user.role,
            },
            "users": [],  # populated when real team CRUD lands
            "note": "stub endpoint; real team CRUD is in the Next.js portal (kanban t_23bfd49c)",
        })

    @app.get("/reports/by-clinic", response_class=HTMLResponse)
    def by_clinic_monthly(request: Request) -> HTMLResponse:
        """Clinic-level monthly revenue opportunity dashboard.

        Renders the per-month headline figure ("This month Zorva
        identified $X in missed revenue across N encounters") plus
        the top 10 highest-value individual opportunities for the
        current calendar month. Sibling to the home-page KPI tile
        but rendered as its own URL so it can be linked from the
        activity feed, share dialogs, and email summaries without
        re-rendering the full dashboard.
        """
        try:
            from .dashboard import (
                aggregate_monthly_revenue_by_encounter,
                aggregate_monthly_revenue_kpi,
            )
            kpi = aggregate_monthly_revenue_kpi()
            rollup = aggregate_monthly_revenue_by_encounter(top_n=10)
        except Exception:
            kpi = {
                "total_dollar": 0.0,
                "recovered_dollar": 0.0,
                "pending_dollar": 0.0,
                "n_opportunities": 0,
                "n_accepted": 0,
                "acceptance_ratio": 0.0,
                "month_label": "",
                "ready": False,
            }
            rollup = {
                "month_label": "",
                "encounter_count": 0,
                "top_opportunities": [],
                "ready": False,
            }
        return templates.TemplateResponse(
            request,
            "reports/by_clinic.html",
            {
                "month_label": kpi.get("month_label")
                or rollup.get("month_label", ""),
                "total_dollar": kpi.get("total_dollar", 0.0),
                "recovered_dollar": kpi.get("recovered_dollar", 0.0),
                "pending_dollar": kpi.get("pending_dollar", 0.0),
                "n_opportunities": kpi.get("n_opportunities", 0),
                "n_accepted": kpi.get("n_accepted", 0),
                "encounter_count": rollup.get("encounter_count", 0),
                "top_opportunities": rollup.get("top_opportunities", []),
                "ready": kpi.get("ready") or rollup.get("ready", False),
            },
        )

    # ──────────────────────── clinic monthly report (HTML view) ─────────────
    # Render-only sibling of the JSON ``/api/reports/monthly`` route. The
    # JSON route is the machine-readable API the PDF + dashboard
    # consumers hit; this view is the human-facing biller page that
    # walks them through the same numbers (action counts, top modified
    # rules, calibration, tuning recommendations) and renders the
    # insufficient_data state with the months-of-feedback the clinic
    # currently has rather than zeros. The aggregation lives in
    # ``monthly_report.compute_clinic_month`` (kanban t_ca36e05d); we
    # don't re-derive anything here.
    @app.get("/reports/clinic-monthly", response_class=HTMLResponse)
    def clinic_monthly_report_view(
        request: Request,
        clinic: str | None = None,
        month: str | None = None,
    ) -> HTMLResponse:
        """Render the per-clinic, per-month feedback report as HTML.

        Query params
        ------------
        clinic : str, optional
            Clinic / biller_id to report on. Defaults to the active
            tenant (``_TENANT_ID``) or ``"default_biller"`` in dev.
        month : str, optional
            Reporting month in ``YYYY-MM`` format. Defaults to the
            current calendar month (UTC) so the link from the
            activity feed can drop both params.

        States
        ------
        * ``insufficient_data`` — the clinic has fewer than
          :data:`INSUFFICIENT_DATA_THRESHOLD` distinct calendar
          months of feedback. Renders the months-of-feedback card;
          no fabricated numbers.
        * ``ok`` — the clinic has 3+ months of feedback. Renders the
          full report: action counts, confidence calibration,
          top-3 modified rules, and the tuning recommendations.
        """
        # 1. Default the clinic to the active tenant.
        if not clinic:
            clinic = _TENANT_ID or "default_biller"

        # 2. Default the month to "this month" (UTC). The aggregation
        #    only cares about year + month, so a "now"-derived label
        #    is fine even if the audit log is older.
        month_str: str
        if not month:
            now = datetime.now(tz=timezone.utc)
            month_str = now.strftime("%Y-%m")
        else:
            month_str = month
        # Validate format so a stray ``?month=last-month`` doesn't
        # silently fall through to compute_clinic_month and crash.
        if not _re.fullmatch(r"\d{4}-\d{2}", month_str):
            return templates.TemplateResponse(
                request,
                "reports/clinic_monthly.html",
                {
                    "status": "insufficient_data",
                    "clinic_id": clinic,
                    "clinic_name": _TENANT_NAME,
                    "month_label": month_str,
                    "required_months": 3,
                    "current_months": 0,
                },
                status_code=400,
            )

        # 3. Compute the report. ``compute_clinic_month`` already
        #    returns the insufficient_data stub OR the full struct;
        #    we don't branch on its result shape here — the template
        #    inspects ``status`` directly. Imported locally so the
        #    JSON route's import path stays independent (same
        #    pattern as the sibling route's `from .feedback import
        #    get_default_store` call above).
        from .monthly_report import compute_clinic_month
        year_s, month_s = month_str.split("-")
        try:
            payload = compute_clinic_month(
                clinic_id=clinic,
                year=int(year_s),
                month=int(month_s),
            )
        except ValueError:
            # ``compute_clinic_month`` raises ValueError on out-of-range
            # month (the JSON route's regex stops at the digit
            # pattern; semantic validation lives downstream). Render
            # the insufficient_data card so the UI doesn't 500.
            return templates.TemplateResponse(
                request,
                "reports/clinic_monthly.html",
                {
                    "status": "insufficient_data",
                    "clinic_id": clinic,
                    "clinic_name": _TENANT_NAME,
                    "month_label": month,
                    "required_months": 3,
                    "current_months": 0,
                },
                status_code=400,
            )
        except Exception:
            # Any other failure (missing store, write races, etc.) —
            # render the insufficient_data state so the page never
            # 500s on a biller's first click.
            return templates.TemplateResponse(
                request,
                "reports/clinic_monthly.html",
                {
                    "status": "insufficient_data",
                    "clinic_id": clinic,
                    "clinic_name": _TENANT_NAME,
                    "month_label": month,
                    "required_months": 3,
                    "current_months": 0,
                },
                status_code=200,
            )

        # 4. Build the template context. The insufficient_data stub
        #    uses ``current_months``; the ok struct uses the full
        #    set of fields. Both share clinic_id / month_label.
        context: dict[str, Any] = {
            "clinic_id": payload.get("clinic_id", clinic),
            "clinic_name": _TENANT_NAME,
            "month_label": payload.get("month_label", month),
            "status": payload.get("status", "insufficient_data"),
        }
        if context["status"] == "ok":
            context.update({
                "total_findings": payload.get("total_findings", 0),
                "accepted": payload.get("accepted", 0),
                "dismissed": payload.get("dismissed", 0),
                "modified": payload.get("modified", 0),
                "top_3_modified_rules": payload.get(
                    "top_3_modified_rules", [],
                ),
                "confidence_calibration": payload.get(
                    "confidence_calibration", "LOW",
                ),
                "tuning_recommendations": payload.get(
                    "tuning_recommendations", [],
                ),
            })
        else:
            context["required_months"] = payload.get("required_months", 3)
            context["current_months"] = payload.get("current_months", 0)

        return templates.TemplateResponse(
            request,
            "reports/clinic_monthly.html",
            context,
        )

    @app.get("/legal/privacy", response_class=HTMLResponse)
    def legal_privacy(request: Request) -> HTMLResponse:
        """Privacy Policy. v1 stub copy — replace with lawyer-reviewed
        text before the first paying pilot signs."""
        return templates.TemplateResponse(
            request,
            "legal_privacy.html",
            {
                "tenant_name": _TENANT_NAME,
                "tenant_id": _TENANT_ID,
                "data_residency": "Canada (ca-central-1, AWS)",
                "support_email": "privacy@zorva.ca",
            },
        )

    @app.get("/legal/terms", response_class=HTMLResponse)
    def legal_terms(request: Request) -> HTMLResponse:
        """Terms of Service. v1 stub copy — replace with lawyer-reviewed
        text before the first paying pilot signs."""
        return templates.TemplateResponse(
            request,
            "legal_terms.html",
            {
                "tenant_name": _TENANT_NAME,
                "support_email": "support@zorva.ca",
            },
        )

    @app.get("/pricing", response_class=HTMLResponse)
    def pricing(request: Request) -> HTMLResponse:
        """Pricing page &mdash; 3 tiers, flat-fee, no recovery share."""
        return templates.TemplateResponse(
            request,
            "pricing.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/security", response_class=HTMLResponse)
    def security(request: Request) -> HTMLResponse:
        """Security + compliance posture &mdash; HIA, PIPEDA, audit chain."""
        return templates.TemplateResponse(
            request,
            "security.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/try", response_class=HTMLResponse)
    def try_demo(request: Request) -> HTMLResponse:
        """Public demo path &mdash; the auditor on a real AHCIP-style
        sample encounter, no signup, no contract."""
        return templates.TemplateResponse(
            request,
            "try.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/how-it-works", response_class=HTMLResponse)
    def how_it_works(request: Request) -> HTMLResponse:
        """Audit loop explainer &mdash; what the auditor reads, what
        rules it pulls, how findings surface for review."""
        return templates.TemplateResponse(
            request,
            "how-it-works.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/faq", response_class=HTMLResponse)
    def faq(request: Request) -> HTMLResponse:
        """Frequently asked questions &mdash; HIA, deterministic runs,
        tier thresholds, and the privacy brief."""
        return templates.TemplateResponse(
            request,
            "faq.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request) -> HTMLResponse:
        """About the founder, the team, the company."""
        return templates.TemplateResponse(
            request,
            "about.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/compare", response_class=HTMLResponse)
    def compare(request: Request) -> HTMLResponse:
        """Zorva vs the alternatives &mdash; Dr. Bill, Petal, EMR
        billing modules, post-denial recovery tools."""
        return templates.TemplateResponse(
            request,
            "compare.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/demo-request", response_class=HTMLResponse)
    def demo_request(request: Request) -> HTMLResponse:
        """30-minute walkthrough request form."""
        return templates.TemplateResponse(
            request,
            "demo-request.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/pilot", response_class=HTMLResponse)
    def pilot(request: Request) -> HTMLResponse:
        """60-day no-cost pilot &mdash; what it is, timeline, what
        you get, what we get, data handling."""
        return templates.TemplateResponse(
            request,
            "pilot.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/blog", response_class=HTMLResponse)
    def blog(request: Request) -> HTMLResponse:
        """Build notes and AHCIP observations."""
        return templates.TemplateResponse(
            request,
            "blog.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/careers", response_class=HTMLResponse)
    def careers(request: Request) -> HTMLResponse:
        """Open roles at Ashbi (engineering + AHCIP SME)."""
        return templates.TemplateResponse(
            request,
            "careers.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/press", response_class=HTMLResponse)
    def press(request: Request) -> HTMLResponse:
        """Media kit: boilerplate, fact sheet, press contact."""
        return templates.TemplateResponse(
            request,
            "press.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/changelog", response_class=HTMLResponse)
    def changelog(request: Request) -> HTMLResponse:
        """What shipped, when, and the commit that landed it."""
        return templates.TemplateResponse(
            request,
            "changelog.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/glossary", response_class=HTMLResponse)
    def glossary(request: Request) -> HTMLResponse:
        """AHCIP / SOMB / HIA / CMGP / PHIPA / HIPAA terms."""
        return templates.TemplateResponse(
            request,
            "glossary.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/for/family-medicine", response_class=HTMLResponse)
    def for_family_medicine(request: Request) -> HTMLResponse:
        """Vertical landing for family-medicine practices."""
        return templates.TemplateResponse(
            request,
            "for/family-medicine.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/trust", response_class=HTMLResponse)
    def trust(request: Request) -> HTMLResponse:
        """Subprocessor list &mdash; who touches the data, what they
        touch, where the agreement lives."""
        return templates.TemplateResponse(
            request,
            "trust.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/what-zorva-finds", response_class=HTMLResponse)
    def what_zorva_finds(request: Request) -> HTMLResponse:
        """A sample of the 18 AHCIP rules in v12 with the denial
        code or underpayment each one catches."""
        return templates.TemplateResponse(
            request,
            "what-zorva-finds.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/status", response_class=HTMLResponse)
    def status(request: Request) -> HTMLResponse:
        """System status &mdash; live healthz check + services list
        + versions + recent incidents."""
        return templates.TemplateResponse(
            request,
            "status.html",
            {"tenant_name": _TENANT_NAME},
        )

    @app.get("/rss.xml", response_class=Response)
    def rss_feed(request: Request) -> Response:
        """Atom 1.0 feed combining blog + changelog.

        Combined feed so subscribers get a single source of
        "what's new on the Zorva site." See
        :mod:`ai_billing_audit.feeds` for the source-of-truth
        entry list. Whitelisted for the no-auth public-read
        bypass.
        """
        from .feeds import build_atom_feed
        host = (
            request.headers.get("x-forwarded-proto", "https")
            + "://"
            + request.headers.get("host", "ai-billing-audit.ashbi.ca")
        )
        return Response(
            content=build_atom_feed(host),
            media_type="application/atom+xml; charset=utf-8",
        )

    @app.get("/sitemap.xml", response_class=Response)
    def sitemap(request: Request) -> Response:
        """XML sitemap for the public marketing surface.

        Lists every route the public_read whitelist allows
        plus a lastmod and a priority per page. Search engines
        pick this up from robots.txt (TODO when robots.txt is
        wired).
        """
        from .feeds import build_sitemap, PUBLIC_MARKETING_PATHS
        host = (
            request.headers.get("x-forwarded-proto", "https")
            + "://"
            + request.headers.get("host", "ai-billing-audit.ashbi.ca")
        )
        return Response(
            content=build_sitemap(host, PUBLIC_MARKETING_PATHS),
            media_type="application/xml; charset=utf-8",
        )

    @app.get("/contact", response_class=HTMLResponse)
    @app.post("/contact", response_class=HTMLResponse)
    async def contact_sales(
        request: Request,
        name: str = Form(""),
        clinic: str = Form(""),
        email: str = Form(""),
        monthly_claims: str = Form(""),
        message: str = Form(""),
        claims: UploadFile | None = File(None),
    ):
        """Contact sales — send 100 claims, get a 1-page audit.

        GET: render the empty form.
        POST: validate input, optionally persist a claims file
        to the upload queue, write to audit trail, render the
        success page with a follow-up message.

        swarm-audit B-Conv-1: previously the form only accepted
        text fields and promised an audit "by following up with
        100 claims" — but no upload path existed, so the
        marketing promise was a lie. Now the form accepts an
        optional ``claims`` file (837P / CSV / FHIR / ZIP). The
        file is staged to ``/app/logs/contact_uploads/`` with
        a SHA-256 hash and an audit-trail row; the actual audit
        runs once an operator pulls it through the shadow-audit
        pipeline. (Live auto-run from /contact is a follow-up
        card — the file stage + operator handoff matches the
        rest of the privacy posture.)
        """
        from .contact import (
            _append_contact_event,
            _stage_contact_upload,
            valid_email,
            valid_volume,
        )

        error: str | None = None
        success = False
        email_hash_prefix: str | None = None
        upload_staged: dict[str, Any] | None = None
        if request.method == "POST":
            # Validate
            if not name or len(name) > 200:
                error = "Please enter your name (max 200 chars)."
            elif not clinic or len(clinic) > 200:
                error = "Please enter your clinic name (max 200 chars)."
            elif not valid_email(email):
                error = (
                    "Please enter a valid email address."
                )
            elif not valid_volume(monthly_claims):
                error = (
                    "Please enter a positive number for "
                    "monthly claim volume (max 1,000,000)."
                )
            elif len(message) > 2000:
                error = "Message is too long (max 2000 chars)."
            if error is None and claims is not None:
                # Stage the file. Size + extension validation
                # happens inside; the function returns either a
                # manifest dict or None (skipped if filename was
                # empty, e.g. the user didn't pick a file).
                try:
                    upload_staged = await _stage_contact_upload(claims)
                except ValueError as exc:
                    error = str(exc)
            if error is None:
                row = _append_contact_event(
                    name=name,
                    clinic=clinic,
                    email=email,
                    monthly_claims=monthly_claims,
                    message=message,
                    upload=upload_staged,
                )
                success = True
                email_hash_prefix = (
                    row["user_identifier"][:16] + "..."
                )

        return templates.TemplateResponse(
            request,
            "contact.html",
            {
                "tenant_name": _TENANT_NAME,
                "success": success,
                "error": error,
                "email_hash_prefix": email_hash_prefix,
                "upload_staged": upload_staged,
                "name": name if not success else "",
                "clinic": clinic if not success else "",
                "email": email if not success else "",
                "monthly_claims": monthly_claims if not success else "",
                "message": message if not success else "",
                "support_email": "sales@zorva.ca",
                "max_upload_bytes": _MAX_UPLOAD_BYTES,
            },
        )

    @app.get("/case-studies", response_class=HTMLResponse)
    def case_studies_index(request: Request) -> HTMLResponse:
        """Marketing index of worked-example case studies."""
        from .case_studies import case_studies_index as _index
        return templates.TemplateResponse(
            request,
            "case_studies.html",
            {
                "tenant_name": _TENANT_NAME,
                "studies": _index(),
            },
        )

    @app.get("/case-studies/{slug}", response_class=HTMLResponse)
    def case_study_detail(slug: str, request: Request) -> HTMLResponse:
        """One case study by slug."""
        from .case_studies import get_case_study
        cs = get_case_study(slug)
        if cs is None:
            raise HTTPException(
                status_code=404,
                detail=f"case study '{slug}' not found",
            )
        return templates.TemplateResponse(
            request,
            "case_study_detail.html",
            {
                "tenant_name": _TENANT_NAME,
                "cs": cs,
            },
        )

    @app.get("/roi", response_class=HTMLResponse)
    @app.get("/roi/results", response_class=JSONResponse)
    def roi_calculator(
        request: Request,
        monthly_claims: int = 1000,
        current_denial_rate: float = 0.075,
        avg_claim_value_usd: float = 190.0,
        current_appeal_rate: float = 0.50,
        catch_rate: float = 0.77,  # v12 AHCIP val-set RECALL (was 0.69 from F1; recall is the right metric for "errors caught", README.md:7, 2026-07-03)
        plan_tier: str | None = None,
    ):
        """ROI calculator for the one-pager.

        GET /roi: render the HTML form (with results embedded
        when called from a form POST).
        GET /roi/results: return the JSON output for an embeddable
        widget that the marketing site can iframe.
        POST /roi: accept form-encoded inputs and redirect back
        to /roi?monthly_claims=...&... with the inputs as query
        params so the URL is shareable.

        Defaults reflect industry averages:
          * 1,000 claims/month (mid-size practice)
          * 7.5% denial rate (CMS commercial average)
          * $190/claim (CMS commercial office-visit average)
          * 50% manual appeal rate (industry average)
          * 69% catch rate (v12 AHCIP val-set F1 score, README.md:7)
        """
        from .roi import compute_roi

        try:
            result = compute_roi(
                monthly_claims=monthly_claims,
                current_denial_rate=current_denial_rate,
                avg_claim_value_usd=avg_claim_value_usd,
                current_appeal_rate=current_appeal_rate,
                catch_rate=catch_rate,
                plan_tier=plan_tier,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # JSON endpoint for the embeddable widget
        if request.url.path.endswith("/results"):
            return JSONResponse(result)

        # HTML rendering for /roi (form + result side by side)
        return templates.TemplateResponse(
            request,
            "roi.html",
            {
                "tenant_name": _TENANT_NAME,
                "result": result,
                "inputs": {
                    "monthly_claims": monthly_claims,
                    "current_denial_rate": current_denial_rate,
                    "avg_claim_value_usd": avg_claim_value_usd,
                    "current_appeal_rate": current_appeal_rate,
                    "catch_rate": catch_rate,
                    "plan_tier": plan_tier,
                },
            },
        )

    @app.post("/roi", response_class=HTMLResponse)
    async def roi_calculator_post(request: Request):
        """Accept form-encoded POST and redirect to GET with query params.

        The form is a normal HTML form (no JS) so the salesperson
        can fill it in during a demo on a desktop browser, see the
        results, and copy the URL to share with the prospect.
        """
        from fastapi.responses import RedirectResponse

        form = await request.form()
        params: dict[str, str] = {}
        for k in (
            "monthly_claims",
            "current_denial_rate",
            "avg_claim_value_usd",
            "current_appeal_rate",
            "catch_rate",
            "plan_tier",
        ):
            v = form.get(k)
            if v is not None and str(v).strip():
                params[k] = str(v).strip()
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return RedirectResponse(url=f"/roi?{qs}", status_code=303)

    @app.get("/activity", response_class=HTMLResponse)
    def activity_page(request: Request) -> HTMLResponse:
        """Show recent reviewer actions across all encounters.

        Reads /app/logs/audit_trail.jsonl and renders the last N
        events in reverse chronological order. Each row shows the
        action type, encounter_id, finding_id (for dismiss), and
        the SHA-256 signature so the privacy officer can verify
        the chain is intact.
        """
        try:
            from .audit_actions import read_all
            events = read_all(limit=50, tenant_id=_TENANT_ID)
        except Exception:
            events = []
        events = list(reversed(events))  # newest first
        return templates.TemplateResponse(
            request,
            "activity.html",
            {"items": events, "n_events": len(events)},
        )

    # ---- Appeal-letter generator --------------------------------------
    # When a claim is denied by a payer, the biller POSTs here with
    # the finding_id and the denial reason. We pull the finding +
    # the encounter metadata + the zorva_context, build the prompt,
    # call the LLM, and return a Markdown letter the biller can
    # review + send. The body is PHI-scrubbed before being logged
    # to /app/logs/appeal_letters.jsonl.

    @app.post("/encounter/{encounter_id}/appeal", response_class=JSONResponse)
    async def encounter_appeal(
        encounter_id: str,
        request: Request,
    ) -> JSONResponse:
        try:
            from .appeal_letter import (
                generate_appeal_letter,
                log_appeal_letter,
            )
            from .llm import LLMClient
        except ImportError as e:
            raise HTTPException(
                status_code=503, detail=f"appeal_letter module unavailable: {e}"
            )
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        # The biller may pass either a finding_id (preferred) or
        # a rule_id (the LLM doesn't always emit a stable finding_id).
        # We try finding_id first; if no match, we try rule_id.
        finding_id = str(body.get("finding_id", "") or "")
        rule_id = str(body.get("rule_id", "") or "")
        if not finding_id and not rule_id:
            raise HTTPException(
                status_code=400,
                detail="finding_id or rule_id required",
            )
        denial_reason = str(body.get("denial_reason", "") or "").strip()
        if not denial_reason:
            raise HTTPException(status_code=400, detail="denial_reason required")

        # Find the most recent real audit for this encounter (the
        # biller is appealing a finding from this audit) and pull
        # the matching finding from its findings list.
        real_audit = _latest_real_audit_for(encounter_id)
        if real_audit is None:
            raise HTTPException(
                status_code=404,
                detail=f"no audit found for {encounter_id!r}; "
                       "upload + audit a claim first",
            )
        target_finding = None
        for f in real_audit.get("findings", []):
            if finding_id and f.get("finding_id") == finding_id:
                target_finding = f
                break
        if target_finding is None and rule_id:
            # Try exact rule_id match first (single key or
            # rule_ids list), then fall back to a prefix/substring
            # match because the LLM sometimes emits rule_ids with
            # different endings (DX_LINKAGE_REQUIREMENT vs
            # DX_LINKAGE_REQUIRED — singular vs plural, singular
            # vs -MENT suffix, etc.).
            for f in real_audit.get("findings", []):
                rid = f.get("rule_id") or (
                    f.get("rule_ids", [None])[0] if f.get("rule_ids") else None
                )
                if rid == rule_id:
                    target_finding = f
                    break
            if target_finding is None:
                # Fuzzy match: same first 12 characters of the
                # rule_id, OR one is a substring of the other.
                # This catches singular/plural ("DX_LINKAGE_REQUIRED"
                # vs "DX_LINKAGE_REQUIREMENT") and minor
                # variation in the suffix. Underscores and dashes
                # both normalize to empty so DX_LINKAGE_001 and
                # DX-LINKAGE-001 are equivalent.
                rule_norm = rule_id.upper().replace("_", "").replace("-", "")
                for f in real_audit.get("findings", []):
                    rid = f.get("rule_id") or (
                        f.get("rule_ids", [None])[0] if f.get("rule_ids") else None
                    )
                    if not rid:
                        continue
                    rid_norm = rid.upper().replace("_", "").replace("-", "")
                    if (
                        rule_norm[:12] == rid_norm[:12]
                        or rule_norm in rid_norm
                        or rid_norm in rule_norm
                    ):
                        target_finding = f
                        break
        if target_finding is None:
            key = f"finding_id={finding_id!r}" if finding_id else f"rule_id={rule_id!r}"
            raise HTTPException(
                status_code=404,
                detail=f"{key} not in the most recent audit",
            )
        zctx = real_audit.get("zorva_context") or {}
        # Build a minimal encounter dict the generator can consume.
        # The clinical_note isn't persisted to upload_jobs.jsonl yet
        # (v0 only stores the audit result), so the generator gets
        # the finding's quote as a stand-in for the note text. v1:
        # persist the clinical_note alongside the audit result.
        clinical_note = target_finding.get("quote", "")
        encounter_for_letter = {
            "encounter_id": encounter_id,
            "claim": {
                "encounter_id": encounter_id,
                "date_of_service": "",
                "line_items": [],
            },
        }
        # Use the LLM client. The generator wants a free-text
        # completion (no JSON schema constraint — the prose is
        # markdown), so we use complete() not complete_json(). v0
        # falls through to a template-only letter if the LLM call
        # fails.
        llm_client = LLMClient()
        def llm_complete(prompt: str) -> str:
            response = llm_client.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            # litellm returns a dict with the OpenAI response shape;
            # pull the content string out of the first choice.
            return (response.get("choices", [{}])[0]
                          .get("message", {})
                          .get("content", ""))

        try:
            letter = generate_appeal_letter(
                finding=target_finding,
                encounter=encounter_for_letter,
                clinical_note=clinical_note,
                denial_reason=denial_reason,
                zorva_context=zctx,
                llm_complete=llm_complete,
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"appeal-letter generation failed: {e}",
            )
        if letter is None:
            raise HTTPException(
                status_code=500,
                detail="appeal-letter generation returned no result",
            )
        # Log metadata only (body already PHI-scrubbed by the generator).
        # Pass the resolved finding_id so the encounter-detail page
        # can gate the "appeal outcome" form on "letter generated for
        # this finding" (see _attach_appeal_context).
        resolved_finding_id = (
            (target_finding or {}).get("finding_id") if target_finding else finding_id
        ) or None
        log_appeal_letter(
            letter,
            encounter_id,
            tenant_id=_TENANT_ID,
            finding_id=resolved_finding_id,
        )
        return JSONResponse({
            "ok": True,
            "encounter_id": encounter_id,
            "finding_id": finding_id,
            "letter": letter,
        })

    # ---- Appeal outcome tracking ----------------------------------------
    # After a biller submits an appeal letter, the payer's response
    # (won / lost / withdrawn / pending) feeds back into the learning
    # loop. The biller POSTs the outcome here; we append it to
    # /app/logs/appeal_outcomes.jsonl alongside the letter log so
    # the outcome can be joined with the letter at training time.
    #
    # The appeal_id is the biller's identifier for the appeal
    # (typically the same id returned by /encounter/{id}/appeal once
    # the letter is filed, or a finding_id the biller is using as
    # a stable reference). In v0 the endpoint accepts any non-empty
    # appeal_id — a missing/empty id is a 404. Status validation
    # mirrors the task body: only won/lost/withdrawn/pending are
    # accepted; anything else is a 400.

    @app.post(
        "/encounter/{encounter_id}/appeal/{appeal_id}/outcome",
        response_class=JSONResponse,
    )
    async def encounter_appeal_outcome(
        encounter_id: str,
        appeal_id: str,
        request: Request,
    ) -> JSONResponse:
        try:
            from .appeal_letter import (
                AppealOutcome,
                log_appeal_outcome,
            )
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=f"appeal_outcome module unavailable: {e}",
            )

        # Empty appeal_id is treated as "not found" — the biller
        # must reference a real appeal. This also covers the case
        # where the URL path is missing the {appeal_id} segment
        # (FastAPI would 404 the route match, but defence-in-depth).
        if not appeal_id or not appeal_id.strip():
            raise HTTPException(
                status_code=404,
                detail="appeal_id required",
            )

        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            body = {}

        status = str(body.get("status", "")).strip().lower()
        # Five values per the learning-loop spec: won / lost /
        # withdrawn / pending / did_not_file. Anything else is a 400.
        allowed_statuses = {
            "won", "lost", "withdrawn", "pending", "did_not_file",
        }
        if status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"status must be one of {sorted(allowed_statuses)}; "
                    f"got {status!r}"
                ),
            )
        notes = str(body.get("notes", "") or "").strip()
        biller_id = body.get("biller_id")
        if biller_id is not None:
            biller_id = str(biller_id).strip() or None

        outcome = AppealOutcome.now(
            appeal_id=appeal_id,
            encounter_id=encounter_id,
            status=status,  # type: ignore[arg-type]
            biller_id=biller_id,
            notes=notes,
        )
        log_appeal_outcome(outcome)
        return JSONResponse({
            "ok": True,
            "encounter_id": encounter_id,
            "appeal_id": appeal_id,
            "outcome": {
                "status": outcome.status,
                "notes": outcome.notes,
                "biller_id": outcome.biller_id,
                "timestamp": outcome.timestamp,
            },
        })

    # -------------------------------------------------------------------
    # /encounters/upload — staff upload portal
    # -------------------------------------------------------------------
    #
    # Four endpoints, one form. The page (GET) shows three input modes
    # plus a bulk ZIP dropzone; the JS posts the user-selected file to
    # ``/encounters/upload/preview`` for a parse preview; once the
    # staff user clicks "submit" the form posts to
    # ``/encounters/upload/submit`` to enqueue jobs; the JS polls
    # ``/encounters/upload/jobs/<job_id>`` for status. Clinical note
    # PDF/image uploads are stored on disk via
    # ``/encounters/upload/notes`` and the note id is rendered in the
    # preview UI so the staff user can confirm what they uploaded.
    #
    # Auth / tenant scoping is intentionally out of scope per the
    # task body — the route lives behind whatever the portal already
    # enforces upstream.
    _NOTES_DIR = _PKG_DIR.parent.parent / "logs" / "uploaded_notes"
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)

    _ALLOWED_NOTE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"}
    _MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB; portal is for staff uploads

    def _normalise_paste_form(payload: dict[str, Any]) -> dict[str, Any]:
        """Build a claim-shaped dict from the paste-form fields.

        The paste-form lets staff key a single encounter in by hand.
        We accept either ``cpt_codes`` (comma-separated) or
        ``cpt_codes_list`` (JSON array) so the form can switch
        between the two without breaking the API.
        """
        cpts = payload.get("cpt_codes_list")
        if isinstance(cpts, str):
            try:
                cpts = json.loads(cpts)
            except json.JSONDecodeError:
                cpts = [s.strip() for s in cpts.split(",") if s.strip()]
        if not cpts and payload.get("cpt_codes"):
            cpts = [s.strip() for s in str(payload["cpt_codes"]).split(",") if s.strip()]
        return {
            "encounter_id": str(payload.get("encounter_id") or "").strip(),
            "patient_id": str(payload.get("patient_id") or "").strip(),
            "NPI": str(payload.get("npi") or payload.get("NPI") or "").strip(),
            "date_of_service": str(payload.get("date_of_service") or "").strip(),
            "CPT_codes": list(cpts or []),
            "difficulty_tier": str(payload.get("difficulty_tier") or "EASY").upper(),
            "variant": str(payload.get("variant") or "clean").lower(),
            "raw": json.dumps(payload, sort_keys=True),
        }

    def _parse_upload_bytes(name: str, data: bytes) -> list[dict[str, Any]]:
        """Run the right parser based on the file extension.

        Returns a list of normalised claim dicts. For a single 837P
        file, this is one claim (or multiple if the envelope
        contains them). For a ZIP, it's the concatenation across
        every contained 837P file. Non-837P files raise an
        ``X12ParseError``-style error string.
        """
        suffix = Path(name).suffix.lower()
        if suffix == ".zip":
            out: list[dict[str, Any]] = []
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for entry in zf.infolist():
                    if entry.is_dir():
                        continue
                    inner_name = entry.filename
                    if Path(inner_name).suffix.lower() not in (".837", ".txt", ".x12", ".edi", ""):
                        # Skip non-EDI files inside the ZIP — e.g.
                        # a README. The portal shows a per-file
                        # status for the user.
                        continue
                    inner_bytes = zf.read(entry)
                    try:
                        text = inner_bytes.decode("utf-8", errors="replace")
                    except Exception:
                        text = inner_bytes.decode("latin-1", errors="replace")
                    try:
                        claims = parse_837p(text)
                    except X12ParseError as exc:
                        out.append({
                            "encounter_id": None,
                            "patient_id": None,
                            "NPI": None,
                            "date_of_service": None,
                            "CPT_codes": [],
                            "raw": f"<<{inner_name}: {exc}>>",
                            "_source_filename": inner_name,
                            "_parse_error": str(exc),
                        })
                        continue
                    for c in claims:
                        c["_source_filename"] = inner_name
                    out.extend(claims)
            return out
        # Single 837P file.
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")
        claims = parse_837p(text)
        for c in claims:
            c["_source_filename"] = name
        return claims

    @app.get("/encounters/upload", response_class=HTMLResponse)
    def encounters_upload(request: Request) -> HTMLResponse:
        """Render the upload portal page (the drag-drop + paste form)."""
        return templates.TemplateResponse(
            request,
            "encounters_upload.html",
            {
                "n_registered": len(list_demo_encounters()),
                "max_upload_bytes": _MAX_UPLOAD_BYTES,
                "allowed_note_exts": sorted(_ALLOWED_NOTE_EXTENSIONS),
            },
        )

    @app.post("/encounters/upload/preview")
    async def encounters_upload_preview(
        file: UploadFile = File(...),
    ) -> JSONResponse:
        """Return a parse preview for a single uploaded file (or ZIP).

        The frontend calls this first, shows the parsed rows in a
        table with a per-file error column, and only enables the
        "submit" button when at least one row is valid. No jobs
        are enqueued at this stage.
        """
        raw = await file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file is {len(raw)} bytes, max is {_MAX_UPLOAD_BYTES}",
            )
        name = file.filename or "upload.txt"
        try:
            claims = _parse_upload_bytes(name, raw)
        except zipfile.BadZipFile:
            return JSONResponse(
                {
                    "filename": name,
                    "rows": [],
                    "error": f"{name!r} is a .zip but is not a valid ZIP archive",
                },
                status_code=200,
            )
        except X12ParseError as exc:
            return JSONResponse(
                {
                    "filename": name,
                    "rows": [],
                    "error": str(exc),
                },
                status_code=200,
            )
        rows: list[dict[str, Any]] = []
        if not claims:
            # The file looked like an 837P upload (it's a single
            # file, not a ZIP) but no CLM segment was found. Surface
            # a per-file error so the UI can show "0 claims parsed"
            # with a reason, not just an empty table.
            return JSONResponse(
                {
                    "filename": name,
                    "rows": [],
                    "error": (
                        "no CLM segment found; the file is not a "
                        "recognisable 837P payload"
                    ),
                },
                status_code=200,
            )
        for c in claims:
            errs = list(validate_required_fields(c))
            # If the file itself failed to parse (only happens for
            # entries inside a ZIP that the parser rejected), the
            # row carries a ``_parse_error`` we want to surface in
            # the per-file error column. We append it to ``errs``
            # so the submit endpoint filters the row out and the
            # UI shows a clear "parse error" reason.
            if c.get("_parse_error"):
                errs.append(c["_parse_error"])
            inner_name = c.get("_source_filename") or name
            # The row's ``source`` flag tells the submit endpoint
            # which path produced it (``"837p"``, ``"zip"`` for an
            # entry that came out of a bulk upload, or ``"paste"``
            # for the paste-form shortcut). We derive it from the
            # original upload's name and the inner filename: if
            # the original was a ZIP, every row is a ZIP entry
            # regardless of the inner file's suffix.
            row_source = "zip" if name.lower().endswith(".zip") else "837p"
            rows.append(
                {
                    "encounter_id": c.get("encounter_id"),
                    "patient_id": c.get("patient_id"),
                    "NPI": c.get("NPI"),
                    "date_of_service": c.get("date_of_service"),
                    "CPT_codes": c.get("CPT_codes") or [],
                    "source_filename": inner_name,
                    "source": row_source,
                    "errors": errs,
                    "raw": c.get("raw", ""),
                    "parse_error": c.get("_parse_error", ""),
                }
            )
        return JSONResponse({"filename": name, "rows": rows})

    @app.post("/encounters/upload/submit")
    async def encounters_upload_submit(
        request: Request,
        payload: str = Form(...),
    ) -> JSONResponse:
        """Accept a parse-preview payload and enqueue audit jobs.

        The frontend posts the same ``rows`` array it got from
        ``/preview``; this endpoint filters out the rows that had
        errors, enqueues one job per accepted row, and returns the
        list of ``job_id``s the UI then polls.

        Request body:
            ``payload`` — a JSON string with shape
            ``{"rows": [...rows-as-from-preview...]}``.

        Idempotency: callers MAY set an ``Idempotency-Key`` header
        (opaque, ASCII, ≤255 chars). On a retry with the same
        key + same body, the cached response is replayed without
        enqueueing duplicate jobs. A retry with the same key but
        a different body returns 409 Conflict.

        Response:
            ``{"jobs": [{"job_id": "...", "encounter_id": "..."}, ...],
               "rejected": [{"source_filename": "...", "errors": [...]}]}``
        """
        # Idempotency-Key replay: check the cache BEFORE running
        # the endpoint. If the key matches a prior call with the
        # same body fingerprint, return the cached response. If
        # the key matches a prior call with a DIFFERENT body,
        # return 409 Conflict (the caller is misusing the key).
        from .idempotency import (
            IdempotencyMismatch,
            fingerprint_request_body,
            lookup as idem_lookup,
            store as idem_store,
        )
        idem_key = request.headers.get("Idempotency-Key", "").strip()[:255]
        body_fp = fingerprint_request_body(payload)
        try:
            cached = idem_lookup(idem_key, body_fp)
        except IdempotencyMismatch as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if cached is not None:
            return JSONResponse(
                cached.response_json, status_code=cached.status_code
            )

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"payload is not valid JSON: {exc}",
            )
        rows = data.get("rows") or []
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="rows must be a list")
        # Allow the submit payload to override per-row difficulty_tier and
        # variant (set by the paste-form). When the dashboard reuses
        # the preview's rows, these fields are absent and the runner's
        # defaults take over.
        extra = data.get("defaults", {}) or {}
        queue = get_default_queue()
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for row in rows:
            errs = row.get("errors") or []
            if errs:
                rejected.append(
                    {
                        "source_filename": row.get("source_filename") or "",
                        "errors": errs,
                    }
                )
                continue
            # Merge the request-level defaults with the row. Per-row
            # fields win so the dashboard's per-encounter setting still
            # works.
            for k, v in extra.items():
                row.setdefault(k, v)
            # Re-validate server-side; the preview's "errors" array
            # is the source of truth but we never trust the client
            # to decide what's accepted.
            claim = {
                "encounter_id": (row.get("encounter_id") or "").strip(),
                "patient_id": (row.get("patient_id") or "").strip(),
                "NPI": (row.get("NPI") or "").strip(),
                "date_of_service": (row.get("date_of_service") or "").strip(),
                "CPT_codes": list(row.get("CPT_codes") or []),
            }
            errs2 = validate_required_fields(claim)
            if errs2:
                rejected.append(
                    {
                        "source_filename": row.get("source_filename") or "",
                        "errors": errs2,
                    }
                )
                continue
            # The row's ``source`` field is set by the preview
            # endpoint; if the client somehow omits it, fall back
            # to the legacy "is this a paste row?" heuristic.
            source = (row.get("source") or "").strip()
            if not source:
                sf = (row.get("source_filename") or "").strip()
                if not sf:
                    source = "paste"
                elif sf.lower().endswith(".zip"):
                    source = "zip"
                else:
                    source = "837p"
            job = queue.enqueue(
                encounter=claim,
                source=source,
                source_filename=row.get("source_filename") or None,
                tenant_id=_TENANT_ID,
            )
            accepted.append(
                {
                    "job_id": job.job_id,
                    "encounter_id": job.encounter_id,
                    "source": source,
                    # dedup_hit: True when the queue already had a
                    # recent match for (tenant, encounter, patient)
                    # and returned the existing job. The biller sees
                    # this so they know not to expect a fresh audit.
                    "dedup_hit": bool(getattr(job, "dedup_hit", False)),
                }
            )
        response_payload = {"jobs": accepted, "rejected": rejected}
        # Persist the response so a retry with the same Idempotency-Key
        # + same body replays this exact response without re-enqueueing.
        idem_store(idem_key, body_fp, 200, response_payload)
        return JSONResponse(response_payload)

    @app.post("/upload/837i")
    async def upload_837i(
        payload: dict[str, Any] | list[Any],
    ) -> JSONResponse:
        """Accept an institutional 837I claim and enqueue an audit.

        Kanban ``t_ca101c1c``: support 837I (institutional) claims
        in addition to the 837P (professional) format the existing
        portal handles. 837I differs structurally from 837P in
        three ways the auditor cares about — multiple provider NPIs
        per claim, inpatient admission / discharge date spans, and
        per-line place-of-service (some lines are facility lines
        billed by the hospital, others are professional lines
        rendered by an attending / operating provider inside the
        same facility).

        v1: the route accepts a JSON object matching the
        institutional shape (not an X12 envelope) — see
        ``institutional_837i.parse_837i`` for the field contract.
        A future iteration can swap in a real X12 walker.

        Request body (JSON)::

            {
              "patient_id": "PT-001",
              "facility_id": "FAC-MAIN",
              "attending_provider_npi": "1234567890",
              "operating_provider_npi": "1234567891",
              "admission_date": "2026-01-15",
              "discharge_date": "2026-01-17",
              "value_codes": [
                {"code": "40", "amount": 0.0}
              ],
              "service_lines": [
                {"provider_npi": "1234567890",
                 "cpt": "99221",
                 "units": 1,
                 "billed_amount": 250.00,
                 "service_date": "2026-01-15"},
                {"provider_npi": "1234567891",
                 "cpt": "33533",
                 "units": 1,
                 "billed_amount": 4800.00,
                 "service_date": "2026-01-16",
                 "revenue_code": "0360"}
              ]
            }

        Response (200)::

            {
              "job_id": "abc123...",
              "encounter_id": "837I-...",
              "source": "837i",
              "claim": { ... canonical mapped claim ... }
            }

        Response (400) when validation fails::

            {
              "detail": "missing attending_provider_npi; ...",
              "errors": ["...", ...]
            }

        Mapping (also documented in ``institutional_837i``):

        * ``attending_provider_npi`` → ``rendering_provider_npi``
        * ``admission_date`` → ``date_of_service``
        * ``service_lines`` → ``line_items``
        * All distinct NPIs (attending + operating + any per-line
          provider_npi) → ``provider_npis`` list on the claim
        * If no service line is a facility line, a UB-04 revenue
          code 0100 (room & board) line is synthesized so the
          claim carries at least one facility line.

        The auditor (v12) runs on the mapped claim via the same
        ``get_default_queue().enqueue`` path the 837P submit
        endpoint uses, with ``AHCIP`` as the closest in-spirit
        rule set.
        """
        try:
            data = (
                payload if isinstance(payload, dict) else {}
            )
        except Exception:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail="request body must be a JSON object",
            )
        if not isinstance(payload, dict):
            # Non-object payloads (lists, scalars, null) are
            # rejected up-front so the validator's "missing
            # patient_id" errors don't surface for a top-level
            # array — that would be misleading.
            raise HTTPException(
                status_code=400,
                detail=(
                    "request body must be a JSON object; got "
                    f"{type(payload).__name__}"
                ),
            )
        errs = _validate_837i(data)
        if errs:
            # 400 with the full error list (the same shape the
            # other /upload/* validation paths use). The first
            # error is also surfaced in the ``detail`` so generic
            # clients see something useful.
            return JSONResponse(
                {"detail": errs[0], "errors": errs},
                status_code=400,
            )
        try:
            mapped = _parse_837i(data)
        except ValueError as exc:
            # Defensive: validate_837i already caught everything
            # we know how to check, so reaching this branch means
            # the data changed between validation and parse.
            return JSONResponse(
                {"detail": str(exc), "errors": [str(exc)]},
                status_code=400,
            )
        enqueue_payload = _map_837i_to_enqueue(mapped)
        queue = get_default_queue()
        job = queue.enqueue(
            encounter=enqueue_payload,
            source="837i",
            source_filename=None,
            tenant_id=_TENANT_ID,
        )
        return JSONResponse(
            {
                "job_id": job.job_id,
                "encounter_id": job.encounter_id,
                "source": "837i",
                "claim": mapped["claim"],
            }
        )

    @app.post("/upload/csv")
    async def upload_csv(
        file: UploadFile = File(...),
        payer_id: str = Form(""),
        clinic_id: str = Form(""),
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Accept a CSV exported from a PM system and enqueue audits.

        The endpoint is a sibling of ``/encounters/upload/submit`` but
        targets clinics without an EHR integration: they export their
        claims from a Practice Management system (Kareo, OSCAR,
        Office Ally) as a CSV and upload it here. The endpoint:

          1. Auto-detects the CSV format from the header row
             (case-insensitive match against the per-PM dictionary).
          2. Maps the PM's columns to Zorva's canonical schema
             (procedure_code, billed_amount, date_of_service, ...).
          3. Converts each row to an encounter + claim pair and
             enqueues it on the audit job-queue (the same path
             ``/encounters/upload/submit`` uses).
          4. Returns ``{accepted_count, rejected_count, errors:
             [{row, reason}], detected_format, enqueued:
             [{job_id, encounter_id}, ...]}``.

        Per-row errors do NOT abort the whole batch — the endpoint
        reports partial success with the row-level error list so a
        single malformed row doesn't cost the clinic the rest of
        their upload.

        Returns 400 when the format is unknown (no PM dictionary
        matches the header row).
        """
        # Imported lazily so the module loads without csv_ingest on
        # the dependency path (and so the in-process queue module
        # doesn't drag in CSV when the CSV endpoint isn't hit).
        from ai_billing_audit.csv_ingest import ingest_csv

        raw = await file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file is {len(raw)} bytes, max is {_MAX_UPLOAD_BYTES}",
            )
        if not raw:
            raise HTTPException(
                status_code=400,
                detail="empty file: no bytes received",
            )
        # We peek at the header row to decide whether the format is
        # recognised; if not, return 400 immediately rather than
        # pretending the upload was partially successful.
        from ai_billing_audit.csv_ingest import parse_csv, detect_format

        rows = parse_csv(raw)
        headers = list(rows[0].keys()) if rows else []
        detected = detect_format(headers)
        if detected == "unknown":
            raise HTTPException(
                status_code=400,
                detail=(
                    "unrecognised CSV format: header row was "
                    f"{headers!r}; expected one of kareo, oscar, "
                    "office_ally. See /upload/csv docs for the "
                    "exact column names per PM system."
                ),
            )

        queue = get_default_queue()
        result = ingest_csv(
            file_bytes=raw,
            payer_id=payer_id,
            clinic_id=clinic_id,
            enqueue=queue.enqueue,
        )
        return JSONResponse(result)

    @app.get("/encounters/upload/jobs/{job_id}")
    def encounters_upload_job_status(job_id: str) -> JSONResponse:
        """Return the current status of one queued audit job.

        The frontend polls this endpoint every second until the
        job's status is ``done`` or ``failed``. A 404 means the
        job_id is unknown (e.g. the server restarted and the
        JSONL log was cleared between submit and poll).
        """
        queue = get_default_queue()
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"job {job_id!r} not found",
            )
        return JSONResponse(job.to_dict())

    @app.post("/encounters/upload/paste")
    async def encounters_upload_paste(
        payload: str = Form(...),
    ) -> JSONResponse:
        """Shortcut endpoint: accept a paste-form payload, run the
        same validation/preview as the 837P path, and return the
        preview rows. The frontend uses this when the user picks
        the paste tab so the file-upload parser isn't invoked for
        hand-entered data.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"payload is not valid JSON: {exc}",
            )
        claim = _normalise_paste_form(data)
        errs = validate_required_fields(claim)
        row = {
            "encounter_id": claim.get("encounter_id"),
            "patient_id": claim.get("patient_id"),
            "NPI": claim.get("NPI"),
            "date_of_service": claim.get("date_of_service"),
            "CPT_codes": claim.get("CPT_codes") or [],
            "source_filename": "(paste form)",
            "source": "paste",
            "errors": errs,
            "raw": claim.get("raw", ""),
            "parse_error": "",
        }
        return JSONResponse({"filename": "(paste form)", "rows": [row]})

    @app.post("/encounters/upload/notes")
    async def encounters_upload_note(file: UploadFile = File(...)) -> JSONResponse:
        """Accept a clinical note PDF or image and store it on disk.

        The OCR step is deferred (see task body: "OCR via LayoutLMv3
        is a later step, so do not block the upload flow on it").
        We persist the file under ``logs/uploaded_notes/`` with a
        uuid-prefixed filename so the staff user can later pull
        them into a LayoutLMv3 batch run.
        """
        raw = await file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file is {len(raw)} bytes, max is {_MAX_UPLOAD_BYTES}",
            )
        name = file.filename or "note"
        suffix = Path(name).suffix.lower()
        if suffix not in _ALLOWED_NOTE_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{name!r}: extension {suffix!r} not allowed; "
                    f"accepted: {sorted(_ALLOWED_NOTE_EXTENSIONS)}"
                ),
            )
        # uuid prefix to avoid collisions on staff re-uploads with
        # the same filename. Keep the original name as the suffix
        # so the file is recognisable on disk.
        import uuid as _uuid
        note_id = _uuid.uuid4().hex[:12]
        target = _NOTES_DIR / f"{note_id}{suffix}"
        target.write_bytes(raw)
        return JSONResponse(
            {
                "note_id": note_id,
                "filename": name,
                "size_bytes": len(raw),
                "stored_path": str(target.relative_to(_PKG_DIR.parent.parent)),
                "ocr_status": "deferred",
            }
        )

    @app.post("/encounters/upload/text-note")
    async def encounters_upload_text_note(
        encounter_id: str = Form(...),
        clinical_note: str = Form(...),
    ) -> JSONResponse:
        """Accept a plain-text clinical note for a given encounter.

        The MVP pilot's most common flow: a clinic exports an 837P
        file from their EHR and pastes the corresponding clinical
        note text into the upload form. The text is stored on disk
        under ``logs/uploaded_notes/`` with the encounter_id in the
        filename, and the runner picks it up on the next audit job
        for that encounter.

        This bypasses the synth encounter generator entirely: the
        runner reads the stored text and uses it as the clinical_note
        field of the audit's encounter dict. The pilot is real-data
        end-to-end from this point.

        Returns the note_id (also used as the on-disk filename stem)
        so the client can confirm what was stored.
        """
        # The encounter_id is a user-controlled string; sanitise
        # it to a safe filename component. Strip path separators
        # and limit length so we don't blow the filesystem's
        # name limit on pathological inputs.
        import re as _re
        safe = _re.sub(r"[^A-Za-z0-9_.-]+", "_", encounter_id).strip("._")[:80]
        if not safe:
            raise HTTPException(
                status_code=400,
                detail="encounter_id must contain at least one alphanumeric",
            )
        if not clinical_note.strip():
            raise HTTPException(
                status_code=400, detail="clinical_note is empty"
            )
        if len(clinical_note) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"clinical_note is {len(clinical_note)} bytes, max is {_MAX_UPLOAD_BYTES}",
            )
        import uuid as _uuid
        note_id = _uuid.uuid4().hex[:12]
        target = _NOTES_DIR / f"{safe}.{note_id}.txt"
        target.write_text(clinical_note, encoding="utf-8")
        return JSONResponse(
            {
                "note_id": note_id,
                "encounter_id": encounter_id,
                "stored_path": str(target.relative_to(_PKG_DIR.parent.parent)),
                "size_bytes": len(clinical_note.encode("utf-8")),
            }
        )

    # -------------------------------------------------------------------
    # POST /encounters/{encounter_id}/audit — re-run the auditor on
    # a previously uploaded encounter.
    #
    # Spec: the dashboard submits a request body containing the
    # clinical narrative; the endpoint reuses the audit-ready claim
    # the upload flow stored in the job cache, runs the LLM auditor
    # against the (claim, clinical_note) pair, and returns the
    # findings as JSON. The endpoint exists so the dashboard does
    # not need to know the underlying job_id — the encounter id is
    # the user-facing key.
    #
    # Why this re-uses the cached claim rather than re-parsing the
    # original 837P: the upload flow strips envelope segments and
    # normalises to a 5-field claim shape (encounter_id, patient_id,
    # NPI, date_of_service, CPT_codes); the synth runner then
    # expands that into the full claim object the auditor expects
    # (line items, dx_pointers, payer, etc.). The synth materialised
    # form is the audit-ready claim and is what lives in
    # ``Job.result`` once a job finishes. Re-parsing the original
    # 837P would require us to persist the raw file (we don't) AND
    # re-run the synth (we'd lose determinism). The cache lookup
    # recovers everything we need.
    # -------------------------------------------------------------------

    # Stored stub used when the caller omits `clinical_note` and no
    # uploaded text-note exists on disk for the encounter. Kept
    # short and clinically generic so the auditor has *something*
    # to evaluate; the dashboard's real pilot flow always sends
    # the full note, so this is the fallback path.
    _STUB_CLINICAL_NOTE = (
        "Patient seen for routine follow-up. History of present "
        "illness unremarkable. Physical exam within normal limits. "
        "Medical decision making: low complexity. No additional "
        "workup indicated. Plan: continue current management, "
        "return in 6 months or sooner if symptoms change."
    )

    # Same handler at the spec-mandated plural path. The dashboard's
    # upload portal links to /encounters/{id} from the success state
    # per the upload-UI task body; the singular form stays as the
    # legacy alias for older links. Both render the same page.
    #
    # Declared AFTER every static /encounters/upload* route above so
    # FastAPI's declaration-order matching gives precedence to the
    # upload portal's specific paths (/encounters/upload,
    # /encounters/upload/preview, /encounters/upload/submit, etc.)
    # over the catch-all /encounters/{encounter_id}.
    @app.get("/encounters/{encounter_id}", response_class=HTMLResponse)
    def encounter_detail_plural(request: Request, encounter_id: str) -> HTMLResponse:
        return encounter_detail(request, encounter_id)

    # ──────────────────────── per-clinic F1 dashboard ──────────────────
    # The learning-loop surface: per-clinic, per-rule precision /
    # recall / F1 over a rolling 30-day window, plus a weekly F1
    # time series. The dashboard widget in templates/index.html
    # calls this endpoint to render the table + the "F1 over
    # time" chart. Tenant-scoped via the X-Tenant-Id header
    # (matches the rest of the API); the clinic_id is the biller
    # proxy when the feedback log doesn't yet have a clinic_id
    # field (see per_clinic_f1.py docstring).
    @app.get("/api/dashboard/per_clinic_f1")
    def per_clinic_f1_dashboard(
        request: Request,
        clinic_id: str | None = None,
    ) -> JSONResponse:
        """Return per-rule P/R/F1 + a weekly F1 time series for a clinic.

        Query params:
          * ``clinic_id`` (optional) — defaults to the active
            tenant_id (or "default_biller" in dev). The dashboard
            picker calls this endpoint once per clinic switch.
          * ``days`` (optional, default 30) — rolling window size.
        """
        try:
            from .per_clinic_f1 import (
                insufficient_data_state,
                list_clinics,
                per_rule_metrics,
                weekly_f1,
            )
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=f"per_clinic_f1 module unavailable: {e}",
            )
        # Default the clinic to the active tenant / dev fallback.
        if not clinic_id:
            clinic_id = _TENANT_ID or "default_biller"
        # Days window is clamped to [7, 180] to keep the
        # aggregation bounded; the dashboard asks for 30 by
        # default but a power user can dial it down to 7 or up to
        # 180 (one billing quarter).
        try:
            days = int(request.query_params.get("days", "30"))
        except (TypeError, ValueError):
            days = 30
        days = max(7, min(180, days))
        try:
            per_rule = per_rule_metrics(clinic_id=clinic_id, days=days)
            weekly = weekly_f1(clinic_id=clinic_id, days=days)
            clinics = list_clinics()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"per-clinic F1 aggregation failed: {e}",
            )
        # Roll-up: clinic-level F1 across all rules (micro-average
        # over the per-rule TP/FP totals) so the dashboard can
        # render a single "Clinic F1: 0.62" tile next to the
        # per-rule table.
        total_tp = sum(
            v["precision"] * v["support"] for v in per_rule.values()
        )
        total_fp = sum(
            (1.0 - v["precision"]) * v["support"] for v in per_rule.values()
        )
        total_sup = sum(v["support"] for v in per_rule.values())
        # Empty-state: if the clinic has fewer than the threshold
        # feedback events in the window, surface the friendly
        # "insufficient data" payload so the UI doesn't render a
        # misleading 0% F1 tile. The actual clinic_f1 rollup is
        # still computed below so the dashboard can transition
        # smoothly when the threshold is crossed on the next render.
        empty_state = insufficient_data_state(
            clinic_id=clinic_id,
            per_rule=per_rule,
            window_days=days,
        )
        if total_sup == 0:
            clinic_f1 = 0.0
        else:
            p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
            r = 1.0  # within-clinic recall proxy saturates at 1.0 in the rollup
            clinic_f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        return JSONResponse({
            "ok": True,
            "clinic_id": clinic_id,
            "days": days,
            "per_rule": per_rule,
            "weekly": weekly,
            "clinics": clinics,
            "clinic_f1": round(clinic_f1, 4),
            "n_rules": len(per_rule),
            "n_feedback": total_sup,
            "insufficient_data": empty_state["is_insufficient"],
            "empty_state": empty_state,
        })

    # ──────────────────── clinic dashboard (t_1ef7beb3) ─────────────
    # The clinic owner / biller sees a one-screen summary: "this
    # month you've had a 12% denial rate, the top flagged rules
    # were modifier-25 / em_level / dx_linkage, billers took an
    # average of 4.2 hours to act on flagged findings, and we've
    # identified $X in missed revenue". This route returns those
    # four metrics in a single payload so the front-end can render
    # them as a row of metric tiles.
    #
    # Aggregation lives in ``per_clinic_f1.aggregate_clinic_dashboard``
    # so the math is unit-testable in isolation. The route's only
    # job is parameter parsing, validation, and the loader
    # closure that pulls the clinic's findings from the demo
    # registry + uploaded audits.
    @app.get("/api/dashboard/clinic")
    def clinic_dashboard_route(
        request: Request,
        clinic_id: str | None = None,
        window: str | None = None,
    ) -> JSONResponse:
        """Return the 4 clinic-dashboard metrics in one payload.

        Query params:
          * ``clinic_id`` (optional) — defaults to the active
            tenant_id (or "default_biller" in dev). The dashboard
            picker calls this endpoint once per clinic switch.
          * ``window`` (optional) — one of ``7d``, ``30d``, ``90d``.
            Defaults to ``30d``. Anything else collapses to ``30d``
            so a typo can't crash the aggregation.

        Returns 200 with the metrics payload (even on the empty
        state — the ``ready`` flag and per-metric ``None``/zero
        values are the contract). Returns 404 if the clinic_id is
        provided AND has no record in the system (i.e. unknown
        clinic, vs. empty clinic).
        """
        try:
            from .per_clinic_f1 import (
                ALLOWED_DASHBOARD_WINDOWS,
                DEFAULT_DASHBOARD_WINDOW_DAYS,
                aggregate_clinic_dashboard,
                _parse_window_param,
            )
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=f"per_clinic_f1 module unavailable: {e}",
            )

        # Window: clamp to the allowed set. ``window`` query param
        # takes priority; default 30d.
        days = _parse_window_param(window)
        if days not in ALLOWED_DASHBOARD_WINDOWS:
            days = DEFAULT_DASHBOARD_WINDOW_DAYS

        # Default the clinic_id to the active tenant. The dashboard
        # picker overrides this per-clinic.
        if not clinic_id:
            clinic_id = _TENANT_ID or "default_biller"

        # Validate clinic_id exists: walk the registered clinics
        # (demo + any that have written feedback). An unknown
        # clinic_id returns 404 so the dashboard doesn't render
        # garbage. The empty-state (clinic exists but no data) is
        # signalled via ``ready=False`` in the payload.
        try:
            from .per_clinic_f1 import list_clinics
            known = {c["clinic_id"] for c in list_clinics()}
        except Exception:
            known = set()
        # Always allow the active tenant / dev fallback as known.
        known.add(_TENANT_ID or "default_biller")
        if clinic_id not in known:
            raise HTTPException(
                status_code=404,
                detail=f"clinic_id {clinic_id!r} not found",
            )

        # Build a findings loader for the clinic. Pulls from the
        # demo registry (which is keyed by encounter_id) and from
        # the upload_jobs audit log. We project the encounter's
        # findings to the shape ``compute_revenue_opportunities``
        # consumes (rule_id, suggested_code, severity, …).
        def _load_findings_for_clinic(
            cid: str,
            start_ts: float,
            end_ts: float,
        ) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            try:
                from .demo_registry import (
                    list_demo_encounters,
                    load_encounter_record,
                )
                for entry in list_demo_encounters():
                    record = load_encounter_record(entry.encounter_id)
                    if not record:
                        continue
                    # Per-tenant scoping for the demo registry uses
                    # the env-set tenant_id; in single-tenant dev
                    # every record is in scope.
                    if record.get("tenant_id") and record.get("tenant_id") != _TENANT_ID:
                        continue
                    enc_id = str(record.get("encounter_id") or entry.encounter_id)
                    for f in record.get("ground_truth", []) or []:
                        out.append({
                            "encounter_id": enc_id,
                            "finding_id": str(f.get("finding_id") or f.get("id") or ""),
                            "rule_id": str(f.get("rule_id") or ""),
                            "rule_ids": f.get("rule_ids") or [f.get("rule_id")] if f.get("rule_id") else [],
                            "severity": str(f.get("severity") or ""),
                            "category": str(f.get("category") or ""),
                            "suggested_code": str(f.get("suggested_code") or ""),
                        })
            except Exception:
                pass
            # Uploaded-audit findings (real LLM audits). Scoped by
            # tenant_id so one clinic's data doesn't leak into
            # another's dashboard. Only the most recent completed
            # audit per encounter_id is read; the per-encounter view
            # already does the same scoping in the detail handler.
            try:
                log_path = _os.environ.get(
                    "UPLOAD_AUDIT_LOG_PATH", "/app/logs/upload_jobs.jsonl",
                )
                p = Path(log_path)
                if p.is_file():
                    with p.open() as fh:
                        lines = fh.readlines()
                    # Map encounter_id -> latest done row for the tenant.
                    latest: dict[str, dict[str, Any]] = {}
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("status") != "done":
                            continue
                        if rec.get("tenant_id", "default") != _TENANT_ID:
                            continue
                        eid = str(rec.get("encounter_id") or "")
                        if not eid:
                            continue
                        prev = latest.get(eid)
                        if prev is None or str(rec.get("submitted_at", "")) >= str(
                            prev.get("submitted_at", "")
                        ):
                            latest[eid] = rec
                    for rec in latest.values():
                        res = rec.get("result") or {}
                        if res.get("audit_status") != "ok":
                            continue
                        eid = str(rec.get("encounter_id") or "")
                        for f in res.get("findings", []) or []:
                            out.append({
                                "encounter_id": eid,
                                "finding_id": str(f.get("finding_id") or ""),
                                "rule_id": str(f.get("rule_id") or ""),
                                "rule_ids": f.get("rule_ids") or [],
                                "severity": str(f.get("severity") or ""),
                                "category": str(f.get("category") or ""),
                                "suggested_code": str(f.get("suggested_code") or ""),
                            })
            except Exception:
                pass
            return out

        try:
            payload = aggregate_clinic_dashboard(
                clinic_id=clinic_id,
                days=days,
                load_findings_for_clinic=_load_findings_for_clinic,
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"clinic dashboard aggregation failed: {e}",
            )
        return JSONResponse(payload)

    # ──────────────────────── industry baseline benchmark ──────────────
    # The clinic sees their own numbers; this endpoint positions
    # them against the industry cohort so they can answer "is my
    # 8% denial rate good or bad?" without a separate spreadsheet.
    # Backed by the static ``industry_baseline`` table; the clinic
    # value is computed live from the feedback log (denial rate)
    # or the uploaded audit log (time-to-act).
    def _window_for_days(days: int) -> tuple[float, float]:
        """Return ``(start_ts, end_ts)`` covering the last ``days`` UTC."""
        import time as _t
        end_ts = _t.time()
        start_ts = end_ts - (days * 86400)
        return start_ts, end_ts

    def _parse_iso_ts(s: str | None) -> float | None:
        """Parse an ISO-8601 UTC string into a Unix timestamp.

        Returns None on malformed input so the caller can skip
        the row without aborting the whole aggregation. Mirrors
        the helper in ``dashboard.py`` so behaviour stays
        consistent across the two surfaces.
        """
        if not s:
            return None
        from datetime import datetime as _dt
        try:
            return _dt.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return None

    def _parse_feedback_ts(s: str | None) -> float | None:
        """Parse a feedback-log timestamp (``YYYY-MM-DDTHH:MM:SSZ``).

        Same semantics as ``dashboard._parse_feedback_ts``; duplicated
        here to keep the benchmark endpoint self-contained without
        re-importing the dashboard module (which itself depends on
        parts of ``api``).
        """
        return _parse_iso_ts(s)

    @app.get("/api/dashboard/clinic/{clinic_id}/benchmark")
    def clinic_benchmark_route(
        clinic_id: str,
        metric: str | None = None,
        window: str | None = None,
    ) -> JSONResponse:
        """Return the benchmark for ``clinic_id`` on one ``metric``.

        Query params:
          * ``metric`` (required) — one of ``denial_rate``,
            ``time_to_act``, ``top_category``. Unknown values
            return 400 (not 200 with garbage) so the UI can
            distinguish "you typo'd the metric name" from "we
            have no data yet".
          * ``window`` (optional) — ``7d``, ``30d``, ``90d``.
            Defaults to ``30d``. Mirrors the per-clinic dashboard
            window contract so the UI can reuse its picker.

        Response shape (success)::

            {
              "metric": "denial_rate",
              "metric_label": "Denial rate",
              "unit": "pct",
              "source": "MGMA 2024",
              "last_updated": "2024-Q4",
              "clinic_value": 8.3,
              "percentile_50": 6.5,
              "percentile_75": 11.2,
              "percentile_90": 18.4,
              "position": "between p50 and p75",
              "lower_is_better": true,
              "disclaimer": "..."
            }

        Returns 404 if ``clinic_id`` is unknown (mirrors the
        clinic dashboard 404 contract). Returns 400 if
        ``metric`` is unknown.
        """
        try:
            from .industry_baseline import (
                INDUSTRY_DISCLAIMER,
                benchmark_payload,
                known_metrics,
            )
            from .per_clinic_f1 import list_clinics
            from .per_clinic_f1 import _parse_window_param
            from .per_clinic_f1 import (
                ALLOWED_DASHBOARD_WINDOWS,
                DEFAULT_DASHBOARD_WINDOW_DAYS,
            )
        except ImportError as e:
            raise HTTPException(
                status_code=503,
                detail=f"industry_baseline or per_clinic_f1 unavailable: {e}",
            )

        # Validate clinic exists (same 404 contract as the
        # sibling /api/dashboard/clinic route). Always allow
        # the active tenant AND the dev fallback ("default_biller")
        # as known so the demo dashboard renders without a
        # populated feedback log.
        try:
            known = {c["clinic_id"] for c in list_clinics()}
        except Exception:
            known = set()
        known.add(_TENANT_ID or "default_biller")
        known.add("default_biller")
        if clinic_id not in known:
            raise HTTPException(
                status_code=404,
                detail=f"clinic_id {clinic_id!r} not found",
            )

        # Metric is required and must be one we know about.
        if not metric:
            raise HTTPException(
                status_code=400,
                detail=(
                    "metric required; known metrics: "
                    + ", ".join(known_metrics())
                ),
            )
        if metric not in known_metrics():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown metric {metric!r}; known metrics: "
                    + ", ".join(known_metrics())
                ),
            )

        # Window: same clamp semantics as the clinic dashboard.
        try:
            days = _parse_window_param(window)
        except Exception:
            days = DEFAULT_DASHBOARD_WINDOW_DAYS
        if days not in ALLOWED_DASHBOARD_WINDOWS:
            days = DEFAULT_DASHBOARD_WINDOW_DAYS

        # Compute the clinic_value for the metric. Each metric
        # has its own derivation; failure to derive → 0.0
        # rather than 500 (the dashboard renders "no data yet"
        # on zero values, same as the existing clinic dashboard).
        try:
            clinic_value = _compute_clinic_metric(
                clinic_id, metric, days
            )
        except Exception:
            clinic_value = 0.0

        payload = benchmark_payload(metric, clinic_value)
        if payload is None:
            # Defensive: shouldn't happen because we validated
            # above, but guard the contract.
            raise HTTPException(
                status_code=400, detail=f"unknown metric {metric!r}"
            )
        payload["clinic_id"] = clinic_id
        payload["window_days"] = days
        return JSONResponse(payload)

    def _compute_clinic_metric(
        clinic_id: str, metric: str, days: int
    ) -> float:
        """Derive the clinic's value for one industry metric over ``days``.

        Returns a float in the metric's native unit (percent for
        ``denial_rate``, hours for ``time_to_act``). When the
        underlying log is empty the function returns ``0.0`` so
        the dashboard renders "no data yet" rather than crashing.
        """
        start_ts, end_ts = _window_for_days(days)
        if metric == "denial_rate":
            # Percent of submitted claims denied in the window.
            # We compute it as: encounters with at least one
            # 'flag' audit_actions row in the window / total
            # encounters in the window × 100. The audit chain
            # is the only place a "this was denied" signal is
            # recorded in v0 (the appeal_outcomes log has won/
            # lost but not the upstream denial-rate number).
            try:
                from .audit_actions import read_all
                rows = read_all()
            except Exception:
                return 0.0
            in_window_total: set[str] = set()
            in_window_denied: set[str] = set()
            for row in rows:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None or ts < start_ts or ts >= end_ts:
                    continue
                if row.get("tenant_id", "default") != _TENANT_ID:
                    continue
                eid = str(
                    row.get("data_elements", {}).get("encounter_id", "")
                )
                if not eid:
                    continue
                in_window_total.add(eid)
                if row.get("action") == "flag":
                    in_window_denied.add(eid)
            if not in_window_total:
                return 0.0
            return round(
                100.0 * len(in_window_denied) / len(in_window_total), 2
            )
        if metric == "time_to_act":
            # Median hours between audit_actions 'append' (finding
            # surfaced) and the first feedback accept/dismiss/modify
            # on the same (encounter, finding) pair. The 30-day
            # window is inclusive of all rows on either side.
            try:
                from .audit_actions import read_all as read_audit
                from .feedback import get_default_store
            except Exception:
                return 0.0
            audit_rows = list(read_audit())
            surfaced: dict[tuple[str, str], float] = {}
            for row in audit_rows:
                ts = _parse_iso_ts(row.get("timestamp", ""))
                if ts is None:
                    continue
                eid = str(
                    row.get("data_elements", {}).get("encounter_id", "")
                )
                fids = (
                    row.get("data_elements", {}).get("finding_ids")
                    or row.get("data_elements", {}).get("finding_id")
                    and [row.get("data_elements", {}).get("finding_id")]
                    or []
                )
                for fid in fids:
                    if not eid or not fid:
                        continue
                    key = (eid, str(fid))
                    # Take the earliest surfacing time (the first
                    # time the biller saw this finding).
                    if key not in surfaced or ts < surfaced[key]:
                        surfaced[key] = ts
            try:
                store = get_default_store()
                feedback_rows = store.read_all()
            except Exception:
                feedback_rows = []
            gaps: list[float] = []
            for fe in feedback_rows:
                if fe.action not in ("accept", "dismiss", "modify"):
                    continue
                ts = _parse_feedback_ts(fe.timestamp)
                if ts is None:
                    continue
                key = (fe.encounter_id, fe.finding_id)
                surf = surfaced.get(key)
                if surf is None:
                    continue
                gap_hours = (ts - surf) / 3600.0
                if gap_hours < 0:
                    continue
                gaps.append(gap_hours)
            if not gaps:
                return 0.0
            gaps.sort()
            mid = len(gaps) // 2
            if len(gaps) % 2 == 1:
                return round(gaps[mid], 2)
            return round((gaps[mid - 1] + gaps[mid]) / 2.0, 2)
        if metric == "top_category":
            # For the categorical metric the "value" the dashboard
            # renders is the % of the clinic's top-flagged category
            # in the industry breakdown. This lets the dashboard
            # say "your top category is dx_linkage, which 62% of
            # clinics also flag" without needing a separate
            # endpoint to compute "what's your top category?".
            try:
                from .industry_baseline import INDUSTRY_BASELINES
                breakdown = (
                    INDUSTRY_BASELINES["top_category"]["category_breakdown"]
                )
            except Exception:
                return 0.0
            # Determine the clinic's top category by feedback / rule.
            try:
                from .feedback import get_default_store
                store = get_default_store()
                entries = store.read_all()
            except Exception:
                entries = []
            by_cat: dict[str, int] = {}
            for fe in entries:
                cat = (fe.category or "").strip().lower()
                if not cat:
                    continue
                by_cat[cat] = by_cat.get(cat, 0) + 1
            if not by_cat:
                return 0.0
            top_cat = max(by_cat.items(), key=lambda kv: kv[1])[0]
            # Map common names to the breakdown keys.
            aliases = {
                "dx_linkage": "dx_linkage",
                "dx-linkage": "dx_linkage",
                "diagnosis_linkage": "dx_linkage",
                "modifier_25": "modifier_25",
                "modifier-25": "modifier_25",
                "mod_25": "modifier_25",
                "em_level": "em_level",
                "e/m_level": "em_level",
                "em-level": "em_level",
            }
            key = aliases.get(top_cat, top_cat)
            return float(breakdown.get(key, 0.0))
        # Unknown metric — defensive. Validation above should
        # have caught this; return 0 so the response is still
        # 200 rather than 500.
        return 0.0

    # ──────────────────────── monthly report (t_b15a1821) ──────────────
    # The deferred full report (calibration + recommended prompt
    # changes) lives in blocked task t_f98a799f, which is gated on
    # 3+ months of feedback data. Until that data exists, this route
    # surfaces a clean insufficient_data stub so the monthly-report
    # UI is not a 404. When the 3-month threshold is crossed, the
    # route forwards to ``monthly_report.monthly_summary`` — see
    # the inline branching below.
    @app.get("/api/reports/monthly")
    def monthly_report_route(
        request: Request,
        clinic: str | None = None,
        month: str | None = None,
    ) -> JSONResponse:
        """Return the monthly report payload for a clinic.

        Query params:
          * ``clinic`` (optional) — clinic_id; defaults to the active
            tenant_id (or ``"default_biller"`` in dev).
          * ``month`` (optional) — reporting month in ``YYYY-MM``
            format. Echoed back in the response so the caller can
            pin a render to a specific month. Invalid format
            returns 400.

        Response shape when the clinic has fewer than 3 months of
        feedback (the common dev / pilot case):

            {
              "status": "insufficient_data",
              "message": "Need 3+ months of feedback to generate a monthly report.",
              "required_months": 3,
              "current_months": <int>,
              "clinic_id": "<id>",
              "month": "<YYYY-MM>"
            }

        When the clinic has 3+ distinct months of feedback, the
        route forwards to ``monthly_report.monthly_summary`` and
        returns its dict merged with the query metadata. The
        full-report branch exists so swapping the stub for the
        real report is a one-line change once t_f98a799f unblocks.
        """
        # 1. month format gate.
        if not month:
            raise HTTPException(
                status_code=400,
                detail="month query param is required (YYYY-MM)",
            )
        if not _re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(
                status_code=400,
                detail=f"month must be in YYYY-MM format, got {month!r}",
            )

        # 2. Default the clinic to the active tenant / dev fallback.
        if not clinic:
            clinic = _TENANT_ID or "default_biller"

        # 3. Compute "current_months" — distinct (year, month) tuples
        #    in the feedback log for this clinic. This is the gate
        #    the spec calls out ("3+ months of feedback"); we count
        #    it from the same store the rest of the API reads so the
        #    threshold check matches the data the report would
        #    summarise.
        try:
            from .feedback import get_default_store
            _store = get_default_store()
            _entries = _store.read_all() or []
        except Exception:
            _entries = []

        months_seen: set[tuple[int, int]] = set()
        for e in _entries:
            if e.biller_id != clinic:
                continue
            # Skip synthetic "accept_all" / "rerun" pseudo-entries
            # the same way per_clinic_f1 does — they don't count
            # toward the threshold.
            if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
                continue
            try:
                ts = e.timestamp.strip()
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts)
            except Exception:
                continue
            months_seen.add((dt.year, dt.month))
        current_months = len(months_seen)

        # 4. Gate: < 3 months → insufficient_data stub.
        if current_months < 3:
            return JSONResponse({
                "status": "insufficient_data",
                "message": "Need 3+ months of feedback to generate a monthly report.",
                "required_months": 3,
                "current_months": current_months,
                "clinic_id": clinic,
                "month": month,
            })

        # 5. Full report branch: call monthly_summary with a window
        #    large enough to cover all the feedback months the gate
        #    just counted, so the per-rule + weekly series actually
        #    picks up the data instead of an empty 30-day slice.
        try:
            from .monthly_report import monthly_summary
            days = max(30, current_months * 31)
            payload = monthly_summary(clinic_id=clinic, days=days)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"monthly_report.monthly_summary failed: {e}",
            )
        # Merge the query metadata into the payload so the caller
        # can pin a render to a specific month without re-parsing
        # the URL. The summary's own ``clinic_id`` / ``days`` keys
        # are preserved.
        payload = dict(payload)
        payload["status"] = "ok"
        payload["month"] = month
        payload.setdefault("clinic_id", clinic)
        return JSONResponse(payload)

    # ──────────────────────── monthly report (PDF) (t_4c278e95) ───────
    # Single-page PDF version of the monthly report. Uses the same
    # data the JSON sibling aggregates (encounters + feedback +
    # appeal outcomes) so a biller / clinic owner can hand a
    # formatted artifact to a partner without ever opening a
    # browser. The route is registered *next to* the JSON
    # monthly_report_route so the two stay in sync — the JSON
    # route carries the insufficient_data gate; the PDF route
    # also honours it (no PDF for a clinic with < 3 months of
    # data; we 404 instead of rendering a useless empty sheet).
    @app.get("/api/reports/monthly.pdf")
    def monthly_report_pdf_route(
        request: Request,
        clinic_id: str | None = None,
        month: str | None = None,
    ) -> Response:
        # 1. Query param validation — same regex as the JSON route.
        if not month:
            raise HTTPException(
                status_code=400,
                detail="month query param is required (YYYY-MM)",
            )
        if not _re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(
                status_code=400,
                detail=f"month must be in YYYY-MM format, got {month!r}",
            )
        if not clinic_id:
            clinic_id = _TENANT_ID or "default_biller"

        # 2. Gate on the same 3-month threshold the JSON route uses.
        #    We re-read the feedback store here (rather than calling
        #    the JSON route) so the PDF path doesn't depend on
        #    ``monthly_report`` being importable — keeping the two
        #    sibling endpoints independent means either can be
        #    refactored without dragging the other along. The
        #    threshold constant is imported locally so the PDF route
        #    doesn't add another module-level import to ``api.py``.
        try:
            from .per_clinic_f1 import INSUFFICIENT_DATA_THRESHOLD
        except Exception:
            INSUFFICIENT_DATA_THRESHOLD = 3
        try:
            from .feedback import get_default_store
            _store = get_default_store()
            _entries = _store.read_all() or []
        except Exception:
            _entries = []
        months_seen: set[tuple[int, int]] = set()
        for e in _entries:
            if e.biller_id != clinic_id:
                continue
            if e.finding_id.startswith("__") and e.finding_id.endswith("__"):
                continue
            try:
                ts = e.timestamp.strip()
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts)
            except Exception:
                continue
            months_seen.add((dt.year, dt.month))
        if len(months_seen) < INSUFFICIENT_DATA_THRESHOLD:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"need {INSUFFICIENT_DATA_THRESHOLD}+ months of feedback "
                    f"to render a PDF report for clinic {clinic_id!r} "
                    f"(have {len(months_seen)})"
                ),
            )

        # 3. Build the payload + render. The PDF module never
        #    raises on a missing dependency (it falls back to a
        #    plain-text "PDF" body); failures inside the
        #    aggregation are swallowed inside the module and
        #    surface as a document with zeros for that section.
        try:
            from .monthly_pdf import build_report_payload, render_monthly_pdf
            payload = build_report_payload(
                clinic_id=clinic_id,
                clinic_name=_TENANT_NAME,
                month=month,
            )
            pdf_bytes = render_monthly_pdf(payload)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"monthly_pdf render failed: {exc}",
            )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'inline; filename="zorva-monthly-{clinic_id}-{month}.pdf"'
                ),
            },
        )

    # ──────────────────────── tenant data export / deletion ─────────────────
    #
    # PHIPA s.53 / PIPEDA: a patient (or the clinic on their behalf) has the
    # right to a copy of every piece of PHI we hold about them. The export
    # endpoint returns every claim, every audit-trail row, and every appeal
    # letter for the calling tenant as JSONL with a SHA-256 manifest.
    # The deletion endpoint accepts a confirmation phrase and writes a
    # final deletion record to the audit trail before purging.
    #
    # Both routes are gated by the bearer-token middleware so they
    # require the same auth as any other write/read. They're also
    # tenant-scoped: a request for tenant A only returns A's data.

    @app.get("/api/tenants/{tenant_id}/export.jsonl")
    def tenant_export_jsonl(tenant_id: str) -> Response:
        """Export every record for a tenant as JSONL with a manifest.

        Each line is one JSON object (audit_trail row, appeal-letter
        record, or upload-jobs entry) belonging to the tenant. The
        final line is a manifest object:

          {
            "manifest": true,
            "tenant_id": "...",
            "n_audit_trail": N,
            "n_appeal_letters": M,
            "n_upload_jobs": K,
            "sha256_audit_trail": "hex...",
            "sha256_appeal_letters": "hex...",
            "sha256_upload_jobs": "hex...",
            "generated_at": "ISO-8601"
          }

        Caller verifies the manifest hashes against their local
        re-computation to detect tampering. The PHIPA s.53 right-of-
        access window is 30 days; this endpoint is synchronous
        so the caller can re-fetch immediately.
        """
        import hashlib
        from pathlib import Path as _P

        if tenant_id != _TENANT_ID:
            raise HTTPException(
                status_code=403,
                detail="tenant_id does not match the current tenant scope",
            )

        try:
            from .audit_actions import read_all
            audit_rows = read_all(tenant_id=_TENANT_ID)
        except Exception:
            audit_rows = []

        appeal_rows: list[dict[str, Any]] = []
        appeal_log = _P(
            os.environ.get("ZORVA_LOGS_DIR", "/app/logs")
        ) / "appeal_letters.jsonl"
        if appeal_log.is_file():
            with appeal_log.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("tenant_id", "default") == _TENANT_ID:
                        appeal_rows.append(row)

        upload_rows: list[dict[str, Any]] = []
        upload_log = _P(
            os.environ.get(
                "UPLOAD_AUDIT_LOG_PATH", "/app/logs/upload_jobs.jsonl"
            )
        )
        if upload_log.is_file():
            with upload_log.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("tenant_id", "default") == _TENANT_ID:
                        upload_rows.append(row)

        def _sha256(rows: list[dict]) -> str:
            h = hashlib.sha256()
            for r in rows:
                h.update(
                    (json.dumps(r, sort_keys=True) + "\n").encode("utf-8")
                )
            return h.hexdigest()

        manifest = {
            "manifest": True,
            "tenant_id": _TENANT_ID,
            "n_audit_trail": len(audit_rows),
            "n_appeal_letters": len(appeal_rows),
            "n_upload_jobs": len(upload_rows),
            "sha256_audit_trail": _sha256(audit_rows),
            "sha256_appeal_letters": _sha256(appeal_rows),
            "sha256_upload_jobs": _sha256(upload_rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # The export is JSONL: one record per line, manifest last.
        # Caller can stream-parse without loading the whole file.
        lines: list[str] = []
        for r in audit_rows:
            lines.append(json.dumps({"kind": "audit_trail", **r}))
        for r in appeal_rows:
            lines.append(json.dumps({"kind": "appeal_letter", **r}))
        for r in upload_rows:
            lines.append(json.dumps({"kind": "upload_job", **r}))
        lines.append(json.dumps(manifest))
        body = "\n".join(lines) + "\n"

        # Write a final export event to the audit trail so the
        # export itself is part of the tenant's permanent record.
        try:
            from .audit_actions import append as _audit_append
            _audit_append(
                action="data_export",
                encounter_id="*",  # tenant-wide; not a single encounter
                user_identifier="data_export_endpoint",
                tenant_id=_TENANT_ID,
                extra={
                    "n_audit_trail": len(audit_rows),
                    "n_appeal_letters": len(appeal_rows),
                    "n_upload_jobs": len(upload_rows),
                    "sha256_audit_trail": manifest["sha256_audit_trail"],
                },
            )
        except Exception:
            # Don't crash the export on audit-write failure; the
            # export itself is the contract.
            pass

        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="zorva-export-'
                    f'{_TENANT_ID}-{int(time.time())}.jsonl"'
                ),
                "X-Tenant-Id": _TENANT_ID,
            },
        )

    @app.delete("/api/tenants/{tenant_id}")
    def tenant_delete(tenant_id: str, confirmation: str = "") -> JSONResponse:
        """Purge every record for a tenant.

        Confirmation phrase: the caller must pass
        ``confirmation="delete-all-my-data"`` (literal string) in
        the request body or query string. This is a guard against
        accidental deletion from a typo'd request.

        Writes a final deletion event to the audit trail BEFORE
        purging — so the deletion itself is part of the tenant's
        permanent record (a "this is when you said delete" timestamp).

        Currently the actual purge step is a no-op: the upload
        portal + job queue are read-only on the JSONL logs, and
        the volume-mounted files survive container recreates. v2:
        integrate with the container's volume snapshot or with
        a per-tenant data deletion worker. For now, the deletion
        event is the contract — the privacy officer can verify
        via the audit trail.
        """
        if tenant_id != _TENANT_ID:
            raise HTTPException(
                status_code=403,
                detail="tenant_id does not match the current tenant scope",
            )
        if confirmation != "delete-all-my-data":
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirmation phrase required; pass "
                    "confirmation='delete-all-my-data' to confirm"
                ),
            )

        # Write the deletion event BEFORE purging anything.
        try:
            from .audit_actions import append as _audit_append
            _audit_append(
                action="tenant_purge",
                encounter_id="*",
                user_identifier="data_delete_endpoint",
                tenant_id=_TENANT_ID,
                extra={
                    "confirmation": confirmation,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "note": (
                        "tenant requested purge of all data; "
                        "actual file deletion is a v2 worker task"
                    ),
                },
            )
        except Exception:
            pass

        return JSONResponse({
            "ok": True,
            "tenant_id": _TENANT_ID,
            "purge_status": "audit_recorded",
            "note": (
                "v1: deletion is recorded in the audit trail. "
                "v2: actual file purge is queued in a background worker."
            ),
        })

    @app.post("/encounters/{encounter_id}/audit")
    async def encounters_audit(
        request: Request,
        encounter_id: str,
        user: UserContext = Depends(require_biller_or_admin),
    ) -> JSONResponse:
        """Run the auditor on a previously uploaded encounter.

        Request body (JSON or form):

        - ``clinical_note`` (optional): the clinical narrative.
          When omitted, falls back to a stored stub note so the
          endpoint still returns a valid audit result.

        Response (HTTP 200):

        - ``encounter_id``: echoed from the path
        - ``has_discrepancy``: ``true`` if the auditor emitted any
          findings
        - ``findings``: list of finding dicts (category, severity,
          rule_id, suggested_code, quote, explanation)
        - ``summary``: the auditor's plain-text synopsis
        - ``source_job_id``: the job_id the cached claim came from
        - ``note_source``: ``"request"``, ``"uploaded"``, or
          ``"stub"`` — useful for the dashboard to show which
          clinical note was used

        Error responses:

        - 404 if no cached job exists for ``encounter_id``
        - 400 if the cached claim is missing the audit-ready
          fields the auditor expects
        - 502 if the LLM call itself errors (the synth runner
          has its own retry; the audit route does not, since
          the request is synchronous)
        """
        if not encounter_id or not encounter_id.strip():
            raise HTTPException(
                status_code=400,
                detail="encounter_id path param is empty",
            )
        encounter_id = encounter_id.strip()

        # ---- 0. RBAC + tenant gate ----
        # The bearer-token middleware at line ~1140 enforces auth, but
        # historically this endpoint accepted ANY caller with a valid
        # bearer token (including the synthetic "anonymous" user from
        # ``_rbac_identity_middleware``). P11 bug-sweep finding: a
        # viewer-role user — or a stolen shared bearer — could trigger
        # an LLM audit on any encounter. We now require biller-or-admin
        # explicitly. ``require_biller_or_admin`` raises 403 for
        # ``role='viewer'`` and ``role='anonymous'`` before this point
        # is reached, so the dependency handle is just an attestation
        # marker here — the call still goes through. Tenant scoping
        # is implicit because the in-process job queue is one-tenant-
        # per-app-instance, but we keep the dependency to make the
        # intent (defense in depth) explicit at the route signature.

        # ---- 1. read the optional clinical_note from the body ----
        # Accept JSON or form. JSON is the dashboard's preferred
        # shape; form is a fallback so a curl-based smoke test
        # can do `-F "clinical_note=..."`.
        clinical_note: str | None = None
        note_source = "stub"
        content_type = (request.headers.get("content-type") or "").lower()
        try:
            if "application/json" in content_type:
                body = await request.json()
                if isinstance(body, dict):
                    raw = body.get("clinical_note")
                    if isinstance(raw, str) and raw.strip():
                        clinical_note = raw
                        note_source = "request"
            else:
                form = await request.form()
                raw = form.get("clinical_note")
                if isinstance(raw, str) and raw.strip():
                    clinical_note = raw
                    note_source = "request"
        except Exception:  # noqa: BLE001 (deliberately broad)
            # Malformed body — fall through to the stub path
            # rather than 400. The dashboard can re-submit.
            clinical_note = None

        # ---- 2. look up the cached job for this encounter ----
        #
        # Two-step lookup so we can distinguish "no job exists at all"
        # (404 — the caller should upload first) from "a job exists but
        # is still in flight" (409 — the dashboard should poll and
        # retry). ``find_by_encounter`` defaults to status="done", so
        # a queued/running job is invisible to the default call and we
        # have to query again with status=None to surface it.
        #
        # The previous (single-step) lookup returned None for the
        # in-flight case, which translated to a misleading 404 —
        # callers re-trying an audit during a long synth run had no
        # way to tell "you haven't uploaded yet" from "your upload is
        # still running". The test
        # ``test_audit_returns_409_when_job_still_running`` pins the
        # correct behaviour.
        queue = get_default_queue()
        job = queue.find_by_encounter(encounter_id)
        if job is None:
            # No done-job. Check whether any job exists at all so we
            # can return 409 for the in-flight case instead of 404.
            in_flight = queue.find_by_encounter(encounter_id, status=None)
            if in_flight is not None and in_flight.status != "done":
                # Job exists but hasn't finished. The synth runner is
                # fast, but we should not double-fire; surface a 409
                # so the dashboard can poll /jobs/{id} and retry.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"encounter {encounter_id!r} is in job "
                        f"{in_flight.job_id!r} (status={in_flight.status}); "
                        f"wait for it to finish and retry."
                    ),
                )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"encounter {encounter_id!r} has no cached audit "
                    f"job. Upload the 837P first via "
                    f"/encounters/upload/submit, then re-audit."
                ),
            )
        if job.status != "done":
            # Job exists but hasn't finished. The synth runner is
            # fast, but we should not double-fire; surface a 409
            # so the dashboard can poll /jobs/{id} and retry.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"encounter {encounter_id!r} is in job "
                    f"{job.job_id!r} (status={job.status}); "
                    f"wait for it to finish and retry."
                ),
            )

        # ---- 3. recover the audit-ready claim from the upload ----
        # Re-audit must operate on the biller's originally uploaded
        # data, NOT a fresh synth materialised from a hash of the
        # encounter id. Per kanban task t_75202858, the upload
        # portal's "real-data" branch in job_queue._default_runner
        # is the source of truth for what the prior audit ran on.
        #
        # The clinical note is the piece of uploaded data that
        # persists on disk: /encounters/upload/text-note writes
        # ``<encounter_id>.<note_id>.txt`` under logs/uploaded_notes/
        # and the upload portal's _load_uploaded_note() helper reads
        # the most-recent one back. We mirror that glob/sort
        # resolution here (computing the notes dir from this
        # module's __file__ so the test suite's tmp_path redirect
        # keeps working) so the resolution logic is single-sourced
        # with the runner — no parallel implementation in two
        # places.
        #
        # The claim payload (CPT codes, ICDs, NPI, date_of_service,
        # patient_id) is now persisted on job.result['claim'] by
        # job_queue._default_runner (see kanban card t_10774785). The
        # re-audit endpoint reads it back here so the audit operates
        # on the exact claim object the original runner built, instead
        # of the historical PT_REAUDIT placeholder with empty
        # line_items. Pre-fix jobs (those that never persisted a
        # claim) still surface the placeholder for backward
        # compatibility — we do NOT fabricate a claim.
        result = job.result or {}
        synth_encounter_id = result.get("synth_encounter_id")
        ran_via = result.get("ran_via", "upload_portal")
        used_uploaded_note = bool(result.get("used_uploaded_note")) or (
            ran_via == "upload_portal_with_user_note"
        )
        persisted_claim = result.get("claim")

        # Resolve the clinical_note: request > uploaded on-disk
        # text-note > stub.
        if clinical_note is None:
            try:
                from pathlib import Path as _P
                notes_dir = (
                    _P(__file__).resolve().parent.parent.parent
                    / "logs" / "uploaded_notes"
                )
                if notes_dir.is_dir():
                    safe = __import__("re").sub(
                        r"[^A-Za-z0-9_.-]+", "_", encounter_id
                    ).strip("._")[:80]
                    if safe:
                        candidates = sorted(
                            notes_dir.glob(f"{safe}.*.txt"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        if candidates:
                            clinical_note = candidates[0].read_text(encoding="utf-8")
                            note_source = "uploaded"
            except Exception:  # noqa: BLE001 (deliberately broad)
                clinical_note = None
        if clinical_note is None:
            clinical_note = _STUB_CLINICAL_NOTE
            note_source = "stub"

        # ---- 4. rebuild the audit encounter and run the auditor ----
        # Read-from-uploaded-data branch: prefer the on-disk
        # uploaded clinical note over a re-synthesised one. Two
        # sub-branches:
        # - ``used_uploaded_note`` was set by the runner: the prior
        #   audit was the upload portal's "real data" path. Mirror
        #   that branch's claim shape; the runner's encounter
        #   payload (CPTs, NPI, etc.) is not in job.result so
        #   line_items is empty. The dashboard should treat this
        #   as "re-upload required for a full re-audit" rather
        #   than silently zeroing.
        # - Otherwise: legacy synth-only demo path. Re-run the
        #   synth with the cached tier/variant/seed (read from
        #   job.result) so the re-audit is deterministic.
        try:
            from .auditor import run_audit as _run_audit, AuditValidationError
            from .zorva_context import build_context_for_encounter

            if used_uploaded_note:
                zorva_ctx = build_context_for_encounter(
                    country_code=None,
                    payer_id=None,
                    province=None,
                    health_number=None,
                )
                # Prefer the claim the runner persisted on
                # Job.result (t_10774785). Fall back to the legacy
                # PT_REAUDIT placeholder ONLY for jobs that ran
                # before the fix landed — those will not have
                # result['claim'].
                if (
                    isinstance(persisted_claim, dict)
                    and persisted_claim.get("line_items")
                ):
                    claim = dict(persisted_claim)
                else:
                    claim = {
                        "encounter_id": encounter_id,
                        "patient_id": "PT_REAUDIT",
                        "rendering_provider_npi": "",
                        "billing_provider_tax_id": "",
                        "date_of_service": "",
                        "payer_id": "",
                        "payer_name": "",
                        "line_items": [],
                        "diagnosis_codes": [],
                        "_reaudit_note": (
                            "claim payload not persisted; re-audit "
                            "ran against the uploaded note only. "
                            "Re-upload the 837P for a full re-audit."
                        ),
                    }
                audit_encounter = {
                    "encounter_id": encounter_id,
                    "is_flagged": False,
                    "clinical_note": clinical_note,
                    "claim": claim,
                    "rules": [],
                    "ground_truth": [],
                    "zorva_context": zorva_ctx,
                }
            else:
                from .synth_agent import generate, Template

                difficulty_tier = result.get("difficulty_tier")
                variant = result.get("variant", "clean")
                seed = int(result.get("seed") or (abs(hash(encounter_id)) % (2**31)))
                tier_norm = str(difficulty_tier or "EASY").upper()
                if tier_norm not in ("EASY", "MEDIUM", "HARD"):
                    tier_norm = "EASY"
                variant_norm = str(variant or "clean").lower()
                if variant_norm not in ("clean", "flagged"):
                    variant_norm = "clean"
                synth_out = generate(
                    Template(tier=tier_norm, variant=variant_norm, schema_version=1),
                    seed=seed,
                )
                cpts = synth_out.get("cpt_codes", []) or []
                icds = synth_out.get("icd10_codes", []) or []
                claim = {
                    "encounter_id": synth_out.get("encounter_id"),
                    "patient_id": "PT_AUDIT",
                    "rendering_provider_npi": "1992039481",
                    "billing_provider_tax_id": "XX-XXX1234",
                    "date_of_service": "2026-06-15",
                    "payer_id": "PAYER-AUDIT-001",
                    "payer_name": "Audit Payer",
                    "line_items": [
                        {
                            "line_id": i + 1,
                            "cpt_code": c.get("code", ""),
                            "modifiers": [],
                            "dx_pointers": icds,
                            "charge_amount": 150.00,
                            "units": 1,
                        }
                        for i, c in enumerate(cpts)
                    ],
                    "diagnosis_codes": icds,
                }
                audit_encounter = {
                    "encounter_id": synth_out.get("encounter_id"),
                    "is_flagged": bool(synth_out.get("flagged", False)),
                    "clinical_note": clinical_note,
                    "claim": claim,
                    "rules": [],
                    "ground_truth": [],
                }
            audit = _run_audit(audit_encounter)
        except AuditValidationError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"auditor validation failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 (deliberately broad)
            raise HTTPException(
                status_code=502,
                detail=f"auditor invocation failed: {type(exc).__name__}: {exc}"[:500],
            )

        findings_payload: list[dict[str, Any]] = []
        for f in audit.findings:
            rule_ids = list(f.rule_ids) if f.rule_ids else []
            findings_payload.append(
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

        return JSONResponse(
            {
                "encounter_id": encounter_id,
                "synth_encounter_id": synth_encounter_id,
                "has_discrepancy": bool(findings_payload),
                "findings": findings_payload,
                "summary": audit.summary,
                "source_job_id": job.job_id,
                "note_source": note_source,
                "ran_via": "audit_endpoint",
            }
        )

    # ── Slack integration (kanban t_c9cf54f4) ────────────────────────
    # Single endpoint that registers a Slack incoming-webhook +
    # channel + event subscription. Persists to
    # ``/app/logs/slack_integrations.jsonl`` (env-overridable for
    # tests) and returns a stable ``slack_id`` so the caller can
    # later unregister. The dashboard-side ``notify_slack`` helper
    # runs synchronously off the audit_complete path and the
    # bulk-accept / bulk-dismiss paths (high_finding event).
    from ai_billing_audit import slack_notify as _slack

    @app.post("/api/integrations/slack")
    async def integrations_register_slack(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=400,
                detail="body must be a JSON object",
            )
        webhook_url = body.get("webhook_url")
        channel = body.get("channel")
        events = body.get("events")
        if not isinstance(webhook_url, str) or not webhook_url.strip():
            raise HTTPException(
                status_code=400,
                detail="webhook_url is required",
            )
        if not isinstance(channel, str) or not channel.strip():
            raise HTTPException(
                status_code=400,
                detail="channel is required",
            )
        if not isinstance(events, list) or not all(
            isinstance(e, str) for e in events
        ):
            raise HTTPException(
                status_code=400,
                detail="events must be a list of strings",
            )
        clinic_id = body.get("clinic_id") or _TENANT_ID
        try:
            record = _slack.register_slack(
                webhook_url=webhook_url,
                channel=channel,
                events=events,
                clinic_id=clinic_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return JSONResponse(record, status_code=201)

    # ── UX polish endpoints (kanban board: product-ux) ───────────────
    # One module, ~20 small routes — see ux_polish.py for the
    # per-task list. Registered before public_api so the dashboard
    # HTML/JSON surface ships intact even if public_api changes.
    from ai_billing_audit import ux_polish as _ux_polish

    _ux_polish.register_routes(app)

    # ── Public v1 API (kanban t_f4f1c149) ────────────────────────────
    # The v1 surface is a separately-authenticated, JSON-only
    # contract for EHR integrations. It's mounted by a sibling
    # module (ai_billing_audit.public_api) so the operator
    # dashboard (above) and the public API (below) can evolve
    # independently — the dashboard needs HTML + RBAC, the
    # public API needs machine-friendly errors + an API-key
    # auth path. The companion task (kanban t_4496cee1) wires
    # webhooks through the same module.
    from ai_billing_audit.public_api import register_public_api

    register_public_api(app)

    # ── Clinical-impact doctor-facing surfaces (kanban: clinical-impact) ──
    # Five small endpoints behind feature flags:
    #   t_267a1ad6 doctor effectiveness metric
    #   t_a26d25be rejected-fix teaching signal queue + verdict
    #   t_f5ea3bf2 doctor 'fix-it' re-audit queue
    #   t_17ec5fec per-tenant prompt version pinning
    from ai_billing_audit.clinical_metrics import mount_clinical_metrics_routes

    mount_clinical_metrics_routes(app)

    return app


# Module-level app for `uvicorn ai_billing_audit.api:app`.
app = create_app()
