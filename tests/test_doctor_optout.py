"""Tests for the per-doctor opt-out mechanism.

Some doctors will be hostile to the email — "I don't have time for
this, my notes are fine." For v1 the opt-out is a JSON file in
/app/logs. v2 will move it to a per-tenant DB table.

What's pinned
-------------
* Opt-out is per-email-address, case-insensitive
* Opt-out is idempotent (re-calling opt_out_doctor returns False)
* Opt-in is idempotent (re-calling opt_in_doctor returns False)
* Empty/None email is a no-op
* send_doctor_summary respects the opt-out
* Opt-out file is missing/corrupt -> treated as no opt-outs
"""

from __future__ import annotations

import pytest

from ai_billing_audit.doctor_email import (
    DoctorSummary,
    _is_doctor_opted_out,
    _load_optouts,
    opt_out_doctor,
    opt_in_doctor,
    send_doctor_summary,
)
from ai_billing_audit.clinical_note_storage import PhiStorageIntegrityError


def _summary(to_email="dr.lee@clinic.ca", opt_in_env="1"):
    """Build a doctor summary with a configurable opt-in env var."""
    import os

    os.environ["DOCTOR_SUMMARY_OPT_IN"] = opt_in_env
    return DoctorSummary(
        to_email=to_email,
        subject="test",
        body_text="body",
        encounter_id="E-1",
        finding_id="F-1",
    )


def test_opt_out_creates_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    assert opt_out_doctor("Dr.Lee@clinic.ca", reason="too busy") is True
    assert b"dr.lee@clinic.ca" not in (tmp_path / "doctor_optouts.json").read_bytes()
    data = _load_optouts()
    assert "dr.lee@clinic.ca" in data
    assert data["dr.lee@clinic.ca"]["reason"] == "too busy"


def test_opt_out_is_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    opt_out_doctor("DR.LEE@clinic.ca")
    # Lookup with lowercase is True
    assert _is_doctor_opted_out("dr.lee@clinic.ca") is True
    # Lookup with mixed case is also True
    assert _is_doctor_opted_out("Dr.Lee@Clinic.CA") is True


def test_opt_out_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    assert opt_out_doctor("dr.lee@clinic.ca") is True
    assert opt_out_doctor("dr.lee@clinic.ca") is False  # already there
    assert opt_out_doctor("DR.LEE@clinic.ca") is False  # case-insensitive
    assert len(_load_optouts()) == 1


def test_opt_in_removes_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    opt_out_doctor("dr.lee@clinic.ca")
    assert opt_in_doctor("dr.lee@clinic.ca") is True
    assert _is_doctor_opted_out("dr.lee@clinic.ca") is False
    # Idempotent
    assert opt_in_doctor("dr.lee@clinic.ca") is False


def test_opt_out_empty_email_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    assert opt_out_doctor("") is False
    assert opt_out_doctor(None) is False
    assert _load_optouts() == {}


def test_load_optouts_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    # No file exists yet
    assert _load_optouts() == {}
    assert _is_doctor_opted_out("anyone@clinic.ca") is False


def test_load_optouts_corrupt_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    p = tmp_path / "doctor_optouts.json"
    p.write_text("this is not json {")
    with pytest.raises(PhiStorageIntegrityError):
        _load_optouts()


def test_send_respects_opt_out(tmp_path, monkeypatch):
    """When the doctor is opted out, send_doctor_summary returns False
    AND does not write to the dev mailbox."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    opt_out_doctor("dr.lee@clinic.ca")
    s = _summary(to_email="dr.lee@clinic.ca")
    assert send_doctor_summary(s) is False
    # No dev mailbox entry
    assert not (tmp_path / "doctor_emails.jsonl").exists()


def test_send_proceeds_when_not_opted_out(tmp_path, monkeypatch):
    """When the doctor is NOT opted out, send proceeds (to dev mailbox)."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    # Not opted out
    s = _summary(to_email="dr.lee@clinic.ca")
    assert send_doctor_summary(s) is True
    assert (tmp_path / "doctor_emails.jsonl").exists()
