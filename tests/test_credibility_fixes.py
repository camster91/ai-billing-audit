"""Tests for the P2 audit fixes (2026-07-13):
  - F1 citation includes val-set size + precision/recall
  - 19-encounter claim is honest about being a shadow audit
  - Press testimonials are honestly attributed (no fake clinic names)
  - Third-party coverage section explains the outreach status
  - Cookie consent banner is present + has the correct copy
"""
from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


# ─── F1 citation honesty ─────────────────────────────────────────


def test_about_html_f1_citation_includes_val_set_size(client):
    """about.html used to say 'F1=0.690 on the cleaned AHCIP val
    set' without telling the prospect the val set is 10 encounters.
    Now it cites precision + recall + the val set size + that it's
    small-n."""
    resp = client.get("/about")
    assert resp.status_code == 200
    body = resp.text
    # The new honest F1 citation
    assert "F1=0.690" in body
    assert "precision 0.625" in body
    assert "recall 0.769" in body
    assert "10-encounter" in body
    assert "13-gold-finding" in body
    # Acknowledgement that small-n is a limitation
    assert "small-n" in body.lower() or "small n" in body.lower()


def test_home_html_catch_rate_explains_val_set(client):
    """home.html used to say 'about 77 of every 100 errors caught'
    without context. Now the 77% number is labeled as recall on
    the 10-encounter val set."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # "77 of every 100" is still there
    assert "77" in body
    # But now it's contextualized
    assert "10-encounter" in body or "val set" in body.lower()
    # Precision / recall distinction is explained
    assert "precision" in body.lower() or "real finding" in body.lower()


def test_status_html_f1_citation_includes_val_set_size(client):
    """status.html used to say 'F1=0.690 on cleaned val' without
    val set size. Now it includes precision + recall + n."""
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.text
    assert "F1=0.690" in body
    assert "10-encounter" in body
    assert "precision 0.625" in body
    assert "recall 0.769" in body


# ─── 19-encounter claim honesty ─────────────────────────────────


def test_home_html_19_encounter_claim_attributed_correctly(client):
    """home.html used to say 'A 19-encounter audit on a real
    AHCIP-style sample' without attributing it. Now it says it
    was a 2025-Q4 shadow audit."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # The 19-encounter claim is still here
    assert "19-encounter" in body
    # But now attributed to a 2025-Q4 shadow audit (not a current claim)
    assert "2025-Q4" in body or "shadow audit" in body
    # Honest about the finding count
    assert "23 findings" in body or "23" in body


# ─── Press testimonials honesty ──────────────────────────────────


def test_press_html_testimonials_are_honestly_attributed(client):
    """press.html quotes should not claim to be from a named
    clinic (since we don't have written permission). The
    attribution should be by role only + an explicit note
    explaining why we don't name the clinic yet."""
    resp = client.get("/press")
    assert resp.status_code == 200
    body = resp.text
    # The two quotes are still here
    assert "Zorva caught four patterns" in body
    assert "reads the clinical note" in body
    # They are attributed by role, not by clinic name
    assert "Billing lead" in body
    assert "PCN operations director" in body
    # The honest explanation is in the page
    assert "permission" in body.lower()
    assert "anonymously" in body.lower() or "role only" in body.lower()
    # No fake clinic names like "Calgary Family Health Clinic"
    for fake in [
        "Calgary Family",
        "Edmonton Medical",
        "Red Deer",
        "Dr. Smith",
        "Dr. Jones",
    ]:
        assert fake not in body, f"press.html contains fake clinic name: {fake!r}"


def test_press_html_third_party_coverage_section_honest(client):
    """The 'Third-party coverage' section should explain the
    current state (no coverage yet) AND the active outreach
    (in-progress pitches to PCN networks, trade press, etc.)
    so a journalist can see we're not just sitting still."""
    resp = client.get("/press")
    assert resp.status_code == 200
    body = resp.text
    # "no published third-party coverage" or similar
    assert "no" in body.lower() and "coverage" in body.lower()
    # Outreach in progress
    assert "outreach" in body.lower() or "in progress" in body.lower()
    # Named outlets (PCN Network, CHT, HIMSS Alberta)
    assert "PCN" in body
    # Reference customers in progress
    assert "Reference customers" in body or "reference-customer" in body.lower()


# ─── About.html geography fix ────────────────────────────────────


def test_about_html_drops_toronto_studio_framing(client):
    """about.html used to lead with 'a small Toronto studio' which
    conflicts with the Alberta-first positioning. Now it says
    'a small Ontario studio' (matches the company facts in the
    boilerplate, doesn't claim a Toronto-specific street cred)."""
    resp = client.get("/about")
    assert resp.status_code == 200
    body = resp.text
    # New framing
    assert "Ontario studio" in body
    # First paragraph no longer leads with Toronto as the studio
    # location
    assert "a small Toronto studio that ships" not in body


# ─── Cookie consent banner ──────────────────────────────────────


def test_cookie_consent_banner_present_on_every_public_page(client):
    """The cookie consent banner is in base.html so it should
    appear on every page that extends base.html. The disclosure
    is a PIPEDA / HIA / GDPR requirement even though the site
    doesn't actually set cookies — a privacy officer should be
    able to confirm at a glance that no tracking is in use."""
    paths = [
        "/", "/about", "/blog", "/blog/why-we-built-zorva",
        "/pricing", "/contact", "/demo-request", "/newsletter",
        "/glossary", "/glossary/ahcip", "/changelog/v0.5.0",
        "/case-studies", "/security", "/status", "/try",
        "/legal/privacy", "/legal/terms",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        body = resp.text
        # The banner element is present
        assert "cookie-consent" in body, f"{path} missing cookie-consent element"
        # The disclosure text mentions "no third-party trackers"
        assert "third-party trackers" in body or "no third-party" in body.lower()
        # The privacy policy is linked
        assert "/legal/privacy" in body


def test_cookie_consent_banner_has_dismiss_button(client):
    """The banner must have a dismiss button that the user can
    click to hide it (and persist the dismissal in localStorage)."""
    resp = client.get("/")
    body = resp.text
    assert "cookie-consent-dismiss" in body
    assert "Got it" in body


def test_cookie_consent_uses_localstorage_not_cookies(client):
    """The banner explicitly says it uses localStorage, NOT
    cookies. This is the PIPEDA / HIA compliance posture."""
    resp = client.get("/")
    body = resp.text
    assert "localStorage" in body
    # No actual cookies set by the banner
    # (the response shouldn't have Set-Cookie for the banner)
    assert "Set-Cookie" not in resp.headers or "consent" not in resp.headers.get("Set-Cookie", "")


def test_cookie_consent_banner_hidden_by_default(client):
    """The banner HTML is in the page (so screen readers can
    find it) but `hidden` is set by default. The script reveals
    it on the client side if no localStorage dismissal exists."""
    resp = client.get("/")
    body = resp.text
    # The element has the `hidden` attribute (the script
    # reveals it via JS, not the server)
    assert 'id="cookie-consent"' in body
    assert 'hidden' in body
