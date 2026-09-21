"""Tests for the multi-user team RBAC middleware.

Covers the acceptance criteria from kanban task t_846407c4:

1. Three roles: admin, biller, viewer. Correct gate on each write endpoint.
2. The user-identity middleware reads X-User-Id and X-User-Role from
   request headers and produces a ``UserContext``.
3. Per-endpoint RBAC: write endpoints require biller-or-admin. Read
   endpoints allow all roles. Admin-only endpoints (user management)
   require admin.
4. Missing X-User-Id header returns 401 (or dev-mode synthetic when
   ``AUDIT_ALLOW_NO_AUTH`` is set; we exercise both paths).
5. Unknown role returns 403.
6. The audit chain records ``user_id`` + ``user_role`` on write actions.

The tests run in-process via ``starlette.testclient.TestClient``.
"""

from __future__ import annotations

import os
from pathlib import Path

# Set dev-mode allow-no-auth BEFORE importing api so the module-level
# ``app = create_app()`` builds without bearer auth. The RBAC middleware
# has its own dev-mode fallback inside ``_resolve_user_from_request``
# that reads AUDIT_ALLOW_NO_AUTH at call-time, so this also lets the
# RBAC tests work without setting headers when they want the synthetic
# (dev_user, admin) identity.
os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")

# Override AUDIT_TRAIL_LOG to a tmp location for the audit-chain tests
# below. This must happen before audit_actions is imported, otherwise
# _LOG_PATH captures the original /app/logs/audit_trail.jsonl at
# module-import time. By using a fixed tmp path (NOT a per-test path),
# pytest's module-level caching keeps the override stable across tests.
_TMP_AUDIT_LOG = "/tmp/test_audit_trail_rbac.jsonl"
os.environ.setdefault("AUDIT_TRAIL_LOG", _TMP_AUDIT_LOG)

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_billing_audit import api  # noqa: E402
from ai_billing_audit import audit_actions  # noqa: E402


# --------------------------------------------------------------------
# Test fixtures
# --------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """A TestClient against the module-level app."""
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def _clean_audit_log():
    """Truncate the test audit log around each test that touches it."""
    p = Path(_TMP_AUDIT_LOG)
    if p.exists():
        p.unlink()
    yield
    # Leave the file in place between runs for debugging


def _hdr(user_id: str | None, role: str | None) -> dict[str, str]:
    """Build request headers with optional X-User-Id / X-User-Role."""
    out: dict[str, str] = {}
    if user_id is not None:
        out["X-User-Id"] = user_id
    if role is not None:
        out["X-User-Role"] = role
    return out


@pytest.mark.parametrize(
    ("path", "kwargs"),
    [
        ("/encounters/upload/preview", {}),
        ("/encounters/upload/submit", {}),
        ("/encounters/upload/paste", {}),
        ("/encounters/upload/notes", {}),
        ("/encounters/upload/text-note", {}),
        ("/upload/837i", {"json": {}}),
        ("/api/audits", {"json": {}}),
    ],
)
def test_viewer_cannot_use_claim_or_note_upload_mutations(client, path, kwargs):
    response = client.post(path, headers=_hdr("viewer-1", "viewer"), **kwargs)

    assert response.status_code == 403, (path, response.text)


