"""Tests for the appeal-letter generator.

The generator is the second agent in the Zorva pipeline. It takes
an auditor's finding + encounter metadata + a payer's denial
reason and emits a formal appeal letter addressed to the right
recipient (per the Zorva market context).

What's pinned
-------------
* build_appeal_prompt fills all template slots from the zorva_context
* The LLM response is parsed (strips ```json``` fences, validates
  required keys, recovers from leading prose)
* Template-only fallback (no LLM) still returns a usable letter
  with the rule_citation resolved from the built-in rule catalog
* PHI is scrubbed before the letter is logged to disk
* Each market (CA / US / MX / CO) addresses the right appeal
  recipient
* Unknown rule_ids fall through to a generic medical-necessity
  statement (not a hard error)
* The appeal_letters.jsonl log is written with metadata only,
  not the full body
"""

from __future__ import annotations

import json

import pytest

from ai_billing_audit.appeal_letter import (
    _DEFAULT_RULE_CITATION,
    _format_billed_codes,
    _pseudonymize_patient,
    _resolve_rule_citation,
    _scrub_phi,
    build_appeal_prompt,
    generate_appeal_letter,
    parse_appeal_response,
)


# ----- fixtures -----


@pytest.fixture
def finding():
    return {
        "finding_id": "F-1",
        "rule_id": "MOD-25",
        "rule_ids": ["MOD-25"],
        "severity": "high",
        "category": "modifier",
        "suggested_code": "99214-25",
        "quote": "patient also had a separate E/M for the same-day procedure",
        "explanation": "The note documents a separately identifiable E/M "
        "on the same day as the procedure, supporting "
        "modifier -25 on the E/M code.",
    }


@pytest.fixture
def encounter():
    return {
        "encounter_id": "E-APPEAL-1",
        "claim": {
            "encounter_id": "E-APPEAL-1",
            "date_of_service": "2026-05-12",
            "line_items": [
                {
                    "line_id": 1,
                    "cpt_code": "99214",
                    "modifiers": ["25"],
                    "charge_amount": 95.00,
                    "units": 1,
                },
                {
                    "line_id": 2,
                    "cpt_code": "12001",
                    "modifiers": [],
                    "charge_amount": 250.00,
                    "units": 1,
                },
            ],
            "rendering_provider_npi": "1992039481",
        },
        "NPI": "1992039481",
    }


@pytest.fixture
def zctx_ca():
    return {
        "market": "CA",
        "market_name": "Canada",
        "province": "ON",
        "billing_authority": "OHIP Schedule of Benefits (Section GP-17)",
        "compliance_law": "PIPEDA",
        "data_residency_required": True,
        "phi_identifiers_required": False,
    }


# ----- _resolve_rule_citation -----


def test_known_rule_returns_catalog_text():
    text = _resolve_rule_citation("MOD-25")
    assert "Modifier -25" in text
    assert "separately identifiable" in text


def test_unknown_rule_falls_back_to_generic():
    text = _resolve_rule_citation("not_in_catalog_999")
    assert text == _DEFAULT_RULE_CITATION


def test_no_rule_id_returns_generic():
    text = _resolve_rule_citation(None)
    assert text == _DEFAULT_RULE_CITATION


# ----- _format_billed_codes -----


def test_format_billed_codes_with_line_items(encounter):
    out = _format_billed_codes(encounter["claim"])
    assert "99214-25" in out
    assert "12001" in out
    assert "$95.00" in out
    assert "$250.00" in out


def test_format_billed_codes_with_only_cpts():
    claim = {"CPT_codes": ["99213", "93000"]}
    out = _format_billed_codes(claim)
    assert "99213" in out
    assert "93000" in out
    # No dollar sign because no charge_amount provided
    assert "$" not in out


def test_format_billed_codes_no_data():
    assert _format_billed_codes({}) == "—"
    assert _format_billed_codes(None) == "—"


# ----- _pseudonymize_patient -----


def test_pseudonymize_uses_encounter_id():
    h1 = _pseudonymize_patient({"encounter_id": "X"}, {"encounter_id": "Y"})
    h2 = _pseudonymize_patient({"encounter_id": "X"}, {"encounter_id": "Y"})
    h3 = _pseudonymize_patient({"encounter_id": "Z"}, {})
    # Same seed -> same hash; different seed -> different hash
    assert h1 == h2
    assert h1 != h3
    # Hash is 12 chars (truncated SHA-256)
    assert len(h1) == 12


# ----- _scrub_phi -----


def test_scrub_phi_removes_10_digit_numbers():
    text = "Patient MRN: 1234567890, please call 1234567899"
    out = _scrub_phi(text)
    assert "1234567890" not in out
    assert "1234567899" not in out
    assert "[PATIENT_ID]" in out


