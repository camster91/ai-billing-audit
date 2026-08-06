"""Regression tests for the three known ``x12_parser`` bugs filed as
GitHub issues 1, 2, and 3 (kanban ``t_x12_parser_fixes``).

The bugs:

* #1 — multiple ``DTP*472`` segments within one claim use
  last-wins, which is unstable across runs and disagrees with X12
  spec (a claim has at most one service date). Fixed by switching
  to first-wins (deterministic).
* #2 — the file-level 2010AA billing-provider ``NM1*85*XX*NPI``
  applies to every claim in a multi-claim file, but the bucketing
  logic drops it after claim 1, so subsequent claims report
  ``NPI=None``. Fixed by carrying the billing context into every
  claim group before extraction.
* #3 — ``HI`` segments in the 2300 loop (diagnosis pointers /
  ICD-10 codes) were silently ignored. Fixed by collecting the
  codes into a ``diagnosis_codes`` field on the claim dict.

Each test builds the smallest 837P payload that exercises the
target bug; we deliberately do not import the project-level
``_FULL_837P`` fixture (kept under ``tests/test_encounters_upload.py``)
because the bug-triggering shapes are tiny enough to spell out.
"""
from __future__ import annotations

import pytest

from ai_billing_audit.x12_parser import (
    X12ParseError,
    parse_837p,
    validate_required_fields,
)


# ---------------------------------------------------------------------------
# Tiny reusable 837P envelope. We use ISA/GS/ST/BHT/SE/GE/IEA so the parser
# sees a real interchange (the parser is permissive about missing
# envelopes, but starting from a real envelope keeps the test honest).
# ---------------------------------------------------------------------------


def _envelope(*body: str) -> str:
    """Wrap ``body`` segments in a minimal valid 837P envelope.

    Each ``body`` element is one segment WITHOUT its trailing ``~``
    terminator; we add it here so the result is a properly-terminated
    X12 interchange. ``SE*<count>*...`` counts the ST segment plus
    every body segment.
    """
    segments_in_envelope = 1 + len(body)  # ST + body
    terminated = "\n".join(seg + "~" for seg in body)
    return (
        "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     "
        "*240515*1200*^*00501*000000001*0*P*:~"
        "GS*HC*SUBMITTER*RECEIVER*20240515*1200*1*X*005010X222A1~"
        "ST*837*0001*005010X222A1~"
        + terminated
        + "\n"
        f"SE*{segments_in_envelope}*0001~"
        "GE*1*1~"
        "IEA*1*000000001~"
    )


# ---------------------------------------------------------------------------
# Bug #3 — HI segments (issue 3)
# ---------------------------------------------------------------------------


def test_hi_segment_extracts_single_diagnosis_code() -> None:
    """A claim with one ``HI*ABK:Z0000`` segment exposes the code
    on the parsed claim dict as ``diagnosis_codes=['Z0000']``."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-HI-001*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    assert claims[0]["diagnosis_codes"] == ["Z0000"]


def test_hi_segment_extracts_multiple_codes_per_segment() -> None:
    """One ``HI`` segment can carry up to 12 codes (qualifier + N×code).
    We surface every code in order — the upload form renders the list
    and the audit grader cares about primary/secondary position."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-HI-002*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000:Z0011:Z0100~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    assert claims[0]["diagnosis_codes"] == ["Z0000", "Z0011", "Z0100"]


def test_hi_segment_multiple_segments_concatenate() -> None:
    """Multiple ``HI`` segments in one claim (primary + secondary
    diagnosis pointers) concatenate into the same flat list."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-HI-003*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000~",         # ICD-10 primary
        "HI*ABF:Z0011~",         # ICD-10 secondary
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    assert claims[0]["diagnosis_codes"] == ["Z0000", "Z0011"]


def test_no_hi_segment_yields_empty_diagnosis_codes() -> None:
    """A claim with no ``HI`` segment has ``diagnosis_codes == []``,
    not missing key, so downstream code can rely on the field."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-NO-HI-001*100.00***11:B:1*Y*A*Y*Y~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    assert claims[0]["diagnosis_codes"] == []


def test_hi_segment_does_not_invalidate_validate_required_fields() -> None:
    """The new field doesn't break ``validate_required_fields`` —
    diagnosis_codes is a bonus; the required list is unchanged."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-HI-004*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    # Valid claim should produce zero errors.
    assert validate_required_fields(claims[0]) == []


def test_alternative_x12_separators_match_canonical_claim() -> None:
    """Legal non-asterisk/non-tilde delimiters preserve claim output."""
    standard = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-ALT-001*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    alternative = standard.replace("*", "^").replace("~", "!")

    canonical_claim = parse_837p(standard)[0]
    alternative_claim = parse_837p(alternative)[0]

    assert alternative_claim == canonical_claim


# ---------------------------------------------------------------------------
# Bug #1 — date_of_service is last-wins on multiple DTP*472
# ---------------------------------------------------------------------------


def test_multiple_dtp_472_uses_first_segment() -> None:
    """A claim with two ``DTP*472`` segments should expose the FIRST
    service date, not the last (which is unstable across runs and
    disagrees with X12 spec — at most one service date per claim)."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-DTP-001*100.00***11:B:1*Y*A*Y*Y~",
        "DTP*472*D8*20240510~",   # the correct service date
        "DTP*472*D8*20240601~",   # garbage; should NOT overwrite
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    assert claims[0]["date_of_service"] == "2024-05-10"


