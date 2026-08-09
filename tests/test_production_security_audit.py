"""Regression tests for the 2026-07 production security audit fixes.

Covers:
  * Bearer-gated /activity and /reports/* (no longer public GETs)
  * Appeal-letters list requires auth (enumerable metadata)
  * Webhook SSRF: private / link-local / metadata URLs rejected
  * Job errors exposed to clients are sanitized codes
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import pytest


def _signed_principal_headers(
    secret: str,
    *,
    subject: str = "user-1",
    role: str = "admin",
    tenant_id: str = "clinic-a",
    expires_at: int | None = None,
) -> dict[str, str]:
    payload = {
        "subject": subject,
        "role": role,
        "tenant_id": tenant_id,
        "expires_at": expires_at or int(time.time()) + 300,
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": "Bearer production-test-token",
        "X-Zorva-Principal": encoded,
        "X-Zorva-Signature": signature,
    }


@pytest.fixture()
def secured_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "audit-regression-bearer")
    monkeypatch.delenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", raising=False)
    # create_app() captures env at call time for the bearer middleware.
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_activity_requires_bearer(secured_client):
    r = secured_client.get("/activity")
    assert r.status_code == 401


def test_reports_require_bearer(secured_client):
    assert secured_client.get("/reports/by-clinic").status_code == 401
    assert secured_client.get("/reports/clinic-monthly").status_code == 401


def test_appeal_letters_list_requires_bearer(secured_client):
    r = secured_client.get("/api/encounters/enc_demo/appeal-letters")
    assert r.status_code == 401


def test_denial_risk_requires_bearer(secured_client):
    r = secured_client.get("/api/encounters/enc_does_not_exist/denial-risk")
    assert r.status_code == 401


def test_metrics_and_docs_require_bearer(secured_client):
    for path in ("/metrics", "/docs", "/openapi.json", "/redoc"):
        assert secured_client.get(path).status_code == 401, path


def test_webhook_ssrf_blocks_metadata_and_loopback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", raising=False)
    from ai_billing_audit.webhooks import validate_webhook_url

    with pytest.raises(ValueError):
        validate_webhook_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        validate_webhook_url("https://127.0.0.1/hook")
    with pytest.raises(ValueError):
        validate_webhook_url("http://example.com/hook")  # http blocked
    # Public https still ok.
    assert validate_webhook_url("https://example.com/hooks/zorva").startswith(
        "https://"
    )


def test_job_error_sanitized_in_to_dict():
    from ai_billing_audit.job_queue import Job

    job = Job(
        job_id="abc",
        encounter_id="enc_1",
        source="paste",
        source_filename=None,
    )
    job.status = "failed"
    job.error = "RuntimeError: Connection refused to postgres://user:secret@db/1"
    body = job.to_dict()
    assert body["error"] == "audit_job_failed"
    assert "secret" not in body["error"]
    assert "postgres" not in body["error"]


def test_deploy_requires_phi_encryption_key_for_api_and_worker():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy-to-vps.sh").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "PHI_ENCRYPTION_KEY_FILE=" in script
    assert "ERROR: $PHI_ENCRYPTION_KEY_FILE missing" in script
    assert "ZORVA_PHI_ENCRYPTION_KEY=${PHI_ENCRYPTION_KEY}" in script
    assert compose.count("ZORVA_PHI_ENCRYPTION_KEY: ${ZORVA_PHI_ENCRYPTION_KEY}") == 2
    assert "PRINCIPAL_SIGNING_SECRET_FILE=" in script
    assert "ERROR: $PRINCIPAL_SIGNING_SECRET_FILE missing" in script
    assert "ZORVA_PRINCIPAL_SIGNING_SECRET=${PRINCIPAL_SIGNING_SECRET}" in script
    assert (
        compose.count(
            "ZORVA_PRINCIPAL_SIGNING_SECRET: ${ZORVA_PRINCIPAL_SIGNING_SECRET}"
        )
        == 2
    )
    assert "AUDIT_BEARER_TOKEN_FILE=" in script
    assert "ERROR: $AUDIT_BEARER_TOKEN_FILE missing" in script
    assert "AUDIT_BEARER_TOKEN=${AUDIT_BEARER_TOKEN}" in script
    assert compose.count("AUDIT_BEARER_TOKEN: ${AUDIT_BEARER_TOKEN}") == 2


def test_portal_deploy_shares_service_auth_credentials():
    root = Path(__file__).resolve().parents[1]
    script = (root / "deploy-portal.sh").read_text(encoding="utf-8")
    template = (root / "apps/portal/.env.production.example").read_text(
        encoding="utf-8"
    )

    assert "read_secret audit_bearer_token" in script
    assert "read_secret principal_signing_secret" in script
    assert "FASTAPI_BEARER_TOKEN=" in template
    assert "FASTAPI_PRINCIPAL_SIGNING_SECRET=" in template


def test_production_rejects_unsigned_identity_headers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    monkeypatch.delenv("AUDIT_ALLOW_HEADER_RBAC", raising=False)
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    response = client.post(
        "/encounters/bulk-dismiss",
        json={"encounter_ids": [], "rule_id": "rule-x"},
        headers={
            "Authorization": "Bearer production-test-token",
            "X-User-Id": "caller-controlled-user",
            "X-User-Role": "biller",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "verified_principal_required"


def test_production_accepts_signed_admin_principal(monkeypatch: pytest.MonkeyPatch):
    secret = "principal-signing-secret-at-least-32-bytes"
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.setenv("ZORVA_PRINCIPAL_SIGNING_SECRET", secret)
    monkeypatch.setenv("TENANT_ID", "clinic-a")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    response = TestClient(create_app()).get(
        "/admin/users", headers=_signed_principal_headers(secret)
    )

    assert response.status_code == 200
    assert response.json()["user"] == {"user_id": "user-1", "role": "admin"}


def test_production_rejects_tampered_principal_signature(
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "principal-signing-secret-at-least-32-bytes"
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.setenv("ZORVA_PRINCIPAL_SIGNING_SECRET", secret)
    monkeypatch.setenv("TENANT_ID", "clinic-a")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    headers = _signed_principal_headers(secret)
    headers["X-Zorva-Signature"] = "0" * 64
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    response = TestClient(create_app()).get("/admin/users", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_principal_signature"


def test_production_rejects_expired_signed_principal(
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "principal-signing-secret-at-least-32-bytes"
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.setenv("ZORVA_PRINCIPAL_SIGNING_SECRET", secret)
    monkeypatch.setenv("TENANT_ID", "clinic-a")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    response = TestClient(create_app()).get(
        "/admin/users",
        headers=_signed_principal_headers(secret, expires_at=int(time.time()) - 1),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "principal_expired"


def test_production_rejects_overlong_signed_principal_lifetime(
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "principal-signing-secret-at-least-32-bytes"
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.setenv("ZORVA_PRINCIPAL_SIGNING_SECRET", secret)
    monkeypatch.setenv("TENANT_ID", "clinic-a")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    response = TestClient(create_app()).get(
        "/admin/users",
        headers=_signed_principal_headers(
            secret,
            expires_at=int(time.time()) + 301,
        ),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "principal_lifetime_too_long"


def test_production_rejects_principal_for_another_tenant(
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "principal-signing-secret-at-least-32-bytes"
    monkeypatch.setenv("AUDIT_BEARER_TOKEN", "production-test-token")
    monkeypatch.setenv("ZORVA_PRINCIPAL_SIGNING_SECRET", secret)
    monkeypatch.setenv("TENANT_ID", "clinic-a")
    monkeypatch.delenv("AUDIT_ALLOW_NO_AUTH", raising=False)
    from ai_billing_audit.api import create_app
    from fastapi.testclient import TestClient

    response = TestClient(create_app()).get(
        "/admin/users",
        headers=_signed_principal_headers(secret, tenant_id="clinic-b"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "principal_tenant_mismatch"
