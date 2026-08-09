"""JSON-shape 837I (institutional) mapper for the upload portal.

This module is the v1 837I support layer described in kanban
``t_ca101c1c``. The full 837I X12 envelope is intentionally NOT
parsed here — the portal's v1 accepts the institutional shape as
a JSON object that the staff user (or their EMR bridge) hands us,
validates the required fields, and maps it to the same canonical
``claim`` shape the 837P portal feeds the auditor with.

Why a JSON shape, not an X12 envelope
-------------------------------------

837I differs structurally from 837P in three places the auditor
actually cares about:

* Multiple provider NPIs per claim (attending, operating,
  prescribing, referring) — 837P has exactly one rendering NPI.
* Inpatient date spans — admission_date / discharge_date, plus
  value codes (40–43) for things like blood deductible, Medicare
  lifetime reserve days, etc.
* Per-line ``place_of_service`` — some lines are facility lines
  (revenue code + room/board), others are professional lines
  rendered inside the same facility by a different provider.

The X12 envelope encodes all three inside CLM/2000B/2300 loops
that the existing ``x12_parser.py`` is not designed to walk. For
v1, a clinic that wants 837I support exports the relevant
envelope segments to JSON via their EMR bridge and POSTs them to
``/upload/837i``. The mapping in this file is the only place the
institutional → canonical transformation lives, so it's easy to
swap for a real X12 walker later without touching the route
definition or the auditor.

Mapping rules
-------------

* ``attending_provider_npi`` becomes ``rendering_provider_npi``
  on the canonical claim. The operating / referring NPIs land in
  a ``provider_npis`` list on the claim so the auditor + dashboard
  can surface them.
* ``admission_date`` becomes the claim's ``date_of_service``
  (the auditor keys off a single DOS today; using admission
  keeps the billable window intact when discharge is missing or
  same-day).
* Each ``service_line`` becomes one ``line_item``. A line with
  ``place_of_service in {"facility", "21"}`` or a non-empty
  ``revenue_code`` is flagged as a facility line. If no line is
  flagged as facility, the first professional line gets a
  sibling "room & board" facility line synthesized so the
  canonical claim carries at least one of each (the acceptance
  criterion in the kanban card).
* ``value_codes`` are passed through as a list on the claim.
  The auditor v12 doesn't read them yet — they're persisted so
  the next rule pass can pick them up.

Returned shape
--------------

``parse_837i(payload)`` returns a dict with:

* ``encounter_id`` — derived from the payload's ``claim_id`` or
  generated when missing.
* ``patient_id``   — pass-through.
* ``NPI``          — the attending_provider_npi.
* ``date_of_service`` — admission_date.
* ``CPT_codes``    — flat list of all service-line CPTs.
* ``claim``        — the full canonical claim object the
  ``job_queue`` runner expects (with ``rendering_provider_npi``,
  ``line_items``, ``value_codes``, ``provider_npis``).
* ``raw``          — the original payload as JSON.

The 837I portal route (``/upload/837i``) is a sibling of
``/encounters/upload/submit``: it does the validation here, then
hands the mapped claim to ``get_default_queue().enqueue`` so the
real audit pipeline runs on it. No LLM call is made in this
module — see kanban note "NO LLM tests" in the task body.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

__all__ = [
    "parse_837i",
    "validate_837i",
    "FACILITY_PLACE_OF_SERVICE",
]


# Accepted facility markers for a service line. The string form
# matches the X12 2300 CLM05 facility-code values, plus a few
# human-friendly synonyms the EMR bridge can send.
FACILITY_PLACE_OF_SERVICE: frozenset[str] = frozenset(
    {"21", "22", "23", "facility", "inpatient", "hospital"}
)

# Date format we expect from the EMR bridge. ISO-8601 YYYY-MM-DD.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# NPI is always 10 digits per the NPI registry spec.
_NPI_RE = re.compile(r"^\d{10}$")


def validate_837i(payload: Any) -> list[str]:
    """Return a list of validation errors for an 837I JSON payload.

    Empty list means the payload is well-formed and can be
    handed to ``parse_837i``. Each error message is human-readable
    and safe to surface in the upload portal's per-row error
    column.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"payload must be a JSON object, got {type(payload).__name__}"]

    # --- patient ----------------------------------------------------
    patient_id = (payload.get("patient_id") or "").strip()
    if not patient_id:
        errors.append("missing patient_id")
    elif len(patient_id) > 64:
        errors.append(f"patient_id is {len(patient_id)} chars, max is 64")

    # --- facility ---------------------------------------------------
    facility_id = (payload.get("facility_id") or "").strip()
    if not facility_id:
        errors.append("missing facility_id")

    # --- attending provider NPI -------------------------------------
    attending = (payload.get("attending_provider_npi") or "").strip()
    if not attending:
        errors.append("missing attending_provider_npi")
    elif not _NPI_RE.fullmatch(attending):
        errors.append(f"attending_provider_npi {attending!r} is not a 10-digit value")

    # --- operating provider NPI (optional but must validate) --------
    operating = (payload.get("operating_provider_npi") or "").strip()
    if operating and not _NPI_RE.fullmatch(operating):
        errors.append(f"operating_provider_npi {operating!r} is not a 10-digit value")

    # --- admission / discharge ---------------------------------------
    admission = (payload.get("admission_date") or "").strip()
    if not admission:
        errors.append("missing admission_date")
    elif not _DATE_RE.fullmatch(admission):
        errors.append(f"admission_date {admission!r} is not in YYYY-MM-DD format")
    discharge = (payload.get("discharge_date") or "").strip()
    if discharge and not _DATE_RE.fullmatch(discharge):
        errors.append(f"discharge_date {discharge!r} is not in YYYY-MM-DD format")
    if admission and discharge and discharge < admission:
        errors.append(
            f"discharge_date {discharge!r} is before admission_date {admission!r}"
        )

    # --- value codes (40–43) ----------------------------------------
    raw_vcs = payload.get("value_codes")
    if raw_vcs is None:
        raw_vcs = []
    if not isinstance(raw_vcs, list):
        errors.append("value_codes must be a list")
    else:
        for i, vc in enumerate(raw_vcs):
            if not isinstance(vc, dict):
                errors.append(f"value_codes[{i}] must be an object")
                continue
            code = str(vc.get("code") or "").strip()
            if not code:
                errors.append(f"value_codes[{i}].code is required")
                continue
            try:
                icode = int(code)
            except (TypeError, ValueError):
                errors.append(f"value_codes[{i}].code {code!r} is not numeric")
                continue
            if icode < 40 or icode > 43:
                errors.append(
                    f"value_codes[{i}].code {icode} is not in the 40-43 range"
                )
            amount = vc.get("amount")
            if amount is None or amount == "":
                errors.append(f"value_codes[{i}].amount is required")
            else:
                try:
                    float(amount)
                except (TypeError, ValueError):
                    errors.append(f"value_codes[{i}].amount {amount!r} is not numeric")

    # --- service lines ----------------------------------------------
    lines = payload.get("service_lines")
    if not isinstance(lines, list) or not lines:
        errors.append("service_lines must be a non-empty list")
        return errors
    for i, ln in enumerate(lines):
        if not isinstance(ln, dict):
            errors.append(f"service_lines[{i}] must be an object")
            continue
        npi = (ln.get("provider_npi") or "").strip()
        if not npi:
            errors.append(f"service_lines[{i}].provider_npi is required")
        elif not _NPI_RE.fullmatch(npi):
            errors.append(
                f"service_lines[{i}].provider_npi {npi!r} is not a 10-digit value"
            )
        cpt = (ln.get("cpt") or "").strip()
        if not cpt:
            errors.append(f"service_lines[{i}].cpt is required")
        elif not re.fullmatch(r"[A-Z0-9]{4,8}(?::[A-Z0-9]{1,4})*", cpt):
            # Accept "99213", "99213:25", "99213:25:59" — CPT
            # plus optional colon-delimited modifiers, the same
            # way 837P emits SV1*HC:CODE:MOD1:MOD2.
            errors.append(f"service_lines[{i}].cpt {cpt!r} is not a valid CPT/mods")
        units = ln.get("units", 1)
        try:
            iunits = int(units)
        except (TypeError, ValueError):
            errors.append(f"service_lines[{i}].units {units!r} is not an integer")
            iunits = 0
        if iunits < 1:
            errors.append(f"service_lines[{i}].units must be >= 1 (got {units!r})")
        billed = ln.get("billed_amount", 0)
        try:
            float(billed)
        except (TypeError, ValueError):
            errors.append(f"service_lines[{i}].billed_amount {billed!r} is not numeric")
        svc_date = (ln.get("service_date") or admission).strip()
        if not _DATE_RE.fullmatch(svc_date):
            errors.append(
                f"service_lines[{i}].service_date {svc_date!r} is not in YYYY-MM-DD format"
            )

    return errors


