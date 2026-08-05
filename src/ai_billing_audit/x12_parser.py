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


# File-level X12 segments that describe the envelope / billing-provider /
# subscriber loops and apply to every claim in the interchange. When we
# group segments into per-claim buckets, we copy these into every group so
# the 2010AA billing-provider NPI (and the 2000B subscriber) doesn't
# silently disappear after claim 1 — kanban ``t_x12_parser_fixes`` issue #2.
_FILE_LEVEL_SEGMENTS: frozenset[str] = frozenset(
    {"ISA", "GS", "ST", "BHT", "NM1", "N1", "PER", "HL", "N3", "N4", "REF"}
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


def _split_segments(text: str, seg_term: str, element_separator: str = "*") -> list[list[str]]:
    """Split the X12 envelope into ``[[element, ...], ...]`` rows."""
    out: list[list[str]] = []
    for raw in text.split(seg_term):
        seg = raw.strip()
        if not seg:
            continue
        out.append(seg.split(element_separator))
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


def _cpt_codes_from_sv1(elements: list[str], component_separator: str = ":") -> list[str]:
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
    parts = proc.split(component_separator)
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


def _diagnosis_codes_from_hi(elements: list[str], component_separator: str = ":") -> list[str]:
    """Extract diagnosis codes from an ``HI`` segment (2300 loop).

    X12 5010 ``HI`` carries ICD-10-CM (qualifier ``ABK``/``ABF``/``ABJ``/
    ``ABN``) or ICD-9-CM (qualifier ``BK``/``BF``/``BJ``/``BN``) codes:

        HI*ABK:Z0000:Z0011:Z0100
        HI*ABF:Z0011
        HI*BK:250.00

    The qualifier tells the receiver which code set the values are
    drawn from; the upload form needs the raw codes in document
    order so the audit grader can spot missing or out-of-order
    diagnosis pointers. Kanban ``t_x12_parser_fixes`` issue #3.
    """
    if not elements or elements[0] != "HI":
        return []
    out: list[str] = []
    for elem in elements[1:]:
        elem = (elem or "").strip()
        if not elem:
            continue
        # First colon component is the qualifier (ABK, ABF, BK, BF, ...);
        # subsequent components are the actual codes. We surface every
        # code in document order and let the caller decide what to do
        # with qualifiers (the v1 upload form doesn't need them).
        parts = elem.split(component_separator)
        if len(parts) < 2:
            # No qualifier; the value itself is the code (rare but
            # legal for single-element composites).
            out.append(parts[0])
            continue
        for code in parts[1:]:
            code = code.strip()
            if code:
                out.append(code)
    return out


# --- per-claim assembly ---------------------------------------------------


def _extract_claim(
    claim_segments: list[list[str]], element_separator: str = "*",
    segment_terminator: str = "~", component_separator: str = ":",
) -> dict[str, Any]:
    """Project a 2000-loop (one claim) into the normalised dict."""
    encounter_id: str | None = None
    patient_id: str | None = None
    npi: str | None = None
    date_of_service: str | None = None
    cpt_codes: list[str] = []
    diagnosis_codes: list[str] = []
    raw_segments: list[str] = []

    for seg in claim_segments:
        if not seg:
            continue
        tag = seg[0]
        # Serialise back to an X12-style string for the per-file
        # "raw" preview the upload form shows the user.
        raw_segments.append(element_separator.join(seg))

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
            # First-wins: X12 spec allows at most one DTP*472 per claim,
            # so seeing two is malformed input. We pick the first
            # deterministically rather than last-wins so the upload
            # preview is stable across runs (kanban ``t_x12_parser_fixes``
            # issue #1).
            if d and not date_of_service:
                date_of_service = d

        elif tag == "SV1":
            cpt_codes.extend(_cpt_codes_from_sv1(seg, component_separator))

        elif tag == "HI":
            diagnosis_codes.extend(_diagnosis_codes_from_hi(seg, component_separator))

    return {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "NPI": npi,
        "date_of_service": date_of_service,
        "CPT_codes": cpt_codes,
        "diagnosis_codes": diagnosis_codes,
        # "raw" is shown in the parse preview so the user can spot a
        # misparsed line at a glance. We omit the envelope segments
        # (ISA/GS/ST/SE/GE/IEA/BHT) so the preview is focused on the
        # claim body.
        "raw": segment_terminator.join(raw_segments) + segment_terminator,
    }


def _group_into_claims(segments: list[list[str]]) -> list[list[list[str]]]:
    """Split the segment list into one bucket per CLM.

    The 2000A / 2000B / 2300 loops are separated by ``CLM``. We
    bucket everything from one ``CLM`` (inclusive) to the next
    ``CLM`` (exclusive) into a single claim group.

    File-level segments (everything BEFORE the first ``CLM``: the
    envelope, the 2010AA billing-provider loop, the 2000B subscriber
    loop) describe properties of the interchange as a whole and
    apply to every claim. We copy them into every claim group so
    claim 2+ still sees the file-level billing-provider NPI and
    subscriber ID (kanban ``t_x12_parser_fixes`` issue #2).

    Segments after the last ``CLM`` (footer envelope: ``SE``, ``GE``,
    ``IEA``) still end up in the last claim group; that's harmless
    because the per-claim ``raw`` preview just joins them back into
    the X12 string for display.
    """
    pre_clm: list[list[str]] = []
    groups: list[list[list[str]]] = []
    provider_context: list[str] | None = None
    patient_context: list[str] | None = None

    def scoped_context() -> list[list[str]]:
        return [s for s in (provider_context, patient_context) if s is not None]

    for seg in segments:
        if not seg:
            continue
        tag = seg[0]
        if tag == "HL":
            # A new hierarchy cannot inherit a subscriber from the
            # preceding hierarchy. Provider context remains available to
            # its child subscriber loop.
            patient_context = None
        elif tag == "NM1":
            if _npi_from_nm1(seg):
                provider_context = seg
            elif _patient_id_from_nm1(seg):
                patient_context = seg

        if tag == "CLM":
            # Every CLM gets a fresh copy of the file-level context
            # BEFORE its own CLM segment. Using ``list(pre_clm)`` is
            # important — if we reused the same list reference, the
            # following segments would mutate every claim group at
            # once.
            groups.append(list(pre_clm) + scoped_context() + [seg])
        elif groups:
            # After at least one CLM has been seen, append to the
            # current (last) claim group.
            groups[-1].append(seg)
        elif tag in _FILE_LEVEL_SEGMENTS and tag not in {"NM1", "HL"}:
            # Before any CLM: file-level context. Accumulate so we
            # can prepend a copy to each claim group.
            pre_clm.append(seg)
        # else: drop unknown pre-CLM segments (parser is permissive on
        # envelope shape; the validator surfaces real missing-required
        # fields separately).
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
    component = (
        text[104]
        if text.startswith("ISA") and len(text) >= _ISA_FIXED_WIDTH
        else ":"
    )
    if seg_term == element:
        # Both separators resolved to the same char; the file is
        # likely plain text, not X12.
        raise X12ParseError(
            "no X12 segment terminator found (ISA header missing or "
            "segment terminator equals element separator)"
        )
    segments = _split_segments(text, seg_term, element)
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
    return [
        _extract_claim(group, element, seg_term, component)
        for group in claim_groups
    ]


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
