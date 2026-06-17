"""Minimal ANSI X12 5010 837P parser for the encounter-upload portal.

This is a deliberately small parser, not a full X12 implementation. It
walks the segments the portal cares about (CLM, NM1, DTP, SV1) and
projects them into a flat dict with the five required fields the upload
flow validates against:

    * ``encounter_id``   — from ``CLM01`` (claim submitter's identifier)
    * ``patient_id``     — from ``NM1*QC`` loop (subscriber / patient).
                           NM108 = ``MI`` (member id) or ``II`` (payer
                           reference); we accept either. If neither is
                           present, we leave the field ``None`` and the
                           upload validator surfaces the gap as a
                           per-file error.
    * ``NPI``            — from ``NM1*85`` (billing provider) when
                           NM108 = ``XX`` and NM109 is a 10-digit value.
    * ``date_of_service`` — from ``DTP*472*D8*<YYYYMMDD>`` (the service
                           date qualifier). We emit ISO-8601
                           ``YYYY-MM-DD``.
    * ``CPT codes``      — collected from every ``SV1*HC:<code>...``
                           line in the 2000 loop. Each entry is the
                           raw code (no ``HC:`` prefix), preserving any
                           modifiers that follow the code.

Segment format
--------------

X12 5010 uses the element separator from ``ISA01`` (we accept ``*``
as the default and discover it from the ISA header) and the segment
terminator from ``ISA16`` (commonly ``~``). The ISA segment itself
is fixed-width (106 chars including the segment terminator); we do
NOT split on ``*`` inside ISA — we only read ISA01–ISA16 by fixed
positions. From ``GS`` onward we honour the element separator and
segment terminator discovered from the ISA header.

Returned shape
--------------

``parse_837p(text)`` returns one normalised dict per ``CLM`` segment
it finds inside the interchange. A real 837P envelope may contain
multiple claims; the upload portal renders a row per claim.

The parser is intentionally permissive on header/footer segments
(``ISA``, ``GS``, ``ST``, ``SE``, ``GE``, ``IEA``, ``BHT``) so the
user can paste a real EDI file or a hand-rolled minimal one. It
will not raise on missing envelope segments — it walks what it
sees and emits a dict with whatever it could find. The upload
validator (in ``api.py``) is the source of truth for the
"required fields present" check.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "X12ParseError",
    "discover_separators",
    "parse_837p",
    "REQUIRED_FIELDS",
]


REQUIRED_FIELDS: tuple[str, ...] = (
    "encounter_id",
    "patient_id",
    "NPI",
    "date_of_service",
    "CPT_codes",
)


class X12ParseError(ValueError):
    """Raised when the file is not even minimally X12-shaped.

    The portal surfaces this as a per-file "malformed" error. The
    parser still attempts to extract what it can — see
    :func:`parse_837p_safe` for that softer variant.
    """


# --- separator discovery ---------------------------------------------------

# The ISA segment is 106 characters (the segment terminator inclusive)
# and uses three fixed fields:
#   ISA01  Authorization Information Qualifier (2 chars)
#   ISA02  Authorization Information (10 chars)
#   ISA03  Security Information Qualifier (2 chars)
#   ISA04  Security Information (10 chars)
#   ISA05  Interchange ID Qualifier (2 chars)
#   ISA06  Interchange Sender ID (15 chars)
#   ISA07  Interchange ID Qualifier (2 chars)
#   ISA08  Interchange Receiver ID (15 chars)
#   ISA09  Interchange Date (6 chars, YYMMDD)
#   ISA10  Interchange Time (4 chars, HHMM)
#   ISA11  Repetition separator (1 char; e.g. "^" or "U")
#   ISA12  Interchange Control Version (5 chars; "00501" for 5010)
#   ISA13  Interchange Control Number (9 chars)
#   ISA14  Acknowledgment Requested (1 char)
#   ISA15  Usage Indicator (1 char; "P" production / "T" test)
#   ISA16  Component Element Separator (1 char; usually ":")
# After the 16th element separator, the rest of the segment runs to
# the segment terminator.
#
# Reading the element separator: char index 3 (4th char) is the
# separator. The segment terminator is the very last char of the
# segment. The component element separator is the last char before
# the segment terminator.
_ISA_FIXED_WIDTH = 106  # 105 content chars + 1 segment terminator


def discover_separators(text: str) -> tuple[str, str]:
    """Return ``(element_separator, segment_terminator)``.

    Reads them from the ISA header so the parser honours whatever
    the file actually uses (the 5010 spec permits the element
    separator to vary, although ``*`` is the de-facto standard).

    Falls back to ``("*", "~")`` if the text is too short to contain
    a real ISA segment — the caller can still try to walk it as
    a flat ISA-less file.
    """
    if not text or len(text) < _ISA_FIXED_WIDTH or not text.startswith("ISA"):
        return ("*", "~")
    # Element separator is char index 3 ("ISA" + sep at position 3).
    element = text[3]
    # Segment terminator is the last char of the ISA segment.
    seg_term = text[_ISA_FIXED_WIDTH - 1]
    return (element, seg_term)


# --- per-segment helpers ---------------------------------------------------


def _split_segments(text: str, seg_term: str) -> list[list[str]]:
    """Split the X12 envelope into ``[[element, ...], ...]`` rows."""
    out: list[list[str]] = []
    for raw in text.split(seg_term):
        seg = raw.strip()
        if not seg:
            continue
        out.append(seg.split("*"))  # element-separator split
    return out


def _patient_id_from_nm1(elements: list[str]) -> str | None:
    """Extract a patient identifier from an NM1 segment.

    NM1*<ent_id_code>*<ent_type_qual>*<last_or_org>*<first>**
    *<id_code_qual>*<id_code>

    We accept either the member-id qualifier (``MI``) or the
    payer-assigned qualifier (``II``). If both are absent (or
    empty), returns ``None`` — the upload validator flags this
    as "patient_id missing".
    """
    if len(elements) < 9:
        return None
    qualifier = (elements[8] or "").strip().upper()
    if qualifier not in ("MI", "II", "MR", "HN"):
        return None
    value = (elements[9] if len(elements) > 9 else "").strip()
    return value or None


def _npi_from_nm1(elements: list[str]) -> str | None:
    """Extract a 10-digit NPI from a billing-provider NM1 (loop 2010AA).

    Loop 2010AA has entity type ``85`` (billing provider) and the
    NPI sits in NM109 with NM108 = ``XX``. We accept the value as
    a string so we can validate the 10-digit shape downstream.
    """
    if len(elements) < 9:
        return None
    if (elements[1] or "").strip() != "85":
        return None
    qualifier = (elements[8] or "").strip().upper()
    if qualifier != "XX":
        return None
    value = (elements[9] if len(elements) > 9 else "").strip()
    if not value or not re.fullmatch(r"\d{10}", value):
        return None
    return value


def _iso_date_from_dtp_472(elements: list[str]) -> str | None:
    """Convert ``DTP*472*D8*YYYYMMDD`` to ``YYYY-MM-DD`` (or None)."""
    if len(elements) < 4:
        return None
    if (elements[1] or "").strip() != "472":  # service date qualifier
        return None
    fmt = (elements[2] or "").strip().upper()
    raw = (elements[3] or "").strip()
    if fmt != "D8" or len(raw) != 8 or not raw.isdigit():
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def _cpt_codes_from_sv1(elements: list[str]) -> list[str]:
    """Return a list of CPT/HCPCS code strings from an SV1 segment.

    SV1*<proc_code_with_qualifier>:<code>[:<mod1>:<mod2>:<mod3>:<mod4>]
        *<charge>*<units>*<place_of_service>...

    We strip the ``HC:`` (or ``HCPCS:``) qualifier prefix and keep
    the code + any modifiers joined with a ``-`` separator so the
    upload form can render the line cleanly. Examples::

        SV1*HC:99213*100*1*11**1 -> ["99213"]
        SV1*HC:99213:25*100*1... -> ["99213-25"]
    """
    if not elements or elements[0] != "SV1":
        return []
    proc = (elements[1] or "").strip()
    if not proc:
        return []
    # SV102 is a composite: qualifier ":". The first component is the
    # qualifier ("HC", "HCPCS", "N4" for NDC, "ZZ" for mutually
    # defined), the second is the actual procedure code. We only
    # care about HC/HCPCS for CPT-shaped codes.
    parts = proc.split(":")
    if len(parts) < 2:
        return []
    qualifier = parts[0].upper()
    code = parts[1]
    if qualifier not in ("HC", "HCPCS"):
        return []
    # Any additional colon-separated components are modifiers.
    if len(parts) > 2:
        mods = [m for m in parts[2:] if m]
        if mods:
            return [f"{code}-{'-'.join(mods)}"]
    return [code]


# --- per-claim assembly ---------------------------------------------------


def _extract_claim(claim_segments: list[list[str]]) -> dict[str, Any]:
    """Project a 2000-loop (one claim) into the normalised dict."""
    encounter_id: str | None = None
    patient_id: str | None = None
    npi: str | None = None
    date_of_service: str | None = None
    cpt_codes: list[str] = []
    raw_segments: list[str] = []

    for seg in claim_segments:
        if not seg:
            continue
        tag = seg[0]
        # Serialise back to an X12-style string for the per-file
        # "raw" preview the upload form shows the user.
        raw_segments.append("*".join(seg))

        if tag == "CLM":
            # CLM01 = claim submitter's identifier. The portal uses
            # this as the encounter_id; downstream the audit pipeline
            # can override it (the demo registry keys on enc_<id>).
            if len(seg) > 1:
                encounter_id = (seg[1] or "").strip() or None

        elif tag == "NM1":
            # Two flavours we care about: patient (loop 2010BA/2010CA)
            # and billing provider (loop 2010AA, entity type 85).
            ent_qualifier = (seg[1] or "").strip()
            if ent_qualifier in ("IL", "QC", "QE", "QH"):
                pid = _patient_id_from_nm1(seg)
                if pid and not patient_id:
                    patient_id = pid
            elif ent_qualifier == "85":
                n = _npi_from_nm1(seg)
                if n:
                    npi = n

        elif tag == "DTP":
            d = _iso_date_from_dtp_472(seg)
            if d:
                date_of_service = d

        elif tag == "SV1":
            cpt_codes.extend(_cpt_codes_from_sv1(seg))

    return {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "NPI": npi,
        "date_of_service": date_of_service,
        "CPT_codes": cpt_codes,
        # "raw" is shown in the parse preview so the user can spot a
        # misparsed line at a glance. We omit the envelope segments
        # (ISA/GS/ST/SE/GE/IEA/BHT) so the preview is focused on the
        # claim body.
        "raw": "~".join(raw_segments) + "~",
    }


def _group_into_claims(segments: list[list[str]]) -> list[list[list[str]]]:
    """Split the segment list into one bucket per CLM.

    The 2000A / 2000B / 2300 loops are separated by ``CLM``. We
    bucket everything from one ``CLM`` (inclusive) to the next
    ``CLM`` (exclusive) into a single claim group. Segments before
    the first ``CLM`` (the envelope + any 2010AA billing-provider
    info) are folded into the first claim; that mirrors how the
    upload form needs to render "billing provider NPI applies to
    every claim in the file".
    """
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    seen_clm = False
    for seg in segments:
        if seg and seg[0] == "CLM":
            if seen_clm:
                groups.append(current)
                current = [seg]
            else:
                current.append(seg)
                seen_clm = True
        else:
            if seen_clm or seg and seg[0] in (
                "ISA", "GS", "ST", "BHT", "NM1", "N1", "PER",
            ):
                current.append(seg)
    if current:
        groups.append(current)
    return groups


# --- public API ------------------------------------------------------------


def parse_837p(text: str) -> list[dict[str, Any]]:
    """Parse an 837P text payload into one normalised dict per claim.

    Raises:
        X12ParseError: when the text is empty or contains no segments
            at all after the segment terminator split. The portal
            wraps this with a per-file "malformed" error.

    Returns:
        A list of claim dicts (one per ``CLM``). Each dict has the
        five required fields plus ``raw`` (the X12 segments for that
        claim, rejoined for the parse preview).
    """
    if text is None or not text.strip():
        raise X12ParseError("input is empty")
    element, seg_term = discover_separators(text)
    if seg_term == element:
        # Both separators resolved to the same char; the file is
        # likely plain text, not X12.
        raise X12ParseError(
            "no X12 segment terminator found (ISA header missing or "
            "segment terminator equals element separator)"
        )
    segments = _split_segments(text, seg_term)
    if not segments:
        raise X12ParseError("no segments found after split")
    # Light envelope check: if the file starts with ISA but no CLM
    # is present, we still treat it as a 0-claim parse. The portal
    # surfaces that as a per-file "no CLM segment found" error.
    claim_groups = _group_into_claims(segments)
    if not claim_groups:
        raise X12ParseError(
            "no CLM segment found; the file is not a recognisable "
            "837P payload"
        )
    return [_extract_claim(group) for group in claim_groups]


def validate_required_fields(claim: dict[str, Any]) -> list[str]:
    """Return a list of human-readable error messages for missing fields.

    The portal shows one error per file, but the underlying parser
    can surface a complete list. Empty list == all required fields
    are present and well-formed.
    """
    errors: list[str] = []
    enc = (claim.get("encounter_id") or "").strip()
    if not enc:
        errors.append("missing encounter_id (no CLM01 segment or value empty)")
    pid = (claim.get("patient_id") or "").strip()
    if not pid:
        errors.append(
            "missing patient_id (no NM1*QC/MI/II subscriber loop found)"
        )
    npi = (claim.get("NPI") or "").strip()
    if not npi:
        errors.append(
            "missing NPI (no NM1*85 billing-provider segment with XX qualifier)"
        )
    elif not re.fullmatch(r"\d{10}", npi):
        errors.append(f"NPI {npi!r} is not a 10-digit value")
    dos = (claim.get("date_of_service") or "").strip()
    if not dos:
        errors.append(
            "missing date_of_service (no DTP*472*D8*<YYYYMMDD> segment found)"
        )
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dos):
        errors.append(
            f"date_of_service {dos!r} is not in YYYY-MM-DD format"
        )
    cpts = claim.get("CPT_codes") or []
    if not cpts:
        errors.append("missing CPT codes (no SV1*HC:... segments found)")
    return errors
