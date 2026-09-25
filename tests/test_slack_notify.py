"""Tests for the Slack notification surface (kanban ``t_c9cf54f4``).

Pins three contracts from the task body:

1. ``POST /api/integrations/slack`` registers the integration
   and persists a row to ``slack_integrations.jsonl``.
2. :func:`slack_notify.notify_slack` POSTs a Block-Kit-shaped
   body to the registered webhook on ``audit_complete``.
3. :func:`notify_slack` filters by ``clinic_id`` so a clinic
   only receives events it subscribed to (multi-tenant safety).

Test isolation
--------------
* The Slack log is redirected to ``tmp_path`` via
  ``ZORVA_SLACK_LOG_PATH`` so tests don't pollute
  ``/app/logs/slack_integrations.jsonl``.
* ``urllib.request.urlopen`` is monkeypatched to a fake so the
  test never opens a real socket. The fake records every
  ``Request`` it received so the assertions can inspect the
  Block Kit body verbatim.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib import request as _urlreq

# Bypass the dashboard's bearer-token middleware so the integration
# endpoint is reachable. Matches the convention in test_webhooks.py
# and test_public_api.py.
os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ai_billing_audit import api as api_mod  # noqa: E402
from ai_billing_audit import slack_notify as slack  # noqa: E402
from ai_billing_audit.clinical_note_storage import (  # noqa: E402
    read_encrypted_json_records,
)
from ai_billing_audit.job_queue import (  # noqa: E402
    JobQueue,
    reset_default_queue_for_tests,
)


# ─── In-process HTTP receiver (mirrors test_webhooks) ────────────────────


class _Capture:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, req: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(req)


def _make_handler(capture: _Capture) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
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
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
            return

    return _Handler


@pytest.fixture
def webhook_server() -> dict[str, Any]:
    capture = _Capture()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(capture))
    thread = threading.Thread(
        target=server.serve_forever, name="slack-test", daemon=True
    )
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"

    def _shutdown() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    return {"capture": capture, "url": base_url, "shutdown": _shutdown}


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _allow_loopback_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permit loopback webhook receivers for this file.

    ``register_slack`` now runs the SSRF validator from ``webhooks``
    (issue #116), which rejects loopback / link-local / private addresses.
    Every test here stands up an in-process ``HTTPServer`` on 127.0.0.1, so
    the validator's documented test escape hatch is enabled. The rejection
    tests at the bottom of this file explicitly unset it.
    """
    monkeypatch.setenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", "1")


