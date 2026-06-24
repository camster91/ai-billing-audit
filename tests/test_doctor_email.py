"""Tests for the doctor-summary email module.

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
* Dev mailbox fallback writes to /app/logs/doctor_emails.jsonl.
* NPI lookup: malformed NPI returns None without an API call.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

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


def test_send_no_mailgun_key_writes_to_dev_mailbox(tmp_path, monkeypatch):
    """If MAILGUN_API_KEY is unset, the email is dropped to the dev mailbox."""
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.delenv("MAILGUN_API_KEY", raising=False)
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


def test_send_with_mailgun_calls_api(monkeypatch):
    """If MAILGUN_API_KEY is set, the mailgun REST API is called."""
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-1234test")

    # Mock requests.post to return a 200 with a Mailgun-shaped body.
    mock_post = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "<msg-id@ashbi.ca>", "message": "Queued"}
    mock_post.return_value = mock_response

    mock_requests = MagicMock()
    mock_requests.post = mock_post
    mock_requests.RequestException = Exception

    with patch.dict("sys.modules", {"requests": mock_requests}):
        from ai_billing_audit import doctor_email
        # Force re-import so the module picks up the mocked requests.
        # The module imports requests inside _send_via_mailgun at call
        # time, so a sys.modules entry is sufficient.
        doctor_email._send_via_mailgun.__globals__["requests"] = mock_requests
        summary = DoctorSummary(
            to_email="dr.lee@clinic.ca",
            subject="test",
            body_text="body",
            encounter_id="E-1",
            finding_id="F-1",
        )
        result = doctor_email.send_doctor_summary(summary)
        assert result is True
        # Verify Mailgun was hit with the right URL and auth.
        assert mock_post.called
        call = mock_post.call_args
        assert "api.mailgun.net/v3/ashbi.ca/messages" in call.args[0]
        assert call.kwargs["auth"] == ("api", "key-1234test")
        assert call.kwargs["data"]["to"] == "dr.lee@clinic.ca"
        assert call.kwargs["data"]["from"] == "Zorva Audit <audit@ashbi.ca>"


def test_send_with_mailgun_4xx_falls_back_to_dev_mailbox(monkeypatch, tmp_path):
    """If Mailgun returns 4xx, the email is dropped to the dev mailbox."""
    monkeypatch.setenv("DOCTOR_SUMMARY_OPT_IN", "1")
    monkeypatch.setenv("MAILGUN_API_KEY", "key-1234test")
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)

    mock_post = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"message": "Forbidden"}
    mock_response.text = '{"message": "Forbidden"}'
    mock_post.return_value = mock_response

    mock_requests = MagicMock()
    mock_requests.post = mock_post
    mock_requests.RequestException = Exception

    with patch.dict("sys.modules", {"requests": mock_requests}):
        from ai_billing_audit import doctor_email
        doctor_email._send_via_mailgun.__globals__["requests"] = mock_requests
        summary = DoctorSummary(
            to_email="dr.lee@clinic.ca",
            subject="test",
            body_text="body",
            encounter_id="E-1",
            finding_id="F-1",
        )
        result = doctor_email.send_doctor_summary(summary)
        # Still returns True — the dev mailbox caught it
        assert result is True
        # Verify the dev mailbox was written
        mailbox = tmp_path / "doctor_emails.jsonl"
        assert mailbox.is_file()
        record = json.loads(mailbox.read_text().strip())
        assert record["to"] == "dr.lee@clinic.ca"


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
