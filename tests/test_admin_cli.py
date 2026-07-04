"""Tests for the admin CLI (``python -m ai_billing_audit.admin_cli``).

The CLI is small (5 subcommands, all read-only on the audit
trail / idempotency cache). Tests exercise:

1. Each subcommand's argparse wiring (--help, required flags).
2. ``list-tenants`` correctly aggregates the audit_trail.jsonl
   into per-tenant counts.
3. ``inspect-idempotency --key <key>`` returns the stored entry.
4. ``prune-idempotency --older-than-hours N`` drops stale entries.
5. ``tail-audit --tenant <id> --n N`` filters + trims events.
6. Exit codes: 0 = success, 1 = log file missing, 2 = key not found.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run ``python -m ai_billing_audit.admin_cli <args>`` and
    capture stdout/stderr/returncode."""
    cmd = [sys.executable, "-m", "ai_billing_audit.admin_cli", *args]
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd, capture_output=True, text=True, env=full_env, cwd=ROOT, timeout=30
    )


@pytest.fixture
def tmp_logs(tmp_path, monkeypatch):
    """Point the CLI at per-test tmp paths so it doesn't touch
    the real /app/logs/audit_trail.jsonl."""
    audit = tmp_path / "audit_trail.jsonl"
    idem = tmp_path / "idempotency.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit))
    monkeypatch.setenv("IDEMPOTENCY_LOG", str(idem))
    return audit, idem


def test_help_exits_0():
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "zorva-admin" in r.stdout


def test_list_tenants_aggregates_counts(tmp_logs):
    audit, _ = tmp_logs
    audit.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"tenant_id": "t1", "action": "accept"},
        {"tenant_id": "t1", "action": "dismiss"},
        {"tenant_id": "t2", "action": "accept"},
        {"tenant_id": "t2", "action": "modify"},
        {"tenant_id": "t2", "action": "comment"},
        {"tenant_id": "", "action": "system"},  # <unset>
    ]
    with audit.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r = _run_cli(
        "list-tenants",
        env={"AUDIT_TRAIL_LOG": str(audit)},
    )
    assert r.returncode == 0
    assert "t2" in r.stdout
    assert "t1" in r.stdout
    assert "3" in r.stdout  # t2 has 3 events
    assert "2" in r.stdout  # t1 has 2 events


def test_list_tenants_missing_log_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(tmp_path / "nope.jsonl"))
    r = _run_cli(
        "list-tenants",
        env={"AUDIT_TRAIL_LOG": str(tmp_path / "nope.jsonl")},
    )
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_inspect_idempotency_finds_key(tmp_logs):
    _, idem = tmp_logs
    idem.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "key": "client-req-abc",
        "fingerprint": "fp1",
        "status_code": 200,
        "response_json": {"jobs": [{"job_id": "j-1"}]},
        "stored_at": time.time(),
    }
    idem.write_text(json.dumps(entry) + "\n")
    r = _run_cli(
        "inspect-idempotency", "--key", "client-req-abc",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 0
    assert "client-req-abc" in r.stdout


def test_inspect_idempotency_missing_key_returns_2(tmp_logs):
    _, idem = tmp_logs
    idem.parent.mkdir(parents=True, exist_ok=True)
    idem.write_text("")  # empty log
    r = _run_cli(
        "inspect-idempotency", "--key", "no-such-key",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 2


def test_prune_idempotency_drops_stale(tmp_logs):
    _, idem = tmp_logs
    idem.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    entries = [
        {"key": "fresh", "stored_at": now - 60, "status_code": 200, "response_json": {}, "fingerprint": "f"},
        {"key": "stale-1d", "stored_at": now - 86400, "status_code": 200, "response_json": {}, "fingerprint": "f"},
        {"key": "stale-7d", "stored_at": now - 604800, "status_code": 200, "response_json": {}, "fingerprint": "f"},
    ]
    with idem.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    r = _run_cli(
        "prune-idempotency", "--older-than-hours", "24",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 0
    assert "pruned 2" in r.stdout
    # Read back: only "fresh" should remain
    remaining = [json.loads(ln)["key"] for ln in idem.read_text().splitlines() if ln.strip()]
    assert remaining == ["fresh"]


def test_tail_audit_filters_by_tenant(tmp_logs):
    audit, _ = tmp_logs
    audit.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    rows = [
        {"tenant_id": "t1", "event_id": "e1", "ts": now - 10, "action": "accept"},
        {"tenant_id": "t2", "event_id": "e2", "ts": now - 5, "action": "dismiss"},
        {"tenant_id": "t1", "event_id": "e3", "ts": now - 1, "action": "modify"},
    ]
    with audit.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r = _run_cli(
        "tail-audit", "--tenant", "t1", "--n", "10",
        env={"AUDIT_TRAIL_LOG": str(audit)},
    )
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2  # only t1 events
    assert all('"t1"' in ln for ln in lines)


def test_tail_audit_truncates_to_n(tmp_logs):
    audit, _ = tmp_logs
    audit.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"tenant_id": "t1", "event_id": f"e{i}"} for i in range(20)]
    with audit.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r = _run_cli(
        "tail-audit", "--n", "5",
        env={"AUDIT_TRAIL_LOG": str(audit)},
    )
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 5