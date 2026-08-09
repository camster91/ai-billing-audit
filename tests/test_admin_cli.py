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

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    read_encrypted_json_records,
    write_encrypted_json_records,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _run_cli(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run ``python -m ai_billing_audit.admin_cli <args>`` and
    capture stdout/stderr/returncode."""
    cmd = [sys.executable, "-m", "ai_billing_audit.admin_cli", *args]
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd, capture_output=True, text=True, env=full_env, cwd=ROOT, timeout=90
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
    for row in rows:
        append_encrypted_json_record(audit, row)
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
    append_encrypted_json_record(idem, entry)
    r = _run_cli(
        "inspect-idempotency",
        "--key",
        "client-req-abc",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 0
    assert "client-req-abc" in r.stdout


def test_inspect_idempotency_missing_key_returns_2(tmp_logs):
    _, idem = tmp_logs
    idem.parent.mkdir(parents=True, exist_ok=True)
    idem.write_text("")  # empty log
    r = _run_cli(
        "inspect-idempotency",
        "--key",
        "no-such-key",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 2


def test_prune_idempotency_drops_stale(tmp_logs):
    _, idem = tmp_logs
    idem.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    entries = [
        {
            "key": "fresh",
            "stored_at": now - 60,
            "status_code": 200,
            "response_json": {},
            "fingerprint": "f",
        },
        {
            "key": "stale-1d",
            "stored_at": now - 86400,
            "status_code": 200,
            "response_json": {},
            "fingerprint": "f",
        },
        {
            "key": "stale-7d",
            "stored_at": now - 604800,
            "status_code": 200,
            "response_json": {},
            "fingerprint": "f",
        },
    ]
    write_encrypted_json_records(idem, entries)
    r = _run_cli(
        "prune-idempotency",
        "--older-than-hours",
        "24",
        env={"IDEMPOTENCY_LOG": str(idem)},
    )
    assert r.returncode == 0
    assert "pruned 2" in r.stdout
    # Read back: only "fresh" should remain
    remaining = [entry["key"] for entry in read_encrypted_json_records(idem)]
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
    for row in rows:
        append_encrypted_json_record(audit, row)
    r = _run_cli(
        "tail-audit",
        "--tenant",
        "t1",
        "--n",
        "10",
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
    for row in rows:
        append_encrypted_json_record(audit, row)
    r = _run_cli(
        "tail-audit",
        "--n",
        "5",
        env={"AUDIT_TRAIL_LOG": str(audit)},
    )
    assert r.returncode == 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 5


def test_migrate_job_log_encrypts_legacy_records(tmp_path):
    job_log = tmp_path / "upload_jobs.jsonl"
    job_log.write_text(
        '{"job_id":"job-1","encounter_id":"PATIENT-SECRET",'
        '"source":"837p","status":"done","result":{}}\n',
        encoding="utf-8",
    )

    result = _run_cli("migrate-job-log", env={"UPLOAD_JOB_LOG": str(job_log)})

    assert result.returncode == 0, result.stderr
    assert "migrated 1" in result.stdout
    assert b"PATIENT-SECRET" not in job_log.read_bytes()
    backup = job_log.with_suffix(".jsonl.plaintext.bak.enc")
    assert backup.exists()
    assert b"PATIENT-SECRET" not in backup.read_bytes()


def test_migrate_doctor_emails_encrypts_legacy_outbox(tmp_path):
    mailbox = tmp_path / "doctor_emails.jsonl"
    optouts = tmp_path / "doctor_optouts.json"
    mailbox.write_text(
        '{"to":"doctor@example.ca","body":"Patient Jane Doe"}\n',
        encoding="utf-8",
    )
    optouts.write_text(
        '{"doctor@example.ca":{"reason":"Patient Jane Doe"}}',
        encoding="utf-8",
    )

    result = _run_cli(
        "migrate-doctor-emails",
        env={
            "DOCTOR_EMAIL_LOG": str(mailbox),
            "DOCTOR_OPTOUT_PATH": str(optouts),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "migrated 1" in result.stdout
    assert b"doctor@example.ca" not in mailbox.read_bytes()
    assert b"doctor@example.ca" not in optouts.read_bytes()
    assert mailbox.with_suffix(".jsonl.plaintext.bak.enc").exists()


def test_migrate_appeal_logs_encrypts_letters_and_outcomes(tmp_path):
    letters = tmp_path / "appeal_letters.jsonl"
    outcomes = tmp_path / "appeal_outcomes.jsonl"
    letters.write_text('{"encounter_id":"ENC-SECRET"}\n', encoding="utf-8")
    outcomes.write_text(
        '{"appeal_id":"A-1","encounter_id":"ENC-SECRET",'
        '"status":"won","timestamp":"2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )

    result = _run_cli("migrate-appeal-logs", env={"ZORVA_LOGS_DIR": str(tmp_path)})

    assert result.returncode == 0, result.stderr
    assert "letters=1" in result.stdout
    assert "outcomes=1" in result.stdout
    assert b"ENC-SECRET" not in letters.read_bytes()
    assert b"ENC-SECRET" not in outcomes.read_bytes()


def test_migrate_feedback_logs_encrypts_decisions_corrections_and_comments(tmp_path):
    feedback = tmp_path / "feedback.jsonl"
    corrections = tmp_path / "corrections.jsonl"
    comments = tmp_path / "comments.jsonl"
    feedback.write_text('{"encounter_id":"ENC-SECRET"}\n', encoding="utf-8")
    corrections.write_text('{"rationale":"Patient Jane Doe"}\n', encoding="utf-8")
    comments.write_text('{"body":"Patient Jane Doe"}\n', encoding="utf-8")

    result = _run_cli(
        "migrate-feedback-logs",
        env={
            "FEEDBACK_LOG": str(feedback),
            "BILLER_CORRECTIONS_LOG": str(corrections),
            "FINDING_COMMENTS_LOG": str(comments),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "feedback=1" in result.stdout
    assert "corrections=1" in result.stdout
    assert "comments=1" in result.stdout
    assert b"ENC-SECRET" not in feedback.read_bytes()
    assert b"Jane Doe" not in corrections.read_bytes()
    assert b"Jane Doe" not in comments.read_bytes()


def test_migrate_clinical_metric_logs_encrypts_phi_surfaces(tmp_path):
    suggestions = tmp_path / "suggestions.jsonl"
    owner_emails = tmp_path / "owner_emails.jsonl"
    suggestions.write_text('{"suggestion":"Patient Jane Doe"}\n', encoding="utf-8")
    owner_emails.write_text('{"body":"Encounter ENC-SECRET"}\n', encoding="utf-8")

    result = _run_cli(
        "migrate-clinical-metric-logs",
        env={
            "NOTE_SUGGESTION_LOG": str(suggestions),
            "OWNER_EMAIL_LOG": str(owner_emails),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "migrated 2 clinical-metric records" in result.stdout
    assert b"Jane Doe" not in suggestions.read_bytes()
    assert b"ENC-SECRET" not in owner_emails.read_bytes()


def test_migrate_audit_trail_encrypts_legacy_chain(tmp_path):
    audit = tmp_path / "audit_trail.jsonl"
    audit.write_text(
        '{"tenant_id":"clinic-a","data_elements":'
        '{"encounter_id":"ENC-SECRET","note":"Patient Jane Doe"}}\n',
        encoding="utf-8",
    )

    result = _run_cli(
        "migrate-audit-trail",
        env={"AUDIT_TRAIL_LOG": str(audit)},
    )

    assert result.returncode == 0, result.stderr
    assert "migrated 1 audit-trail records" in result.stdout
    assert b"ENC-SECRET" not in audit.read_bytes()
    assert audit.with_suffix(".jsonl.plaintext.bak.enc").exists()


def test_migrate_integration_logs_encrypts_identifiers_and_secrets(tmp_path):
    usage = tmp_path / "usage.jsonl"
    audit_index = tmp_path / "v1_audits.jsonl"
    webhooks = tmp_path / "webhooks.jsonl"
    slack = tmp_path / "slack.jsonl"
    usage.write_text('{"encounter_id":"ENC-SECRET"}\n', encoding="utf-8")
    audit_index.write_text('{"job_id":"JOB-SECRET"}\n', encoding="utf-8")
    webhooks.write_text(
        '{"url":"https://example.test/hook","_signing_secret":"SIGNING-SECRET"}\n',
        encoding="utf-8",
    )
    slack.write_text(
        '{"webhook_url":"https://hooks.slack.test/SECRET"}\n',
        encoding="utf-8",
    )

    result = _run_cli(
        "migrate-integration-logs",
        env={
            "ZORVA_USAGE_LOG_PATH": str(usage),
            "ZORVA_WEBHOOK_LOG_PATH": str(webhooks),
            "ZORVA_SLACK_LOG_PATH": str(slack),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "usage=1" in result.stdout
    assert "audit_index=1" in result.stdout
    assert "webhooks=1" in result.stdout
    assert "slack=1" in result.stdout
    for path, secret in (
        (usage, b"ENC-SECRET"),
        (audit_index, b"JOB-SECRET"),
        (webhooks, b"SIGNING-SECRET"),
        (slack, b"SECRET"),
    ):
        assert secret not in path.read_bytes()


def test_migrate_portal_state_logs_encrypts_encounter_state(tmp_path):
    logs = {
        "IDEMPOTENCY_LOG": tmp_path / "idempotency.jsonl",
        "FINDING_ASSIGNMENT_LOG": tmp_path / "assignments.jsonl",
        "SNOOZE_LOG": tmp_path / "snoozes.jsonl",
        "SAVED_FILTERS_LOG": tmp_path / "saved_filters.jsonl",
    }
    for path in logs.values():
        path.write_text('{"encounter_id":"ENC-SECRET"}\n', encoding="utf-8")
    sticky = tmp_path / "sticky_notes.jsonl"
    sticky.write_text('{"note":"Patient Jane Doe"}\n', encoding="utf-8")

    result = _run_cli(
        "migrate-portal-state-logs",
        env={
            **{name: str(path) for name, path in logs.items()},
            "UX_POLISH_LOG_DIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "idempotency=1" in result.stdout
    assert "assignments=1" in result.stdout
    assert "snoozes=1" in result.stdout
    assert "saved_filters=1" in result.stdout
    assert "ux=1" in result.stdout
    for path in (*logs.values(), sticky):
        assert b"ENC-SECRET" not in path.read_bytes()
        assert b"Jane Doe" not in path.read_bytes()


def test_migrate_contact_uploads_encrypts_legacy_claim_files(tmp_path):
    upload_dir = tmp_path / "contact_uploads"
    upload_dir.mkdir()
    claim = upload_dir / "legacy.837"
    claim.write_bytes(b"CLM*PATIENT-SECRET*100~")

    result = _run_cli(
        "migrate-contact-uploads",
        env={"CONTACT_UPLOAD_DIR": str(upload_dir)},
    )

    assert result.returncode == 0, result.stderr
    assert "migrated 1 contact-upload files" in result.stdout
    assert b"PATIENT-SECRET" not in claim.read_bytes()
