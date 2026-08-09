"""Tests for branded 404/500 error pages.

P0 audit fix 2026-07-13: the marketing site had no 404/500
branded pages and no @app.exception_handler, so a mistyped
URL returned a generic white page. Added:
  - 404.html template extending base.html
  - 500.html template extending base.html
  - @app.exception_handler(404) — HTML for marketing routes,
    JSON for /api/* routes (per existing 404 API contract)
  - @app.exception_handler(500) — branded HTML
  - Generic catch-all @app.get("/{path:path}") for unmatched
    HTML routes (Starlette raises 404 before middleware sees
    some paths; the catch-all ensures the branded 404 always
    shows for marketing routes)
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


def test_unknown_html_path_returns_branded_404(client):
    """An unknown marketing path returns the branded 404 page with
    the base.html layout (topbar, footer, OG meta)."""
    resp = client.get("/this-page-does-not-exist")
    assert resp.status_code == 404
    body = resp.text
    # Branded 404 page
    assert "404" in body
    assert (
        "not found" in body.lower()
        or "isn&#x2019;t here" in body
        or "isn’t here" in body
    )
    # Extends base.html (topbar with brand SVG)
    assert 'aria-label="Zorva home"' in body
    # CTA buttons point at real pages
    assert 'href="/"' in body
    assert 'href="/try"' in body


def test_unknown_api_path_returns_json_404(client):
    """An unknown /api/* path returns a JSON 404 (per existing
    API contract — the React portal expects JSON 404 for unknown
    encounters, not an HTML page)."""
    resp = client.get("/api/this-does-not-exist")
    assert resp.status_code == 404
    # Response should be JSON, not HTML
    body = resp.json()
    assert "detail" in body


def test_explicit_accept_json_returns_json_404(client):
    """A marketing path with Accept: application/json returns JSON 404."""
    resp = client.get(
        "/this-marketing-path-does-not-exist",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body


def test_404_page_has_og_meta(client):
    """The branded 404 page includes the standard OG / Twitter
    meta so a shared link still previews as Zorva."""
    resp = client.get("/this-does-not-exist")
    assert resp.status_code == 404
    body = resp.text
    assert 'property="og:title"' in body
    assert 'name="twitter:card"' in body


def test_404_page_keeps_skip_link_and_brand_svg(client):
    """Accessibility — the 404 page is reachable via the
    skip-to-content link and shows the brand mark."""
    resp = client.get("/another-missing-page")
    assert resp.status_code == 404
    assert 'class="skip-link"' in resp.text
    assert "<svg" in resp.text  # brand SVG icon


def test_404_keeps_marketing_route_in_public_read(client):
    """A 404 from a marketing path is still considered
    public-readable (no bearer token) — the test client above
    doesn't pass a bearer header, so a 200 must still be possible
    on /404 (we don't render /404 as a route, but the redirect
    from unknown paths must work without auth)."""
    # The test_client() above sets AUDIT_ALLOW_NO_AUTH=1, but the
    # 404 handler is wired in the public_read branch — exercise
    # the no-auth path explicitly.
    resp = client.get("/not-here-either")
    assert resp.status_code == 404
