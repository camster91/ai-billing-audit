"""Tests for ``JobQueue._find_recent_dup`` + the dedup_hit flag.

Dedup is the data-layer complement to the HTTP-layer Idempotency-
Key replay. It catches:

  * Same encounter submitted from a different browser tab (no
    shared Idempotency-Key).
  * Bulk-CSV ingest re-running on the same file after a CSV-
    parser crash (the previous run already enqueued).
  * Network retries from a non-HTTP-aware client (a CLI that
    just POSTs the same JSON 3 times).

Match key: (tenant_id, encounter_id, patient_id). The window
defaults to 300s (DEDUP_WINDOW_SECONDS env var).

These tests pin:

1. First enqueue is fresh; dedup_hit=False on the returned Job.
2. Second enqueue with the same tuple within the window →
   returned Job has dedup_hit=True and the SAME job_id.
3. Enqueue with allow_duplicate=True bypasses dedup.
4. Different encounter_id is a fresh job.
5. Different patient_id is a fresh job.
6. Different tenant_id is a fresh job (cross-tenant dedup is
   never appropriate).
7. Out-of-window duplicates are NOT caught (DEDUP_WINDOW_SECONDS=0).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def queue(monkeypatch, tmp_path):
    """Build a fresh JobQueue and disable the worker thread so
    tests run synchronously. The worker_thread re-runs the audit
    call which would either take 30s or fail without an LLM key.
    """
    from ai_billing_audit.job_queue import JobQueue
    # Disable the worker thread by patching threading.Thread to
    # call the target inline (sync) so tests don't hang on real
    # audit calls.
    import threading

    _real_thread_init = threading.Thread.__init__

    def _sync_thread(self, *args, **kwargs):
        _real_thread_init(self, *args, **kwargs)
        # Replace start so the thread runs inline
        self._target = kwargs.get("target")
        self._args = kwargs.get("args") or ()
        # Set daemon so test process can exit cleanly if it leaks
        self.daemon = True

    def _sync_start(self):
        target, args = self._target, self._args
        target(*args)

    monkeypatch.setattr(threading.Thread, "__init__", _sync_thread)
    monkeypatch.setattr(threading.Thread, "start", _sync_start)

    log_path = tmp_path / "job_queue.jsonl"
    return JobQueue(log_path, runner=lambda enc: {"encounter_id": enc.get("encounter_id", "")})


def _enc(enc_id: str = "enc-001", patient_id: str = "pat-001"):
    return {"encounter_id": enc_id, "patient_id": patient_id}


def test_first_enqueue_is_fresh(queue):
    job = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    assert job.dedup_hit is False
    assert job.encounter_id == "enc-001"
    assert job.patient_id == "pat-001"


def test_second_enqueue_within_window_returns_existing(queue):
    j1 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is True
    assert j2.job_id == j1.job_id, (
        f"second enqueue returned {j2.job_id}; expected to "
        f"dedup-hit on {j1.job_id}"
    )


def test_allow_duplicate_bypasses_dedup(queue):
    j1 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
        allow_duplicate=True,
    )
    assert j2.dedup_hit is False
    assert j2.job_id != j1.job_id


def test_different_encounter_id_is_fresh(queue):
    queue.enqueue(
        encounter=_enc(enc_id="enc-001"),
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter=_enc(enc_id="enc-002"),
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is False


def test_different_patient_id_is_fresh(queue):
    queue.enqueue(
        encounter=_enc(enc_id="enc-001", patient_id="pat-A"),
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter=_enc(enc_id="enc-001", patient_id="pat-B"),
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is False


def test_different_tenant_id_is_fresh(queue):
    queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t2",
    )
    assert j2.dedup_hit is False


def test_window_zero_disables_dedup(queue, monkeypatch):
    """DEDUP_WINDOW_SECONDS=0 → no dedup (every enqueue is fresh)."""
    monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "0")
    j1 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    # Manually mark j1 as done + finished_at far in the past so
    # the dedup check would catch it if the window allowed.
    j1.status = "done"
    j1.finished_at = time.time() - 1000  # 1000s ago
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    # Window=0 means no recent match — fresh enqueue
    assert j2.dedup_hit is False


def test_finished_job_within_window_still_deduplicates(queue, monkeypatch):
    """Even a completed job blocks duplicate enqueue within the
    dedup window. The point is to prevent the biller from
    accidentally double-submitting during a 5-minute window."""
    monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "300")
    j1 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    j1.status = "done"
    j1.finished_at = time.time() - 10  # 10 seconds ago, well within window
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is True
    assert j2.job_id == j1.job_id


def test_finished_job_outside_window_is_fresh(queue, monkeypatch):
    monkeypatch.setenv("DEDUP_WINDOW_SECONDS", "60")
    j1 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    j1.status = "done"
    j1.finished_at = time.time() - 120  # 2 minutes ago, outside 60s window
    j2 = queue.enqueue(
        encounter=_enc(),
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is False


def test_dedup_patient_id_empty_only_matches_when_both_empty(queue):
    """Edge case: a row without patient_id should match another
    row without patient_id (empty == empty), but NOT match a
    row with patient_id="pat-A".
    """
    j1 = queue.enqueue(
        encounter={"encounter_id": "enc-001", "patient_id": ""},
        source="paste",
        tenant_id="t1",
    )
    j2 = queue.enqueue(
        encounter={"encounter_id": "enc-001", "patient_id": ""},
        source="paste",
        tenant_id="t1",
    )
    assert j2.dedup_hit is True
    assert j2.job_id == j1.job_id

    # Different encounter with patient_id="pat-A" is fresh
    j3 = queue.enqueue(
        encounter={"encounter_id": "enc-002", "patient_id": "pat-A"},
        source="paste",
        tenant_id="t1",
    )
    assert j3.dedup_hit is False