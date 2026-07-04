"""Pins the in-process rate-limit middleware contract.

Traefik does the network-edge rate limit; the FastAPI
middleware is defence-in-depth so a misconfigured proxy or a
direct-container-request from the host can't drive /contact
into spam.

Limit: 10 requests/minute per IP for:
  * POST /contact
  * POST /api/encounters/upload

The 11th request in a 60-second window returns 429 with a
Retry-After header. The middleware does NOT limit:
  * GET routes (marketing pages, /roi, /case-studies, etc.)
  * Auth-required routes (already gated by bearer)
  * Anything else
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient with a fresh rate-limit state."""
    import ai_billing_audit.api as api_mod
    # Reset the module-level rate-limit state so previous tests'
    # buckets don't carry over.
    if hasattr(api_mod, "_rate_limit_state"):
        api_mod._rate_limit_state.clear()
    from fastapi.testclient import TestClient
    return TestClient(api_mod.create_app())


def test_eleventh_post_contact_returns_429(client):
    """11 rapid POST /contact requests → first 10 are 200/422
    (validation may reject some), 11th is 429."""
    statuses: list[int] = []
    for _ in range(11):
        # Empty body is fine for testing rate limit; we don't
        # care if validation rejects the form, only that the
        # middleware ran.
        r = client.post("/contact", data={})
        statuses.append(r.status_code)
    assert statuses[-1] == 429, (
        f"11th POST /contact returned {statuses[-1]}; "
        "expected 429 (rate limit). All responses: {statuses}"
    )
    # The 429 response includes Retry-After
    r429 = client.post("/contact", data={})
    assert r429.status_code == 429
    assert r429.headers.get("Retry-After") == "60"


def test_rate_limit_is_per_ip(client):
    """Two different X-Forwarded-For values → independent buckets.

    TestClient doesn't let us change request.client.host
    directly, but X-Forwarded-For is what Traefik sets, and
    the middleware keys on X-Forwarded-For first.
    """
    # Burn 10 requests from IP A
    for _ in range(10):
        client.post(
            "/contact",
            data={},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
    # 11th from IP A → 429
    r = client.post(
        "/contact",
        data={},
        headers={"X-Forwarded-For": "10.0.0.1"},
    )
    assert r.status_code == 429, (
        f"11th from 10.0.0.1 returned {r.status_code}; expected 429"
    )
    # IP B is unaffected
    r = client.post(
        "/contact",
        data={},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert r.status_code != 429, (
        f"first from 10.0.0.2 returned {r.status_code}; "
        "different IPs must have independent rate-limit buckets"
    )


def test_get_routes_are_not_rate_limited(client):
    """Marketing GETs are cheap and unrate-limited."""
    for _ in range(50):
        r = client.get("/roi")
        assert r.status_code != 429, (
            f"GET /roi returned {r.status_code} on request {_ + 1}; "
            "marketing GETs are not rate-limited"
        )


def test_unrelated_post_routes_are_not_rate_limited(client):
    """A POST that's not /contact or /api/encounters/upload is
    not rate-limited (e.g. /api/encounters/{id}/accept which
    requires auth — it's gated by the bearer middleware).

    We test this by hitting a small body-less POST that the
    middleware will let through (because /healthz's POST is
    not limited and not gated). The actual response status
    doesn't matter for the rate-limit assertion; only that the
    status is NEVER 429.
    """
    # /healthz POST is not in the limited set, and it's a no-op
    # FastAPI route (the @app.get doesn't bind POST). Use it
    # as a sentinel — the rate-limit middleware lets it through
    # immediately, and 405 from FastAPI is fine for our purpose.
    for _ in range(15):
        r = client.post("/healthz")
        assert r.status_code != 429, (
            f"POST /healthz returned {r.status_code} on request "
            f"{_ + 1}; only /contact and /api/encounters/upload "
            "are rate-limited"
        )


def test_upload_route_is_rate_limited(client):
    """POST /api/encounters/upload is rate-limited like /contact."""
    # No auth → expect 401, not 429, for first 10.
    # 11th should be 429 because the rate-limit middleware
    # runs BEFORE the bearer check (it's listed first in the
    # middleware chain).
    for i in range(11):
        r = client.post(
            "/api/encounters/upload",
            json={},
            headers={"X-Forwarded-For": "10.0.0.99"},
        )
        if i < 10:
            assert r.status_code != 429, (
                f"request {i + 1} returned 429; first 10 should pass"
            )
        else:
            assert r.status_code == 429, (
                f"request {i + 1} returned {r.status_code}; "
                "expected 429 (rate limit)"
            )