def test_scrub_phi_removes_ssn_format():
    text = "SSN: 123-45-6789"
    out = _scrub_phi(text)
    assert "123-45-6789" not in out
    assert "[SSN]" in out


def test_scrub_phi_removes_emails():
    text = "Contact: jane.doe@clinic.ca"
    out = _scrub_phi(text)
    assert "jane.doe@clinic.ca" not in out
    assert "[EMAIL]" in out


# ----- build_appeal_prompt -----


def test_build_prompt_fills_market_slots(finding, encounter, zctx_ca):
    prompt = build_appeal_prompt(
        finding=finding,
        encounter=encounter,
        clinical_note="Patient presents for follow-up...",
        denial_reason="Service not medically necessary",
        zorva_context=zctx_ca,
    )
    assert "Canada" in prompt
    assert "PIPEDA" in prompt
    # The recipient is the right per-market string (Ontario goes to
    # the provincial appeals office).
    assert "Provincial" in prompt
    # The encounter metadata is filled in
    assert "1992039481" in prompt  # provider NPI
    assert "99214-25" in prompt  # billed code
    assert "2026-05-12" in prompt  # date of service
    # The denial reason is quoted
    assert "Service not medically necessary" in prompt
    # The clinical note is included verbatim
    assert "Patient presents for follow-up" in prompt
    # The auditor's finding is summarised
    assert "MOD-25" in prompt
    assert "modifier -25" in prompt.lower() or "Modifier -25" in prompt


def test_build_prompt_uses_appeal_recipient_for_market(finding, encounter):
    zctx_us = {
        "market": "US",
        "market_name": "United States",
        "compliance_law": "HIPAA",
    }
    prompt = build_appeal_prompt(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=zctx_us,
    )
    assert "United States" in prompt
    assert "HIPAA" in prompt
    assert "Payer" in prompt  # US appeal recipient


def test_build_prompt_includes_all_rule_ids_in_citation(finding, encounter, zctx_ca):
    finding["rule_ids"] = ["MOD-25", "DX_LINKAGE_REQUIRED"]
    prompt = build_appeal_prompt(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=zctx_ca,
    )
    # Primary rule gets the full citation, secondary is mentioned
    assert "Modifier -25" in prompt
    assert "DX_LINKAGE_REQUIRED" in prompt


def test_build_prompt_with_no_zctx_uses_defaults(finding, encounter):
    """When no zorva_context is passed, defaults to CA/PIPEDA."""
    prompt = build_appeal_prompt(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=None,
    )
    assert "Canada" in prompt
    assert "PIPEDA" in prompt


# ----- parse_appeal_response -----


def test_parse_clean_json():
    raw = json.dumps(
        {
            "letter_markdown": "# Appeal\n\nBody text",
            "appeal_basis": "Documentation supports medical necessity",
            "cited_rule_ids": ["MOD-25"],
            "requested_action": "Reconsider and pay",
        }
    )
    parsed = parse_appeal_response(raw)
    assert parsed is not None
    assert parsed["letter_markdown"] == "# Appeal\n\nBody text"
    assert parsed["cited_rule_ids"] == ["MOD-25"]


def test_parse_with_fenced_json():
    raw = (
        "```json\n"
        + json.dumps(
            {
                "letter_markdown": "# Appeal",
                "appeal_basis": "supports",
                "cited_rule_ids": [],
                "requested_action": "reconsider",
            }
        )
        + "\n```"
    )
    parsed = parse_appeal_response(raw)
    assert parsed is not None
    assert parsed["letter_markdown"] == "# Appeal"


def test_parse_with_leading_prose_and_trailing_brace():
    raw = (
        "Here is the letter:\n"
        + json.dumps(
            {
                "letter_markdown": "Body",
                "appeal_basis": "x",
                "cited_rule_ids": ["R1"],
                "requested_action": "y",
            }
        )
        + "\nDone."
    )
    parsed = parse_appeal_response(raw)
    assert parsed is not None
    assert parsed["letter_markdown"] == "Body"


def test_parse_missing_key_returns_none():
    raw = json.dumps({"letter_markdown": "Body", "appeal_basis": "x"})
    parsed = parse_appeal_response(raw)
    assert parsed is None


def test_parse_empty_letter_returns_none():
    raw = json.dumps(
        {
            "letter_markdown": "   ",
            "appeal_basis": "x",
            "cited_rule_ids": [],
            "requested_action": "y",
        }
    )
    parsed = parse_appeal_response(raw)
    assert parsed is None


def test_parse_empty_input_returns_none():
    assert parse_appeal_response("") is None
    assert parse_appeal_response("not json at all") is None


def test_parse_garbage_braces_returns_none():
    assert parse_appeal_response("Here is {some text} but no JSON object") is None


# ----- generate_appeal_letter (template-only path) -----


