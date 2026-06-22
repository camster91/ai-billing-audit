"""Tests for the /contact sales form.

Sales calls need a 'book a walkthrough' CTA. The contact form
writes to the audit trail so the privacy officer can verify
who asked what and when. We don't store PHI in the contact
form (it's a sales request, not a clinical action).

What's pinned
-------------
* GET /contact renders the form
* POST /contact validates input: name, clinic, email, volume, message
* Invalid input → form re-renders with the error message
* Valid input → success page with SHA-256 prefix of email
* The contact event is written to the audit trail
* Email is SHA-256-hashed in the audit trail (no plaintext)
* The contact event has tenant_id (multi-tenant scoping)
* Topbar nav has Contact link
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit.contact import (
    valid_email,
    valid_volume,
)


# ---------- pure-validation tests ----------


def test_valid_email_accepts_normal_addresses():
    for e in [
        "doctor@example.com",
        "billing@north-york-medical.ca",
        "jane.doe+a-tag@example.co.uk",
        "x@y.io",
    ]:
        assert valid_email(e), f"should accept {e!r}"


def test_valid_email_rejects_garbage():
    for e in [
        "",
        "no-at-sign.com",
        "@no-local.com",
        "no-domain@",
        "spaces in@email.com",
        "tabs\tin@email.com",
        "x@" + "y" * 400,  # domain too long
        None,  # type: ignore
        "trailing-newline@email.com\n",
    ]:
        assert not valid_email(e), f"should reject {e!r}"


def test_valid_volume_accepts_positive_integers():
    for v in ["1", "100", "10000", "1000000"]:
        assert valid_volume(v), f"should accept {v!r}"


def test_valid_volume_rejects_garbage():
    for v in ["0", "-1", "abc", "1.5", "1000001", "", " "]:
        assert not valid_volume(v), f"should reject {v!r}"


# ---------- HTTP route tests ----------


@pytest.fixture
def client(monkeypatch, tmp_path):
    audit_log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(tmp_path / "upload_jobs.jsonl"))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.audit_actions as aa_mod
    importlib.reload(aa_mod)
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app), audit_log


def test_contact_get_renders_form(client):
    test_client, _ = client
    resp = test_client.get("/contact")
    assert resp.status_code == 200
    assert "Book a 15-minute walkthrough" in resp.text
    # The form fields
    assert 'name="name"' in resp.text
    assert 'name="clinic"' in resp.text
    assert 'name="email"' in resp.text
    assert 'name="monthly_claims"' in resp.text
    assert 'name="message"' in resp.text


def test_contact_post_valid_submission_writes_audit_event(client):
    test_client, audit_log = client
    resp = test_client.post("/contact", data={
        "name": "Dr. Jane Smith",
        "clinic": "North York Medical",
        "email": "doctor@example.com",
        "monthly_claims": "1500",
        "message": "We're looking for tools that catch modifier-25 issues.",
    })
    assert resp.status_code == 200
    # Success page
    assert "Thanks" in resp.text
    assert "doctor@example.com" not in resp.text  # email never echoed back
    # The audit trail has the event
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    contact_events = [e for e in events if e.get("action") == "contact_request"]
    assert len(contact_events) == 1
    assert contact_events[0]["tenant_id"] == "default"
    # Email is hashed
    assert "doctor@example.com" not in str(contact_events[0])
    assert len(contact_events[0]["user_identifier"]) == 64  # SHA-256 hex
    # Chain signature is present (audit_actions.append goes
    # through the SHA-256 chain)
    assert "cryptographic_signature" in contact_events[0]
    assert "previous_signature" in contact_events[0]


def test_contact_post_hashes_email_lowercase(client):
    """Email is normalized to lowercase before hashing so 'A@x' and
    'a@x' produce the same SHA-256 — useful for dedupe."""
    test_client, audit_log = client
    test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "MixedCase@Example.COM",
        "monthly_claims": "100",
        "message": "x",
    })
    test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "mixedcase@example.com",
        "monthly_claims": "100",
        "message": "x",
    })
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    contact_events = [e for e in events if e.get("action") == "contact_request"]
    # Both should hash to the same SHA-256 prefix
    assert len(contact_events) == 2
    assert contact_events[0]["user_identifier"] == contact_events[1]["user_identifier"]


def test_contact_post_invalid_email_returns_form_with_error(client):
    test_client, audit_log = client
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "not-an-email",
        "monthly_claims": "100",
        "message": "x",
    })
    assert resp.status_code == 200
    assert "valid email" in resp.text.lower() or "couldn't submit" in resp.text.lower()
    # No audit event written
    if audit_log.exists():
        events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
        contact_events = [e for e in events if e.get("action") == "contact_request"]
        assert len(contact_events) == 0


def test_contact_post_missing_name_returns_form_with_error(client):
    test_client, _ = client
    resp = test_client.post("/contact", data={
        "name": "",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "100",
        "message": "x",
    })
    assert resp.status_code == 200
    assert "name" in resp.text.lower()


def test_contact_post_missing_volume_returns_form_with_error(client):
    test_client, _ = client
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "",
        "message": "x",
    })
    assert resp.status_code == 200
    assert "claim volume" in resp.text.lower() or "monthly" in resp.text.lower()


def test_contact_post_message_truncation(client):
    """A 500-char message gets stored as a 500-char excerpt."""
    test_client, audit_log = client
    long_msg = "x" * 500
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "100",
        "message": long_msg,
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    contact_events = [e for e in events if e.get("action") == "contact_request"]
    assert len(contact_events) == 1
    assert len(contact_events[0]["data_elements"]["message_excerpt"]) == 500


def test_contact_post_oversized_message_rejected(client):
    test_client, audit_log = client
    overlong_msg = "x" * 2001
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "100",
        "message": overlong_msg,
    })
    assert resp.status_code == 200
    assert "too long" in resp.text.lower()
    if audit_log.exists():
        events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
        contact_events = [e for e in events if e.get("action") == "contact_request"]
        assert len(contact_events) == 0


def test_contact_success_page_has_email_hash_prefix(client):
    test_client, _ = client
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "100",
        "message": "x",
    })
    # The success page shows a hash prefix for confirmation
    import re
    assert re.search(r"[0-9a-f]{16}\.\.\.", resp.text), (
        "Success page should show the SHA-256 hash prefix"
    )


def test_contact_success_page_has_follow_up_ctas(client):
    """After successful submit, the page should drive the prospect
    toward case studies + ROI calculator."""
    test_client, _ = client
    resp = test_client.post("/contact", data={
        "name": "Dr",
        "clinic": "Clinic",
        "email": "doctor@example.com",
        "monthly_claims": "100",
        "message": "x",
    })
    assert "/case-studies" in resp.text
    assert "/roi" in resp.text


def test_contact_page_uses_base_template(client):
    """The contact page shares the layout with the rest of the app."""
    test_client, _ = client
    resp = test_client.get("/contact")
    assert "<header" in resp.text
    assert "tenant-pill" in resp.text


def test_contact_in_topbar_nav(client):
    """The Contact link is in the topbar so it's discoverable."""
    test_client, _ = client
    resp = test_client.get("/")
    assert "/contact" in resp.text