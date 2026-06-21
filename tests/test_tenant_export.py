"""Tests for the tenant data export and deletion endpoints.

PHIPA s.53 (Ontario) and PIPEDA require that patients (or clinics
on their behalf) can request a copy of every piece of PHI we
hold, and request deletion. These tests pin the contract for
GET /api/tenants/{tenant_id}/export.jsonl and
DELETE /api/tenants/{tenant_id}.

What's pinned
-------------
* Export returns JSONL with a manifest object as the last line
* Manifest has SHA-256 hashes for each log section
* Tenant scope: requesting a different tenant_id → 403
* Export records a "data_export" event in the audit trail
* Deletion requires confirmation phrase
* Wrong confirmation → 400
* Wrong tenant_id → 403
* Deletion records a "tenant_purge" event in the audit trail
* Manifest is verifiable: SHA-256 over the rows matches
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _seed_audit_trail(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _seed_appeal_letters(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _seed_upload_jobs(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _make_app_for_tenant(monkeypatch, *, tmp_path: Path, tenant_id: str):
    """Build a fresh app with a tmp log dir."""
    audit_log = tmp_path / "audit_trail.jsonl"
    appeal_log = tmp_path / "appeal_letters.jsonl"
    upload_log = tmp_path / "upload_jobs.jsonl"

    # Set the env var BEFORE reloading the api module so the
    # audit_actions._LOG_PATH and appeal_letter._LOGS_DIR
    # module-level constants read our tmp paths. Otherwise the
    # writes would go to the production /app/logs paths.
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(upload_log))
    monkeypatch.setenv("ZORVA_LOGS_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", tenant_id)

    import ai_billing_audit.audit_actions as aa_mod
    importlib.reload(aa_mod)
    import ai_billing_audit.appeal_letter as al_mod
    importlib.reload(al_mod)
    import ai_billing_audit.api as api_mod
    importlib.reload(api_mod)
    app = api_mod.create_app()
    return app, audit_log, appeal_log, upload_log


def test_export_returns_jsonl_with_manifest(tmp_path, monkeypatch):
    app, audit_log, appeal_log, upload_log = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    _seed_audit_trail(audit_log, [
        {"action": "accept_all", "tenant_id": "default",
         "data_elements": {"encounter_id": "E-1"}},
    ])
    _seed_appeal_letters(appeal_log, [
        {"encounter_id": "E-1", "tenant_id": "default",
         "appeal_basis": "x", "cited_rule_ids": ["rule_1"]},
    ])
    _seed_upload_jobs(upload_log, [
        {"job_id": "J-1", "encounter_id": "E-1",
         "tenant_id": "default", "status": "done",
         "result": {"audit_status": "ok", "findings": []}},
    ])

    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    body = resp.text
    lines = [l for l in body.split("\n") if l]
    # 1 audit_trail + 1 appeal_letter + 1 upload_job + 1 manifest = 4
    assert len(lines) == 4
    parsed = [json.loads(l) for l in lines]
    kinds = [p.get("kind", "manifest") for p in parsed]
    assert "audit_trail" in kinds
    assert "appeal_letter" in kinds
    assert "upload_job" in kinds
    manifest = parsed[-1]
    assert manifest["manifest"] is True
    assert manifest["tenant_id"] == "default"
    assert manifest["n_audit_trail"] == 1
    assert manifest["n_appeal_letters"] == 1
    assert manifest["n_upload_jobs"] == 1
    assert "sha256_audit_trail" in manifest
    assert "sha256_appeal_letters" in manifest
    assert "sha256_upload_jobs" in manifest


def test_export_records_event_in_audit_trail(tmp_path, monkeypatch):
    app, audit_log, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    assert resp.status_code == 200
    # The audit log should have a new data_export event
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    export_events = [e for e in events if e.get("action") == "data_export"]
    assert len(export_events) == 1
    assert export_events[0]["tenant_id"] == "default"


def test_export_other_tenant_403(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="acme"
    )
    client = TestClient(app)
    # Request for a different tenant is rejected
    resp = client.get("/api/tenants/other-tenant/export.jsonl")
    assert resp.status_code == 403


def test_export_manifest_hashes_verify(tmp_path, monkeypatch):
    """Caller can re-hash the rows and verify the manifest matches."""
    import hashlib
    app, audit_log, appeal_log, upload_log = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    rows = [
        {"action": "accept_all", "tenant_id": "default",
         "data_elements": {"encounter_id": "E-1"}},
        {"action": "dismiss", "tenant_id": "default",
         "data_elements": {"encounter_id": "E-2"}},
    ]
    _seed_audit_trail(audit_log, rows)

    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    body = resp.text
    lines = [json.loads(l) for l in body.split("\n") if l]
    manifest = lines[-1]

    # Re-hash the rows the caller would receive
    h = hashlib.sha256()
    for r in rows:
        h.update((json.dumps(r, sort_keys=True) + "\n").encode("utf-8"))
    expected = h.hexdigest()
    assert manifest["sha256_audit_trail"] == expected


def test_export_filters_by_tenant(tmp_path, monkeypatch):
    """Other tenants' rows are not included in the export."""
    app, audit_log, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="acme"
    )
    _seed_audit_trail(audit_log, [
        {"action": "accept_all", "tenant_id": "acme",
         "data_elements": {"encounter_id": "A-1"}},
        {"action": "accept_all", "tenant_id": "north_york",
         "data_elements": {"encounter_id": "B-1"}},
    ])
    client = TestClient(app)
    resp = client.get("/api/tenants/acme/export.jsonl")
    lines = [json.loads(l) for l in resp.text.split("\n") if l]
    # Only the acme row, plus the manifest
    audit_events = [l for l in lines if l.get("kind") == "audit_trail"]
    assert len(audit_events) == 1
    assert audit_events[0]["data_elements"]["encounter_id"] == "A-1"