@pytest.fixture
def tmp_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ZORVA_SLACK_LOG_PATH", str(tmp_path / "slack.jsonl"))
    # Public v1 audit submission writes to ``v1_audits.jsonl`` next
    # to the usage log; redirect both so the end-to-end test stays
    # in tmp_path instead of trying to mkdir /app on a read-only fs.
    monkeypatch.setenv("ZORVA_USAGE_LOG_PATH", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("ZORVA_API_KEY", "test-key-abc")
    return tmp_path


@pytest.fixture
def fast_queue(tmp_log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> JobQueue:
    """A JobQueue with a runner that finishes quickly.

    Mirrors test_webhooks.fast_queue so the audit-complete path
    drives through to the ``done`` status the public_api dispatcher
    watches for.
    """

    def _runner(_encounter: dict[str, Any]) -> dict[str, Any]:
        return {
            "difficulty_tier": "EASY",
            "ran_via": "slack_test_runner",
            "seed": 1,
            "synth_encounter_id": "enc_slack_test",
            "variant": "clean",
            "findings": [
                {
                    "finding_id": "fnd_slack_1",
                    "category": "code_mismatch",
                    "severity": "medium",
                    "rule_id": "R_SLACK",
                    "rule_ids": ["R_SLACK"],
                    "suggested_code": "99213",
                    "quote": "slack test quote",
                    "explanation": "y",
                }
            ],
            "summary": "slack test summary",
        }

    reset_default_queue_for_tests()
    log = tmp_log_dir / "upload_jobs.jsonl"
    q = JobQueue(log_path=log, worker_count=1, runner=_runner)
    from ai_billing_audit import public_api as _pa

    monkeypatch.setattr(_pa, "get_default_queue", lambda: q)
    return q


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_mod.app)


@pytest.fixture(autouse=True)
def _reset_notify_dedup() -> None:
    """Clear the in-process ``audit_complete`` dedup set per test.

    Without this the second audit in a single test would never
    fire the webhook (the dedup lives in public_api as a module-
    level set keyed on audit_id).
    """
    from ai_billing_audit import public_api as _pa

    _pa._already_notified.clear()


# ─── Helpers ──────────────────────────────────────────────────────────────


def _claim(encounter_id: str = "ENC-SLACK-001") -> dict[str, Any]:
    return {
        "encounter_id": encounter_id,
        "patient_id": "PT-SLACK-001",
        "NPI": "1234567890",
        "date_of_service": "2026-06-24",
        "CPT_codes": ["99213"],
        "clinical_note": "Established patient follow-up with documented assessment.",
    }


def _bearer() -> dict[str, str]:
    return {"Authorization": "Bearer test-key-abc"}


# ─── Tests ────────────────────────────────────────────────────────────────


def test_register_endpoint_returns_id_and_persists(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    webhook_server: dict[str, Any],
) -> None:
    """``POST /api/integrations/slack`` returns 201 + slack_id + writes a log row."""
    url = webhook_server["url"] + "/hook"
    r = client.post(
        "/api/integrations/slack",
        json={
            "webhook_url": url,
            "channel": "#billing-audits",
            "events": ["audit_complete", "high_finding"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slack_id"].startswith("sl_")
    assert body["webhook_url"] == url
    assert body["channel"] == "#billing-audits"
    assert body["events"] == ["audit_complete", "high_finding"]
    assert body["clinic_id"] == "default"  # falls back to TENANT_ID

    log = tmp_log_dir / "slack.jsonl"
    assert url.encode() not in log.read_bytes()
    rows = read_encrypted_json_records(log)
    assert any(r.get("slack_id") == body["slack_id"] for r in rows)


def test_register_rejects_empty_webhook_url(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
) -> None:
    """An empty webhook_url gets a 400 (no row written)."""
    r = client.post(
        "/api/integrations/slack",
        json={"webhook_url": "", "channel": "#x", "events": []},
    )
    assert r.status_code == 400
    log = tmp_log_dir / "slack.jsonl"
    assert not log.exists() or log.read_text().strip() == ""


def test_register_rejects_missing_channel(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
) -> None:
    r = client.post(
        "/api/integrations/slack",
        json={"webhook_url": "https://hooks.slack.com/x", "events": []},
    )
    assert r.status_code == 400


def test_register_rejects_non_list_events(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
) -> None:
    r = client.post(
        "/api/integrations/slack",
        json={
            "webhook_url": "https://hooks.slack.com/x",
            "channel": "#x",
            "events": "audit_complete",
        },
    )
    assert r.status_code == 400


def test_notify_slack_posts_block_kit_on_audit_complete(
    tmp_log_dir: Path,
    webhook_server: dict[str, Any],
) -> None:
    """Register a Slack integration, fire audit_complete, verify the
    Block-Kit body the receiver got.

    Pins:
    * ``text`` field (Slack fallback for clients without block render)
    * ``channel`` override (the registered channel, not the webhook's default)
    * ``blocks`` array with ``type: section`` + mrkdwn text + findings count
    """
    url = webhook_server["url"] + "/slack"
    slack.register_slack(
        webhook_url=url,
        channel="#billing-audits",
        events=["audit_complete", "high_finding"],
        clinic_id="default",
    )

    summary = notify_slack = None  # noqa: F841 (kept for clarity)
    result = slack.notify_slack(
        clinic_id="default",
        event=slack.EVENT_AUDIT_COMPLETE,
        payload={
            "audit_id": "va_test_1",
            "encounter_id": "ENC-SLACK-001",
            "findings_count": 3,
            "summary": "Three findings flagged",
        },
    )
    assert result == {"delivered": 1, "failed": 0, "subscribers": 1}

    requests = webhook_server["capture"].requests
    assert len(requests) == 1, "exactly one POST expected"
    sent = requests[0]
    assert sent["path"] == "/slack"
    # Slack contract: Content-Type + User-Agent + X-Zorva-Event header.
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["headers"]["X-Zorva-Event"] == "audit_complete"
    body = sent["body"]
    # Top-level Slack fields
    assert body["text"] == "Zorva: audit_complete"
    assert body["channel"] == "#billing-audits"
    assert isinstance(body["blocks"], list) and len(body["blocks"]) >= 1
    # Block-kit shape: each block has a type; section blocks have mrkdwn text.
    first = body["blocks"][0]
    assert first["type"] == "section"
    assert "text" in first and first["text"]["type"] == "mrkdwn"
    # Encounter id and findings count surfaced in the message text.
    blob = json.dumps(body)
    assert "ENC-SLACK-001" in blob
    assert "3" in blob  # findings_count


def test_notify_slack_block_kit_high_finding_shape(
    tmp_log_dir: Path,
    webhook_server: dict[str, Any],
) -> None:
    """The high_finding event builds a block with a fields row showing
    encounter / rule / action / severity. Billers triage these on
    their phones, so the contract has to stay compact."""
    url = webhook_server["url"] + "/slack"
    slack.register_slack(
        webhook_url=url,
        channel="#billing-audits",
        events=["high_finding"],
        clinic_id="default",
    )

    slack.notify_slack(
        clinic_id="default",
        event=slack.EVENT_HIGH_FINDING,
        payload={
            "encounter_id": "ENC-X",
            "finding_id": "fnd-X",
            "rule_id": "R_DOC_GAP",
            "severity": "high",
            "action": "dismiss",
            "quote": "Documentation lacks diagnosis linkage",
        },
    )
    body = webhook_server["capture"].requests[0]["body"]
    assert body["channel"] == "#billing-audits"
    blob = json.dumps(body)
    assert "ENC-X" in blob
    assert "R_DOC_GAP" in blob
    assert "dismiss" in blob
    # The high_finding builder emits a "fields" section block so
    # the four metadata fields render in a 2x2 grid on Slack clients.
    has_fields = any(
        b.get("type") == "section" and "fields" in b for b in body["blocks"]
    )
    assert has_fields, "expected a section block with fields for high_finding"


def test_notify_slack_filters_by_clinic_id(
    tmp_log_dir: Path,
    webhook_server: dict[str, Any],
) -> None:
    """Multi-tenant safety: a clinic B webhook must not receive clinic A's events."""
    slack.register_slack(
        webhook_url=webhook_server["url"] + "/A",
        channel="#a",
        events=["audit_complete"],
        clinic_id="clinicA",
    )
    slack.register_slack(
        webhook_url=webhook_server["url"] + "/B",
        channel="#b",
        events=["audit_complete"],
        clinic_id="clinicB",
    )

    slack.notify_slack(
        clinic_id="clinicA",
        event=slack.EVENT_AUDIT_COMPLETE,
        payload={"encounter_id": "ENC-A", "summary": "A"},
    )
    paths = [r["path"] for r in webhook_server["capture"].requests]
    assert paths == ["/A"], f"clinicB webhook should not have fired, got {paths}"


def test_notify_slack_no_subscribers_is_noop(
    tmp_log_dir: Path,
    webhook_server: dict[str, Any],
) -> None:
    """Firing an event with zero matching subscribers returns
    delivered=0 and never opens a socket."""
    result = slack.notify_slack(
        clinic_id="nobody",
        event=slack.EVENT_AUDIT_COMPLETE,
        payload={"encounter_id": "ENC-X"},
    )
    assert result == {"delivered": 0, "failed": 0, "subscribers": 0}
    assert webhook_server["capture"].requests == []


def test_notify_slack_swallows_network_errors(
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing webhook URL must not raise out of notify_slack.

    Pins the contract that notify_slack is best-effort: a Slack
    outage cannot break the audit pipeline. The mock below
    simulates the URL returning a 500 and verify the dispatcher
    swallows it (returns failed=1) instead of bubbling up.
    """
    slack.register_slack(
        webhook_url="https://hooks.slack.com/services/T0/B0/XX",
        channel="#x",
        events=["audit_complete"],
        clinic_id="default",
    )

    class _BoomCM:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    class _BoomResp(_BoomCM):
        status = 500

    def _fake_urlopen(req: Any, timeout: float = 5.0) -> Any:
        # Simulate a transient network failure so the except branch
        # is exercised end-to-end (including the delivery-log row).
        raise OSError("simulated network failure")

    monkeypatch.setattr(_urlreq, "urlopen", _fake_urlopen)

    result = slack.notify_slack(
        clinic_id="default",
        event=slack.EVENT_AUDIT_COMPLETE,
        payload={"encounter_id": "ENC-X"},
    )
    assert result["subscribers"] == 1
    assert result["delivered"] == 0
    assert result["failed"] == 1
    # And the delivery-log row carries the failure.
    rows = read_encrypted_json_records(tmp_log_dir / "slack.jsonl")
    delivery = [r for r in rows if r.get("_kind") == "delivery"]
    assert len(delivery) == 1
    assert delivery[0]["ok"] is False
    assert "simulated network failure" in delivery[0]["error"]


def test_audit_complete_end_to_end_fires_slack(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    webhook_server: dict[str, Any],
) -> None:
    """End-to-end: register a Slack webhook, run a v1 audit, poll
    GET until the audit is done, and verify the Slack receiver got
    an ``audit_complete`` POST with the expected Block Kit body.

    This pins the wiring in
    :mod:`public_api._maybe_notify_audit_complete` — a refactor
    that drops the Slack call would fail this test even if
    ``notify_slack`` still works in isolation.
    """
    url = webhook_server["url"] + "/slack"
    slack.register_slack(
        webhook_url=url,
        channel="#billing-audits",
        events=["audit_complete"],
        clinic_id="default",
    )

    # Submit a v1 audit.
    r = client.post(
        "/v1/audits",
        json=_claim(),
        headers=_bearer(),
    )
    assert r.status_code == 202, r.text
    audit_id = r.json()["audit_id"]

    # Poll GET until done (the webhook + Slack fire on the
    # transition to status="done"). The fast_queue runner is
    # synchronous so this should converge in <1s in practice.
    deadline = time.time() + 5.0
    body: dict[str, Any] = {}
    while time.time() < deadline:
        g = client.get(f"/v1/audits/{audit_id}", headers=_bearer())
        assert g.status_code == 200, g.text
        body = g.json()
        if body.get("status") == "complete":
            break
        time.sleep(0.05)
    assert body.get("status") == "complete", f"audit never completed: {body}"

    # The receiver got at least one POST for audit_complete.
    paths = [r["path"] for r in webhook_server["capture"].requests]
    assert "/slack" in paths, f"expected Slack POST, got {paths}"
    slack_req = next(
        r for r in webhook_server["capture"].requests if r["path"] == "/slack"
    )
    payload = slack_req["body"]
    assert slack_req["headers"]["X-Zorva-Event"] == "audit_complete"
    # Block-kit body: channel override + blocks array.
    assert payload["channel"] == "#billing-audits"
    assert isinstance(payload["blocks"], list) and payload["blocks"]
    assert payload["blocks"][0]["type"] == "section"


# ─── Bulk-accept high_finding wiring smoke test ──────────────────────────


def test_bulk_accept_high_finding_fires_slack(
    tmp_log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a biller bulk-accepts a finding with severity='high',
    the Slack ``high_finding`` event fires with the encounter /
    rule / action metadata. Pins the dashboard-side wiring added
    in ``_bulk_apply`` (kanban t_c9cf54f4).
    """
    # Set up: register a Slack webhook that catches the high_finding
    # event. Use an in-process HTTPServer like the earlier tests
    # so the assertion can inspect the Block Kit body verbatim.
    capture = _Capture()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(capture))
    thread = threading.Thread(
        target=server.serve_forever, name="slack-bulk", daemon=True
    )
    thread.start()
    try:
        host, port = server.server_address[:2]
        slack.register_slack(
            webhook_url=f"http://{host}:{port}/hook",
            channel="#billing-audits",
            events=["high_finding"],
            clinic_id="default",
        )

        # Drive a bulk-accept through the FastAPI app. We rely on
        # the train.json fixtures (already loaded by the demo
        # registry on import) so this test exercises the same
        # path real billers use. ``fresh_logs`` from
        # test_bulk_actions isn't importable here, so we point
        # the audit + feedback + upload logs at tmp_path via
        # env vars.
        audit_log = tmp_log_dir / "audit_trail.jsonl"
        feedback_log = tmp_log_dir / "feedback.jsonl"
        upload_log = tmp_log_dir / "upload_jobs.jsonl"
        monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
        monkeypatch.setenv("FEEDBACK_LOG", str(feedback_log))
        monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(upload_log))
        monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
        monkeypatch.setenv("TENANT_ID", "default")
        import importlib
        from ai_billing_audit import api as api_mod_bulk

        importlib.reload(api_mod_bulk)

        bulk_client = TestClient(api_mod_bulk.app)

        # Find an encounter with a high-severity finding from
        # the bundled train.json so we don't depend on any
        # external state.
        train_path = (
            Path(api_mod_bulk.__file__).resolve().parents[2]
            / "data"
            / "synth"
            / "train.json"
        )
        with train_path.open() as fh:
            train = json.load(fh)
        high_ids: list[str] = []
        for rec in train:
            for f in rec.get("ground_truth", []) or []:
                if (f.get("severity") or "").lower() == "high":
                    high_ids.append(rec["encounter_id"])
                    break
        assert high_ids, "no high-severity findings in train.json"
        ids = high_ids[:5]

        resp = bulk_client.post(
            "/encounters/bulk-accept",
            json={"encounter_ids": ids, "notes": "high_finding smoke"},
        )
        assert resp.status_code == 200, resp.text

        # The Slack receiver got at least one high_finding POST.
        slack_posts = [
            r
            for r in capture.requests
            if r["headers"].get("X-Zorva-Event") == "high_finding"
        ]
        assert slack_posts, "no high_finding Slack POST captured"
        body = slack_posts[0]["body"]
        assert body["channel"] == "#billing-audits"
        # Block-kit body + the rule_id surfaces in the message.
        assert isinstance(body["blocks"], list) and body["blocks"]
        blob = json.dumps(body)
        assert "high" in blob.lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


# ─── SSRF controls on webhook registration (issue #116) ────────────────────
#
# ``register_slack`` used to validate only that the URL was a non-empty
# string, then ``_deliver_one`` fetched it with ``urlopen``. An authenticated
# caller could therefore point the server at internal hosts. It now runs
# ``webhooks.validate_webhook_url``, the same control the generic webhook
# path already used.


@pytest.fixture
def deny_private_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-disable the loopback escape hatch for the rejection tests.

    The autouse ``_allow_loopback_webhooks`` fixture enables it for the rest
    of the file, which would also make ``http://`` acceptable — so these
    tests turn it back off.
    """
    monkeypatch.delenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", raising=False)


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://hooks.slack.com/services/T/B/X", "plain http is refused"),
        ("file:///etc/passwd", "non-http scheme"),
        ("ftp://hooks.slack.com/x", "non-http scheme"),
        ("https://user:pass@hooks.slack.com/x", "userinfo is refused"),
        ("https://localhost/hook", "loopback hostname"),
        ("http://127.0.0.1:9/hook", "loopback address"),
        ("http://169.254.169.254/latest/meta-data/", "cloud metadata address"),
        ("https://127.0.0.1/hook", "loopback address over https"),
        ("", "empty"),
        ("   ", "whitespace only"),
        ("not-a-url", "no scheme"),
    ],
)
def test_register_slack_rejects_non_public_urls(
    url: str,
    why: str,
    deny_private_webhooks: None,
) -> None:
    """Every one of these must raise before anything is persisted."""
    with pytest.raises(ValueError):
        slack.register_slack(webhook_url=url, channel="#x", events=[])


def test_register_slack_rejection_reaches_the_api_as_400(
    client: TestClient,
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    deny_private_webhooks: None,
) -> None:
    """The HTTP surface must refuse a hostile URL, not 201 it."""
    r = client.post(
        "/api/integrations/slack",
        json={
            "webhook_url": "http://169.254.169.254/latest/meta-data/",
            "channel": "#x",
            "events": [],
        },
    )
    assert r.status_code == 400, r.text
    log = tmp_log_dir / "slack.jsonl"
    assert not log.exists() or log.read_text().strip() == ""


def test_delivery_revalidates_and_blocks_a_hostile_url(
    tmp_log_dir: Path,
    fast_queue: JobQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registration-time checks alone would miss DNS rebinding.

    Simulates a stored hook whose URL becomes hostile after registration:
    ``_deliver_one`` must refuse to fetch it, report ``False``, and write a
    delivery-log row rather than performing the request.
    """
    monkeypatch.setenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", "1")
    hook = slack.register_slack(
        webhook_url="http://127.0.0.1:9/hook",
        channel="#x",
        events=["audit_complete"],
    )
    # Now revoke the allowance, as production would never have it.
    monkeypatch.delenv("ZORVA_WEBHOOK_ALLOW_PRIVATE", raising=False)

    hooked = {**hook, "webhook_url": "http://169.254.169.254/latest/meta-data/"}
    delivered = slack._deliver_one(hooked, "audit_complete", {"encounter_id": "e"})
    assert delivered is False

    rows = read_encrypted_json_records(tmp_log_dir / "slack.jsonl")
    blocked = [
        r
        for r in rows
        if r.get("_kind") == "delivery" and "SSRF validation" in str(r.get("error", ""))
    ]
    assert blocked, "expected a blocked-delivery audit row"
