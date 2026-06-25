#!/usr/bin/env python3
"""
Kanban decompose helper — creates sub-tasks and parent comments via direct SQL.

Usage:
    python3 scripts/_kanban_decompose_helper.py <board> --decompose <parent_id> \
        --subtask '<title>' --subtask '<title2>' [--link] [--comment '<text>']

For each parent task it:
  - Inserts one or more new sub-tasks into the same board, status='ready'
  - Records parent_id -> child_id in task_links
  - Optionally adds a comment on the parent task describing the decomposition
  - Optionally re-blocks the parent with a sharper reason
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

KANBAN_HOME = Path.home() / ".hermes" / "kanban" / "boards"


def board_db(board: str) -> sqlite3.Connection:
    path = KANBAN_HOME / board / "kanban.db"
    if not path.exists():
        sys.exit(f"board db not found: {path}")
    return sqlite3.connect(path)


def fetch_task(cur: sqlite3.Cursor, task_id: str) -> dict | None:
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def gen_id(prefix: str = "t") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def create_subtask(
    cur: sqlite3.Cursor,
    parent: dict,
    title: str,
    body: str,
    priority: int = 3,
    status: str = "ready",
    workspace_kind: str = "scratch",
) -> str:
    """Insert a new task in the same board, linked to parent."""
    child_id = gen_id()
    now = int(time.time())
    tenant = parent.get("tenant")
    created_by = parent.get("created_by") or "hermes"
    workspace_path = parent.get("workspace_path") or ""
    cur.execute(
        """
        INSERT INTO tasks (
            id, title, body, assignee, status, priority, created_by, created_at,
            workspace_kind, workspace_path, tenant, consecutive_failures
        ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            child_id,
            title,
            body,
            status,
            priority,
            created_by,
            now,
            workspace_kind,
            workspace_path,
            tenant,
        ),
    )
    return child_id


def link_to_parent(
    cur: sqlite3.Cursor, parent_id: str, child_id: str, kind: str = "decomposes"
) -> None:
    cur.execute(
        """
        INSERT OR IGNORE INTO task_links (parent_id, child_id)
        VALUES (?, ?)
        """,
        (parent_id, child_id),
    )


def add_comment(cur: sqlite3.Cursor, task_id: str, body: str, author: str = "hermes") -> None:
    cur.execute(
        """
        INSERT INTO task_comments (task_id, author, body, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (task_id, author, body, int(time.time())),
    )


def reblock(cur: sqlite3.Cursor, task_id: str, reason: str) -> None:
    """Re-affirm blocked status with a sharper reason (no-op if already blocked)."""
    cur.execute(
        "UPDATE tasks SET status='blocked', body = body || ? WHERE id = ? AND status='blocked'",
        (
            f"\n\n---\n[re-blocked 2026-06-25] {reason}",
            task_id,
        ),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("board")
    p.add_argument("--decompose", action="append", help="parent id (repeatable)")
    p.add_argument("--subtask", action="append", default=[], help="sub-task title (repeatable)")
    p.add_argument("--body", action="append", default=[], help="sub-task body (matches subtask order)")
    p.add_argument("--priority", type=int, default=3)
    p.add_argument("--from-json", help="path to JSON list of {parent, title, body, priority, status}")
    p.add_argument("--board-default", help="when using --from-json, board name")
    p.add_argument("--status", default="ready", choices=["ready", "blocked", "todo"])
    p.add_argument("--comment", help="parent comment describing decomposition")
    p.add_argument("--reblock-reason", help="sharper reason to append to parent body")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.from_json:
        import json as _json
        items = _json.loads(Path(args.from_json).read_text())
        args.board = args.board_default or args.board
        ops: list[tuple[str, str, str, int, str]] = []
        for it in items:
            ops.append(
                (
                    it["parent"],
                    it["title"],
                    it.get("body", ""),
                    it.get("priority", args.priority),
                    it.get("status", args.status),
                )
            )
    else:
        if not args.decompose:
            sys.exit("--decompose required when not using --from-json")
        if len(args.subtask) != len(args.decompose):
            sys.exit(f"--subtask count {len(args.subtask)} != --decompose count {len(args.decompose)}")
        ops = [
            (pid, t, b or f"Decomposed from {pid}", args.priority, args.status)
            for pid, t, b in zip(args.decompose, args.subtask, args.body)
        ]

    conn = board_db(args.board)
    cur = conn.cursor()

    for parent_id, title, body, priority, status in ops:
        parent = fetch_task(cur, parent_id)
        if parent is None:
            print(f"SKIP: {parent_id} not found", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"[dry] {args.board} {parent_id} -> sub: {title}")
            continue
        child_id = create_subtask(cur, parent, title, body, priority=priority, status=status)
        link_to_parent(cur, parent_id, child_id, "decomposes")
        print(f"{args.board}\t{parent_id}\t->\t{child_id}\t{title}")

    if not args.dry_run and ops:
        if args.comment:
            for parent_id, *_ in ops:
                add_comment(cur, parent_id, args.comment)
        if args.reblock_reason:
            for parent_id, *_ in ops:
                reblock(cur, parent_id, args.reblock_reason)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()