def test_delete_requires_confirmation(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    # No confirmation
    resp = client.delete("/api/tenants/default")
    assert resp.status_code == 400


def test_delete_with_wrong_phrase_400(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.delete("/api/tenants/default?confirmation=delete-something")
    assert resp.status_code == 400


def test_delete_with_correct_phrase_returns_ok(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.delete(
        "/api/tenants/default?confirmation=delete-all-my-data"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["tenant_id"] == "default"
    assert data["purge_status"] == "audit_recorded"


def test_delete_records_purge_event_in_audit_trail(tmp_path, monkeypatch):
    app, audit_log, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.delete(
        "/api/tenants/default?confirmation=delete-all-my-data"
    )
    assert resp.status_code == 200
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    purge_events = [e for e in events if e.get("action") == "tenant_purge"]
    assert len(purge_events) == 1
    assert purge_events[0]["tenant_id"] == "default"
    assert purge_events[0]["data_elements"]["confirmation"] == "delete-all-my-data"


def test_delete_other_tenant_403(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="acme"
    )
    client = TestClient(app)
    resp = client.delete(
        "/api/tenants/other-tenant?confirmation=delete-all-my-data"
    )
    assert resp.status_code == 403


def test_export_attachment_filename_includes_tenant_and_timestamp(tmp_path, monkeypatch):
    app, _, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    disposition = resp.headers.get("content-disposition", "")
    assert "zorva-export-default-" in disposition
    assert ".jsonl" in disposition


def test_export_empty_logs_returns_minimal_manifest(tmp_path, monkeypatch):
    """No audit/appeal/upload rows → manifest still has zeros + hashes."""
    app, audit_log, appeal_log, upload_log = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    assert resp.status_code == 200
    lines = [json.loads(l) for l in resp.text.split("\n") if l]
    manifest = lines[-1]
    assert manifest["n_audit_trail"] == 0
    assert manifest["n_appeal_letters"] == 0
    assert manifest["n_upload_jobs"] == 0
    # Empty SHA-256 of zero bytes
    assert manifest["sha256_audit_trail"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_export_writes_event_with_sha256_in_extra(tmp_path, monkeypatch):
    """The audit_trail export event includes the manifest's sha256."""
    app, audit_log, _, _ = _make_app_for_tenant(
        monkeypatch, tmp_path=tmp_path, tenant_id="default"
    )
    _seed_audit_trail(audit_log, [
        {"action": "accept_all", "tenant_id": "default",
         "data_elements": {"encounter_id": "E-1"}},
    ])
    client = TestClient(app)
    resp = client.get("/api/tenants/default/export.jsonl")
    # The data_export event in audit trail
    events = [json.loads(l) for l in audit_log.read_text().split("\n") if l]
    export_event = next(e for e in events if e.get("action") == "data_export")
    assert "sha256_audit_trail" in export_event["data_elements"]