# ---------------------------------------------------------------------------
# Bug #2 — NPI bleeds (interpreted as: file-level 2010AA billing NPI
# applies to every claim, not just the first).
# ---------------------------------------------------------------------------


def test_two_claims_share_file_level_billing_npi() -> None:
    """The file-level 2010AA ``NM1*85`` (billing provider) applies
    to every claim in the file. Claim 1 and claim 2 should both
    report that NPI, not just claim 1."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890",
        "HL*1**20*1",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "CLM*ENC-MULTI-001*100.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
        "CLM*ENC-MULTI-002*200.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240511",
        "SV1*HC:99214*200.00*UN*1***1",
    )
    claims = parse_837p(payload)
    assert len(claims) == 2
    assert claims[0]["NPI"] == "1234567890", "claim 1 missing billing NPI"
    assert claims[1]["NPI"] == "1234567890", "claim 2 missing billing NPI"


def test_two_claims_each_have_their_own_service_date() -> None:
    """Each claim's ``DTP*472`` is local to that claim. Claim 2
    should NOT inherit claim 1's date."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890",
        "HL*1**20*1",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "CLM*ENC-MULTI-001*100.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
        "CLM*ENC-MULTI-002*200.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240511",
        "SV1*HC:99214*200.00*UN*1***1",
    )
    claims = parse_837p(payload)
    assert len(claims) == 2
    assert claims[0]["date_of_service"] == "2024-05-10"
    assert claims[1]["date_of_service"] == "2024-05-11"


def test_two_claims_each_have_their_own_cpt_codes() -> None:
    """Each claim's ``SV1*HC:...`` is local. Claim 2 should NOT
    inherit claim 1's CPT codes."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890",
        "HL*1**20*1",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "CLM*ENC-MULTI-001*100.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
        "CLM*ENC-MULTI-002*200.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240511",
        "SV1*HC:99214*200.00*UN*1***1",
    )
    claims = parse_837p(payload)
    assert len(claims) == 2
    assert claims[0]["CPT_codes"] == ["99213"]
    assert claims[1]["CPT_codes"] == ["99214"]


def test_two_claims_each_have_their_own_encounter_id() -> None:
    """Each claim's ``CLM01`` is local."""
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890",
        "HL*1**20*1",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "CLM*ENC-MULTI-001*100.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
        "CLM*ENC-MULTI-002*200.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240511",
        "SV1*HC:99214*200.00*UN*1***1",
    )
    claims = parse_837p(payload)
    assert len(claims) == 2
    assert claims[0]["encounter_id"] == "ENC-MULTI-001"
    assert claims[1]["encounter_id"] == "ENC-MULTI-002"


def test_provider_and_subscriber_context_is_scoped_to_hl_loop() -> None:
    payload = _envelope(
        "HL*1**20*1",
        "NM1*85*2*PROVIDER A*****XX*1111111111",
        "HL*2*1*22*0",
        "NM1*IL*1*DOE*ONE****MI*MEMBER-1",
        "CLM*ENC-HL-001*100.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
        "HL*3**20*1",
        "NM1*85*2*PROVIDER B*****XX*2222222222",
        "HL*4*3*22*0",
        "NM1*IL*1*DOE*TWO****MI*MEMBER-2",
        "CLM*ENC-HL-002*200.00***11:B:1*Y*A*Y*Y",
        "DTP*472*D8*20240511",
        "SV1*HC:99214*200.00*UN*1***1",
    )
    claims = parse_837p(payload)
    assert [(c["NPI"], c["patient_id"]) for c in claims] == [
        ("1111111111", "MEMBER-1"),
        ("2222222222", "MEMBER-2"),
    ]


def test_non_default_element_and_segment_separators_are_honoured() -> None:
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "CLM*ENC-SEPS-001*100.00***11:B:1*Y*A*Y*Y",
        "HI*ABK:Z0000",
        "DTP*472*D8*20240510",
        "SV1*HC:99213*100.00*UN*1***1",
    ).replace("*", "|").replace("~", "!")
    claim = parse_837p(payload)[0]
    assert claim["encounter_id"] == "ENC-SEPS-001"
    assert claim["diagnosis_codes"] == ["Z0000"]
    assert claim["CPT_codes"] == ["99213"]
    assert claim["raw"].endswith("!")


# ---------------------------------------------------------------------------
# Sanity: the existing happy-path single-claim shape still works after
# these fixes (no regressions on the baseline).
# ---------------------------------------------------------------------------


def test_single_claim_baseline_shape_unchanged() -> None:
    payload = _envelope(
        "BHT*0019*00*1*20240515*1200*CH~",
        "NM1*85*2*BILLING CLINIC*****XX*1234567890~",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~",
        "CLM*ENC-BASE-001*100.00***11:B:1*Y*A*Y*Y~",
        "HI*ABK:Z0000~",
        "DTP*472*D8*20240510~",
        "SV1*HC:99213*100.00*UN*1***1~",
    )
    claims = parse_837p(payload)
    assert len(claims) == 1
    c = claims[0]
    assert c["encounter_id"] == "ENC-BASE-001"
    assert c["NPI"] == "1234567890"
    assert c["date_of_service"] == "2024-05-10"
    assert c["CPT_codes"] == ["99213"]
    assert c["diagnosis_codes"] == ["Z0000"]
