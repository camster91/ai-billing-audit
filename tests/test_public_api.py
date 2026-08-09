"""Tests for the v1 public API (kanban ``t_f4f1c149``).

Covers the five acceptance criteria from the task body:

1. Auth missing (no ``ZORVA_API_KEY``) → **503**.
2. Auth wrong (key set, presented key is wrong) → **401**.
3. Happy path: ``POST /v1/audits`` returns **202** with an
   ``audit_id`` + ``status_url``.
4. ``GET /v1/audits/{audit_id}`` after a synthetic job returns
   ``status: complete``.
5. ``GET /v1/audits/{audit_id}`` for an unknown id → **404**.

Bonus: every endpoint (including auth failures) appends a
``usage_log`` row so we can later rate-limit / audit per-key.
That row format is asserted by ``test_usage_log_appended_for_each_endpoint``.

Test isolation
--------------
Three env vars are monkeypatched per test (via ``monkeypatch``):

* ``ZORVA_API_KEY`` — flipped on / off per test.
* ``ZORVA_USAGE_LOG_PATH`` — points at ``tmp_path`` so the log
  doesn't accumulate across tests and so we can assert on its
  contents.
* ``ZORVA_WEBHOOK_LOG_PATH`` — same idea (the webhook
  registration side-effect also touches this log).

The default :class:`JobQueue` is replaced with a fresh queue
whose runner writes a deterministic ``result`` so the test
suite doesn't have to wait for the real synth / LLM path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Auth + log env vars are read at request time (per-request),
# but ``ai_billing_audit.api`` reads ``AUDIT_BEARER_TOKEN`` /
# ``AUDIT_ALLOW_NO_AUTH`` at create_app() time. Setting
# ``AUDIT_ALLOW_NO_AUTH=1`` here lets the TestClient bypass the
# dashboard's bearer-token middleware so we can focus on the
# v1 API-key auth layer (which is what kanban t_f4f1c149 is
# about). Without this, every POST in this file would 503 from
# the dashboard layer before the v1 layer ever runs.
os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_billing_audit import api  # noqa: E402
from ai_billing_audit import public_api  # noqa: E402
from ai_billing_audit.clinical_note_storage import (  # noqa: E402
    read_encrypted_json_records,
)
from ai_billing_audit.job_queue import (  # noqa: E402
    JobQueue,
    reset_default_queue_for_tests,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the usage + webhook logs to ``tmp_path``.

    Both :mod:`public_api` and :mod:`webhooks` consult the
    same env vars; setting them in one fixture guarantees
    the test can't accidentally read or write the production
    logs (``/app/logs/...``) — the production paths don't
    exist on a developer workstation and would fail the
    parent-mkdir call.
    """
    monkeypatch.setenv("ZORVA_USAGE_LOG_PATH", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("ZORVA_WEBHOOK_LOG_PATH", str(tmp_path / "webhooks.jsonl"))
    return tmp_path


@pytest.fixture
def with_api_key(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a stable API key for tests that need auth to pass."""
    monkeypatch.setenv("ZORVA_API_KEY", "test-key-abc")


@pytest.fixture
def no_api_key(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``ZORVA_API_KEY`` is unset so the 503 branch is reachable."""
    monkeypatch.delenv("ZORVA_API_KEY", raising=False)


@pytest.fixture
def fast_queue(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> JobQueue:
    """A JobQueue with a no-op runner so tests don't hit the real synth.

    The runner writes a fixed-shape result so the GET endpoint
    has something to return. Tests that want to exercise a
    failure path can call ``queue.set_runner(...)`` with their
    own callable (see ``test_get_audit_after_failed_job``).
    """
    reset_default_queue_for_tests()

    def _runner(_encounter: dict[str, Any]) -> dict[str, Any]:
        return {
            "difficulty_tier": "EASY",
            "ran_via": "v1_test_runner",
            "seed": 1,
            "synth_encounter_id": "enc_test_v1",
            "variant": "clean",
            "findings": [
                {
                    "finding_id": "fnd_test_1",
                    "category": "code_mismatch",
                    "severity": 3,
                    "rule_id": "R_TEST",
                    "rule_ids": ["R_TEST"],
                    "suggested_code": "99213",
                    "quote": "test quote",
                    "explanation": "test explanation",
                }
            ],
            "summary": "v1 test summary",
        }

    # Build a queue against the tmp usage-log dir so the
    # audit_id → job_id index lives next to the usage log.
    log = tmp_log_dir / "upload_jobs.jsonl"
    q = JobQueue(log_path=log, worker_count=1, runner=_runner)
    monkeypatch.setattr(public_api, "get_default_queue", lambda: q)
    return q


@pytest.fixture
def client() -> TestClient:
    """A TestClient pointed at the freshly built app."""
    return TestClient(api.app)


# ─── Minimal valid claim body ─────────────────────────────────────────────


def _claim_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "encounter_id": "ENC-V1-001",
        "patient_id": "PT-V1-001",
        "NPI": "1234567890",
        "date_of_service": "2026-06-24",
        "CPT_codes": ["99213"],
        "clinical_note": "Established patient follow-up with documented assessment.",
    }
    body.update(overrides)
    return body


def test_post_audits_rejects_missing_clinical_note_before_enqueue(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    body = _claim_body()
    body.pop("clinical_note")

    response = client.post("/v1/audits", json=body, headers=_bearer())

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "clinical_note_required"
    assert fast_queue.list_jobs() == []


def _bearer(key: str = "test-key-abc") -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ─── 1. Auth missing → 503 ────────────────────────────────────────────────


def test_missing_api_key_returns_503(
    client: TestClient, no_api_key: None, fast_queue: JobQueue
) -> None:
    """When ``ZORVA_API_KEY`` is unset, every ``/v1/*`` call 503s.

    The task body explicitly asks for 503 here (the
    "feature-flagged off" pattern), so this is the test that
    pins that behaviour.
    """
    r = client.post("/v1/audits", json=_claim_body())
    assert r.status_code == 503, r.text
    body = r.json()
    assert "ZORVA_API_KEY" in body.get("detail", "")
    assert body.get("code") == "api_key_not_configured"


def test_missing_api_key_get_also_503(
    client: TestClient, no_api_key: None, fast_queue: JobQueue
) -> None:
    """The same 503 contract applies to GET, not just POST."""
    r = client.get("/v1/audits/va_doesnotmatter")
    assert r.status_code == 503


def test_missing_api_key_webhook_also_503(
    client: TestClient, no_api_key: None, fast_queue: JobQueue
) -> None:
    """Same for ``POST /v1/webhooks`` — auth is global to /v1/*."""
    r = client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["audit_complete"]},
    )
    assert r.status_code == 503


# ─── 2. Auth wrong → 401 ──────────────────────────────────────────────────


def test_wrong_api_key_returns_401(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """A wrong bearer token (or ``X-API-Key``) returns 401."""
    # Bearer wrong.
    r = client.post(
        "/v1/audits",
        json=_claim_body(),
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401, r.text
    assert r.json().get("code") == "unauthorized"

    # X-API-Key wrong.
    r = client.post(
        "/v1/audits",
        json=_claim_body(),
        headers={"X-API-Key": "also-wrong"},
    )
    assert r.status_code == 401, r.text

    # Missing auth entirely (when key is configured).
    r = client.post("/v1/audits", json=_claim_body())
    assert r.status_code == 401, r.text


def test_x_api_key_header_is_accepted(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """``X-API-Key: <key>`` is the documented alternate auth header."""
    r = client.post(
        "/v1/audits",
        json=_claim_body(),
        headers={"X-API-Key": "test-key-abc"},
    )
    assert r.status_code == 202, r.text


# ─── 3. Happy path POST → 202 ─────────────────────────────────────────────


def test_post_audits_returns_202_with_id(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """Successful POST returns 202 + ``audit_id`` + ``status_url``."""
    r = client.post(
        "/v1/audits",
        json=_claim_body(),
        headers=_bearer(),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["audit_id"].startswith("va_"), body
    assert body["status"] == "queued"
    assert body["status_url"] == f"/v1/audits/{body['audit_id']}"
    assert body["encounter_id"] == "ENC-V1-001"


def test_post_audits_encrypts_clinical_note_at_rest(
    client: TestClient,
    with_api_key: None,
    fast_queue: JobQueue,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notes_dir = tmp_path / "uploaded_notes"
    monkeypatch.setenv("ZORVA_UPLOADED_NOTES_DIR", str(notes_dir))
    note = "Patient Jane Doe has diagnosis E11.9"

    response = client.post(
        "/v1/audits",
        json=_claim_body(encounter_id="ENC-V1-PHI", clinical_note=note),
        headers=_bearer(),
    )

    assert response.status_code == 202, response.text
    stored = list(notes_dir.iterdir())
    assert len(stored) == 1
    assert stored[0].name.endswith(".txt.enc")
    assert note not in stored[0].read_text(encoding="ascii")
    from ai_billing_audit.clinical_note_storage import load_clinical_note

    assert load_clinical_note(stored[0]).decode("utf-8") == note


def test_post_audits_accepts_comma_separated_cpts(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """``CPT_codes`` may be a comma-separated string (837P friendly)."""
    r = client.post(
        "/v1/audits",
        json=_claim_body(CPT_codes="99213, 99214-25"),
        headers=_bearer(),
    )
    assert r.status_code == 202, r.text


def test_post_audits_rejects_missing_required_fields(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """A claim without all required fields returns 400 with a list of errors."""
    r = client.post(
        "/v1/audits",
        json={"encounter_id": "ENC-X"},  # missing NPI, date, CPT, patient
        headers=_bearer(),
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", {})
    errors = detail.get("errors") if isinstance(detail, dict) else []
    assert any("patient_id" in e for e in errors)
    assert any("NPI" in e for e in errors)
    assert any("date_of_service" in e for e in errors)
    assert any("CPT_codes" in e for e in errors)


def test_post_audits_rejects_malformed_json(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """Malformed JSON returns 400 (not 500)."""
    r = client.post(
        "/v1/audits",
        content=b"{not json",
        headers={**_bearer(), "Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ─── 4. GET after POST → complete ────────────────────────────────────────


def test_get_audit_after_synthetic_job_returns_complete(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """The full POST→GET round trip returns ``status: complete``."""
    post = client.post(
        "/v1/audits",
        json=_claim_body(encounter_id="ENC-V1-LOOP"),
        headers=_bearer(),
    )
    assert post.status_code == 202, post.text
    audit_id = post.json()["audit_id"]

    # Wait briefly for the background job to complete. The
    # fast_queue fixture uses a synchronous runner that
    # finishes in microseconds; the test still polls a few
    # times because the daemon thread needs to wake up.
    import time

    for _ in range(50):
        get = client.get(f"/v1/audits/{audit_id}", headers=_bearer())
        if get.json().get("status") in ("complete", "failed"):
            break
        time.sleep(0.05)

    assert get.status_code == 200, get.text
    body = get.json()
    assert body["audit_id"] == audit_id
    assert body["status"] == "complete", body
    # Findings flow through from the runner's result.
    assert body["has_discrepancy"] is True
    findings = body["findings"]
    assert isinstance(findings, list) and len(findings) == 1
    assert findings[0]["finding_id"] == "fnd_test_1"
    assert body["summary"] == "v1 test summary"


# ─── 5. GET unknown → 404 ─────────────────────────────────────────────────


def test_get_unknown_audit_returns_404(
    client: TestClient, with_api_key: None, fast_queue: JobQueue
) -> None:
    """An unknown audit_id returns 404 with a stable error code."""
    r = client.get("/v1/audits/va_doesnotexist", headers=_bearer())
    assert r.status_code == 404
    body = r.json()
    assert body.get("code") == "not_found"
    assert "va_doesnotexist" in body.get("detail", "")


# ─── Bonus: usage_log rows ───────────────────────────────────────────────


def test_usage_log_appended_for_each_endpoint(
    client: TestClient,
    tmp_log_dir: Path,
    with_api_key: None,
    fast_queue: JobQueue,
) -> None:
    """Every ``/v1/*`` request appends a usage_log row.

    Even 401/404 requests must be logged so we can later
    rate-limit / audit per-key. The log file lives at
    ``ZORVA_USAGE_LOG_PATH``; the test reads it back and
    asserts on the entries.
    """
    # POST → 202
    client.post("/v1/audits", json=_claim_body(), headers=_bearer())
    # GET unknown → 404
    client.get("/v1/audits/va_unknown", headers=_bearer())
    # Wrong key → 401
    client.post(
        "/v1/audits", json=_claim_body(), headers={"Authorization": "Bearer wrong"}
    )

    log_path = tmp_log_dir / "usage.jsonl"
    assert log_path.exists(), "usage log was not created"
    assert b"ENC-V1-001" not in log_path.read_bytes()
    rows = read_encrypted_json_records(log_path)
    endpoints = {(r["endpoint"], r["status"]) for r in rows}
    # 202 POST, 404 GET, 401 POST — all logged.
    assert ("POST /v1/audits", 202) in endpoints
    assert ("GET /v1/audits/{id}", 404) in endpoints
    assert ("POST /v1/audits", 401) in endpoints
    # Every row carries the tenant + a timestamp + the
    # auth kind (bearer / x-api-key / missing) so we can
    # later slice the log by source.
    for row in rows:
        assert row["tenant_id"] == "default"
        assert row["auth"] in ("bearer", "x-api-key", "missing")
        assert row["ts"]
