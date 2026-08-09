"""Tests for the Zapier / Make.com connector (kanban ``t_cab76c0b``).

Three contracts to pin:

1. **List endpoint** — ``GET /v1/zapier/encounters?days=N`` returns
   a paginated list of encounter summaries, each with the same
   ``{encounter_id, status, n_findings, n_revenue_opportunities,
   total_dollars}`` shape Zapier expects. The default window is
   30 days; the response is capped at a 50-row page.

2. **Get-by-id endpoint** — ``GET /v1/zapier/encounters/{id}``
   returns the same shape for a single encounter, 404 when the
   encounter has never been audited.

3. **Auth** — missing ``ZORVA_API_KEY`` (header or env) → 401
   when the server has a key configured but the request doesn't
   present one. 503 still applies when the key is *unset* on the
   server (the feature-flagged-off pattern documented in
   :mod:`public_api`).

The trigger (webhook) is already covered by ``test_webhooks.py``
and the v1 surface's existing webhook route (kanban t_4496cee1);
this file focuses on the list + get-by-id surfaces that Zapier
polls.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_billing_audit import api, public_api  # noqa: E402
from ai_billing_audit.job_queue import (  # noqa: E402
    JobQueue,
    reset_default_queue_for_tests,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect usage + webhook logs to ``tmp_path`` (same pattern
    as :mod:`test_public_api`)."""
    monkeypatch.setenv("ZORVA_USAGE_LOG_PATH", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("ZORVA_WEBHOOK_LOG_PATH", str(tmp_path / "webhooks.jsonl"))
    return tmp_path


@pytest.fixture
def with_api_key(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZORVA_API_KEY", "test-key-abc")


@pytest.fixture
def no_api_key(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZORVA_API_KEY", raising=False)


def _seeded_runner(_encounter: dict[str, Any]) -> dict[str, Any]:
    """Deterministic runner that returns a result with one finding
    the revenue-opportunity computer recognises.
    ``rule_ahcip_modifier_25_001`` is registered in
    :data:`REVENUE_OPPORTUNITY_RULES` so the
    ``compute_revenue_opportunities`` enrichment is exercised
    end-to-end without needing the LLM."""
    return {
        "ran_via": "v1_zapier_test_runner",
        "audit_status": "ok",
        "findings": [
            {
                "finding_id": "fnd_zap_1",
                "category": "modifier_required",
                "severity": 3,
                "rule_id": "rule_ahcip_modifier_25_001",
                "rule_ids": ["rule_ahcip_modifier_25_001"],
                "suggested_code": "99213",
                "quote": "test quote",
                "explanation": "test explanation",
            }
        ],
        "summary": "zapier test summary",
    }


def _empty_runner(_encounter: dict[str, Any]) -> dict[str, Any]:
    return {
        "ran_via": "v1_zapier_test_runner_empty",
        "audit_status": "ok",
        "findings": [],
        "summary": "clean claim",
    }


def _build_queue(
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner: Any = _seeded_runner,
) -> JobQueue:
    reset_default_queue_for_tests()
    log = tmp_log_dir / "upload_jobs.jsonl"
    q = JobQueue(log_path=log, worker_count=1, runner=runner)
    monkeypatch.setattr(public_api, "get_default_queue", lambda: q)
    return q


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def _bearer(key: str = "test-key-abc") -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _claim(**overrides: Any) -> dict[str, Any]:
    body = {
        "encounter_id": "ENC-ZAP-001",
        "patient_id": "PT-ZAP-001",
        "NPI": "1234567890",
        "date_of_service": "2026-06-24",
        "CPT_codes": ["99213"],
        "clinical_note": "Established patient follow-up with documented assessment.",
    }
    body.update(overrides)
    return body


# ─── 1. Auth ──────────────────────────────────────────────────────────────


def test_list_missing_api_key_returns_401(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server has ``ZORVA_API_KEY`` set; client doesn't send a key.
    → 401 (the "wrong or missing key" branch). Same contract as
    the rest of ``/v1/*``."""
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get("/v1/zapier/encounters")
    assert r.status_code == 401, r.text
    assert r.json().get("code") == "unauthorized"


def test_list_wrong_api_key_returns_401(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401


def test_list_no_api_key_configured_returns_503(
    client: TestClient,
    no_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ZORVA_API_KEY`` unset on server → 503 (the
    feature-flagged-off pattern, even with a valid client key)."""
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters",
        headers={"Authorization": "Bearer anything"},
    )
    assert r.status_code == 503
    assert "ZORVA_API_KEY" in r.json().get("detail", "")


def test_get_by_id_missing_api_key_returns_401(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get("/v1/zapier/encounters/ENC-001")
    assert r.status_code == 401


# ─── 2. List endpoint shape ─────────────────────────────────────────────


def test_list_empty_returns_zero_count(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No jobs in the queue → empty list, count=0, has_more=False.
    Doesn't 5xx (Zapier would retry forever on a 5xx)."""
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get("/v1/zapier/encounters", headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["encounters"] == []
    assert body["count"] == 0
    assert body["has_more"] is False
    assert body["offset"] == 0
    assert body["limit"] > 0


def test_list_returns_summary_shape(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single audited encounter → a list with one summary dict
    whose shape matches the contract Zapier publishes.
    """
    _build_queue(tmp_log_dir, monkeypatch)
    # Enqueue a real claim so the job lands in the queue.
    r = client.post("/v1/audits", json=_claim(), headers=_bearer())
    assert r.status_code == 202, r.text
    # fast_queue's runner is synchronous, but we wait one tick
    # to be safe across platforms.
    time.sleep(0.05)
    r = client.get("/v1/zapier/encounters", headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    enc = body["encounters"][0]
    # Required fields.
    for key in (
        "encounter_id",
        "status",
        "n_findings",
        "n_revenue_opportunities",
        "total_dollars",
    ):
        assert key in enc, f"missing {key!r} in {enc}"
    # The seeded encounter had R-MOD-25, which is in
    # REVENUE_OPPORTUNITY_RULES → 1 opportunity expected.
    assert enc["n_findings"] == 1
    assert enc["n_revenue_opportunities"] == 1
    assert enc["total_dollars"] > 0
    assert enc["status"] == "complete"  # done → complete on the wire


def test_list_default_window_is_30_days(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job whose ``submitted_at`` is 100 days old must NOT show
    up in the default-30-day list."""
    q = _build_queue(tmp_log_dir, monkeypatch)
    job = q.enqueue(
        encounter=_claim(encounter_id="ENC-OLD"),
        source="v1_api",
        source_filename=None,
        tenant_id="default",
    )
    # Backdate the job to 100 days ago.
    object.__setattr__(job, "submitted_at", time.time() - 100 * 86400)
    r = client.get("/v1/zapier/encounters", headers=_bearer())
    assert r.status_code == 200
    body = r.json()
    enc_ids = [e["encounter_id"] for e in body["encounters"]]
    assert "ENC-OLD" not in enc_ids


def test_list_days_param_widens_window(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``days=200`` should pull in the 100-day-old job."""
    q = _build_queue(tmp_log_dir, monkeypatch)
    job = q.enqueue(
        encounter=_claim(encounter_id="ENC-OLD"),
        source="v1_api",
        source_filename=None,
        tenant_id="default",
    )
    object.__setattr__(job, "submitted_at", time.time() - 100 * 86400)
    r = client.get(
        "/v1/zapier/encounters?days=200",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    enc_ids = [e["encounter_id"] for e in body["encounters"]]
    assert "ENC-OLD" in enc_ids


def test_list_days_param_capped_at_max(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``days=10000`` is clamped to the 365-day max rather than
    spilling a 30 KB list into the Zap. The endpoint must not
    400 on the out-of-range value — the cap is silent so a
    misconfigured Zap still gets *some* data."""
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters?days=10000",
        headers=_bearer(),
    )
    assert r.status_code == 200
    # We can't directly inspect the cap from the response, but
    # the cap-not-400 behaviour is the assertion.


def test_list_pagination(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three jobs in the queue → first page returns all three
    when below the page-size cap, second page returns nothing,
    has_more flips on/off correctly. Verifies the cursor
    contract without depending on the page-size constant."""
    q = _build_queue(tmp_log_dir, monkeypatch)
    for i in range(3):
        q.enqueue(
            encounter=_claim(encounter_id=f"ENC-PAG-{i:03d}"),
            source="v1_api",
            source_filename=None,
            tenant_id="default",
        )
    # Page 1: 3 items, has_more=False (page size > 3).
    r = client.get(
        "/v1/zapier/encounters?offset=0&days=365",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["has_more"] is False
    assert body["offset"] == 0
    # Page 2 (out of bounds): 0 items, has_more=False.
    r = client.get(
        "/v1/zapier/encounters?offset=3&days=365",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["has_more"] is False
    assert body["offset"] == 3


def test_list_pagination_with_page_size(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify has_more flips True when the slice is page-sized.

    Seeds 60 encounters (3 over the 57-row test page) — actually
    we use the module-level page size constant (50) so we seed
    51 to overflow. We expose :data:`_ZAPIER_PAGE_SIZE` so a
    caller can tune; tests that need a specific page size reach
    into the module.
    """
    from ai_billing_audit import public_api

    page_size = public_api._ZAPIER_PAGE_SIZE
    n = page_size + 1
    q = _build_queue(tmp_log_dir, monkeypatch)
    for i in range(n):
        q.enqueue(
            encounter=_claim(encounter_id=f"ENC-OVER-{i:03d}"),
            source="v1_api",
            source_filename=None,
            tenant_id="default",
        )
    r = client.get(
        "/v1/zapier/encounters?days=365",
        headers=_bearer(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == page_size
    assert body["has_more"] is True


def test_list_bad_days_param_returns_400(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters?days=abc",
        headers=_bearer(),
    )
    assert r.status_code == 400
    assert "days" in r.json().get("detail", "").lower()


def test_list_bad_offset_returns_400(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters?offset=abc",
        headers=_bearer(),
    )
    assert r.status_code == 400
    assert "offset" in r.json().get("detail", "").lower()


# ─── 3. Get-by-id endpoint ──────────────────────────────────────────────


def test_get_unknown_encounter_returns_404(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.get(
        "/v1/zapier/encounters/ENC-DOES-NOT-EXIST",
        headers=_bearer(),
    )
    assert r.status_code == 404
    assert r.json().get("code") == "not_found"


def test_get_returns_same_shape_as_list(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successfully-audited encounter returns the SAME shape
    from the list and get-by-id endpoints. Zapier uses the list
    shape as the trigger payload; the get-by-id is the action
    shape. If they diverged a Zap would need a re-mapping."""
    _build_queue(tmp_log_dir, monkeypatch)
    r = client.post("/v1/audits", json=_claim(), headers=_bearer())
    assert r.status_code == 202
    time.sleep(0.05)
    # Get-by-id
    r = client.get(
        "/v1/zapier/encounters/ENC-ZAP-001",
        headers=_bearer(),
    )
    assert r.status_code == 200, r.text
    summary = r.json()
    for key in (
        "encounter_id",
        "status",
        "n_findings",
        "n_revenue_opportunities",
        "total_dollars",
    ):
        assert key in summary
    assert summary["encounter_id"] == "ENC-ZAP-001"
    assert summary["n_findings"] == 1
    assert summary["n_revenue_opportunities"] == 1
    assert summary["total_dollars"] > 0
    assert summary["status"] == "complete"


def test_get_empty_findings_yields_zero_dollars(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean encounter (no findings) returns ``total_dollars=0``,
    ``n_findings=0``, ``n_revenue_opportunities=0``. Regression
    guard: the summary helper must not blow up on a missing
    result.findings field."""
    _build_queue(tmp_log_dir, monkeypatch, runner=_empty_runner)
    r = client.post(
        "/v1/audits",
        json=_claim(encounter_id="ENC-CLEAN"),
        headers=_bearer(),
    )
    assert r.status_code == 202
    time.sleep(0.05)
    r = client.get(
        "/v1/zapier/encounters/ENC-CLEAN",
        headers=_bearer(),
    )
    assert r.status_code == 200
    summary = r.json()
    assert summary["n_findings"] == 0
    assert summary["n_revenue_opportunities"] == 0
    assert summary["total_dollars"] == 0
    assert summary["status"] == "complete"


# ─── 4. Usage log rows for observability ───────────────────────────────


def test_list_and_get_emit_usage_log_rows(
    client: TestClient,
    with_api_key: None,
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every Zapier request appends a usage-log row (the same
    observability layer the rest of /v1/* uses). This is the
    audit-trail hook for "who is hitting the Zapier surface and
    how often" — operators rely on it for rate-limiting later."""
    _build_queue(tmp_log_dir, monkeypatch)
    client.get("/v1/zapier/encounters", headers=_bearer())
    client.get(
        "/v1/zapier/encounters/ENC-MISSING",
        headers=_bearer(),
    )
    log_path = tmp_log_dir / "usage.jsonl"
    assert log_path.exists()
    from ai_billing_audit.clinical_note_storage import read_encrypted_json_records

    rows = read_encrypted_json_records(log_path)
    assert len(rows) >= 2
    # The endpoint field is what we'd grep for when building a
    # per-endpoint dashboard.
    endpoints = [row.get("endpoint") for row in rows]
    assert "GET /v1/zapier/encounters" in endpoints
    assert "GET /v1/zapier/encounters/{id}" in endpoints
