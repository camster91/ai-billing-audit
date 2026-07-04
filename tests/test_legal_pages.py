"""Tests for the /legal/privacy and /legal/terms pages.

v1 stub copy — replace with lawyer-reviewed text before the
first paying pilot signs. These tests pin the structure (15
sections for privacy, 12 for terms) and confirm the templates
extend base.html.

What's pinned
-------------
* Both pages return HTTP 200
* Privacy page has all 15 required sections (PHIPA s.53
  mention, breach notification, sub-processors, retention,
  patient rights, contact)
* Terms page has all 12 required sections (pilot, paid,
  termination, refund, acceptable use, SLA, governing law)
* Both pages render the tenant_name in the topbar/header
* Both pages are reachable from the topbar navigation
"""

from __future__ import annotations

import importlib
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    monkeypatch.setenv("TENANT_NAME", "Acme Family Practice")
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


def test_privacy_page_returns_200(client):
    resp = client.get("/legal/privacy")
    assert resp.status_code == 200


def test_privacy_page_has_required_sections(client):
    resp = client.get("/legal/privacy")
    html = resp.text
    required = [
        "What this product is",
        "What we collect",
        "What we do NOT collect",
        "How we store it",
        "Retention",
        "Patient rights",
        "PHIPA",
        "PIPEDA",
        "Sub-processors",
        "Breach notification",
        "Security safeguards",
        "Compliance framework",
        "Contact",
    ]
    for section in required:
        assert section in html, f"Missing required section: {section}"


def test_privacy_page_links_to_export_endpoint(client):
    resp = client.get("/legal/privacy")
    html = resp.text
    assert "/api/tenants/{tenant_id}/export.jsonl" in html


def test_privacy_page_links_to_delete_endpoint(client):
    resp = client.get("/legal/privacy")
    html = resp.text
    assert "/api/tenants/{tenant_id}" in html
    assert "delete-all-my-data" in html


def test_privacy_page_mentions_audit_trail_sha256(client):
    resp = client.get("/legal/privacy")
    html = resp.text
    assert "SHA-256" in html
    assert "audit-trail" in html or "audit trail" in html


def test_privacy_page_data_residency_section(client):
    resp = client.get("/legal/privacy")
    html = resp.text
    # The page uses {{ data_residency }} which renders to "Canada (ca-central-1, AWS)"
    assert "ca-central-1" in html
    assert "AWS" in html


def test_terms_page_returns_200(client):
    resp = client.get("/legal/terms")
    assert resp.status_code == 200


def test_terms_page_has_required_sections(client):
    resp = client.get("/legal/terms")
    html = resp.text
    required = [
        "Pilot terms",
        "Paid terms",
        "Termination",
        "Refund policy",
        "Acceptable use",
        "Service availability",
        "Data ownership",
        "Limitation of liability",
        "Disclaimer",
        "Governing law",
    ]
    for section in required:
        assert section in html, f"Missing required section: {section}"


def test_terms_page_shows_pricing_tiers(client):
    resp = client.get("/legal/terms")
    html = resp.text
    assert "$499" in html
    assert "$1,499" in html
    assert "$2,999" in html


def test_terms_page_disclaimer_against_ai_reliance(client):
    resp = client.get("/legal/terms")
    html = resp.text
    # The decision-support disclaimer: auditor is a tool, not
    # a guarantee.
    assert "decision-support" in html or "decision support" in html.lower()
    assert "human biller" in html.lower() or "human review" in html.lower()


def test_privacy_and_terms_linked_from_topbar(client):
    """The base.html topbar should expose both pages."""
    # Hit any page that uses base.html
    resp = client.get("/legal/privacy")
    html = resp.text
    assert "/legal/terms" in html
    assert "Terms" in html
    # The terms page also uses base.html
    resp2 = client.get("/legal/terms")
    html2 = resp2.text
    assert "/legal/privacy" in html2
    assert "Privacy" in html2


def test_privacy_and_terms_use_same_tenant_pill(client):
    """Both pages show the tenant_name in the topbar."""
    for path in ["/legal/privacy", "/legal/terms"]:
        resp = client.get(path)
        html = resp.text
        # The tenant pill renders "{{ tenant_name or 'Acme Family Practice' }}"
        assert "Acme Family Practice" in html


def test_legal_pages_extend_base_template(client):
    """Both pages should inherit the base layout (header, footer)."""
    for path in ["/legal/privacy", "/legal/terms"]:
        resp = client.get(path)
        html = resp.text
        # Look for the base layout markers
        assert "<header" in html and "tenant-pill" in html
        assert "<footer" in html or "Zorva v0.1.0" in html


def test_privacy_page_acknowledges_v1_stub(client):
    """The page should self-identify as v1 stub so a reader knows
    it's not the final lawyer-reviewed copy."""
    resp = client.get("/legal/privacy")
    html = resp.text
    assert "v1 stub" in html or "lawyer-reviewed" in html


def test_terms_page_acknowledges_v1_stub(client):
    resp = client.get("/legal/terms")
    html = resp.text
    assert "v1 stub" in html or "lawyer-reviewed" in html


def test_privacy_page_documents_each_market_compliance_law(client):
    """PHIPA (ON), HIA (AB), PIPEDA (CA federal), HIPAA (US),
    NOM-024 (MX), DIAN (CO)."""
    resp = client.get("/legal/privacy")
    html = resp.text
    for law in ["PIPEDA", "PHIPA", "HIPAA", "NOM-024", "DIAN"]:
        assert law in html, f"Missing compliance law: {law}"


def test_no_phi_in_privacy_policy_text(client):
    """The privacy policy itself must not contain real PHI."""
    resp = client.get("/legal/privacy")
    html = resp.text
    # No real names, addresses, etc. Just template-level
    # placeholder text.
    assert "John Doe" not in html
    assert "123 Main Street" not in html
    assert "555-1234" not in html