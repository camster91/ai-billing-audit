"""Tests for the encounter_detail page handling uploaded encounters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit.api import create_app
from ai_billing_audit.clinical_note_storage import encrypt_phi


class _Fixture:
    """Test fixture bag: app, log path, and a TestClient."""

    def __init__(self, app, log, client):
        self.app = app
        self.log = log
        self.client = client


@pytest.fixture
def fx(tmp_path, monkeypatch):
    """Build an app, point the audit-log reader at a tmp log file,
    and return a fixture bag with all three.
    """
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    # Reset severity threshold to default (info) so test data with
    # medium-severity findings isn't filtered out by an env var
    # that an earlier test left set.
    monkeypatch.setenv("MIN_SEVERITY_TO_SHOW", "info")
    log = tmp_path / "upload_jobs.jsonl"
    # Point the closure-bound _latest_real_audit_for at our tmp log
    # via the UPLOAD_AUDIT_LOG_PATH env var (read fresh on every call).
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(log))
    app = create_app()
    return _Fixture(app, log, TestClient(app))


def _write_log_row(
    log: Path,
    encounter_id: str,
    ran_via: str,
    audit_status: str = "ok",
    findings_count: int = 1,
):
    row = {
        "job_id": f"job-{encounter_id}",
        "encounter_id": encounter_id,
        "status": "done",
        "result": {
            "audit_status": audit_status,
            "ran_via": ran_via,
            "findings_count": findings_count,
            "findings": [
                {
                    "finding_id": "F1",
                    "severity": "medium",
                    "rule_id": "DX_LINKAGE_REQUIRED",
                    "quote": "Documentation lacks diagnosis linkage",
                    "explanation": "Test explanation",
                }
            ]
            if findings_count
            else [],
            "summary": f"Test audit summary for {encounter_id}",
            "difficulty_tier": "HARD",
            "variant": "flagged",
        },
    }
    with log.open("ab") as f:
        f.write(encrypt_phi(json.dumps(row).encode("utf-8")) + b"\n")


def test_uploaded_encounter_returns_200_with_audit(fx):
    """An encounter with a real audit log row shows up on the detail page."""
    _write_log_row(fx.log, "REAL_TEST_001", "upload_portal_with_user_note")
    r = fx.client.get("/encounter/REAL_TEST_001")
    assert r.status_code == 200, r.text
    assert "REAL_TEST_001" in r.text
    assert "DX_LINKAGE_REQUIRED" in r.text
    assert "Documentation lacks diagnosis linkage" in r.text
    assert ">Uploaded<" in r.text


def test_uploaded_encounter_plural_route_returns_200(fx):
    """The /encounters/{id} (plural) alias also resolves uploaded encounters."""
    _write_log_row(fx.log, "REAL_TEST_002", "upload_portal_with_user_note")
    r = fx.client.get("/encounters/REAL_TEST_002")
    assert r.status_code == 200, r.text
    assert "REAL_TEST_002" in r.text


def test_unknown_encounter_returns_404(fx):
    """An encounter not in the demo registry AND not in the audit log = 404."""
    r = fx.client.get("/encounter/NEVER_SEEN_BEFORE_999")
    assert r.status_code == 404
    assert "not registered" in r.json()["detail"].lower()


def test_demo_encounter_still_works(fx):
    """The original demo-encounter path still resolves."""
    r = fx.client.get("/encounter/enc_10032")
    assert r.status_code == 200


def test_uploaded_encounter_no_uploaded_badge_for_demo(fx):
    """Demo encounters don't get the Uploaded badge."""
    r = fx.client.get("/encounter/enc_10032")
    assert r.status_code == 200
    assert ">Uploaded<" not in r.text