def test_generate_without_llm_returns_template_letter(finding, encounter, zctx_ca):
    """No llm_complete passed -> template-only letter still works."""
    letter = generate_appeal_letter(
        finding=finding,
        encounter=encounter,
        clinical_note="Patient presents with chest pain...",
        denial_reason="Not medically necessary",
        zorva_context=zctx_ca,
        llm_complete=None,
    )
    assert letter is not None
    assert letter["template_only"] is True
    assert letter["market"] == "CA"
    assert letter["compliance_law"] == "PIPEDA"
    assert (
        "OHIP" in letter["letter_markdown"] or "Provincial" in letter["letter_markdown"]
    )
    assert letter["cited_rule_ids"] == ["MOD-25"]
    assert "Reconsider" in letter["requested_action"]


def test_generate_with_llm_parses_response(finding, encounter, zctx_ca):
    """A well-formed LLM response is parsed and scrubbed."""

    def fake_complete(prompt: str) -> str:
        return json.dumps(
            {
                "letter_markdown": (
                    "Dear payer,\n\n"
                    "We appeal the denial of claim 12345. "
                    "Patient MRN: 1234567890.\n"
                    "Documentation supports medical necessity.\n"
                    "Contact: biller@clinic.ca.\n\n"
                    "Sincerely,\nDr. Smith"
                ),
                "appeal_basis": "Documentation supports medical necessity",
                "cited_rule_ids": ["MOD-25"],
                "requested_action": "Reconsider and pay",
            }
        )

    letter = generate_appeal_letter(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=zctx_ca,
        llm_complete=fake_complete,
    )
    assert letter is not None
    # Non-template path: template_only is absent (or False)
    assert not letter.get("template_only", False)
    # PHI was scrubbed
    assert "1234567890" not in letter["letter_markdown"]
    assert "biller@clinic.ca" not in letter["letter_markdown"]
    assert (
        "[PATIENT_ID]" in letter["letter_markdown"]
        or "PATIENT_ID" in letter["letter_markdown"]
    )
    assert letter["cited_rule_ids"] == ["MOD-25"]


def test_generate_with_llm_failure_returns_none(finding, encounter, zctx_ca):
    def fake_complete(prompt: str) -> str:
        raise RuntimeError("LLM offline")

    letter = generate_appeal_letter(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=zctx_ca,
        llm_complete=fake_complete,
    )
    assert letter is None


def test_generate_with_llm_garbage_response_returns_none(finding, encounter, zctx_ca):
    def fake_complete(prompt: str) -> str:
        return "Sorry, I cannot generate that response."

    letter = generate_appeal_letter(
        finding=finding,
        encounter=encounter,
        clinical_note="note",
        denial_reason="denied",
        zorva_context=zctx_ca,
        llm_complete=fake_complete,
    )
    assert letter is None


# ----- log_appeal_letter -----


def test_log_appeal_letter_writes_metadata_only(tmp_path, monkeypatch):
    """Log file gets the metadata (basis, rules, market) but NOT the body."""
    from ai_billing_audit import appeal_letter as al

    monkeypatch.setattr(al, "_LOGS_DIR", tmp_path)
    monkeypatch.setattr(al, "_APPEAL_LOG", tmp_path / "appeal_letters.jsonl")
    letter = {
        "letter_markdown": "TOP SECRET PATIENT DETAILS THAT MUST NOT HIT DISK",
        "appeal_basis": "Documentation supports the claim",
        "cited_rule_ids": ["MOD-25"],
        "requested_action": "Reconsider",
        "market": "CA",
        "compliance_law": "PIPEDA",
        "generated_at": "2026-06-20T12:00:00Z",
    }
    al.log_appeal_letter(letter, "E-APPEAL-1")
    contents = (tmp_path / "appeal_letters.jsonl").read_bytes()
    assert b"E-APPEAL-1" not in contents
    assert b"MOD-25" not in contents
    assert b"PIPEDA" not in contents
    assert b"TOP SECRET" not in contents
    records = al.read_appeal_letters("E-APPEAL-1")
    assert records[0]["cited_rule_ids"] == ["MOD-25"]
    assert records[0]["compliance_law"] == "PIPEDA"
    assert records[0]["appeal_basis"] == "Documentation supports the claim"
    assert "letter_markdown" not in records[0]


def test_log_failure_doesnt_crash(tmp_path, monkeypatch):
    """A logging failure (read-only fs) doesn't propagate."""
    from ai_billing_audit import appeal_letter as al

    # Point at a path that can't be created (parent is a file)
    bad_path = tmp_path / "not-a-dir" / "nope" / "appeal_letters.jsonl"
    monkeypatch.setattr(al, "_LOGS_DIR", bad_path.parent.parent)
    monkeypatch.setattr(al, "_APPEAL_LOG", bad_path)
    # Should not raise even if the parent doesn't exist
    al.log_appeal_letter({"appeal_basis": "x"}, "E-1")
