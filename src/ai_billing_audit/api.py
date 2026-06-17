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
import zipfile
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["highlight_quote"] = _highlight_quote

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
            cards.append(
                {
                    "encounter_id": entry.encounter_id,
                    "difficulty": entry.difficulty,
                    "summary": entry.summary,
                    "is_flagged": bool(record.get("is_flagged")) if record else False,
                    "n_findings": n_findings,
                    "available": record is not None,
                }
            )
        return templates.TemplateResponse(
            request,
            "index.html",
            {"cards": cards, "n_registered": len(cards)},
        )

    @app.get("/encounter/{encounter_id}", response_class=HTMLResponse)
    def encounter_detail(request: Request, encounter_id: str) -> HTMLResponse:
        demo = get_demo_encounter(encounter_id)
        if demo is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"encounter {encounter_id!r} is not registered on the "
                    "demo dashboard. Use one of the registered ids."
                ),
            )
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
                "findings": findings,
                "n_findings": len(findings),
            },
        )

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

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": app.version,
            "title": app.title,
            "n_registered": len(list_demo_encounters()),
        }

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

    return app


# Module-level app for `uvicorn ai_billing_audit.api:app`.
app = create_app()
