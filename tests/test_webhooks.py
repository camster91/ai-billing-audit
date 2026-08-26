"""Tests for the webhook surface (kanban ``t_4496cee1``).

Covers the two acceptance criteria from the task body:

1. Register a webhook (``POST /v1/webhooks``) + run an audit;
   the registered URL receives a POST with the right event
   payload (``audit_complete``).
2. A webhook URL that doesn't exist (delivery failure) is
   logged but **does not block** the audit pipeline — the
   audit still completes and the GET endpoint returns 200.

Test isolation
--------------
We spin up a local HTTP server in-process via
``http.server.HTTPServer`` on an ephemeral port; the
``threading`` module gives us a background thread that serves
requests until the test ends. Delivery callbacks record every
incoming POST in a shared ``list[dict]`` the test asserts on.

The webhook log is redirected to ``tmp_path`` via
``ZORVA_WEBHOOK_LOG_PATH`` so the test doesn't pollute
``/app/logs/webhooks.jsonl`` and so the registration rows
can be inspected after the fact.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

# Bypass the dashboard's bearer-token middleware for the same
# reason as test_public_api.py — we want to focus on the
# v1 + webhook surface.
os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")
# Hermetic tests spin up a loopback HTTP receiver; allow private
# webhook targets only in this suite (production refuses them).
os.environ.setdefault("ZORVA_WEBHOOK_ALLOW_PRIVATE", "1")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_billing_audit import api  # noqa: E402
from ai_billing_audit import public_api  # noqa: E402
from ai_billing_audit import webhooks as webhooks_module  # noqa: E402
from ai_billing_audit.clinical_note_storage import (  # noqa: E402
    read_encrypted_json_records,
)
from ai_billing_audit.webhooks import verify_webhook_signature  # noqa: E402
from ai_billing_audit.job_queue import (  # noqa: E402
    JobQueue,
    reset_default_queue_for_tests,
)


# ─── In-process webhook receiver ─────────────────────────────────────────


class _Capture:
    """Thread-safe collector for HTTP requests the receiver gets."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, req: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(req)


