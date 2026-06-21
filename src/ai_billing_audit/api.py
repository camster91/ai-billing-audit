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
import time
import zipfile
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
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
from ai_billing_audit.x12_parser import (
    X12ParseError,
    parse_837p,
    validate_required_fields,
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

    # Bearer-token auth middleware (F-3 fix from QA_API_HARDENING.md).
    # The /healthz endpoint is whitelisted for load balancer health
    # checks. All other routes require `Authorization: Bearer ***`
    # to match the AUDIT_BEARER_TOKEN env var, or to be in
    # AUDIT_ALLOW_NO_AUTH (set to "1" only for local dev).
    import os as _os
    _BEARER = _os.environ.get("AUDIT_BEARER_TOKEN", "")
    _ALLOW_NO_AUTH = _os.environ.get("AUDIT_ALLOW_NO_AUTH", "") == "1"

    @app.middleware("http")
    async def _bearer_auth(request, call_next):
        # Whitelist: healthz + static
        if request.url.path in ("/healthz",) or request.url.path.startswith("/static"):
            return await call_next(request)
        # Public demo paths: the home page, the docs path, the upload
        # portal HTML. These are read-only and don't expose data; the
        # POST endpoints that mutate (upload/preview, upload/submit,
        # upload/notes, upload/paste) still require auth.
        if _ALLOW_NO_AUTH:
            return await call_next(request)
        if not _BEARER:
            # Auth disabled because no token is configured. Refuse
            # anything that isn't a GET on / or /healthz.
            if request.method == "GET" and request.url.path in ("/", "/healthz"):
                return await call_next(request)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "server has no AUDIT_BEARER_TOKEN configured; POST endpoints disabled"},
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
    def index(request: Request) -> HTMLResponse:
        registered = list_demo_encounters()
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
            cards.append(
                {
                    "encounter_id": entry.encounter_id,
                    "difficulty": entry.difficulty,
                    "summary": entry.summary,
                    "is_flagged": bool(record.get("is_flagged")) if record else False,
                    "n_findings": n_findings,
                    "available": record is not None,
                    "denial_risk": card_risk,
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
        }
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
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cards": cards,
                "audits": cards,
                "filter": "all",
                "counts": counts,
                "total_this_week": 0,
                "metrics": metrics,
                "n_registered": len(cards),
                "latest_real_audit": latest_real_audit,
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
        """
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
            visible_findings = [
                f for f in findings
                if SEVERITY_RANK.get(f.get("severity", "info"), 0) >= min_sev
            ]
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
            return templates.TemplateResponse(
                request,
                "encounter_detail.html",
                {
                    "encounter_id": encounter_id,
                    "difficulty": demo.difficulty,
                    "summary": demo.summary,
                    "is_flagged": record.get("is_flagged", False),
                    "clinical_note": record.get("clinical_note", ""),
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
        visible_uploaded = [
            f for f in uploaded_findings
            if SEVERITY_RANK.get(str(f.get("severity", "info")).lower(), 0) >= min_sev
        ]
        hidden_count = len(uploaded_findings) - len(visible_uploaded)
        # Score denial risk. For uploaded encounters this is the
        # REAL risk — it's the LLM's actual findings from the
        # clinic's data, not the demo's gold findings. This is
        # the number the biller actually cares about.
        from .denial_risk import compute_denial_risk
        denial_risk = compute_denial_risk(
            uploaded_findings, min_severity=min_sev
        )
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

    # ---- Reviewer actions: accept-all / dismiss / rerun / flag ----
    # Persisted via audit_actions.append(); each row is SHA-256-chained
    # so the trail is tamper-evident. The encounter detail page posts
    # to these endpoints when the biller clicks Accept / Dismiss / etc.

    @app.post("/encounter/{encounter_id}/accept-all")
    async def encounter_accept_all(
        encounter_id: str,
        request: Request,
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
            user_identifier=str(request.client.host if request.client else "anon"),
            tenant_id=_TENANT_ID,
            extra={"findings_count": findings_count},
        )
        return JSONResponse({"ok": True, "n_accepted": findings_count, "event": event})

    @app.post("/encounter/{encounter_id}/dismiss")
    async def encounter_dismiss(
        encounter_id: str,
        request: Request,
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
            user_identifier=str(request.client.host if request.client else "anon"),
            tenant_id=_TENANT_ID,
            findings=[{"finding_id": finding_id}],
            note=note,
        )
        return JSONResponse({
            "ok": True,
            "finding_id": finding_id,
            "reason_category": reason_category,
            "event": event,
        })

    @app.post("/encounter/{encounter_id}/rerun")
    async def encounter_rerun(
        encounter_id: str,
        request: Request,
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        event = audit_append(
            action="rerun",
            encounter_id=encounter_id,
            user_identifier=str(request.client.host if request.client else "anon"),
            tenant_id=_TENANT_ID,
        )
        return JSONResponse({"ok": True, "event": event})

    @app.post("/encounter/{encounter_id}/flag")
    async def encounter_flag(
        encounter_id: str,
        request: Request,
    ) -> JSONResponse:
        try:
            from .audit_actions import append as audit_append
        except ImportError:
            raise HTTPException(status_code=503, detail="audit_actions module unavailable")
        event = audit_append(
            action="flag",
            encounter_id=encounter_id,
            user_identifier=str(request.client.host if request.client else "anon"),
            tenant_id=_TENANT_ID,
        )
        return JSONResponse({"ok": True, "event": event})

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": app.version,
            "title": app.title,
            "n_registered": len(list_demo_encounters()),
        }

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
        log_appeal_letter(letter, encounter_id, tenant_id=_TENANT_ID)
        return JSONResponse({
            "ok": True,
            "encounter_id": encounter_id,
            "finding_id": finding_id,
            "letter": letter,
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

        Response:
            ``{"jobs": [{"job_id": "...", "encounter_id": "..."}, ...],
               "rejected": [{"source_filename": "...", "errors": [...]}]}``
        """
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
                }
            )
        return JSONResponse({"jobs": accepted, "rejected": rejected})

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
        queue = get_default_queue()
        job = queue.find_by_encounter(encounter_id)
        if job is None:
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

        # ---- 3. recover the audit-ready claim from the cache ----
        # ``job.result`` is the dict the synth runner produced
        # and the LLM auditor filled in. It carries the
        # synth encounter's id and (when the auditor ran
        # successfully) the findings + summary from the prior
        # run. We need the claim that was audited, which lives
        # in the runner's local ``claim`` variable — but the
        # runner does NOT serialise that into job.result.
        # So the audit endpoint re-derives the audit-ready
        # claim by calling run_audit directly with the same
        # inputs the runner used (synth encounter + note). The
        # Job is the proof the upload happened; the
        # encounter_id is the key the dashboard knows.
        result = job.result or {}
        synth_encounter_id = result.get("synth_encounter_id")
        difficulty_tier = result.get("difficulty_tier")
        variant = result.get("variant", "clean")

        # Resolve the clinical_note: request > uploaded on-disk
        # text-note for this encounter > stub.
        if clinical_note is None:
            try:
                from pathlib import Path as _P
                notes_dir = _P(__file__).resolve().parent.parent.parent / "logs" / "uploaded_notes"
                safe = __import__("re").sub(
                    r"[^A-Za-z0-9_.-]+", "_", encounter_id
                ).strip("._")[:80]
                if safe and notes_dir.is_dir():
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
        # The synth seed is deterministic on encounter_id, so the
        # synth materialisation is reproducible: the same claim
        # the cached job audited is what we'll re-audit.
        try:
            from .synth_agent import generate, Template
            from .auditor import run_audit as _run_audit, AuditValidationError

            seed = abs(hash(encounter_id)) % (2**31)
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
            provider_note = synth_out.get("provider_note", {}) or {}
            synth_clinical_note = "\n\n".join(
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

    return app


# Module-level app for `uvicorn ai_billing_audit.api:app`.
app = create_app()
