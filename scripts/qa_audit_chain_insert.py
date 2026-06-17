"""QA helper for kanban t_e9c443e3.

Inserts a small batch of realistic ``audit_trail`` rows with correctly
chained SHA-256 signatures so the chain verifier can be exercised
against a real Postgres table.

Why a separate script (not psql alone): the chain payload includes
``data_elements`` as JSONB.  Postgres' JSONB ``::text`` form is the
canonical, deterministic representation (sorted keys, no whitespace).
A Python ``str(dict)`` would produce a different byte sequence and
break the chain.  Computing the signature in Python with
``json.dumps(..., sort_keys=True, separators=(",", ":"))`` matches
the JSONB ``::text`` output exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from audit_log import compute_signature  # noqa: E402

# Source DB. The QA DB is a sibling of the production one; the chain
# is identical because the chain algorithm is the same.
DB = "ai_billing_audit_QA"

# Truncate any prior QA rows so this script is rerunnable.
# (The trigger blocks UPDATE/DELETE on signed rows; the table starts
# empty, so a plain DELETE works on the first run.  On a rerun, the
# trigger blocks DELETE; drop+recreate the table is the escape hatch
# -- but we never reach that path because the prior run of this
# script left signed rows that are immutable.  Practically: drop the
# DB and recreate it between QA runs.)


def build_rows() -> list[dict]:
    """Return a realistic batch of audit_trail rows in chain order.

    Field set is the project's canonical set (see CHAIN_FIELDS).  We
    model a single billing-audit session: read claim, run LLM, emit
    finding, accept/dismiss, plus a /findings bulk-action pair at the
    end.  Each row's ``previous_signature`` is left for the signer
    pass to set; ``id`` and ``created_at`` are DB-assigned.
    """
    base_ts = "2026-06-17T14:00:00.000000Z"
    session = "sess-20260617-001"
    run = "run-7a3f1"
    auditor = "auditor@ashbi.ca"
    reviewer = "reviewer@ashbi.ca"
    patient = "ab" * 32  # 64 hex
    raw = [
        {
            "event_id": f"e-001-{session}",
            "timestamp": "2026-06-17T14:00:00.000000Z",
            "user_identifier": auditor,
            "action": "READ_CLAIM",
            "patient_hash": patient,
            "data_elements_jsonb": {"claim_id": "c-001", "source": "edi_837"},
            "model_run_id": run,
        },
        {
            "event_id": f"e-002-{session}",
            "timestamp": "2026-06-17T14:00:01.000000Z",
            "user_identifier": auditor,
            "action": "RUN_AUDIT",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "claim_id": "c-001",
                "model": "claude-opus-4",
                "tokens_in": 1284,
                "tokens_out": 312,
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-003-{session}",
            "timestamp": "2026-06-17T14:00:02.000000Z",
            "user_identifier": "model",
            "action": "EMIT_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "finding_id": "f-001",
                "category": "duplicate_billing",
                "severity": "high",
                "evidence_claim_ids": ["c-001", "c-001b"],
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-004-{session}",
            "timestamp": "2026-06-17T14:00:03.000000Z",
            "user_identifier": reviewer,
            "action": "ACCEPT_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {"finding_id": "f-001", "verdict": "ACCEPT"},
            "model_run_id": run,
        },
        {
            "event_id": f"e-005-{session}",
            "timestamp": "2026-06-17T14:00:04.000000Z",
            "user_identifier": auditor,
            "action": "READ_CLAIM",
            "patient_hash": patient,
            "data_elements_jsonb": {"claim_id": "c-002", "source": "edi_837"},
            "model_run_id": run,
        },
        {
            "event_id": f"e-006-{session}",
            "timestamp": "2026-06-17T14:00:05.000000Z",
            "user_identifier": auditor,
            "action": "RUN_AUDIT",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "claim_id": "c-002",
                "model": "claude-opus-4",
                "tokens_in": 982,
                "tokens_out": 188,
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-007-{session}",
            "timestamp": "2026-06-17T14:00:06.000000Z",
            "user_identifier": "model",
            "action": "EMIT_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "finding_id": "f-002",
                "category": "code_mismatch",
                "severity": "medium",
                "evidence_claim_ids": ["c-002"],
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-008-{session}",
            "timestamp": "2026-06-17T14:00:07.000000Z",
            "user_identifier": reviewer,
            "action": "DISMISS_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "finding_id": "f-002",
                "verdict": "DISMISS",
                "rationale": "code matches documentation",
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-009-{session}",
            "timestamp": "2026-06-17T14:00:08.000000Z",
            "user_identifier": auditor,
            "action": "READ_CLAIM",
            "patient_hash": patient,
            "data_elements_jsonb": {"claim_id": "c-003", "source": "edi_837"},
            "model_run_id": run,
        },
        {
            "event_id": f"e-010-{session}",
            "timestamp": "2026-06-17T14:00:09.000000Z",
            "user_identifier": auditor,
            "action": "RUN_AUDIT",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "claim_id": "c-003",
                "model": "claude-opus-4",
                "tokens_in": 1102,
                "tokens_out": 240,
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-011-{session}",
            "timestamp": "2026-06-17T14:00:10.000000Z",
            "user_identifier": "model",
            "action": "EMIT_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {
                "finding_id": "f-003",
                "category": "unbundling",
                "severity": "low",
                "evidence_claim_ids": ["c-003"],
            },
            "model_run_id": run,
        },
        {
            "event_id": f"e-012-{session}",
            "timestamp": "2026-06-17T14:00:11.000000Z",
            "user_identifier": reviewer,
            "action": "ACCEPT_FINDING",
            "patient_hash": patient,
            "data_elements_jsonb": {"finding_id": "f-003", "verdict": "ACCEPT"},
            "model_run_id": run,
        },
    ]
    return raw


def insert_raw_rows(rows: list[dict]) -> list[dict]:
    """Insert the raw rows (without real signatures) and return them.

    The schema has ``cryptographic_signature TEXT NOT NULL`` -- the
    pre-image for the chain must already be in place at insert time.
    We satisfy that with a placeholder (64 zeros) and then overwrite
    each row's signature in ``write_signatures_no_trigger`` after we
    have read back the JSONB ``::text`` canonical form.

    Postgres' JSONB ``::text`` preserves key insertion order, so the
    placeholder->real-sign two-phase is required: the row must already
    be stored before we can hash against its on-disk ``data_elements``
    text form.
    """
    def sql_str(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    values_sql: list[str] = []
    payloads: list[dict] = []
    for r in rows:
        data_elements_json = json.dumps(
            r["data_elements_jsonb"], sort_keys=True
        )
        values_sql.append(
            "("
            + sql_str(r["event_id"]) + ", "
            + sql_str(r["timestamp"]) + "::timestamptz, "
            + sql_str(r["user_identifier"]) + ", "
            + sql_str(r["action"]) + ", "
            + sql_str(r["patient_hash"]) + ", "
            + sql_str(data_elements_json) + "::jsonb, "
            + sql_str(r["model_run_id"]) + ", "
            + sql_str("0" * 64) + ", "
            + sql_str("0" * 64)
            + ")"
        )
        payloads.append(
            {
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "user_identifier": r["user_identifier"],
                "action": r["action"],
                "patient_hash": r["patient_hash"],
                "data_elements_jsonb": r["data_elements_jsonb"],
                "model_run_id": r["model_run_id"],
            }
        )
    sql = (
        "TRUNCATE TABLE audit_trail;\n"
        "INSERT INTO audit_trail (event_id, \"timestamp\", user_identifier, action, "
        "patient_hash, data_elements, model_run_id, previous_signature, cryptographic_signature) "
        "VALUES " + ", ".join(values_sql) + ";\n"
    )
    sql_path = Path("/tmp/qa_audit_chain_insert.sql")
    sql_path.write_text(sql)
    proc = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-X", "-q", "-d", DB, "-f", str(sql_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return payloads


def fetch_canonical_rows() -> list[dict]:
    """Read every row back from the DB, including ``data_elements::text``.

    The verifier hashes against this ``::text`` form, so the signer
    must use the same form.  The Postgres JSONB ``::text`` output
    preserves key insertion order; whatever order we wrote the keys
    in, that's what comes back.
    """
    sql = """
    SELECT
        event_id,
        to_char("timestamp" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS ts_iso,
        user_identifier,
        action,
        patient_hash,
        data_elements::text AS data_elements_text,
        model_run_id
    FROM audit_trail
    ORDER BY "timestamp" ASC, event_id ASC
    """
    sql_path = Path("/tmp/qa_audit_chain_select.sql")
    sql_path.write_text(sql)
    proc = subprocess.run(
        [
            "psql",
            "-X",
            "-A",
            "-t",
            "-F",
            "\x1f",
            "-d",
            DB,
            "-f",
            str(sql_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        parts = line.split("\x1f")
        rows.append(
            {
                "event_id": parts[0],
                "timestamp": parts[1],
                "user_identifier": parts[2],
                "action": parts[3],
                "patient_hash": parts[4],
                "data_elements": parts[5],  # JSONB::text
                "model_run_id": parts[6],
            }
        )
    return rows


def write_signatures_no_trigger(canon_rows: list[dict]) -> list[dict]:
    """Drop the mutation guard, sign each row in place, recreate the trigger.

    Returns the chain order rows augmented with their previous and
    cryptographic signatures, suitable for verify_chain().
    """
    # Drop the trigger; signing requires UPDATE which the trigger blocks.
    sql_drop = "DROP TRIGGER IF EXISTS audit_trail_no_mutation ON audit_trail;\n"
    sql_path = Path("/tmp/qa_audit_chain_drop_trigger.sql")
    sql_path.write_text(sql_drop)
    subprocess.run(
        ["psql", "-X", "-q", "-d", DB, "-f", str(sql_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        prev = "0" * 64
        signed: list[dict] = []
        for row in canon_rows:
            sig = compute_signature(prev, row)
            signed.append({**row, "previous_signature": prev, "cryptographic_signature": sig})
            # UPDATE the row in place to thread the chain forward.
            def s(v: str) -> str:
                return "'" + v.replace("'", "''") + "'"
            update_sql = (
                "UPDATE audit_trail SET previous_signature = "
                + s(prev)
                + ", cryptographic_signature = "
                + s(sig)
                + " WHERE event_id = "
                + s(row["event_id"])
                + ";\n"
            )
            sql_path = Path("/tmp/qa_audit_chain_update_one.sql")
            sql_path.write_text(update_sql)
            subprocess.run(
                ["psql", "-X", "-q", "-d", DB, "-f", str(sql_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            prev = sig
        return signed
    finally:
        # Recreate the trigger by re-running the part of audit_trail.sql
        # that defines it.
        trigger_sql = """
        CREATE OR REPLACE FUNCTION audit_trail_block_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.cryptographic_signature IS NULL
               AND NEW.cryptographic_signature IS NOT NULL THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION
                'audit_trail is append-only: % on row id=% with non-null '
                'cryptographic_signature is not permitted (PHIPA / HIA '
                'evidence-of-record)', TG_OP, OLD.id
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS audit_trail_no_mutation ON audit_trail;
        CREATE TRIGGER audit_trail_no_mutation
            BEFORE UPDATE OR DELETE ON audit_trail
            FOR EACH ROW
            EXECUTE FUNCTION audit_trail_block_mutation();
        """
        sql_path = Path("/tmp/qa_audit_chain_recreate_trigger.sql")
        sql_path.write_text(trigger_sql)
        subprocess.run(
            ["psql", "-X", "-q", "-d", DB, "-f", str(sql_path)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    raw = build_rows()
    payloads = insert_raw_rows(raw)
    canon = fetch_canonical_rows()
    if len(canon) != len(payloads):
        print(
            f"FATAL: inserted {len(payloads)} rows but DB has {len(canon)} after fetch",
            file=sys.stderr,
        )
        sys.exit(1)
    signed = write_signatures_no_trigger(canon)
    print(f"Inserted and signed {len(signed)} chained rows in {DB}.")
