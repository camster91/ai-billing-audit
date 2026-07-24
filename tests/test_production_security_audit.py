"""Regression tests for the 2026-07 production security audit fixes.

Covers:
  * Bearer-gated /activity and /reports/* (no longer public GETs)
  * Appeal-letters list requires auth (enumerable metadata)
  * Webhook SSRF: private / link-local / metadata URLs rejected
  * Job errors exposed to clients are sanitized codes
"""
from __future__ import annotations

import os

import pytest

# These tests intentionally exercise the PRODUCTION auth posture:
# bearer required, no AUDIT_ALLOW_NO_AUTH. Clear any ambient flags
# before importing create_app so the middleware captures the right
# values.
os.environ.pop("AUDIT_ALLOW_NO_AUTH", None)
os.environ["AUDIT_BEARER_TOKEN"] = "audit-regression-bearer"
os.environ.pop("ZORVA_WEBHOOK_ALLOW_PRIVATE", None)


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


def test_denial_risk_remains_public_for_demo(secured_client):
    # Demo registry may 404 for unknown ids; the point is auth is not
    # the rejection reason (not 401).
    r = secured_client.get("/api/encounters/enc_does_not_exist/denial-risk")
    assert r.status_code != 401


def test_webhook_ssrf_blocks_metadata_and_loopback():
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
