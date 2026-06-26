"""Tests for the doctor-summary module.

The doctor summary is the highest-leverage feature in the product:
it makes the doctor a user, not an invisible input. Within 3 months
of seeing 1-2 summaries per month, doctors learn to write notes that
pass the audit. This is what makes the denial rate actually drop.

What's pinned
-------------
* The summary has the 4-part structure: salutation, reason, fix, signoff.
* Reason text uses the rule_id when known (MOD-25 -> missing modifier
  -25), falls back to a generic phrase otherwise.
* Fix text is copy-pasteable, 1 sentence.
* Subject mentions severity.
* No email sent if no doctor email is available.
* Opt-out via env var works.
* ``send_doctor_summary`` writes ONE JSONL record per call to the
  operator outbox at ``_LOGS_DIR / doctor_emails.jsonl``. No auto-
  send (no Mailgun, no SMTP, no HTTP). The biller reads the file
  and dispatches via their own mail client.
* NPI lookup: malformed NPI returns None without an API call.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ai_billing_audit.doctor_email import (
    DoctorSummary,
    build_doctor_summary,
    send_doctor_summary,
    _one_sentence_reason,
    _default_fix_suggestion,
    doctor_email_for_provider,
)


def _finding(**overrides):
    base = {
        "finding_id": "F-1",
        "rule_id": "MOD-25",
        "severity": "high",
        "suggested_code": "99214-25",
        "quote": "Reviewed labs and adjusted metformin",
    }
    base.update(overrides)
    return base


def _encounter(**overrides):
    base = {
        "encounter_id": "E-1",
        "patient_id": "P-1",
        "provider_npi": "1234567890",
        "doctor_email": "dr.lee@clinic.ca",
        "doctor_name": "Sarah Lee",
        "date_of_service": "2026-06-12",
    }
    base.update(overrides)
    return base


def test_build_summary_mod25_contains_required_parts():
    s = build_doctor_summary(
        finding=_finding(rule_id="MOD-25"),
        encounter=_encounter(),
    )
    assert s is not None
    assert s.to_email == "dr.lee@clinic.ca"
    assert "Dr. Lee" in s.body_text or "Hi," in s.body_text
    assert "modifier -25" in s.body_text
    assert "Fix:" in s.body_text
    assert "Zorva" in s.body_text
    assert s.encounter_id == "E-1"
    assert s.finding_id == "F-1"


def test_build_summary_uses_doctor_last_name():
    s = build_doctor_summary(
        finding=_finding(),
        encounter=_encounter(),
        doctor_name="Sarah Lee",
    )
    assert "Dr. Lee" in s.body_text


def test_build_summary_no_email_returns_none():
    s = build_doctor_summary(
        finding=_finding(),
        encounter=_encounter(doctor_email=""),
    )
    assert s is None


def test_build_summary_no_finding_id_returns_none():
    s = build_doctor_summary(
        finding=_finding(finding_id=""),
        encounter=_encounter(),
    )
    assert s is None


def test_build_summary_known_rule_uses_rule_specific_reason():
    s = build_doctor_summary(
        finding=_finding(rule_id="MOD-59"),
        encounter=_encounter(),
    )
    assert "modifier -59" in s.body_text
    assert "bundles them" in s.body_text


def test_build_summary_unknown_rule_falls_back_to_generic():
    s = build_doctor_summary(
        finding=_finding(rule_id="UNKNOWN-999"),
        encounter=_encounter(),
    )
    # No rule-specific match, but the message should still be useful
    assert s is not None
    assert "documentation" in s.body_text.lower() or "support" in s.body_text.lower()


def test_build_summary_uses_suggested_addition_when_provided():
    """If the finding has a 'suggested_addition' field, use that as the fix."""
    s = build_doctor_summary(
        finding=_finding(
            rule_id="MOD-25",
            suggested_addition="Document the separately identifiable E/M",
        ),
        encounter=_encounter(),
    )
    assert "Document the separately identifiable E/M" in s.body_text


def test_subject_mentions_severity():
    s = build_doctor_summary(
        finding=_finding(severity="critical"),
        encounter=_encounter(),
    )
    assert "critical" in s.subject.lower()


def test_send_writes_to_operator_outbox_jsonl(tmp_path, monkeypatch):
    """``send_doctor_summary`` appends ONE JSONL record to
    ``_LOGS_DIR / doctor_emails.jsonl``. No network call, no SMTP,
    no auto-send — the operator reads the file and dispatches via
    their own mail client.
    """
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.setattr(
        "ai_billing_audit.doctor_email._LOGS_DIR",
        tmp_path,
    )
    summary = DoctorSummary(
        to_email="dr.lee@clinic.ca",
        subject="test",
        body_text="body",
        encounter_id="E-1",
        finding_id="F-1",
    )
    result = send_doctor_summary(summary)
    assert result is True
    mailbox = tmp_path / "doctor_emails.jsonl"
    assert mailbox.is_file()
    record = json.loads(mailbox.read_text().strip())
    assert record["to"] == "dr.lee@clinic.ca"
    assert record["encounter_id"] == "E-1"
    # Every field is a JSON-serializable primitive — no nested
    # dataclass or unserializable object leaks into the JSONL.
    for k in ("to", "subject", "body", "encounter_id", "finding_id", "ts"):
        assert k in record, f"missing field {k!r} in outbox record"
        assert isinstance(record[k], (str, int, float))


def test_send_appends_one_record_per_call(tmp_path, monkeypatch):
    """Two calls produce two JSONL lines, not one overwritten line."""
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    base = dict(
        to_email="dr.lee@clinic.ca",
        subject="test",
        body_text="body",
        encounter_id="E-1",
    )
    send_doctor_summary(DoctorSummary(finding_id="F-1", **base))
    send_doctor_summary(DoctorSummary(finding_id="F-2", **base))
    mailbox = tmp_path / "doctor_emails.jsonl"
    lines = [ln for ln in mailbox.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    records = [json.loads(ln) for ln in lines]
    assert records[0]["finding_id"] == "F-1"
    assert records[1]["finding_id"] == "F-2"


def test_send_does_not_make_network_calls(tmp_path, monkeypatch):
    """The post-Mailgun-removal invariant: send_doctor_summary
    never imports or calls ``requests``, never POSTs anywhere.

    We assert by importing ``ai_billing_audit.doctor_email`` fresh
    and verifying the module's namespace has no `requests` symbol
    AND no Mailgun-era helpers (``_send_via_mailgun`` /
    ``_mailgun_configured``) are still attached to the module.
    """
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    import importlib

    from ai_billing_audit import doctor_email as de

    importlib.reload(de)
    assert not hasattr(de, "_send_via_mailgun"), (
        "_send_via_mailgun must not be present — auto-send was removed"
    )
    assert not hasattr(de, "_mailgun_configured"), (
        "_mailgun_configured must not be present — auto-send was removed"
    )
    assert "requests" not in de.__dict__, (
        "doctor_email must not import 'requests' — auto-send was removed"
    )


def test_send_opt_out_disables(monkeypatch):
    """DOCTOR_SUMMARY_OPT_IN=0 disables the email entirely."""
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "0")
    summary = DoctorSummary(
        to_email="dr.lee@clinic.ca",
        subject="test",
        body_text="body",
        encounter_id="E-1",
        finding_id="F-1",
    )
    result = send_doctor_summary(summary)
    assert result is False


def test_one_sentence_reason_known_rule():
    text = _one_sentence_reason("MOD-25", "high", "99214-25", "")
    assert "modifier -25" in text


def test_one_sentence_reason_unknown_rule_falls_back():
    text = _one_sentence_reason("ZZZ-999", "high", "99214-25", "")
    assert "documentation" in text.lower() or "support" in text.lower()


def test_default_fix_suggestion_known_rule():
    text = _default_fix_suggestion("MOD-25", "")
    assert "modifier -25" in text or "separately" in text


def test_npi_lookup_rejects_malformed_npi(tmp_path, monkeypatch):
    """Bad NPI returns None without an API call."""
    monkeypatch.setattr(
        "ai_billing_audit.doctor_email._LOGS_DIR", tmp_path
    )
    assert doctor_email_for_provider("") is None
    assert doctor_email_for_provider("not-a-number") is None
    assert doctor_email_for_provider("123") is None  # too short
    assert doctor_email_for_provider("12345678901") is None  # too long
    # No cache file should be created
    assert not (tmp_path / "npi_email_cache.json").exists()
