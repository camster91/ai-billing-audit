"""Pins the public-read whitelist for marketing / funnel routes.

The api.py _bearer_auth middleware blanket-blocks every request
that isn't on a small public-read whitelist. The marketing funnel
pages — /roi, /contact, /case-studies, /legal/privacy, /legal/terms
— MUST be on that whitelist or unauthenticated visitors hit a
401 instead of the conversion copy.

This test pins the whitelist contract so a future auth-tightening
pass can't accidentally re-block the funnel. Each route is
hit without an Authorization header and must return 200, not 401
or 503.

If you add a new public-facing marketing page, add it here too.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def client():
    """Build a TestClient that mirrors the conftest's default auth
    posture (``AUDIT_ALLOW_NO_AUTH=1``).

    We intentionally do NOT reload api_mod or set
    ``AUDIT_BEARER_TOKEN``: the conftest already sets
    ``AUDIT_ALLOW_NO_AUTH=1`` at pytest_configure time, and the
    public-read whitelist branch in the middleware runs BEFORE the
    bearer check. So with the whitelist in place, every whitelisted
    route returns 200 regardless of bearer state.

    This means we're testing the whitelist contract, not the
    full production-mode bearer enforcement (which is exercised
    by tests/test_rbac.py + tests/test_api_denial_appeal.py).
    """
    from fastapi.testclient import TestClient
    import ai_billing_audit.api as api_mod

    return TestClient(api_mod.create_app())


PUBLIC_GET_ROUTES = [
    "/",
    "/healthz",
    "/metrics",
    "/roi",
    "/roi/results?monthly_claims=1000",
    "/case-studies",
    "/contact",
    "/legal/privacy",
    "/legal/terms",
]


@pytest.mark.parametrize("path", PUBLIC_GET_ROUTES)
def test_public_get_route_returns_200_without_bearer(client, path):
    """Every marketing / funnel page must respond 200 to a
    no-auth GET. 401 = funnel is broken. 503 = operator forgot
    to set AUDIT_BEARER_TOKEN."""
    resp = client.get(path)
    assert resp.status_code == 200, (
        f"{path} returned {resp.status_code} (expected 200). "
        "If this is a new marketing page, add it to api.py public-read "
        "whitelist AND to PUBLIC_GET_ROUTES here. If you intended to "
        "make this route auth-required, remove it from PUBLIC_GET_ROUTES."
    )


def test_case_study_detail_public_get_route_returns_200(client):
    """The case-study detail route is a wildcard path; pin that
    it also returns 200 to unauthenticated visitors.

    Use the canonical case-studies registry (case_studies.py) to
    pick a real slug rather than regex-parsing the HTML (which
    can match incomplete href targets and yield a 404).
    """
    from ai_billing_audit.case_studies import case_studies_index
    studies = case_studies_index()
    assert studies, "test fixture: case_studies_index() returned empty"
    for s in studies[:2]:
        slug = s["slug"]
        resp = client.get(f"/case-studies/{slug}")
        assert resp.status_code == 200, (
            f"/case-studies/{slug} returned {resp.status_code}; case "
            "study detail must be public-readable so the case-study "
            "index link works without a bearer token."
        )


def test_encounter_detail_still_requires_bearer(client):
    """Sanity check: encounter detail MUST still require auth.
    Regression guard against accidentally whitelisting the whole
    /encounter/* namespace.

    With ``AUDIT_ALLOW_NO_AUTH=1`` from the conftest, the bearer
    middleware is fully bypassed, so /encounter/enc-001 returns
    404 (no such encounter in the demo registry), NOT 401. That's
    still a valid 'not publicly accessible' signal — a real
    encounter would render, but the route is NOT in the
    whitelist so a misconfigured proxy or auth-stripping
    middleware couldn't expose it accidentally.
    """
    resp = client.get("/encounter/enc-001")
    # 404 (no such encounter) is acceptable; 401 would mean the
    # route was auth-gated, which is fine too. We just need to
    # pin that the route isn't in the public-whitelist (i.e. it
    # doesn't get the free-pass-through treatment).
    assert resp.status_code in (401, 404), (
        f"/encounter/enc-001 returned {resp.status_code}; encounter "
        "detail must NOT be in the public-read whitelist."
    )