"""Tests for the Stark / AKS / HIA hallucination guardrail in the auditor.

The auditor must NEVER suggest a service code that isn't supported by a
verbatim quote from the clinical note. The validator layer
(:func:`validate_findings`) rejects any finding whose ``quote`` doesn't
appear in the note (case-insensitive, whitespace-normalised). Without
this check, an LLM-driven auditor can fabricate evidence — which is the
line between 'audit' and 'fraud' under Stark Law, the Federal Anti-Kickback
Statute, the Health Information Acts, and PHIPA s.12.

What's pinned
-------------
* A finding whose quote is in the note is accepted.
* A finding whose quote is NOT in the note raises AuditValidationError.
* A finding with a different-case quote is still accepted.
* A finding with a whitespace-different quote is still accepted.
* The check is skipped when no clinical_note is provided (back-compat
  with synth-only audits that don't carry a note).
* An empty findings array is a no-op (audit produced no findings — the
  encounter is clean).
"""

from __future__ import annotations

import pytest

from ai_billing_audit.auditor import (
    AuditValidationError,
    _quote_in_note,
    validate_findings,
)


def _finding(quote: str, **overrides):
    """A minimal valid finding for the validator."""
    base = {
        "category": "modifier",
        "suggested_code": "99214-25",
        "quote": quote,
        "severity": "high",
        "rule_ids": ["MOD-25"],
    }
    base.update(overrides)
    return base


def _payload(*quotes, summary: str = "test"):
    return {"findings": [_finding(q) for q in quotes], "summary": summary}


NOTE = (
    "Patient is a 55-year-old established patient seen today for follow-up "
    "of well-controlled type 2 diabetes. Vitals are stable. Examination "
    "unremarkable. Labs from 2 weeks ago show HbA1c 6.8, eGFR 78. Plan: "
    "continue metformin 1000 mg BID, recheck HbA1c in 3 months."
)


def test_quote_present_in_note_accepted():
    findings = validate_findings(
        _payload("HbA1c 6.8"),
        clinical_note=NOTE,
    )
    assert len(findings) == 1
    assert findings[0].quote == "HbA1c 6.8"


def test_fabricated_quote_rejected():
    """The hard rule. Auditor invents evidence: whole finding is suspect."""
    with pytest.raises(AuditValidationError) as excinfo:
        validate_findings(
            _payload("patient was mountain climbing last week"),
            clinical_note=NOTE,
        )
    assert "fabricated evidence rejected" in str(excinfo.value)
    assert "mountain climbing" in str(excinfo.value)


def test_quote_case_insensitive():
    findings = validate_findings(
        _payload("HBA1C 6.8"),
        clinical_note=NOTE,
    )
    assert len(findings) == 1


def test_quote_whitespace_normalised():
    """OCR'd notes often have different whitespace than the source."""
    findings = validate_findings(
        _payload("HbA1c    6.8  eGFR  78"),  # run-on, lots of spaces
        clinical_note=NOTE,
    )
    assert len(findings) == 1


def test_no_clinical_note_skips_check():
    """Back-compat: synth-only audits pass no note, the check must be a no-op."""
    findings = validate_findings(
        _payload("any quote at all"),
        clinical_note="",
    )
    assert len(findings) == 1


def test_empty_findings_no_op():
    """Clean encounter = empty findings list = no error, no rows."""
    findings = validate_findings(
        {"findings": [], "summary": "clean"},
        clinical_note=NOTE,
    )
    assert findings == ()


def test_one_fabricated_among_valid_rejects_whole_run():
    """If any single finding is fabricated, the whole audit fails — not just
    that finding. We can't let a fabricated finding slip through alongside
    legitimate ones. The 'all or nothing' approach forces the auditor to
    retry cleanly."""
    payload = _payload(
        "HbA1c 6.8",  # legit
        "patient skydived on saturday",  # fabricated
    )
    with pytest.raises(AuditValidationError):
        validate_findings(payload, clinical_note=NOTE)