def _make_handler(capture: _Capture) -> type[BaseHTTPRequestHandler]:
    """Build a request handler that records every POST and 200s.

    We deliberately do NOT inspect the payload here so the
    test can assert on the raw body the receiver saw.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"_raw": raw.decode("utf-8", errors="replace")}
            capture.record(
                {
                    "path": self.path,
                    "headers": {k: v for k, v in self.headers.items()},
                    "body": payload,
                    "raw": raw,
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        # Silence the default stderr access log; pytest
        # captures it but it's noisy on every webhook fire.
        def log_message(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
            return

    return _Handler


@pytest.fixture
def webhook_server() -> dict[str, Any]:
    """Start an HTTP server on an ephemeral port.

    Returns a dict with ``capture`` (the request collector),
    ``url`` (the base URL like ``http://127.0.0.1:NNNN``),
    and ``shutdown`` (a callable the test uses to stop the
    server). The server lives until the test calls
    ``shutdown()`` OR pytest's fixture finalisation runs it.
    """
    capture = _Capture()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(capture))
    thread = threading.Thread(
        target=server.serve_forever, name="webhook-test", daemon=True
    )
    thread.start()

    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"

    def _shutdown() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    return {"capture": capture, "url": base_url, "shutdown": _shutdown}


# ─── Log + queue fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect usage + webhook logs to ``tmp_path``."""
    monkeypatch.setenv("ZORVA_USAGE_LOG_PATH", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("ZORVA_WEBHOOK_LOG_PATH", str(tmp_path / "webhooks.jsonl"))
    monkeypatch.setenv("ZORVA_API_KEY", "test-key-abc")
    return tmp_path


@pytest.fixture
def fast_queue(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> JobQueue:
    """A JobQueue with a runner that finishes quickly and cleanly."""

    def _runner(_encounter: dict[str, Any]) -> dict[str, Any]:
        return {
            "difficulty_tier": "EASY",
            "ran_via": "webhook_test_runner",
            "seed": 1,
            "synth_encounter_id": "enc_webhook_test",
            "variant": "clean",
            "findings": [
                {
                    "finding_id": "fnd_wh_1",
                    "category": "code_mismatch",
                    "severity": 2,
                    "rule_id": "R_WH",
                    "rule_ids": ["R_WH"],
                    "suggested_code": "99213",
                    "quote": "x",
                    "explanation": "y",
                }
            ],
            "summary": "webhook test summary",
        }

    reset_default_queue_for_tests()
    log = tmp_log_dir / "upload_jobs.jsonl"
    q = JobQueue(log_path=log, worker_count=1, runner=_runner)
    monkeypatch.setattr(public_api, "get_default_queue", lambda: q)
    return q


@pytest.fixture
def client() -> TestClient:
    """A TestClient pointed at the module-level app."""
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def _reset_notify_dedup() -> None:
    """Clear the in-process ``audit_complete`` dedup set per test.

    The dedup lives in :mod:`public_api` as a module-level
    set so a server process doesn't fire the webhook twice
    on consecutive GETs. Tests that drive multiple audits
    through the same process need it cleared or the second
    audit won't see its webhook fired.
    """
    public_api._already_notified.clear()


# ─── Helpers ──────────────────────────────────────────────────────────────


def _claim(encounter_id: str = "ENC-WH-001") -> dict[str, Any]:
    return {
        "encounter_id": encounter_id,
        "patient_id": "PT-WH-001",
        "NPI": "1234567890",
        "date_of_service": "2026-06-24",
        "CPT_codes": ["99213"],
        "clinical_note": "Established patient follow-up with documented assessment.",
    }


def _bearer() -> dict[str, str]:
    return {"Authorization": "Bearer test-key-abc"}


# ─── Tests ────────────────────────────────────────────────────────────────


def test_register_webhook_returns_id_and_persists(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    webhook_server: dict[str, Any],
) -> None:
    """``POST /v1/webhooks`` returns 201 + a webhook_id and writes a log row."""
    url = webhook_server["url"] + "/hook"
    r = client.post(
        "/v1/webhooks",
        json={"url": url, "events": ["audit_complete"]},
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["webhook_id"].startswith("wh_")
    assert body["url"] == url
    assert body["events"] == ["audit_complete"]
    assert len(body["signing_secret"]) >= 32

    log = tmp_log_dir / "webhooks.jsonl"
    assert url.encode() not in log.read_bytes()
    assert body["signing_secret"].encode() not in log.read_bytes()
    rows = read_encrypted_json_records(log)
    assert any(r.get("webhook_id") == body["webhook_id"] for r in rows)


def test_register_webhook_forwards_migration_secret(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    webhook_server: dict[str, Any],
) -> None:
    migration_secret = "migration-secret-at-least-32-characters"
    r = client.post(
        "/v1/webhooks",
        json={
            "url": webhook_server["url"] + "/migration",
            "events": ["audit_complete"],
            "signing_secret": migration_secret,
        },
        headers=_bearer(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["signing_secret"] == migration_secret


def test_audit_completion_fires_webhook(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    webhook_server: dict[str, Any],
) -> None:
    """Run an audit; the registered webhook URL receives ``audit_complete``.

    Pins the core contract: when an audit transitions to
    ``done`` (observed via GET), the v1 surface delivers a
    POST to every webhook subscribed to ``audit_complete``
    with the right event + payload shape.
    """
    # 1. Register the webhook.
    url = webhook_server["url"] + "/audit-complete"
    reg = client.post(
        "/v1/webhooks",
        json={"url": url, "events": ["audit_complete"]},
        headers=_bearer(),
    )
    assert reg.status_code == 201, reg.text
    signing_secret = reg.json()["signing_secret"]

    # 2. Submit an audit.
    post = client.post(
        "/v1/audits",
        json=_claim("ENC-WH-FIRE"),
        headers=_bearer(),
    )
    assert post.status_code == 202, post.text
    audit_id = post.json()["audit_id"]

    # 3. GET until complete. The webhook fires inside the
    # GET handler on the first observation of ``done``.
    for _ in range(50):
        get = client.get(f"/v1/audits/{audit_id}", headers=_bearer())
        if get.json().get("status") == "complete":
            break
        time.sleep(0.05)

    assert get.status_code == 200
    assert get.json()["status"] == "complete"

    # 4. Assert the webhook received the POST with the
    # right payload.
    # The receiver runs on a thread; give it a moment to
    # finish writing the request into the capture list.
    deadline = time.time() + 2.0
    while time.time() < deadline and not webhook_server["capture"].requests:
        time.sleep(0.02)

    received = webhook_server["capture"].requests
    assert received, "webhook receiver got no requests"
    # Exactly one POST per audit (the dedup set ensures
    # consecutive polls don't re-fire).
    assert len(received) == 1, received
    payload = received[0]["body"]
    assert payload["event"] == "audit_complete"
    assert payload["data"]["audit_id"] == audit_id
    assert payload["data"]["encounter_id"] == "ENC-WH-FIRE"
    assert payload["data"]["has_discrepancy"] is True
    assert isinstance(payload["data"]["findings"], list)
    assert payload["data"]["summary"] == "webhook test summary"
    # The dispatcher stamps a ``delivered_at`` so consumers
    # can detect out-of-order delivery without trusting
    # ``Date:`` headers.
    assert payload["delivered_at"]
    # Custom event header is set so consumers can route
    # without parsing the body.
    assert received[0]["headers"].get("X-Zorva-Event") == "audit_complete"
    assert received[0]["headers"].get("X-Zorva-Delivery", "").startswith("dlv_")
    assert received[0]["headers"].get("X-Zorva-Timestamp", "").isdigit()
    assert received[0]["headers"].get("X-Zorva-Signature", "").startswith("v1=")
    signed = (
        received[0]["headers"]["X-Zorva-Timestamp"].encode("ascii")
        + b"."
        + received[0]["raw"]
    )
    expected = hmac.new(signing_secret.encode(), signed, hashlib.sha256).hexdigest()
    assert received[0]["headers"]["X-Zorva-Signature"] == f"v1={expected}"


def test_finding_acknowledged_helper_dispatches(
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``emit_finding_acknowledged`` fires the ``finding_acknowledged`` event.

    This helper is called from the operator dashboard's
    accept/dismiss endpoints; the unit test calls it
    directly so we can pin the payload shape without
    driving the dashboard routes.
    """
    captured: list[dict[str, Any]] = []

    def _fake_dispatch(event: str, payload: dict[str, Any]) -> dict[str, int]:
        captured.append({"event": event, "payload": payload})
        return {"delivered": 1, "failed": 0, "subscribers": 1}

    monkeypatch.setattr(webhooks_module, "dispatch_event", _fake_dispatch)
    out = public_api.emit_finding_acknowledged(
        audit_id="va_abc",
        encounter_id="ENC-X",
        finding_id="fnd-1",
        action="accept",
        tenant_id="default",
    )
    assert out["delivered"] == 1
    assert len(captured) == 1
    assert captured[0]["event"] == "finding_acknowledged"
    assert captured[0]["payload"]["audit_id"] == "va_abc"
    assert captured[0]["payload"]["finding_id"] == "fnd-1"
    assert captured[0]["payload"]["action"] == "accept"


# ─── Delivery failure must not block the audit ────────────────────────────


def test_failed_webhook_delivery_logs_but_does_not_block_audit(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A webhook URL that doesn't exist must not 500 the GET response.

    The contract from the task body: "webhook delivery
    failure (URL doesn't exist) is logged but doesn't block
    the audit." We register a webhook pointed at a closed
    port, run the audit, GET the result, and assert:
      * the GET still returns 200 with ``status: complete``
      * a delivery-attempt row landed in the JSONL log
        with ``ok=False`` and an error string
    """
    # 1. Register a webhook against a closed port. Port 1
    # is privileged + unbound on every platform we ship to,
    # so the kernel rejects the connect with ECONNREFUSED.
    bad_url = "http://127.0.0.1:1/never-listening"
    reg = client.post(
        "/v1/webhooks",
        json={"url": bad_url, "events": ["audit_complete"]},
        headers=_bearer(),
    )
    assert reg.status_code == 201, reg.text

    # 2. Submit + GET the audit to completion.
    post = client.post(
        "/v1/audits",
        json=_claim("ENC-WH-FAIL"),
        headers=_bearer(),
    )
    assert post.status_code == 202, post.text
    audit_id = post.json()["audit_id"]

    audit_failed = False
    for _ in range(50):
        get = client.get(f"/v1/audits/{audit_id}", headers=_bearer())
        if get.json().get("status") == "complete":
            break
        time.sleep(0.05)
    else:
        audit_failed = True

    # 3. The audit is still complete despite the broken
    # webhook — that's the entire point of the v1 contract.
    assert not audit_failed, "audit never completed"
    assert get.status_code == 200, get.text
    assert get.json()["status"] == "complete"

    # 4. The delivery attempt is logged with ok=False and
    # a non-empty error string. Search for the row so we
    # don't depend on ordering with the registration row.
    log_path = tmp_log_dir / "webhooks.jsonl"
    rows = read_encrypted_json_records(log_path)
    deliveries = [r for r in rows if r.get("_kind") == "delivery"]
    assert deliveries, "no delivery row was logged"
    delivery = deliveries[0]
    assert delivery["event"] == "audit_complete"
    assert delivery["url"] == bad_url
    assert delivery["ok"] is False
    assert delivery["status_code"] is None
    assert delivery["error"], "expected an error string on failed delivery"


def test_register_webhook_validates_input(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
) -> None:
    """Missing ``url`` and bad ``events`` shape return 400."""
    # Missing url.
    r = client.post(
        "/v1/webhooks", json={"events": ["audit_complete"]}, headers=_bearer()
    )
    assert r.status_code == 400
    # events not a list.
    r = client.post(
        "/v1/webhooks",
        json={"url": "https://example.com", "events": "audit_complete"},
        headers=_bearer(),
    )
    assert r.status_code == 400
    # events list contains non-strings.
    r = client.post(
        "/v1/webhooks",
        json={"url": "https://example.com", "events": ["audit_complete", 42]},
        headers=_bearer(),
    )
    assert r.status_code == 400


def test_verify_webhook_signature_rejects_tamper_stale_and_replay() -> None:
    """The reference verifier enforces the signed-body freshness contract."""
    secret = "test-signing-secret"
    body = b'{"event":"audit_complete","data":{"audit_id":"aud_1"}}'
    timestamp = "1700000000"
    delivery_id = "dlv_reference_1"
    digest = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    seen: set[str] = set()

    assert verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id=delivery_id,
        signature=f"v1={digest}",
        secret=secret,
        now=1700000000,
        seen_delivery_ids=seen,
    )
    assert not verify_webhook_signature(
        body=body + b" ",
        timestamp=timestamp,
        delivery_id="dlv_reference_2",
        signature=f"v1={digest}",
        secret=secret,
        now=1700000000,
        seen_delivery_ids=seen,
    )
    assert not verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id="dlv_reference_3",
        signature=f"v1={digest}",
        secret=secret,
        now=1700003600,
        seen_delivery_ids=seen,
    )
    assert not verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id=delivery_id,
        signature=f"v1={digest}",
        secret=secret,
        now=1700000000,
        seen_delivery_ids=seen,
    )


# ---------------------------------------------------------------------------
# Issue #21: rotation with bounded overlap.
# ---------------------------------------------------------------------------

def test_rotate_signing_secret_accepts_previous_during_overlap(tmp_path) -> None:
    """During a rotation overlap, deliveries signed with EITHER
    secret verify. Outside the overlap, only the new secret
    verifies."""
    from ai_billing_audit import webhooks
    from ai_billing_audit.clinical_note_storage import (
        read_encrypted_json_records,
    )

    old_secret = "old-secret-very-long-string-32-bytes"
    new_secret = "new-secret-very-long-string-32-bytes"

    log = tmp_path / "webhooks.jsonl"
    log_path_str = str(log)
    webhooks._log_path = lambda: log  # type: ignore[assignment]

    # Seed a registration with the old secret.
    webhooks.register_webhook(
        url="http://127.0.0.1:1/hook",
        events=["audit_complete"],
        signing_secret=old_secret,
    )

    # Rotate to the new secret with a 1h overlap.
    rotation = webhooks.rotate_webhook_signing_secret(
        _last_webhook_id(webhooks),
        new_secret=new_secret,
        overlap_seconds=3600,
    )
    assert rotation["signing_secret"] == new_secret
    assert rotation["overlap_seconds"] == 3600
    # The previous_secret is NOT returned; only the new one.
    assert "previous_secret" not in rotation

    # Read the current record to confirm the previous_secret field.
    # Use list_webhooks (which de-duplicates by webhook_id) so we
    # see the post-rotation state, not the original registration.
    rows = webhooks.list_webhooks()
    rec = next(r for r in rows if r.get("webhook_id") == _last_webhook_id(webhooks))
    assert rec["_signing_secret"] == new_secret
    assert rec["previous_secret"] == old_secret
    assert rec["previous_secret_expires_at"]

    # Sign a delivery during the overlap with the OLD secret. The
    # consumer should still accept it because previous_secret is
    # supplied.
    body = b'{"event":"audit_complete","data":{"audit_id":"a1"}}'
    timestamp = "1700000000"
    digest_old = hmac.new(
        old_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    assert webhooks.verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id="dlv_overlap_old",
        signature=f"v1={digest_old}",
        secret=new_secret,
        now=1700000000,
        previous_secret=old_secret,
        previous_signature=f"v1={digest_old}",
        previous_secret_expires_at=rec["previous_secret_expires_at"],
    )

    assert not webhooks.verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id="dlv_overlap_expired",
        signature=f"v1={digest_old}",
        secret=new_secret,
        now=1700000000,
        previous_secret=old_secret,
        previous_signature=f"v1={digest_old}",
        previous_secret_expires_at="2023-11-14T22:00:00+00:00",
    )

    # And with the NEW secret (current primary) it also verifies.
    digest_new = hmac.new(
        new_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    assert webhooks.verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id="dlv_overlap_new",
        signature=f"v1={digest_new}",
        secret=new_secret,
        now=1700000000,
        previous_secret=old_secret,
        previous_signature=f"v1={digest_old}",
        previous_secret_expires_at=rec["previous_secret_expires_at"],
    )

    # A signature signed with a completely different secret
    # does NOT verify, even with previous_secret supplied.
    bogus = hmac.new(
        b"not-the-secret",
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert not webhooks.verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        delivery_id="dlv_overlap_bogus",
        signature=f"v1={bogus}",
        secret=new_secret,
        now=1700000000,
        previous_secret=old_secret,
        previous_signature=f"v1={bogus}",
        previous_secret_expires_at=rec["previous_secret_expires_at"],
    )


def test_second_rotation_uses_latest_secret(tmp_path) -> None:
    from ai_billing_audit import webhooks

    log = tmp_path / "webhooks.jsonl"
    webhooks._log_path = lambda: log  # type: ignore[assignment]
    first_secret = "first-secret-at-least-32-characters"
    second_secret = "second-secret-at-least-32-characters"
    third_secret = "third-secret-at-least-32-characters"
    registered = webhooks.register_webhook(
        url="http://127.0.0.1:1/hook",
        events=["audit_complete"],
        signing_secret=first_secret,
    )
    webhooks.rotate_webhook_signing_secret(
        registered["webhook_id"],
        new_secret=second_secret,
    )
    webhooks.rotate_webhook_signing_secret(
        registered["webhook_id"],
        new_secret=third_secret,
    )

    current = next(
        row for row in webhooks.list_webhooks()
        if row["webhook_id"] == registered["webhook_id"]
    )
    assert current["_signing_secret"] == third_secret
    assert current["previous_secret"] == second_secret


def test_rotate_caps_overlap_to_maximum(tmp_path) -> None:
    """A caller requesting a 30-day overlap is silently capped to
    _MAX_ROTATION_OVERLAP_SECONDS (24h) so a misconfigured
    operator cannot keep a stolen former secret alive."""
    from ai_billing_audit import webhooks
    log = tmp_path / "webhooks.jsonl"
    log_path_str = str(log)
    webhooks._log_path = lambda: log  # type: ignore[assignment]
    webhooks.register_webhook(
        url="http://127.0.0.1:1/hook",
        events=["audit_complete"],
    )

    rotation = webhooks.rotate_webhook_signing_secret(
        _last_webhook_id(webhooks),
        overlap_seconds=30 * 24 * 60 * 60,  # 30 days
    )
    assert rotation["overlap_seconds"] == webhooks._MAX_ROTATION_OVERLAP_SECONDS


def test_rotate_rejects_invalid_overlap(tmp_path) -> None:
    from ai_billing_audit import webhooks
    log = tmp_path / "webhooks.jsonl"
    log_path_str = str(log)
    webhooks._log_path = lambda: log  # type: ignore[assignment]
    webhooks.register_webhook(
        url="http://127.0.0.1:1/hook",
        events=["audit_complete"],
    )
    import pytest as _pytest
    with _pytest.raises(ValueError):
        webhooks.rotate_webhook_signing_secret(
            _last_webhook_id(webhooks),
            overlap_seconds=0,
        )
    with _pytest.raises(ValueError):
        webhooks.rotate_webhook_signing_secret(
            _last_webhook_id(webhooks),
            overlap_seconds=-10,
        )


def test_rotate_rejects_too_short_secret(tmp_path) -> None:
    from ai_billing_audit import webhooks
    import pytest as _pytest
    log = tmp_path / "webhooks.jsonl"
    log_path_str = str(log)
    webhooks._log_path = lambda: log  # type: ignore[assignment]
    webhooks.register_webhook(
        url="http://127.0.0.1:1/hook",
        events=["audit_complete"],
    )
    with _pytest.raises(ValueError):
        webhooks.rotate_webhook_signing_secret(
            _last_webhook_id(webhooks),
            new_secret="too-short",
        )


def test_rotate_unknown_webhook_raises(tmp_path) -> None:
    from ai_billing_audit import webhooks
    import pytest as _pytest
    log = tmp_path / "webhooks.jsonl"
    log_path_str = str(log)
    webhooks._log_path = lambda: log  # type: ignore[assignment]
    with _pytest.raises(KeyError):
        webhooks.rotate_webhook_signing_secret("wh_does_not_exist")


def _last_webhook_id(webhooks) -> str:
    """Helper: read the most recently registered webhook id."""
    rows = read_encrypted_json_records(webhooks._log_path())
    for rec in reversed(rows):
        if rec.get("_kind") != "delivery" and rec.get("webhook_id"):
            return rec["webhook_id"]
    raise AssertionError("no registration found in log")