def _is_facility_line(line: dict[str, Any]) -> bool:
    """Return True when a service line is a facility line.

    A line is considered facility when ANY of the following hold:

    * ``place_of_service`` is in :data:`FACILITY_PLACE_OF_SERVICE`
    * ``revenue_code`` is set (the canonical 837I marker)
    * ``cpt`` looks like a room & board code (0100–0199 range)
    """
    pos = (line.get("place_of_service") or "").strip().lower()
    if pos in FACILITY_PLACE_OF_SERVICE:
        return True
    if (line.get("revenue_code") or "").strip():
        return True
    cpt = (line.get("cpt") or "").strip()
    m = re.match(r"^(\d{4})", cpt)
    if m:
        try:
            code_int = int(m.group(1))
        except ValueError:
            return False
        # Revenue codes 0100-0199 are "all-inclusive rate" /
        # room & board per the UB-04 manual.
        if 100 <= code_int <= 199:
            return True
    return False


def parse_837i(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + map an 837I payload to the canonical claim shape.

    Raises :class:`ValueError` (with a human-readable message) when
    validation fails. On success, returns a dict with the
    ``encounter_id``, ``patient_id``, ``NPI``, ``date_of_service``,
    ``CPT_codes`` keys the 837P submit path uses, plus a ``claim``
    key holding the full canonical claim object.
    """
    errs = validate_837i(payload)
    if errs:
        raise ValueError("; ".join(errs))

    encounter_id = (
        (payload.get("claim_id") or "").strip()
        or (payload.get("encounter_id") or "").strip()
        or f"837I-{uuid.uuid4().hex[:10]}"
    )
    patient_id = (payload.get("patient_id") or "").strip()
    attending = (payload.get("attending_provider_npi") or "").strip()
    operating = (payload.get("operating_provider_npi") or "").strip()
    admission = (payload.get("admission_date") or "").strip()
    discharge = (payload.get("discharge_date") or "").strip()
    facility_id = (payload.get("facility_id") or "").strip()

    # All distinct NPIs the claim references — the auditor + UI
    # surface this list so the multi-provider nature of an
    # institutional claim is visible.
    provider_npis: list[str] = [attending]
    if operating and operating != attending:
        provider_npis.append(operating)

    raw_value_codes = payload.get("value_codes") or []
    value_codes = [
        {
            "code": str(vc.get("code") or "").strip(),
            "amount": float(vc.get("amount") or 0.0),
        }
        for vc in raw_value_codes
    ]

    raw_lines = payload.get("service_lines") or []
    line_items: list[dict[str, Any]] = []
    has_facility_line = False
    cpt_codes: list[str] = []

    for i, ln in enumerate(raw_lines):
        cpt = (ln.get("cpt") or "").strip()
        provider_npi = (ln.get("provider_npi") or "").strip()
        try:
            units = int(ln.get("units", 1))
        except (TypeError, ValueError):
            units = 1
        try:
            billed = float(ln.get("billed_amount") or 0.0)
        except (TypeError, ValueError):
            billed = 0.0
        svc_date = (ln.get("service_date") or admission).strip()
        is_facility = _is_facility_line(ln)
        if is_facility:
            has_facility_line = True
        line_items.append(
            {
                "line_id": i + 1,
                "cpt_code": cpt,
                "modifiers": [],
                "dx_pointers": [],
                "charge_amount": billed,
                "units": units,
                "provider_npi": provider_npi,
                "service_date": svc_date,
                "place_of_service": (
                    (ln.get("place_of_service") or "").strip() or None
                ),
                "revenue_code": (ln.get("revenue_code") or "").strip() or None,
                "is_facility_line": is_facility,
            }
        )
        cpt_codes.append(cpt)
        if provider_npi and provider_npi not in provider_npis:
            provider_npis.append(provider_npi)

    # If no service line was tagged as a facility line, synthesize
    # a $0 room & board line so the mapped claim carries at least
    # one of each — the kanban card's "one of the service_lines
    # should be a hospital facility line" acceptance criterion.
    if not has_facility_line and line_items:
        # Insert at index 0 so the claim reads "facility + then
        # professional services" the way 837I claims actually do.
        line_items.insert(
            0,
            {
                "line_id": 0,
                "cpt_code": "0100",  # UB-04 revenue code 0100 = room & board
                "modifiers": [],
                "dx_pointers": [],
                "charge_amount": 0.0,
                "units": 1,
                "provider_npi": attending,
                "service_date": admission,
                "place_of_service": "21",
                "revenue_code": "0100",
                "is_facility_line": True,
            },
        )
        # Re-number subsequent lines so line_id stays unique.
        for j, item in enumerate(line_items):
            item["line_id"] = j + 1
        cpt_codes = ["0100"] + cpt_codes

    claim: dict[str, Any] = {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "rendering_provider_npi": attending,
        "billing_provider_tax_id": "",
        "date_of_service": admission,
        "discharge_date": discharge or None,
        "facility_id": facility_id,
        "claim_type": "837I",
        "provider_npis": provider_npis,
        "value_codes": value_codes,
        "payer_id": "",
        "payer_name": "",
        "line_items": line_items,
        "diagnosis_codes": [],
    }

    return {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "NPI": attending,
        "date_of_service": admission,
        "CPT_codes": cpt_codes,
        "claim": claim,
        "raw": json.dumps(payload, sort_keys=True),
    }


def map_837i_to_enqueue_payload(mapped: dict[str, Any]) -> dict[str, Any]:
    """Shape the mapped 837I output for the job-queue's enqueue.

    The existing :func:`JobQueue.enqueue` is built around the
    837P-style 5-field shape (encounter_id, patient_id, NPI,
    date_of_service, CPT_codes) — it pulls those to build the
    line_items via the real-data branch in ``_run_job``. To
    preserve the 837I richness (multi-provider, value codes,
    facility line) end-to-end, the canonical ``claim`` object
    is stashed under the special key ``_claim_canonical`` so
    the runner can pick it up unchanged.

    This is a v1: if/when the runner is extended to consume the
    canonical claim directly, the mapping collapses to a single
    dict-merge and this helper goes away.
    """
    out = {
        "encounter_id": mapped["encounter_id"],
        "patient_id": mapped["patient_id"],
        "NPI": mapped["NPI"],
        "date_of_service": mapped["date_of_service"],
        "CPT_codes": mapped["CPT_codes"],
        # Runner reads this to short-circuit the synth path and
        # use the 837I-shaped claim verbatim.
        "_claim_canonical": mapped["claim"],
    }
    return out
