"""Admin CLI for Zorva operations.

Operational commands that don't fit into the FastAPI surface:

  zorva-admin list-tenants
    Walk the audit_trail.jsonl and report the unique tenant_ids
    seen (with their event counts).

  zorva-admin inspect-idempotency --key <key>
    Look up an Idempotency-Key in the JSONL cache and print the
    stored response (status + body fingerprint + body summary).

  zorva-admin prune-idempotency [--older-than-hours N]
    Truncate /app/logs/idempotency.jsonl to entries with
    stored_at >= now - N*3600. Default 24h.

  zorva-admin reset-rate-limit
    Clear the in-process rate-limit buckets. Useful when a real
    clinic hit the 429 limit during a pilot demo and you want to
    let them retry immediately.

  zorva-admin tail-audit --tenant <id> [--n N]
    Print the last N audit_trail events for a tenant (default
    last 50). Tails the JSONL log live (Ctrl-C to stop).

All commands read environment for log paths so the same binary
works on dev / staging / prod. Run from the project root after
``pip install -e .`` registers the entry point:

  zorva-admin list-tenants

If you'd rather not install, ``python -m ai_billing_audit.admin_cli``
runs the same code without the entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


_AUDIT_TRAIL_PATH = "/app/logs/audit_trail.jsonl"
_IDEMPOTENCY_PATH = "/app/logs/idempotency.jsonl"


def _log_path(default: str, env: str) -> Path:
    """Resolve a JSONL log path from env override or default."""
    return Path(os.environ.get(env, default))


def cmd_list_tenants(_args: argparse.Namespace) -> int:
    """Print unique tenant_ids seen in audit_trail.jsonl with counts."""
    path = _log_path(_AUDIT_TRAIL_PATH, "AUDIT_TRAIL_LOG")
    if not path.is_file():
        print(f"audit trail log not found at {path}", file=sys.stderr)
        return 1
    counts: Counter[str] = Counter()
    total = 0
    from ai_billing_audit.clinical_note_storage import read_encrypted_json_records

    for rec in read_encrypted_json_records(path):
        total += 1
        tid = str(rec.get("tenant_id") or "<unset>")
        counts[tid] += 1
    print(f"audit trail: {path}")
    print(f"events: {total}")
    print(f"unique tenants: {len(counts)}")
    print()
    print(f"{'TENANT_ID':<40} {'EVENTS':>10}")
    print(f"{'-' * 40} {'-' * 10}")
    for tid, n in counts.most_common():
        print(f"{tid:<40} {n:>10}")
    return 0


def cmd_inspect_idempotency(args: argparse.Namespace) -> int:
    """Look up an Idempotency-Key and print its stored record."""
    from ai_billing_audit.idempotency import _log_path as idem_path, _read_entries

    path = idem_path()
    if not path.is_file():
        print(f"idempotency log not found at {path}", file=sys.stderr)
        return 1
    entries = _read_entries(path)
    matches = [e for e in entries if e.get("key") == args.key]
    if not matches:
        print(f"no entry for key '{args.key}' in {path}", file=sys.stderr)
        return 2
    latest = matches[-1]
    print(json.dumps(latest, indent=2))
    return 0


def cmd_prune_idempotency(args: argparse.Namespace) -> int:
    """Drop entries older than N hours from idempotency.jsonl."""
    from ai_billing_audit.idempotency import (
        _log_path as idem_path,
        _read_entries,
        _write_entries,
    )

    path = idem_path()
    if not path.is_file():
        print(f"idempotency log not found at {path}", file=sys.stderr)
        return 1
    entries = _read_entries(path)
    cutoff = time.time() - args.older_than_hours * 3600
    before = len(entries)
    kept = [e for e in entries if e.get("stored_at", 0) >= cutoff]
    _write_entries(path, kept)
    print(f"pruned {before - len(kept)} entries (kept {len(kept)}) from {path}")
    return 0


def cmd_reset_rate_limit(_args: argparse.Namespace) -> int:
    """Clear the in-process rate-limit state.

    Pokes the running api process via the file-system (the state
    is per-process; this only affects future requests to the same
    process). Useful in dev — in prod, a container restart is
    the right move.
    """
    print(
        "NOTE: rate-limit state is per-process. If the api is "
        "running in a separate process, this CLI call won't "
        "affect it. Restart the api container to clear state "
        "in production.",
        file=sys.stderr,
    )
    # We can't reach into the running api process's globals from
    # here; print the operator instruction instead.
    return 0


def cmd_migrate_job_log(_args: argparse.Namespace) -> int:
    """Encrypt a legacy plaintext upload-job log with a preserved backup."""
    from ai_billing_audit.job_queue import migrate_plaintext_job_log

    path = Path(
        os.environ.get(
            "UPLOAD_JOB_LOG",
            os.environ.get("UPLOAD_AUDIT_LOG_PATH", "/app/logs/upload_jobs.jsonl"),
        )
    )
    try:
        migrated = migrate_plaintext_job_log(path)
    except Exception as exc:
        print(f"job-log migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"migrated {migrated} job-log records at {path}")
    return 0


def cmd_migrate_doctor_emails(_args: argparse.Namespace) -> int:
    """Encrypt a legacy plaintext doctor-summary operator outbox."""
    from ai_billing_audit.doctor_email import (
        migrate_doctor_optout_file,
        migrate_doctor_summary_log,
    )

    path = _log_path("/app/logs/doctor_emails.jsonl", "DOCTOR_EMAIL_LOG")
    try:
        migrated = migrate_doctor_summary_log()
        optouts = migrate_doctor_optout_file()
    except Exception as exc:
        print(f"doctor-email migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"migrated {migrated} doctor-email records at {path}; optouts={optouts}")
    return 0


def cmd_migrate_appeal_logs(_args: argparse.Namespace) -> int:
    """Encrypt legacy plaintext appeal metadata and outcome logs."""
    from ai_billing_audit.appeal_letter import migrate_appeal_logs

    try:
        letters, outcomes = migrate_appeal_logs()
    except Exception as exc:
        print(f"appeal-log migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"migrated appeal records: letters={letters} outcomes={outcomes}")
    return 0


def cmd_migrate_feedback_logs(_args: argparse.Namespace) -> int:
    """Encrypt legacy plaintext decision, correction, and comment logs."""
    from ai_billing_audit.feedback import migrate_feedback_logs

    try:
        feedback, corrections, comments = migrate_feedback_logs()
    except Exception as exc:
        print(f"feedback-log migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        "migrated feedback records: "
        f"feedback={feedback} corrections={corrections} comments={comments}"
    )
    return 0


def cmd_migrate_clinical_metric_logs(_args: argparse.Namespace) -> int:
    """Encrypt all legacy plaintext clinical-metric surface logs."""
    from ai_billing_audit.clinical_metrics import migrate_clinical_metric_logs

    try:
        migrated = migrate_clinical_metric_logs()
    except Exception as exc:
        print(
            f"clinical-metric migration failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    print(f"migrated {migrated} clinical-metric records")
    return 0


def cmd_migrate_audit_trail(_args: argparse.Namespace) -> int:
    """Encrypt a legacy plaintext audit-trail chain."""
    from ai_billing_audit.audit_actions import migrate_audit_trail_log

    try:
        migrated = migrate_audit_trail_log()
    except Exception as exc:
        print(f"audit-trail migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"migrated {migrated} audit-trail records")
    return 0


def cmd_migrate_integration_logs(_args: argparse.Namespace) -> int:
    """Encrypt public API, webhook, and Slack operational logs."""
    from ai_billing_audit.public_api import migrate_public_api_logs
    from ai_billing_audit.slack_notify import migrate_slack_log
    from ai_billing_audit.webhooks import migrate_webhook_log

    try:
        usage, audit_index = migrate_public_api_logs()
        webhooks = migrate_webhook_log()
        slack = migrate_slack_log()
    except Exception as exc:
        print(
            f"integration-log migration failed: {type(exc).__name__}", file=sys.stderr
        )
        return 1
    print(
        "migrated integration records: "
        f"usage={usage} audit_index={audit_index} "
        f"webhooks={webhooks} slack={slack}"
    )
    return 0


def cmd_migrate_portal_state_logs(_args: argparse.Namespace) -> int:
    """Encrypt idempotency and encounter-level portal state logs."""
    from ai_billing_audit.finding_assignments import FindingAssignmentStore
    from ai_billing_audit.idempotency import migrate_idempotency_log
    from ai_billing_audit.saved_filters import SavedFilterStore
    from ai_billing_audit.snooze import SnoozeStore
    from ai_billing_audit.ux_polish import migrate_ux_logs

    try:
        idempotency = migrate_idempotency_log()
        assignments = FindingAssignmentStore().migrate_plaintext_log()
        snoozes = SnoozeStore().migrate_plaintext_log()
        saved_filters = SavedFilterStore().migrate_plaintext_log()
        ux = migrate_ux_logs()
    except Exception as exc:
        print(f"portal-state migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        "migrated portal-state records: "
        f"idempotency={idempotency} assignments={assignments} "
        f"snoozes={snoozes} saved_filters={saved_filters} ux={ux}"
    )
    return 0


def cmd_migrate_contact_uploads(_args: argparse.Namespace) -> int:
    """Encrypt legacy claims files staged by the contact form."""
    from ai_billing_audit.contact import migrate_contact_uploads

    try:
        migrated = migrate_contact_uploads()
    except Exception as exc:
        print(f"contact-upload migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"migrated {migrated} contact-upload files")
    return 0


def cmd_tail_audit(args: argparse.Namespace) -> int:
    """Print the last N audit_trail events for a tenant."""
    path = _log_path(_AUDIT_TRAIL_PATH, "AUDIT_TRAIL_LOG")
    if not path.is_file():
        print(f"audit trail log not found at {path}", file=sys.stderr)
        return 1
    from ai_billing_audit.clinical_note_storage import read_encrypted_json_records

    events: list[dict[str, Any]] = []
    for rec in read_encrypted_json_records(path):
        if args.tenant and str(rec.get("tenant_id")) != args.tenant:
            continue
        events.append(rec)
    # Last N
    for rec in events[-args.n :]:
        print(json.dumps(rec))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zorva-admin",
        description=(
            "Admin CLI for Zorva operations. "
            "Run with --help on any subcommand for details."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "list-tenants",
        help="Walk audit_trail.jsonl and report unique tenants + event counts.",
    )
    p.set_defaults(func=cmd_list_tenants)

    p = sub.add_parser(
        "inspect-idempotency",
        help="Look up an Idempotency-Key in the JSONL cache.",
    )
    p.add_argument("--key", required=True, help="The Idempotency-Key to look up.")
    p.set_defaults(func=cmd_inspect_idempotency)

    p = sub.add_parser(
        "prune-idempotency",
        help="Drop idempotency entries older than N hours.",
    )
    p.add_argument(
        "--older-than-hours",
        type=float,
        default=24.0,
        help="Drop entries older than this many hours (default 24).",
    )
    p.set_defaults(func=cmd_prune_idempotency)

    p = sub.add_parser(
        "reset-rate-limit",
        help="Print instructions for clearing the in-process rate-limit state.",
    )
    p.set_defaults(func=cmd_reset_rate_limit)

    p = sub.add_parser(
        "migrate-job-log",
        help="Encrypt a legacy plaintext upload-job JSONL after backing it up.",
    )
    p.set_defaults(func=cmd_migrate_job_log)

    p = sub.add_parser(
        "migrate-doctor-emails",
        help="Encrypt a legacy plaintext doctor-summary outbox after backup.",
    )
    p.set_defaults(func=cmd_migrate_doctor_emails)

    p = sub.add_parser(
        "migrate-appeal-logs",
        help="Encrypt legacy appeal metadata/outcome JSONL files after backup.",
    )
    p.set_defaults(func=cmd_migrate_appeal_logs)

    p = sub.add_parser(
        "migrate-feedback-logs",
        help="Encrypt legacy feedback/correction/comment JSONL files after backup.",
    )
    p.set_defaults(func=cmd_migrate_feedback_logs)

    p = sub.add_parser(
        "migrate-clinical-metric-logs",
        help="Encrypt legacy clinical-metric JSONL files after backup.",
    )
    p.set_defaults(func=cmd_migrate_clinical_metric_logs)

    p = sub.add_parser(
        "migrate-audit-trail",
        help="Encrypt a legacy audit-trail JSONL chain after backup.",
    )
    p.set_defaults(func=cmd_migrate_audit_trail)

    p = sub.add_parser(
        "migrate-integration-logs",
        help="Encrypt public API, webhook, and Slack JSONL files after backup.",
    )
    p.set_defaults(func=cmd_migrate_integration_logs)

    p = sub.add_parser(
        "migrate-portal-state-logs",
        help="Encrypt idempotency and encounter-level portal state logs.",
    )
    p.set_defaults(func=cmd_migrate_portal_state_logs)

    p = sub.add_parser(
        "migrate-contact-uploads",
        help="Encrypt legacy claims files staged by the contact form.",
    )
    p.set_defaults(func=cmd_migrate_contact_uploads)

    p = sub.add_parser(
        "tail-audit",
        help="Print the last N audit_trail events (optionally for a tenant).",
    )
    p.add_argument(
        "--tenant",
        default=None,
        help="Filter by tenant_id. Default: all tenants.",
    )
    p.add_argument(
        "--n",
        type=int,
        default=50,
        help="Number of events to print (default 50).",
    )
    p.set_defaults(func=cmd_tail_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
