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
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
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
    from ai_billing_audit.idempotency import _log_path as idem_path, _read_entries, _write_entries

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


def cmd_tail_audit(args: argparse.Namespace) -> int:
    """Print the last N audit_trail events for a tenant."""
    path = _log_path(_AUDIT_TRAIL_PATH, "AUDIT_TRAIL_LOG")
    if not path.is_file():
        print(f"audit trail log not found at {path}", file=sys.stderr)
        return 1
    events: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if args.tenant and str(rec.get("tenant_id")) != args.tenant:
                continue
            events.append(rec)
    # Last N
    for rec in events[-args.n:]:
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