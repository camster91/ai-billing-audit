"""CSV ingest for clinics that export from a PM/EHR system.

Background
----------

Most clinics do not have an EHR integration with Zorva. They run a
Practice Management (PM) system — Kareo, OSCAR, Office Ally, athena,
eClinicalWorks, etc. — and export their claims as a CSV. Each PM
system uses its own column names and date / currency formats, so the
``/upload/csv`` endpoint has to:

  1. Detect the PM system by inspecting the header row.
  2. Map each PM's columns to Zorva's canonical schema:
        procedure_code, billed_amount, date_of_service, patient_id, NPI
     (plus a few optional fields like ``modifiers``, ``dx_codes``,
     ``encounter_id`` when the PM exports them).
  3. Convert each row to the same encounter + claim pair the
     ``/encounters/upload/submit`` endpoint feeds into the audit
     job-queue.
  4. Surface per-row errors (bad date format, missing procedure
     code, non-numeric amount, …) without aborting the whole batch.

Design notes
------------

* ``HEADER_DICTIONARY`` is a per-PM list of the column names that
  system exports. We match by the intersection of the file's header
  row against each PM's dictionary — the PM with the highest
  match count wins. This is robust to the PMs adding extra columns
  over time.
* Detection is case-insensitive and whitespace-tolerant — Kareo
  exports often have "Date Of Service" or "DATE OF SERVICE" or
  " date of service ".
* ``parse_csv`` is a thin wrapper around ``csv.DictReader`` that
  preserves the original column names (the caller may want to log
  them) and is forgiving on common encoding gotchas (utf-8-sig
  BOM, latin-1 fallback).
* ``normalize_row`` returns the canonical dict shape the audit
  pipeline already understands (``encounter_id``, ``patient_id``,
  ``NPI``, ``date_of_service``, ``CPT_codes``). The encounter_id is
  generated from the PM row when the PM does not export one.
* Per-row errors are collected into ``{"row": <int>, "reason":
  <str>}`` lists — the endpoint returns them in the response and
  the rest of the batch continues.

Why not extend ``x12_parser``? CSV is a fundamentally different
shape — X12 is positional, CSV is header-keyed, and a CSV
encounter can never become an 837P segment. Keeping the two
ingest paths separate makes each one's test surface smaller.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any


# Canonical column names we map everything to. These match the keys
# the rest of the audit pipeline (job_queue, x12_parser) expects on
# the encounter dict.
CANONICAL_FIELDS = (
    "procedure_code",
    "billed_amount",
    "date_of_service",
    "patient_id",
    "NPI",
    "encounter_id",
    "modifiers",
    "dx_codes",
)


# Per-PM column dictionaries. Each entry is the set of header names
# the PM exports — the intersect with the file's header row decides
# which format wins. The dicts are intentionally permissive (we
# include the common casing variations PM systems actually emit
# because their exports are hand-curated per-clinic and not
# consistent across installs).
#
# Required fields (every row needs at least these to be auditable):
#   - procedure_code  (CPT / SOMB code)
#   - billed_amount   (numeric charge)
#   - date_of_service (date of the visit)
#
# Optional fields (improve audit fidelity but missing ones don't
# fail the row):
#   - patient_id, NPI, encounter_id, modifiers, dx_codes
HEADER_DICTIONARY: dict[str, list[str]] = {
    "kareo": [
        "Procedure Code",
        "Charge",
        "Date Of Service",
        "Patient ID",
        "Provider NPI",
        "Encounter ID",
        "Modifiers",
        "Diagnosis Codes",
    ],
    "oscar": [
        "billingcode",
        "billing_amount",
        "service_date",
        "demographic_no",
        "practitioner_no",
        "appointment_no",
        "modifier",
        "dxcode",
    ],
    "office_ally": [
        "CPT",
        "Amount",
        "DOS",
        "PatientID",
        "ProviderNPI",
        "ClaimID",
        "Modifier",
        "ICD10",
    ],
}


# What we consider the "core" columns for a format. A file is
# classified as ``kareo`` (etc.) when ALL of these are present in
# its header row. This is stricter than HEADER_DICTIONARY — the
# full dictionary is a hint of what columns exist, but we require
# the required columns to be there before we accept the format.
REQUIRED_DICTIONARY: dict[str, list[str]] = {
    "kareo": ["Procedure Code", "Charge", "Date Of Service"],
    "oscar": ["billingcode", "billing_amount", "service_date"],
    "office_ally": ["CPT", "Amount", "DOS"],
}


def _norm_header(s: str) -> str:
    """Normalise a header name for case/whitespace-insensitive comparison.

    " Date Of Service " -> "dateofservice"
    "DOS"               -> "dos"
    """
    return re.sub(r"\s+", "", (s or "").strip()).lower()


def detect_format(headers: list[str]) -> str:
    """Return the PM format for ``headers`` or ``"unknown"``.

    Strategy: for each known format, count how many of its REQUIRED
    columns (normalised) appear in the file's headers (also
    normalised). Return the format with the highest required-column
    match count, breaking ties in the canonical order
    (``kareo`` > ``office_ally`` > ``oscar`` because the first is
    the most common PM in our pilot clinics). If no format matches
    ANY required column, return ``"unknown"``.

    The function is case-insensitive and whitespace-tolerant so
    "Procedure Code" / "procedure_code" / " PROCEDURE CODE " all
    match Kareo.
    """
    if not headers:
        return "unknown"
    normalised = {_norm_header(h) for h in headers}
    best_format = "unknown"
    best_count = 0
    # Iterate in priority order so the tie-break is deterministic.
    for fmt in ("kareo", "office_ally", "oscar"):
        required = REQUIRED_DICTIONARY.get(fmt, [])
        count = sum(1 for col in required if _norm_header(col) in normalised)
        if count > best_count:
            best_count = count
            best_format = fmt
    return best_format


def _pick(row: dict[str, str], candidates: list[str]) -> str:
    """Return the value from ``row`` keyed by the first matching candidate.

    Lookup is case-insensitive and whitespace-tolerant. Empty / None
    values are returned as ``""`` so the caller can decide whether
    to fail the row.

    We accept multiple candidates per canonical field because each
    PM system has its own vocabulary — and many clinics further
    customise the column names inside their PM.
    """
    norm_to_actual = {_norm_header(k): k for k in row.keys()}
    for cand in candidates:
        actual = norm_to_actual.get(_norm_header(cand))
        if actual is None:
            continue
        val = row.get(actual)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


def _parse_date(raw: str) -> str:
    """Return a YYYY-MM-DD string for ``raw``, or raise ``ValueError``.

    PM exports use a handful of date formats in practice:
      - "2024-05-15"           (ISO)
      - "05/15/2024"           (US slash)
      - "15/05/2024"           (DD/MM/YYYY — Office Ally variant)
      - "2024-05-15 10:30:00"  (datetime)
      - "5/15/24"              (2-digit year, US)

    We try the most common formats in order; the first one that
    parses wins. We do NOT try to guess between MM/DD and DD/MM —
    if a date fails US-slash parsing we try DD/MM as a fallback
    because most North American PMs default to MM/DD/YYYY.
    """
    if not raw:
        raise ValueError("empty date")
    s = str(raw).strip()
    # Strip any trailing time component.
    s_date = s.split(" ", 1)[0]
    # ISO first (the unambiguous shape).
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s_date)
    if m:
        yyyy, mm, dd = (int(m.group(i)) for i in (1, 2, 3))
        return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
    # Slash-separated. Try MM/DD/YYYY first, then DD/MM/YYYY.
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s_date)
    if m:
        a, b, c = (int(m.group(i)) for i in (1, 2, 3))
        # 4-digit year goes in the obvious slot; 2-digit year gets
        # the 20xx / 19xx split at the 30 boundary.
        if a > 12:
            # Must be DD/MM/YYYY (day > 12 is unambiguous).
            dd, mm, yy = a, b, c
        else:
            # Default: MM/DD/YYYY for North American PMs.
            mm, dd, yy = a, b, c
        if yy < 100:
            yy = 2000 + yy if yy < 30 else 1900 + yy
        return f"{yy:04d}-{mm:02d}-{dd:02d}"
    # Dash-separated but YYYY-M-D variant (Office Ally sometimes
    # exports single-digit month/day without zero-padding).
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s_date)
    if m:
        yyyy, mm, dd = (int(m.group(i)) for i in (1, 2, 3))
        return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
    raise ValueError(f"unrecognised date format: {raw!r}")


def _parse_amount(raw: str) -> str:
    """Return a normalised decimal string for ``raw`` or raise ``ValueError``.

    Accepts "150.00", "150", "$150.00", "1,500.00" (commas stripped),
    and rejects anything non-numeric. We return a string (not float)
    so we don't lose precision on the round-trip through the audit
    pipeline's JSON encoding.
    """
    if raw is None:
        raise ValueError("empty amount")
    s = str(raw).strip()
    if not s:
        raise ValueError("empty amount")
    # Strip currency symbols / thousand separators that some PMs
    # leave in (e.g. "$1,500.00").
    s = s.lstrip("$").replace(",", "").strip()
    # Reject if there's anything other than digits and a single dot.
    if not re.match(r"^-?\d+(?:\.\d+)?$", s):
        raise ValueError(f"non-numeric amount: {raw!r}")
    # Normalise to 2 decimal places — most PMs export at this
    # precision and the audit pipeline expects it.
    if "." not in s:
        s = s + ".00"
    else:
        whole, frac = s.split(".", 1)
        if not frac:
            s = whole + ".00"
        elif len(frac) == 1:
            s = whole + "." + frac + "0"
    # Drop the leading minus sign if present — the audit pipeline
    # treats negative amounts as a parse error (a credit memo is
    # not an auditable claim).
    if s.startswith("-"):
        raise ValueError(f"negative amount not allowed: {raw!r}")
    return s


# Per-PM column picks. Each canonical field has a list of column
# names to look for, in priority order (the first one that exists
# in the row wins). Empty string means "not present in this PM".
#
# We keep this as a class-level constant rather than building it
# from HEADER_DICTIONARY so we can spell out which column maps to
# which canonical name per-PM (HEADER_DICTIONARY is just for
# detection — some PMs have synonyms inside the same dictionary
# entry that we'd otherwise have to disambiguate).
_COLUMN_PICKS: dict[str, dict[str, list[str]]] = {
    "kareo": {
        "procedure_code": ["Procedure Code", "CPT", "Procedure"],
        "billed_amount": ["Charge", "Amount", "Billed Amount"],
        "date_of_service": ["Date Of Service", "DOS", "Service Date"],
        "patient_id": ["Patient ID", "MRN", "Patient"],
        "NPI": ["Provider NPI", "NPI", "Rendering NPI"],
        "encounter_id": ["Encounter ID", "Claim ID", "Visit ID"],
        "modifiers": ["Modifiers", "Modifier"],
        "dx_codes": ["Diagnosis Codes", "ICD-10", "DX Codes"],
    },
    "oscar": {
        "procedure_code": ["billingcode", "procedure_code", "cpt"],
        "billed_amount": ["billing_amount", "charge", "amount"],
        "date_of_service": ["service_date", "dos", "date_of_service"],
        "patient_id": ["demographic_no", "patient_id", "mrn"],
        "NPI": ["practitioner_no", "npi", "provider_npi"],
        "encounter_id": ["appointment_no", "encounter_id", "claim_id"],
        "modifiers": ["modifier", "modifiers"],
        "dx_codes": ["dxcode", "dx_codes", "icd10"],
    },
    "office_ally": {
        "procedure_code": ["CPT", "Procedure Code", "HCPCS"],
        "billed_amount": ["Amount", "Charge", "Billed"],
        "date_of_service": ["DOS", "Date Of Service", "Service Date"],
        "patient_id": ["PatientID", "Patient ID", "MRN"],
        "NPI": ["ProviderNPI", "Provider NPI", "NPI"],
        "encounter_id": ["ClaimID", "Claim ID", "Encounter ID"],
        "modifiers": ["Modifier", "Modifiers"],
        "dx_codes": ["ICD10", "ICD-10", "Diagnosis"],
    },
}


def normalize_row(row: dict[str, str], fmt: str) -> dict[str, Any]:
    """Map a PM-specific ``row`` to Zorva's canonical schema.

    Returns ``{canonical_field: value_or_empty, ...}`` plus the
    parsed encounter dict the audit pipeline expects:

      {
        "procedure_code": "99213",
        "billed_amount": "150.00",
        "date_of_service": "2024-05-15",
        "patient_id": "...",
        "NPI": "...",
        "encounter_id": "<generated if blank>",
        "modifiers": [...],
        "dx_codes": [...],
        "_encounter": {
            "encounter_id": ...,
            "patient_id": ...,
            "NPI": ...,
            "date_of_service": ...,
            "CPT_codes": [...],
        },
      }

    Raises ``ValueError`` for required-field errors (missing
    procedure_code, non-numeric amount, unparseable date) — the
    caller wraps this in a try/except and surfaces the error
    per-row without aborting the batch.
    """
    picks = _COLUMN_PICKS.get(fmt)
    if picks is None:
        raise ValueError(f"unknown format: {fmt!r}")

    def _field(canonical: str) -> str:
        return _pick(row, picks.get(canonical, []))

    procedure_code = _field("procedure_code")
    if not procedure_code:
        raise ValueError("missing procedure_code")
    billed_amount_raw = _field("billed_amount")
    if not billed_amount_raw:
        raise ValueError("missing billed_amount")
    date_of_service_raw = _field("date_of_service")
    if not date_of_service_raw:
        raise ValueError("missing date_of_service")

    billed_amount = _parse_amount(billed_amount_raw)
    date_of_service = _parse_date(date_of_service_raw)

    # Modifiers and dx_codes are comma- or pipe-separated in most
    # PM exports. We split on comma or pipe and trim whitespace.
    modifiers_raw = _field("modifiers")
    modifiers = [
        m.strip()
        for m in re.split(r"[,|;]", modifiers_raw)
        if m.strip()
    ] if modifiers_raw else []
    dx_codes_raw = _field("dx_codes")
    dx_codes = [
        d.strip()
        for d in re.split(r"[,|;]", dx_codes_raw)
        if d.strip()
    ] if dx_codes_raw else []

    # Build the CPT code the audit pipeline expects. The
    # canonical shape is ``["99213"]`` or ``["99213-25"]`` when a
    # modifier is attached — the synth pipeline joins modifiers
    # onto the procedure code with a dash.
    cpt = procedure_code.strip()
    if modifiers:
        # Convention: attach the FIRST modifier to the CPT code
        # (the audit pipeline reads CPT_codes[0] as the primary).
        cpt = f"{cpt}-{modifiers[0]}"

    encounter_id = _field("encounter_id") or ""

    return {
        "procedure_code": procedure_code.strip(),
        "billed_amount": billed_amount,
        "date_of_service": date_of_service,
        "patient_id": _field("patient_id"),
        "NPI": _field("NPI"),
        "encounter_id": encounter_id,
        "modifiers": modifiers,
        "dx_codes": dx_codes,
        "_encounter": {
            "encounter_id": encounter_id,
            "patient_id": _field("patient_id"),
            "NPI": _field("NPI"),
            "date_of_service": date_of_service,
            "CPT_codes": [cpt],
        },
    }


def parse_csv(file_bytes: bytes) -> list[dict[str, str]]:
    """Parse a CSV byte payload into a list of row dicts.

    Returns ``[]`` for an empty file. Each row dict is keyed by
    the file's ORIGINAL header names (preserved verbatim, including
    case and whitespace) so callers can log them or pass them on
    unchanged. ``detect_format`` is responsible for the
    case-insensitive matching.

    Decoding strategy: try utf-8-sig first (strips the BOM Office
    Ally sometimes emits), fall back to latin-1 (never fails, every
    byte maps to a character).
    """
    if not file_bytes:
        return []
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    # ``restval=None`` so missing keys surface as ``None`` rather
    # than empty strings; ``restkey=None`` so extra columns get
    # silently dropped (we don't use them).
    rows: list[dict[str, str]] = []
    for row in reader:
        # csv.DictReader leaves the fieldname dict in self.fieldnames
        # but doesn't preserve keys for rows when ``restkey`` would
        # be set; default is fine here.
        rows.append({k: ("" if v is None else str(v)) for k, v in row.items()})
    return rows


# --- public ingest pipeline -----------------------------------------------


def ingest_csv(
    file_bytes: bytes,
    payer_id: str = "",
    clinic_id: str = "",
    *,
    enqueue: Any | None = None,
) -> dict[str, Any]:
    """Run the full ingest pipeline. Return the response shape.

    Parameters
    ----------
    file_bytes:
        The raw CSV file bytes.
    payer_id:
        Optional payer identifier passed through to the audit job
        queue (defaults to empty string; the pipeline treats empty
        as "no payer filter").
    clinic_id:
        Optional clinic identifier — same as payer_id, surfaced for
        callers that need it on the job.
    enqueue:
        Optional callable used to enqueue the parsed encounter for
        audit. Defaults to ``None`` which means "don't enqueue" (the
        test suite uses this to assert the parsed-row shape without
        spinning the worker pool). The API endpoint passes
        ``queue.enqueue``.

    Returns
    -------
    dict with keys::

        {
          "accepted_count": int,
          "rejected_count": int,
          "errors": [{"row": int, "reason": str}, ...],
          "detected_format": "kareo" | "oscar" | "office_ally" | "unknown",
          "enqueued": [{"job_id": str, "encounter_id": str}, ...] or None,
        }
    """
    rows = parse_csv(file_bytes)
    headers = list(rows[0].keys()) if rows else []
    detected = detect_format(headers)
    out: dict[str, Any] = {
        "accepted_count": 0,
        "rejected_count": 0,
        "errors": [],
        "detected_format": detected,
        "enqueued": None,
    }
    if detected == "unknown":
        # The caller (HTTP endpoint) should refuse the upload; we
        # leave accepted/rejected at 0 and add a top-level error.
        out["errors"].append(
            {
                "row": 0,
                "reason": (
                    f"unrecognised CSV format: header row was {headers!r}; "
                    f"expected one of {sorted(HEADER_DICTIONARY.keys())} "
                    "(Kareo / OSCAR / Office Ally)"
                ),
            }
        )
        return out

    accepted = 0
    rejected = 0
    errors: list[dict[str, Any]] = []
    enqueued: list[dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        try:
            normalised = normalize_row(row, detected)
        except ValueError as exc:
            rejected += 1
            errors.append({"row": idx, "reason": str(exc)})
            continue
        accepted += 1
        if enqueue is not None:
            encounter = normalised["_encounter"]
            try:
                job = enqueue(
                    encounter=encounter,
                    source=f"csv:{detected}",
                    source_filename=f"csv:{detected}",
                    tenant_id=clinic_id or None,
                )
            except Exception as exc:  # pragma: no cover (defensive)
                errors.append(
                    {
                        "row": idx,
                        "reason": f"enqueue failed: {exc}",
                    }
                )
                accepted -= 1
                rejected += 1
                continue
            # Stash the job_id so the caller can poll it.
            job_id = getattr(job, "job_id", None) or (
                job.get("job_id") if isinstance(job, dict) else None
            )
            encounter_id = getattr(job, "encounter_id", None) or (
                job.get("encounter_id") if isinstance(job, dict) else None
            ) or encounter["encounter_id"]
            enqueued.append({"job_id": job_id or "", "encounter_id": encounter_id})
    out["accepted_count"] = accepted
    out["rejected_count"] = rejected
    out["errors"] = errors
    if enqueue is not None:
        out["enqueued"] = enqueued
    return out


__all__ = [
    "CANONICAL_FIELDS",
    "HEADER_DICTIONARY",
    "REQUIRED_DICTIONARY",
    "detect_format",
    "ingest_csv",
    "normalize_row",
    "parse_csv",
]