def test_viewer_cannot_poll_audit_job_results(client):
    response = client.get(
        "/encounters/upload/jobs/unknown-job",
        headers=_hdr("viewer-1", "viewer"),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------
# Unit tests on the helpers (no HTTP)
# --------------------------------------------------------------------


def test_user_context_str_round_trips():
    u = api.UserContext(user_id="u-1", role="admin", user_identifier="dev:u-1")
    s = str(u)
    assert "u-1" in s
    assert "admin" in s
    assert u.as_audit_kwargs() == {"user_id": "u-1", "user_role": "admin"}


def test_user_context_as_audit_kwargs_none_user():
    """The as_audit_kwargs helper returns both fields even when None;
    downstream callers (audit_actions.append) skip writing the row
    field when the value is None. The shape contract is two keys,
    always present."""
    u = api.UserContext(user_id=None, role=None, user_identifier="dev:anon")
    assert u.as_audit_kwargs() == {"user_id": None, "user_role": None}


def test_readyz_is_public_and_reports_missing_configuration(
    client, monkeypatch, tmp_path
):
    """Readiness is load-balancer accessible and fails closed when incomplete."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AUDIT_TRAIL_DB", raising=False)
    monkeypatch.delenv("ZORVA_PHI_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ZORVA_PRINCIPAL_SIGNING_SECRET", raising=False)
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(tmp_path / "logs" / "jobs.jsonl"))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database_url_configured": False,
            "audit_trail_db_configured": False,
            "phi_encryption_key_configured": False,
            "principal_signing_secret_configured": False,
            "upload_job_log_directory_writable": False,
        },
    }


def test_readyz_returns_ready_for_configured_writable_baseline(
    client, monkeypatch, tmp_path
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", "postgresql://audit@example.invalid/db")
    monkeypatch.setenv("AUDIT_TRAIL_DB", "postgresql://audit@example.invalid/audit")
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(log_dir / "jobs.jsonl"))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database_url_configured": True,
            "audit_trail_db_configured": True,
            "phi_encryption_key_configured": True,
            "principal_signing_secret_configured": True,
            "upload_job_log_directory_writable": True,
        },
    }


def test_coerce_role_recognizes_known():
    assert api._coerce_role("admin") == "admin"
    assert api._coerce_role("BILLER") == "biller"
    assert api._coerce_role(" Viewer ") == "viewer"
    assert api._coerce_role("superuser") is None
    assert api._coerce_role("") is None
    assert api._coerce_role(None) is None


# --------------------------------------------------------------------
# /healthz and /admin/users (read endpoints, all roles allowed;
# admin endpoint requires admin role)
# --------------------------------------------------------------------


def test_healthz_works_for_all_roles_when_dev_mode(client):
    """When AUDIT_ALLOW_NO_AUTH is set, missing headers fall through
    to a synthetic (dev_user, admin) identity, so healthz works for
    every call regardless of explicit headers."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_admin_endpoint_with_admin_role_works(client):
    r = client.get("/admin/users", headers=_hdr("u-admin", "admin"))
    assert r.status_code == 200


def test_production_bearer_holder_cannot_promote_self_to_admin(monkeypatch):
    """Caller-controlled role headers must not grant production admin access."""
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    monkeypatch.delenv("AUDIT_ALLOW_HEADER_RBAC", raising=False)
    production_client = TestClient(api.create_app())

    response = production_client.get(
        "/admin/users",
        headers={
            "Authorization": "Bearer production-test-token",
            "X-User-Id": "attacker",
            "X-User-Role": "admin",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "verified_principal_required"


def test_admin_endpoint_with_biller_role_returns_403(client):
    r = client.get("/admin/users", headers=_hdr("u-biller", "biller"))
    assert r.status_code == 403
    assert "admin" in r.json()["detail"].lower()


def test_admin_endpoint_with_viewer_role_returns_403(client):
    r = client.get("/admin/users", headers=_hdr("u-viewer", "viewer"))
    assert r.status_code == 403


def test_unknown_role_returns_403(client):
    """An unknown role string should be rejected (defence in depth,
    in case a buggy portal ever sends a typo)."""
    r = client.get("/admin/users", headers=_hdr("u-x", "superuser"))
    assert r.status_code == 403


# --------------------------------------------------------------------
# Write endpoints: viewer should be blocked, biller and admin should pass
# --------------------------------------------------------------------

# Pick a representative write endpoint to exercise. The bulk endpoints
# are the most shape-stable write paths. A "no encounters found" 200/404
# is acceptable — what we're testing is the gate, not the body.


def _post_bulk_dismiss(client, role: str | None):
    return client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": [], "rule_id": "rule_x"},
        headers=_hdr("u-test", role),
    )


def test_viewer_blocked_from_bulk_dismiss(client):
    r = _post_bulk_dismiss(client, "viewer")
    assert r.status_code == 403


def test_biller_allowed_on_bulk_dismiss(client):
    r = _post_bulk_dismiss(client, "biller")
    # 200/400/422 all OK — what we're verifying is the gate PASSED.
    # 400/422 means the bulk endpoint validated the body shape and
    # rejected an empty encounter_ids list (which is the natural
    # response when no demo data is loaded). Anything other than 401/403
    # proves the gate allowed biller through.
    assert r.status_code not in (401, 403), (
        f"biller should pass gate, got {r.status_code}: {r.text}"
    )


def test_admin_allowed_on_bulk_dismiss(client):
    r = _post_bulk_dismiss(client, "admin")
    assert r.status_code not in (401, 403), (
        f"admin should pass gate, got {r.status_code}: {r.text}"
    )


def test_viewer_blocked_from_bulk_accept(client):
    r = client.post(
        "/encounters/bulk-accept",
        json={"encounter_ids": []},
        headers=_hdr("u-test", "viewer"),
    )
    assert r.status_code == 403


def test_viewer_blocked_from_bulk_flag(client):
    r = client.post(
        "/encounters/bulk-flag",
        json={"encounter_ids": []},
        headers=_hdr("u-test", "viewer"),
    )
    assert r.status_code == 403


# --------------------------------------------------------------------
# Audit chain integration: when a write succeeds as biller, the
# audit_actions row records user_id + user_role.
# --------------------------------------------------------------------


def test_audit_row_records_user_id_and_role_when_admin_writes(tmp_path: Path):
    """Manually call audit_actions.append() with user_id + user_role,
    verify the row carries both fields, and verify the chain.

    This test previously declined to call ``verify_chain`` because the
    writer and the verifier disagreed on how ``data_elements`` renders,
    so verification reported rows written by ``append`` as tampered
    (issue #113). The note attributed it to a field separator, which was
    not the cause. Both now share one implementation, so the chain is
    asserted directly."""
    audit_log = Path(_TMP_AUDIT_LOG)
    try:
        # Genesis row (no user_id) — writes with default chain
        audit_actions.append(
            action="finding_emitted",
            encounter_id="enc-1",
            user_identifier="dev:test",
            findings=[{"finding_id": "f-1"}],
        )
        # User row — carries user_id + user_role
        audit_actions.append(
            action="finding_accepted",
            encounter_id="enc-1",
            user_identifier="u-biller-42:biller",
            findings=[{"finding_id": "f-1"}],
            user_id="u-biller-42",
            user_role="biller",
        )
        # Verify the user fields landed on the row
        rows = audit_actions.read_all()
        assert len(rows) >= 2
        last = rows[-1]
        assert last["user_id"] == "u-biller-42"
        assert last["user_role"] == "biller"
        # First row (no user) doesn't carry the fields
        assert "user_id" not in rows[0]
        assert "user_role" not in rows[0]
        # Both rows carry a cryptographic_signature.
        assert "cryptographic_signature" in rows[0]
        assert "cryptographic_signature" in last
        # And the chain they form actually verifies (issue #113).
        # ``user_id`` / ``user_role`` are deliberately outside the chain
        # field set, so adding them must not break verification.
        assert audit_actions.verify_chain(rows) is None
    finally:
        if audit_log.exists():
            audit_log.unlink()


def test_old_audit_rows_without_user_id_still_verify(tmp_path: Path):
    """Pre-existing audit rows (without user_id + user_role) continue to
    write successfully after the schema extension, and still verify.

    Asserts the round-trip plus chain verification, which is now possible
    because the writer and verifier share one implementation (issue
    #113). The additive ``user_id`` / ``user_role`` fields must not affect
    the chain, which is what makes the backward-compatibility guarantee
    real rather than assumed."""
    audit_log = Path(_TMP_AUDIT_LOG)
    try:
        # Clean up any pre-existing rows from an earlier test run
        # that landed in the same shared log path (setdefault at
        # module load pins the path to _TMP_AUDIT_LOG, so other
        # tests in the suite may have already written here).
        # Without this cleanup the len==4 assertion below fails
        # because the read returns the leftover rows too.
        if audit_log.exists():
            audit_log.unlink()
        # Write 3 pre-feature rows (mimicking pre-RBAC logs)
        for i in range(3):
            audit_actions.append(
                action=f"pre_rbac_event_{i}",
                encounter_id=f"enc-{i}",
                user_identifier="dev:legacy",
                findings=[{"finding_id": f"f-{i}"}],
            )
        # Now add a post-feature row with user fields
        audit_actions.append(
            action="finding_accepted",
            encounter_id="enc-9",
            user_identifier="u-admin-1:admin",
            findings=[{"finding_id": "f-9"}],
            user_id="u-admin-1",
            user_role="admin",
        )
        # Round-trip read
        rows = audit_actions.read_all()
        assert len(rows) == 4
        # First 3 are pre-feature (no user fields)
        for r in rows[:3]:
            assert "user_id" not in r
            assert "user_role" not in r
            assert "cryptographic_signature" in r
        # Last row has the new fields
        last = rows[-1]
        assert last["user_id"] == "u-admin-1"
        assert last["user_role"] == "admin"
        assert "cryptographic_signature" in last
        # Rows written before and after the RBAC field extension chain
        # together and verify cleanly.
        assert audit_actions.verify_chain(rows) is None
    finally:
        if audit_log.exists():
            audit_log.unlink()


# --------------------------------------------------------------------
# Per-route authorization on state-changing and admin endpoints
# (issue #117)
# --------------------------------------------------------------------
#
# The bearer middleware is one org-wide gate; these routes additionally need
# a per-user role check. Each was verified to be missing one. FastAPI resolves
# dependencies before invoking the handler, so a role rejection surfaces as
# 403 even when the handler would have returned 404 (feature flag off) or 410
# (expired token).


_ADMIN_ONLY = [
    ("GET", "/api/admin/teaching-signal-queue", {}),
    ("POST", "/api/admin/feedback-loop/run", {}),
    ("PUT", "/api/clinic/default/prompt-version", {"prompt_version_id": "v12"}),
    ("POST", "/api/clinic/default/owner-email", {}),
    (
        "POST",
        "/api/integrations/slack",
        {
            "webhook_url": "https://hooks.slack.com/services/T/B/X",
            "channel": "#x",
            "events": [],
        },
    ),
]


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_ONLY)
def test_non_admin_roles_blocked_from_admin_routes(client, method, path, body):
    """Viewer and biller must both get 403 on admin-only routes."""
    for role in ("viewer", "biller"):
        r = client.request(method, path, json=body, headers=_hdr(f"u-{role}", role))
        assert r.status_code == 403, (method, path, role, r.status_code, r.text[:200])


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_ONLY)
def test_admin_routes_reject_an_unverified_principal(monkeypatch, method, path, body):
    """In production mode, a bearer holder with no verified identity gets 401.

    This is the case that matters: in dev (``AUDIT_ALLOW_NO_AUTH=1``) a
    header-less request is synthesised as ``dev_user``/``admin`` — see
    ``test_healthz_works_for_all_roles_when_dev_mode`` — so the assertion
    only means something once that fallback is off. Follows the pattern of
    ``test_production_bearer_holder_cannot_promote_self_to_admin``.
    """
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    monkeypatch.delenv("AUDIT_ALLOW_HEADER_RBAC", raising=False)
    production_client = TestClient(api.create_app())

    r = production_client.request(
        method,
        path,
        json=body,
        headers={
            "Authorization": "Bearer production-test-token",
            "X-User-Id": "attacker",
            "X-User-Role": "admin",
        },
    )
    assert r.status_code == 401, (method, path, r.status_code, r.text[:200])


