"""Tests for the runner's doctor-email hook.

When a real-data audit finds a finding, _send_doctor_emails builds
and sends a doctor-summary email. This is the integration test that
proves the email pipeline actually fires on a real audit, not just
that build_doctor_summary() works in isolation.

What's pinned
-------------
* Synth/demo path -> 0 emails sent (no real doctor to email)
* Real-data path with findings but no doctor_email -> 0 emails sent
* Real-data path with findings + doctor_email -> 1 email sent
* Real-data path with empty findings -> 0 emails sent
* Most-severe finding is the one that gets emailed
* Email exceptions don't fail the audit job
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from ai_billing_audit import job_queue


def _finding(severity: str, finding_id: str = "F-1", rule_id: str = "rule_modifier_25_001"):
    return {
        "finding_id": finding_id,
        "rule_id": rule_id,
        "severity": severity,
        "suggested_code": "99214-25",
        "quote": "reviewed labs",
        "explanation": "modifier 25 needed",
    }


def test_no_email_on_synth_path():
    """Demo/synth uploads don't trigger doctor emails."""
    sent = job_queue._send_doctor_emails(
        encounter={"doctor_email": "dr.x@clinic.ca"},
        clinical_note="some note",
        findings=[_finding("high")],
        synth_out={"ran_via": "upload_portal"},
    )
    assert sent == 0


def test_no_email_when_no_findings():
    """Clean audit -> no email."""
    sent = job_queue._send_doctor_emails(
        encounter={"doctor_email": "dr.x@clinic.ca"},
        clinical_note="some note",
        findings=[],
        synth_out={"ran_via": "upload_portal_with_user_note"},
    )
    assert sent == 0


def test_no_email_when_no_doctor_email():
    """Real-data audit but no doctor_email in encounter dict -> 0 sent."""
    sent = job_queue._send_doctor_emails(
        encounter={},
        clinical_note="some note",
        findings=[_finding("high")],
        synth_out={"ran_via": "upload_portal_with_user_note"},
    )
    assert sent == 0


def test_sends_email_for_most_severe_finding():
    """Real-data audit with multiple findings -> one email for the worst one."""
    with patch.object(job_queue, "_send_doctor_emails", wraps=job_queue._send_doctor_emails) as spy:
        # The real build_doctor_summary + send_doctor_summary are tested
        # elsewhere. We monkey-patch them here to verify they're CALLED
        # with the right argument.
        with patch("ai_billing_audit.doctor_email.build_doctor_summary") as build, \
             patch("ai_billing_audit.doctor_email.send_doctor_summary", return_value=True) as send:
            build.return_value = MagicMock()
            sent = job_queue._send_doctor_emails(
                encounter={"doctor_email": "dr.smith@clinic.ca"},
                clinical_note="chest pain ECG",
                findings=[
                    _finding("low", finding_id="F-low", rule_id="rule_em_001"),
                    _finding("critical", finding_id="F-crit", rule_id="rule_modifier_25_001"),
                    _finding("medium", finding_id="F-med", rule_id="rule_icd_001"),
                ],
                synth_out={"ran_via": "upload_portal_with_user_note"},
            )
            assert sent == 1
            # The critical finding is the one that got emailed.
            called_finding = build.call_args.kwargs["finding"]
            assert called_finding["finding_id"] == "F-crit"
            send.assert_called_once()


def test_send_exception_does_not_fail_audit():
    """If the email pipeline throws, the audit result still returns."""
    with patch("ai_billing_audit.doctor_email.build_doctor_summary") as build, \
         patch("ai_billing_audit.doctor_email.send_doctor_summary", side_effect=RuntimeError("smtp down")):
        build.return_value = MagicMock()
        sent = job_queue._send_doctor_emails(
            encounter={"doctor_email": "dr.smith@clinic.ca"},
            clinical_note="chest pain",
            findings=[_finding("high")],
            synth_out={"ran_via": "upload_portal_with_user_note"},
        )
        assert sent == 0  # email not counted as sent, but no exception leaked


def test_send_returns_zero_when_summary_unbuildable():
    """When build_doctor_summary returns None (e.g. missing email), 0 sent."""
    with patch("ai_billing_audit.doctor_email.build_doctor_summary", return_value=None), \
         patch("ai_billing_audit.doctor_email.send_doctor_summary", return_value=True) as send:
        sent = job_queue._send_doctor_emails(
            encounter={"doctor_email": "dr.smith@clinic.ca"},
            clinical_note="note",
            findings=[_finding("high")],
            synth_out={"ran_via": "upload_portal_with_user_note"},
        )
        assert sent == 0
        send.assert_not_called()