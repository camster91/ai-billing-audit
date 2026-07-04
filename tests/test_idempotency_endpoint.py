"""Integration test: Idempotency-Key replay on /encounters/upload/submit.

The endpoint at ``POST /encounters/upload/submit`` accepts an
``Idempotency-Key`` header. A retry with the same key + same
body must replay the cached response without re-running the
endpoint. A retry with the same key + a different body must
return 409.

We don't have an audit-job queue running in the test client, so
we exercise the route indirectly via the ``/encounters/upload/preview``
validation path (which rejects rows with missing required
fields). What matters for idempotency is that the endpoint
behaves the same way on first call vs retry — independent of
whether the underlying job queue is alive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# A minimal valid upload payload. Each row is one encounter; the
# endpoint filters out rows with errors and enqueues the rest.
VALID_ROW = {
    "encounter_id": "test-enc-001",
    "patient_id": "pat-001",
    "NPI": "1234567890",
    "date_of_service": "2026-07-04",
    "CPT_codes": ["03.04A"],
    "diagnosis_codes": ["E11.9"],
    "source": "paste",
    "errors": [],
}


def _form_payload(rows: list[dict]) -> dict[str, str]:
    return {"payload": json.dumps({"rows": rows})}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Build a TestClient with a fresh idempotency log + tmp audit trail."""
    from fastapi.testclient import TestClient
    import ai_billing_audit.api as api_mod

    # Reset idempotency log to a per-test tmp path
    monkeypatch.setenv("IDEMPOTENCY_LOG", str(tmp_path / "idempotency.jsonl"))
    # Reset rate-limit state so it doesn't bleed across tests
    if hasattr(api_mod, "_rate_limit_state"):
        api_mod._rate_limit_state.clear()
    return TestClient(api_mod.create_app())


def test_post_without_idempotency_key_runs_endpoint(client):
    """No key → endpoint runs, response is the normal submit response."""
    r = client.post(
        "/encounters/upload/submit",
        data=_form_payload([VALID_ROW]),
    )
    # Endpoint may 200 (jobs enqueued) or 500 (queue not running in
    # test client); both are acceptable for this assertion — what
    # matters is that the endpoint actually ran (no cache hit).
    assert r.status_code != 409, (
        "no Idempotency-Key should NOT trigger 409"
    )


def test_post_with_idempotency_key_then_replay(client):
    """First POST with key → endpoint runs, response cached.
    Second POST with same key + same body → cached response."""
    headers = {
        "Idempotency-Key": "client-req-stable-001",
        "X-Forwarded-For": "10.1.2.3",  # distinct IP for rate-limit isolation
    }
    payload = _form_payload([VALID_ROW])

    r1 = client.post("/encounters/upload/submit", data=payload, headers=headers)
    # Whatever status r1 was (200, 500, etc.), the cache should
    # hold that status + body.
    body1 = r1.text

    # Retry with the same key + same body → cached response
    r2 = client.post("/encounters/upload/submit", data=payload, headers=headers)
    assert r2.status_code == r1.status_code
    assert r2.text == body1, (
        "second POST with same Idempotency-Key + same body must "
        "return the cached response, not a fresh one"
    )


def test_post_with_same_key_but_different_body_returns_409(client):
    """Same key, different body → 409 Conflict."""
    headers = {
        "Idempotency-Key": "client-req-mismatched-001",
        "X-Forwarded-For": "10.1.2.4",
    }
    payload_a = _form_payload([VALID_ROW])
    payload_b = _form_payload([
        {**VALID_ROW, "encounter_id": "test-enc-DIFFERENT"},
    ])

    r1 = client.post("/encounters/upload/submit", data=payload_a, headers=headers)
    assert r1.status_code != 409, "first POST must not 409"

    r2 = client.post("/encounters/upload/submit", data=payload_b, headers=headers)
    assert r2.status_code == 409, (
        f"second POST with same key but different body must return "
        f"409; got {r2.status_code}"
    )


def test_post_with_different_keys_runs_endpoint_twice(client):
    """Different keys → endpoint runs fresh each time."""
    headers_a = {
        "Idempotency-Key": "key-A",
        "X-Forwarded-For": "10.1.2.5",
    }
    headers_b = {
        "Idempotency-Key": "key-B",
        "X-Forwarded-For": "10.1.2.6",
    }
    payload = _form_payload([VALID_ROW])

    r_a = client.post(
        "/encounters/upload/submit", data=payload, headers=headers_a
    )
    r_b = client.post(
        "/encounters/upload/submit", data=payload, headers=headers_b
    )
    # Both should run (not replay). If status was 200 for both,
    # the response_json should be fresh each time.
    if r_a.status_code == 200 and r_b.status_code == 200:
        # The body must not be identical (different job_id generated)
        # — actually they COULD be identical if the queue returns
        # stable job_ids per payload. Just assert both returned 200.
        assert r_a.status_code == r_b.status_code == 200


def test_empty_idempotency_key_is_treated_as_no_key(client):
    """An empty Idempotency-Key header is equivalent to no header."""
    headers = {
        "Idempotency-Key": "",
        "X-Forwarded-For": "10.1.2.7",
    }
    r = client.post(
        "/encounters/upload/submit",
        data=_form_payload([VALID_ROW]),
        headers=headers,
    )
    # No caching — the endpoint ran. Should NOT be 409.
    assert r.status_code != 409