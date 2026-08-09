from __future__ import annotations

from pathlib import Path
import time

import pytest
from cryptography.fernet import Fernet

from ai_billing_audit import job_queue
from ai_billing_audit.clinical_note_storage import (
    PhiStorageConfigurationError,
    PhiStorageIntegrityError,
    append_encrypted_json_record,
    decrypt_phi,
    load_clinical_note,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
    store_clinical_note,
)


def test_clinical_note_is_encrypted_at_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("ZORVA_PHI_ENCRYPTION_KEY", key)
    target = tmp_path / "note.txt.enc"
    plaintext = b"Patient reports chest pain and dizziness."

    store_clinical_note(target, plaintext)

    stored = target.read_bytes()
    assert plaintext not in stored
    assert load_clinical_note(target) == plaintext


def test_clinical_note_storage_fails_closed_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZORVA_PHI_ENCRYPTION_KEY", raising=False)

    with pytest.raises(PhiStorageConfigurationError):
        store_clinical_note(tmp_path / "note.txt.enc", b"sensitive")


def test_encrypted_json_records_hide_phi_and_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    path = tmp_path / "doctor_emails.jsonl.enc"
    first = {"to": "doctor@example.ca", "body": "Patient Jane Doe has E11.9"}
    second = {"encounter_id": "ENC-PHI-2", "notes": "appeal narrative"}

    append_encrypted_json_record(path, first)
    append_encrypted_json_record(path, second)

    stored = path.read_bytes()
    assert b"doctor@example.ca" not in stored
    assert b"Jane Doe" not in stored
    assert b"ENC-PHI-2" not in stored
    assert read_encrypted_json_records(path) == [first, second]


def test_encrypted_json_reader_refuses_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    path = tmp_path / "legacy.jsonl"
    path.write_text('{"patient":"Jane Doe"}\n', encoding="utf-8")

    with pytest.raises(PhiStorageIntegrityError):
        read_encrypted_json_records(path)


def test_generic_plaintext_jsonl_migration_preserves_encrypted_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    path = tmp_path / "doctor_emails.jsonl"
    legacy = b'{"to":"doctor@example.ca","body":"Patient Jane Doe"}\n'
    path.write_bytes(legacy)

    assert migrate_plaintext_jsonl(path) == 1

    backup = path.with_suffix(".jsonl.plaintext.bak.enc")
    assert b"Jane Doe" not in path.read_bytes()
    assert b"Jane Doe" not in backup.read_bytes()
    assert decrypt_phi(backup.read_bytes()) == legacy
    assert read_encrypted_json_records(path)[0]["body"] == "Patient Jane Doe"
    assert migrate_plaintext_jsonl(path) == 0


def test_job_runner_loads_latest_encrypted_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(job_queue, "_UPLOADED_NOTES_DIR", tmp_path)
    older = tmp_path / "enc-001.older.txt.enc"
    newer = tmp_path / "enc-001.newer.txt.enc"
    store_clinical_note(older, b"older note")
    store_clinical_note(newer, b"newer note")
    older.touch()
    newer.touch()
    older_mtime = older.stat().st_mtime - 10
    import os

    os.utime(older, (older_mtime, older_mtime))

    assert job_queue._load_uploaded_note("enc-001") == "newer note"


def test_job_queue_encrypts_identifiers_claims_and_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    log_path = tmp_path / "upload_jobs.jsonl.enc"
    sensitive_result = {
        "claim": {
            "patient_id": "PATIENT-SECRET-99",
            "diagnosis_codes": ["I10"],
        },
        "findings": [{"quote": "secret clinical evidence"}],
    }
    queue = job_queue.JobQueue(
        log_path=log_path, runner=lambda _encounter: sensitive_result
    )

    job = queue.enqueue(encounter={"encounter_id": "ENCOUNTER-SECRET-1"}, source="837p")
    deadline = time.time() + 5
    while job.status not in {"done", "failed"} and time.time() < deadline:
        time.sleep(0.01)

    stored = log_path.read_bytes()
    for secret in (
        b"ENCOUNTER-SECRET-1",
        b"PATIENT-SECRET-99",
        b"I10",
        b"secret clinical evidence",
    ):
        assert secret not in stored

    restored = job_queue.JobQueue(log_path=log_path, runner=lambda _encounter: {})
    restored_job = restored.get(job.job_id)
    assert restored_job is not None
    assert restored_job.result == sensitive_result


def test_job_queue_refuses_legacy_plaintext_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    log_path = tmp_path / "upload_jobs.jsonl"
    log_path.write_text('{"encounter_id":"PLAINTEXT-PHI"}\n', encoding="utf-8")

    with pytest.raises(PhiStorageIntegrityError):
        job_queue.JobQueue(log_path=log_path)


def test_legacy_job_log_migration_backs_up_and_encrypts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    log_path = tmp_path / "upload_jobs.jsonl"
    legacy = (
        '{"job_id":"job-1","encounter_id":"PLAINTEXT-PHI",'
        '"source":"837p","status":"done","result":{}}\n'
    )
    log_path.write_text(legacy, encoding="utf-8")
    legacy_bytes = log_path.read_bytes()

    migrated = job_queue.migrate_plaintext_job_log(log_path)

    assert migrated == 1
    backup = log_path.with_suffix(".jsonl.plaintext.bak.enc")
    assert b"PLAINTEXT-PHI" not in backup.read_bytes()
    assert decrypt_phi(backup.read_bytes()) == legacy_bytes
    assert b"PLAINTEXT-PHI" not in log_path.read_bytes()
    assert job_queue.JobQueue(log_path=log_path).get("job-1") is not None
    assert job_queue.migrate_plaintext_job_log(log_path) == 0


def test_default_queue_uses_configured_encrypted_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "ZORVA_PHI_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    configured = tmp_path / "configured-upload-jobs.jsonl.enc"
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(configured))
    job_queue.reset_default_queue_for_tests()

    queue = job_queue.get_default_queue()
    job = queue.enqueue(encounter={"encounter_id": "enc-configured"}, source="paste")
    deadline = time.time() + 5
    while job.status not in {"done", "failed"} and time.time() < deadline:
        time.sleep(0.01)

    assert configured.exists()
    assert b"enc-configured" not in configured.read_bytes()
