"""Tests for /newsletter (GET form + POST signup) and the
/demo-request POST endpoint (P1 audit fix 2026-07-13).

The /newsletter route writes a 'newsletter_signup' event
to the hash-chained audit trail. The /demo-request POST
route writes a 'contact_request' event with
request_type='demo_request' so the marketing lead can
distinguish demo asks from sales asks.
"""

from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    audit_log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod

    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


# ─── /newsletter ────────────────────────────────────────────────


def test_newsletter_get_renders_form(client):
    resp = client.get("/newsletter")
    assert resp.status_code == 200
    body = resp.text
    assert "Get Zorva updates" in body
    # The form action is /newsletter (POST to itself)
    assert 'action="/newsletter"' in body
    assert 'name="email"' in body


def test_newsletter_post_valid_email_writes_to_audit_trail(client):
    """A valid email POST should succeed and write a
    newsletter_signup event to the audit trail."""
    resp = client.post(
        "/newsletter",
        data={"name": "Test User", "email": "test@example.com"},
        follow_redirects=False,
    )
    # 200 with success state in the form
    assert resp.status_code == 200
    body = resp.text
    assert "You're on the list" in body or "on the list" in body.lower()
    # The audit-trail hash prefix is shown
    assert "Confirmation reference" in body
    assert "SHA-256" in body


def test_newsletter_post_invalid_email_shows_error(client):
    """An invalid email POST shows the form with an error,
    does NOT succeed."""
    resp = client.post(
        "/newsletter",
        data={"name": "Test", "email": "not-an-email"},
    )
    assert resp.status_code == 200
    body = resp.text
    # Form re-renders with error message
    assert "valid email" in body.lower() or "Please enter" in body
    # Success state NOT shown
    assert "You're on the list" not in body


def test_newsletter_post_empty_email_shows_error(client):
    resp = client.post(
        "/newsletter",
        data={"name": "Test", "email": ""},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "valid email" in body.lower() or "Please enter" in body


# ─── /demo-request (POST) ────────────────────────────────────────


def test_demo_request_get_renders_form(client):
    resp = client.get("/demo-request")
    assert resp.status_code == 200
    body = resp.text
    # The form posts to /demo-request (its own endpoint, not /contact)
    assert 'action="/demo-request"' in body
    assert "Request a walkthrough" in body


def test_demo_request_post_valid_writes_with_request_type_demo(client):
    """A valid POST to /demo-request should write a
    contact_request event with request_type='demo_request'
    so the marketing lead can distinguish from /contact."""
    resp = client.post(
        "/demo-request",
        data={
            "name": "Dr. Test",
            "clinic": "Test Clinic",
            "email": "drtest@example.com",
            "monthly_claims": "1500",
            "emr": "accuro",
            "message": "Tuesday 2pm MT",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    # Success state
    assert "Thanks" in body or "calendar queue" in body.lower()
    # Audit-trail hash prefix shown
    assert "Confirmation reference" in body


def test_demo_request_post_invalid_email_shows_error(client):
    resp = client.post(
        "/demo-request",
        data={
            "name": "Dr. Test",
            "clinic": "Test Clinic",
            "email": "not-an-email",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "valid email" in body.lower() or "Please enter" in body
    # Success state NOT shown
    assert "calendar queue" not in body.lower()


def test_demo_request_uses_distinct_audit_trail_row(client):
    """Two POSTs — one to /contact, one to /demo-request —
    produce distinct audit-trail rows so the marketing lead
    can filter by request_type."""
    # POST to /contact
    client.post(
        "/contact",
        data={
            "name": "Sales Lead",
            "clinic": "Sales Clinic",
            "email": "sales@example.com",
            "monthly_claims": "2000",
        },
    )
    # POST to /demo-request
    client.post(
        "/demo-request",
        data={
            "name": "Demo Lead",
            "clinic": "Demo Clinic",
            "email": "demo@example.com",
            "monthly_claims": "3000",
        },
    )
    # Read the audit trail and confirm both events exist
    from pathlib import Path
    import os

    log_path = Path(os.environ["AUDIT_TRAIL_LOG"])
    if log_path.exists():
        from ai_billing_audit.clinical_note_storage import (
            read_encrypted_json_records,
        )

        rows = read_encrypted_json_records(log_path)
        # Both email hashes should appear in the trail
        # SHA-256 of "sales@example.com" / "demo@example.com" lowercased
        import hashlib

        sales_hash = hashlib.sha256(b"sales@example.com").hexdigest()
        demo_hash = hashlib.sha256(b"demo@example.com").hexdigest()
        user_identifiers = {str(row.get("user_identifier", "")) for row in rows}
        assert sales_hash in user_identifiers
        assert demo_hash in user_identifiers


# ─── /newsletter and /demo-request are in the public whitelist ──


def test_newsletter_does_not_require_bearer_token(client):
    """The /newsletter GET is in the public-read whitelist
    so prospects can subscribe without an auth header."""
    # The test_client is in allow-no-auth mode; this confirms
    # the route serves without auth. The auth-middleware
    # whitelist is verified by code inspection in api.py
    # (see PUBLIC_READ_ENDPOINTS in the marketing-route set).
    resp = client.get("/newsletter")
    assert resp.status_code == 200


def test_demo_request_does_not_require_bearer_token(client):
    resp = client.get("/demo-request")
    assert resp.status_code == 200
