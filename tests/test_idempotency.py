"""Tests for the Idempotency-Key replay layer.

The ``encounters_upload_submit`` endpoint accepts an
``Idempotency-Key`` header and replays the cached response on
retry. This is the defence against double-submit (mobile reconnect,
browser back+forward, retry middleware) creating duplicate audit
jobs in the queue.

Contract:

1. First POST with a key: endpoint runs, response is cached.
2. Retry POST with same key + same body: cached response returned
   (status + body), endpoint code never re-runs.
3. Retry POST with same key + DIFFERENT body: 409 Conflict.
4. POST without a key: endpoint runs (no caching). No header, no
   idempotency.
5. POST with the same key after the cache is evicted (manually
   truncate the JSONL log): endpoint runs fresh.
6. Body fingerprint is stable across encodings (the same JSON
   serialised differently produces different fingerprints, but
   byte-identical bodies produce identical fingerprints).
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


@pytest.fixture
def idem_log(tmp_path, monkeypatch):
    """Point the idempotency log at a per-test tmp path."""
    log = tmp_path / "idempotency.jsonl"
    monkeypatch.setenv("IDEMPOTENCY_LOG", str(log))
    yield log


def test_fingerprint_is_stable_for_same_body():
    from ai_billing_audit.idempotency import fingerprint_request_body

    fp1 = fingerprint_request_body('{"a": 1, "b": 2}')
    fp2 = fingerprint_request_body('{"a": 1, "b": 2}')
    assert fp1 == fp2
    # Different bodies → different fingerprints
    fp3 = fingerprint_request_body('{"a": 1, "b": 3}')
    assert fp1 != fp3
    # Bytes vs str → same fingerprint
    fp4 = fingerprint_request_body(b'{"a": 1, "b": 2}')
    assert fp1 == fp4


def test_fingerprint_for_empty_body_is_stable():
    from ai_billing_audit.idempotency import fingerprint_request_body

    fp = fingerprint_request_body("")
    assert len(fp) == 64  # SHA-256 hex
    assert fp == fingerprint_request_body("")
    assert fp != fingerprint_request_body("a")


def test_lookup_returns_none_for_unknown_key(idem_log):
    from ai_billing_audit.idempotency import fingerprint_request_body, lookup

    fp = fingerprint_request_body("payload-1")
    assert lookup("nonexistent-key", fp) is None


def test_store_then_lookup_replays_response(idem_log):
    from ai_billing_audit.idempotency import (
        fingerprint_request_body,
        lookup,
        store,
    )

    fp = fingerprint_request_body("payload-1")
    store(
        key="client-req-001",
        fingerprint=fp,
        status_code=201,
        response_json={"jobs": [{"job_id": "j-1"}], "rejected": []},
    )

    hit = lookup("client-req-001", fp)
    assert hit is not None
    assert hit.status_code == 201
    assert hit.response_json == {"jobs": [{"job_id": "j-1"}], "rejected": []}


def test_lookup_raises_on_key_reuse_with_different_body(idem_log):
    """Same key, different fingerprint → 409 Conflict."""
    from ai_billing_audit.idempotency import (
        IdempotencyMismatch,
        fingerprint_request_body,
        lookup,
        store,
    )

    fp1 = fingerprint_request_body("payload-1")
    fp2 = fingerprint_request_body("payload-2-different")
    store(
        key="reuse-key",
        fingerprint=fp1,
        status_code=200,
        response_json={"jobs": []},
    )
    with pytest.raises(IdempotencyMismatch):
        lookup("reuse-key", fp2)


def test_lookup_uses_most_recent_entry_for_key(idem_log):
    """If a key is somehow stored twice (e.g. cache corruption,
    manual write), the latest entry wins."""
    from ai_billing_audit.idempotency import (
        fingerprint_request_body,
        lookup,
        store,
    )

    fp = fingerprint_request_body("p")
    store("dup-key", fp, 200, {"v": 1})
    store("dup-key", fp, 200, {"v": 2})
    hit = lookup("dup-key", fp)
    assert hit is not None
    assert hit.response_json == {"v": 2}


def test_store_then_eviction_frees_slot_for_new_key(idem_log, monkeypatch):
    """Bounded cache: when the JSONL exceeds IDEMPOTENCY_MAX_ENTRIES,
    the oldest entries are evicted FIFO."""
    from ai_billing_audit.idempotency import store

    monkeypatch.setenv("IDEMPOTENCY_MAX_ENTRIES", "3")
    # Re-import to pick up the new env? The module reads
    # IDEMPOTENCY_MAX_ENTRIES inside ``_evict_if_needed`` on every
    # call so no re-import is needed.
    store("k1", "fp1", 200, {})
    store("k2", "fp2", 200, {})
    store("k3", "fp3", 200, {})
    store("k4", "fp4", 200, {})  # k1 should be evicted
    # Read the log directly and confirm k1 is gone
    lines = idem_log.read_text().splitlines()
    keys = [json.loads(ln).get("key") for ln in lines if ln.strip()]
    assert "k1" not in keys
    assert keys == ["k2", "k3", "k4"]


def test_store_with_empty_key_is_noop(idem_log):
    """Caller didn't ask for idempotency → nothing persisted."""
    from ai_billing_audit.idempotency import store

    store("", "fp", 200, {"junk": True})
    # Log file should not exist
    assert not idem_log.exists()


def test_missing_log_file_returns_empty_cache(idem_log):
    """First run: no cache file → lookup returns None."""
    from ai_billing_audit.idempotency import fingerprint_request_body, lookup

    assert not idem_log.exists()
    assert lookup("anything", fingerprint_request_body("x")) is None


def test_corrupted_log_line_is_skipped_not_raised(idem_log):
    """A partial write (crash mid-flush) leaves a truncated JSON line.
    The reader must skip it, not crash."""
    from ai_billing_audit.idempotency import lookup

    idem_log.parent.mkdir(parents=True, exist_ok=True)
    idem_log.write_text(
        'NOT VALID JSON\n'
        '{"key": "valid", "fingerprint": "fp1", "status_code": 200, "response_json": {"v": 1}}\n'
    )
    # The corrupted line is skipped; the valid one is found
    hit = lookup("valid", "fp1")
    assert hit is not None
    assert hit.response_json == {"v": 1}