def test_viewer_blocked_from_undo_token(client):
    """Undo reverts a prior decision, so it is a write action."""
    r = client.post(
        "/api/undo-token",
        json={"action": "accept", "encounter_id": "e-1", "finding_id": "f-1"},
        headers=_hdr("u-viewer", "viewer"),
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/encounter/e-1/appeal"),
        ("POST", "/encounter/e-1/appeal/ap-1/outcome"),
    ],
)
def test_appeal_routes_require_a_biller_or_admin(client, method, path):
    """A viewer must be rejected; these previously had no role dependency.

    A biller is only asserted *not* to be rejected for role reasons — the
    handler may still fail for other reasons (unknown encounter), which is
    fine for this test's purpose.
    """
    viewer = client.request(method, path, json={}, headers=_hdr("u-viewer", "viewer"))
    assert viewer.status_code == 403, (method, path, viewer.status_code)

    biller = client.request(method, path, json={}, headers=_hdr("u-biller", "biller"))
    assert biller.status_code != 403, (method, path, biller.status_code)


def test_activity_feed_requires_a_principal_but_allows_viewers(client):
    """/api/activity/recent exposes the audit trail.

    It must not be reachable anonymously, but viewers legitimately read the
    activity feed, so the gate is "authenticated principal", not
    "biller-or-admin".
    """
    viewer = client.get("/api/activity/recent", headers=_hdr("u-viewer", "viewer"))
    assert viewer.status_code == 200, viewer.text[:200]


def test_activity_feed_rejects_an_unverified_principal(monkeypatch):
    """No verified identity means no audit-trail read.

    Asserted in production mode only, because dev mode synthesises an admin
    principal for header-less requests.
    """
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    monkeypatch.delenv("AUDIT_ALLOW_HEADER_RBAC", raising=False)
    production_client = TestClient(api.create_app())

    r = production_client.get(
        "/api/activity/recent",
        headers={
            "Authorization": "Bearer production-test-token",
            "X-User-Role": "admin",
        },
    )
    assert r.status_code == 401, (r.status_code, r.text[:200])
