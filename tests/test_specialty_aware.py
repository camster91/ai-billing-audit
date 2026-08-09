"""Tests for the specialty-aware doctor summary phrasing.

A cardiologist and a psychiatrist write notes in completely different
idioms. The doctor summary should match the doctor's specialty.

What's pinned
-------------
* CPT codes map to the right specialty via prefix ranges.
* Specialties with override phrases use them; others fall back.
* The default `_one_sentence_reason` / `_default_fix_suggestion`
  functions still work when specialty is None or unknown.
"""

from __future__ import annotations


from ai_billing_audit.doctor_email import (
    specialty_from_cpt,
    specialty_fix_suggestion,
    build_doctor_summary,
)


def test_specialty_primary_care():
    assert specialty_from_cpt(["99213"]) == "primary_care"


def test_specialty_psychiatry():
    assert specialty_from_cpt(["90837"]) == "psychiatry"


def test_specialty_surgery():
    assert specialty_from_cpt(["11042"]) == "surgery"


def test_specialty_imaging():
    assert specialty_from_cpt(["71045"]) == "imaging"


def test_specialty_path_lab():
    assert specialty_from_cpt(["80061"]) == "pathology_lab"


def test_specialty_emergency():
    assert specialty_from_cpt(["99284"]) == "emergency"


def test_specialty_critical_care():
    assert specialty_from_cpt(["99291"]) == "critical_care"


def test_specialty_unknown_code_returns_none():
    assert specialty_from_cpt(["99999"]) is None


def test_specialty_empty_returns_none():
    assert specialty_from_cpt([]) is None
    assert specialty_from_cpt(None) is None


def test_specialty_handles_string_codes():
    """CPT codes can come in as strings ('99213.0') or ints."""
    assert specialty_from_cpt(["99213"]) == "primary_care"
    assert specialty_from_cpt(["99213.0"]) == "primary_care"
    assert specialty_from_cpt([99213]) == "primary_care"


def test_specialty_handles_invalid_codes():
    """Garbage values are skipped, not crashed."""
    assert specialty_from_cpt(["not-a-code"]) is None
    assert specialty_from_cpt([""]) is None


def test_specialty_first_match_wins():
    """When multiple CPT codes are listed, the first matching one wins."""
    # 99213 (primary_care) listed first, then 90837 (psychiatry)
    assert specialty_from_cpt(["99213", "90837"]) == "primary_care"
    # Reverse order
    assert specialty_from_cpt(["90837", "99213"]) == "psychiatry"


def test_specialty_fix_override_used():
    """Primary-care MOD-25 fix should use the specialty-specific phrasing."""
    text = specialty_fix_suggestion("MOD-25", "99214-25", "primary_care")
    assert "separate concern" in text.lower()


def test_specialty_fix_falls_back_to_default():
    """When no specialty override exists, the default is used."""
    # info rule has no specialty override, only high/critical ones do
    text = specialty_fix_suggestion("INFO-RULE", "99999", "primary_care")
    # Default fallback
    assert (
        "Medical decision making" in text
        or "document the medical decision" in text.lower()
    )


def test_specialty_fix_no_specialty_falls_back():
    text = specialty_fix_suggestion("MOD-25", "99214-25", None)
    # Default fix for MOD-25
    assert (
        "separately identifiable" in text.lower()
        or "procedure performed" in text.lower()
    )


def test_specialty_fix_unknown_specialty_falls_back():
    """Unknown specialty id -> default."""
    text = specialty_fix_suggestion("MOD-25", "99214-25", "not_a_real_specialty")
    # Falls back to default
    assert (
        "separately identifiable" in text.lower()
        or "procedure performed" in text.lower()
    )


def test_build_summary_uses_specialty_fix():
    """When specialty has an override, the email body uses the override."""
    s = build_doctor_summary(
        finding={
            "finding_id": "F-MOD25-PC",
            "rule_id": "MOD-25",
            "severity": "high",
            "suggested_code": "99214-25",
            "quote": "Reviewed labs",
        },
        encounter={
            "encounter_id": "E-PC",
            "doctor_email": "dr.pc@clinic.ca",
            "doctor_name": "Sarah Lee",
            "date_of_service": "2026-06-12",
            "CPT_codes": ["99213"],  # primary_care
        },
    )
    assert s is not None
    # Specialty override for primary care MOD-25
    assert (
        "separate concern" in s.body_text.lower()
        or "preventive visit" in s.body_text.lower()
    )


def test_build_summary_specialty_surgery():
    s = build_doctor_summary(
        finding={
            "finding_id": "F-MOD25-SX",
            "rule_id": "MOD-25",
            "severity": "high",
            "suggested_code": "99214-25",
            "quote": "Reviewed labs",
        },
        encounter={
            "encounter_id": "E-SX",
            "doctor_email": "dr.sx@hospital.ca",
            "doctor_name": "Mike Smith",
            "date_of_service": "2026-06-12",
            "CPT_codes": ["11042"],  # surgery
        },
    )
    assert s is not None
    # Surgery override for MOD-25
    assert (
        "pre- and post-operative" in s.body_text.lower()
        or "above and beyond" in s.body_text.lower()
    )