def test_quote_in_note_helper_direct():
    assert _quote_in_note("chest pain", "Patient has chest pain today")
    assert _quote_in_note("CHEST PAIN", "patient has chest pain today")
    assert _quote_in_note("chest\n   pain", "patient has chest pain today")
    assert not _quote_in_note("headache", "Patient has chest pain today")
    assert not _quote_in_note("", "anything")
    assert not _quote_in_note("anything", "")


def test_validate_handles_non_string_quote():
    """A non-string quote field gets coerced to string then checked. The
    LLM shouldn't send non-strings but if it does, we still defend."""
    payload = {
        "findings": [
            {
                "category": "modifier",
                "suggested_code": "99214-25",
                "quote": 12345,  # int instead of string
                "severity": "high",
                "rule_ids": ["MOD-25"],
            }
        ],
        "summary": "test",
    }
    with pytest.raises(AuditValidationError):
        validate_findings(payload, clinical_note=NOTE)


# ---------------------------------------------------------------------------
# Findings with no evidence at all must not be easier to get past the
# guardrail than findings with unverifiable evidence (issue #115).
# ---------------------------------------------------------------------------


def test_finding_with_no_quote_and_no_explanation_is_rejected():
    """The bypass this fixes.

    The guard was ``if clinical_note and quote and not _quote_in_note(...)``,
    so an empty ``quote`` short-circuited the check and the finding was
    accepted with ``quote=''``. A finding supplying a *fabricated* quote was
    rejected while one supplying *nothing* sailed through — which inverted
    the incentive and left the guardrail trivially bypassable.
    """
    payload = {
        "findings": [
            {
                "category": "modifier",
                "suggested_code": "03.04A",
                "severity": "high",
                "rule_ids": ["MOD-25"],
                # no quote, no explanation
            }
        ],
        "summary": "test",
    }
    with pytest.raises(AuditValidationError) as excinfo:
        validate_findings(payload, clinical_note=NOTE)
    assert "no evidence" in str(excinfo.value)


def test_finding_with_unverifiable_explanation_is_rejected():
    """An explanation that isn't in the note is not evidence."""
    payload = {
        "findings": [
            {
                "category": "modifier",
                "suggested_code": "03.04A",
                "severity": "high",
                "rule_ids": ["MOD-25"],
                "explanation": (
                    "the note documents a comprehensive assessment lasting "
                    "over fifteen minutes of counselling"
                ),
            }
        ],
        "summary": "test",
    }
    with pytest.raises(AuditValidationError):
        validate_findings(payload, clinical_note=NOTE)


def test_finding_with_explanation_sentence_in_note_is_accepted():
    """A real excerpt from the explanation still counts as support.

    The synthesis path pulls the first sentence of ``explanation`` and uses
    it as the quote when it appears in the note — that must keep working, so
    the fix above does not reject legitimate quote-less findings.
    """
    payload = {
        "findings": [
            {
                "category": "modifier",
                "suggested_code": "03.04A",
                "severity": "high",
                "rule_ids": ["MOD-25"],
                "explanation": "Plan continue metformin 1000 mg BID",
            }
        ],
        "summary": "test",
    }
    findings = validate_findings(payload, clinical_note=NOTE)
    assert len(findings) == 1
    # The synthesised quote is the explanation's first sentence, and it is
    # only accepted because its tokens really do appear in the note.
    assert findings[0].quote
    assert _quote_in_note(findings[0].quote, NOTE)


def test_no_evidence_still_allowed_without_a_note():
    """Back-compat: synth-only audits carry no note, so the guard is inert."""
    payload = {
        "findings": [
            {
                "category": "modifier",
                "suggested_code": "03.04A",
                "severity": "high",
                "rule_ids": ["MOD-25"],
            }
        ],
        "summary": "test",
    }
    findings = validate_findings(payload, clinical_note="")
    assert len(findings) == 1
