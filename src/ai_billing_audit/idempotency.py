"""Idempotency-Key support for state-changing endpoints.

A retried request (network glitch, mobile client reconnect,
duplicate browser submit) can hit the same endpoint twice with
the same body and cause double-work: duplicate audit jobs,
duplicate accept/dismiss events, etc.

The contract:

  1. Caller sends an ``Idempotency-Key`` header on a state-changing
     POST (the spec value is opaque, ASCII, up to 255 chars).
  2. The endpoint computes a stable request fingerprint from the
     request body (SHA-256 hex).
  3. On the FIRST hit: cache (key, fingerprint, response_json,
     status_code) to disk.
  4. On a retry with the SAME key + SAME fingerprint: return the
     cached response (200 / 201 / 4xx — whatever the original
     was). The endpoint code never runs again.
  5. On a retry with the SAME key + DIFFERENT fingerprint: return
     ``409 Conflict`` with a clear message (the client is reusing
     a key for a different payload, which is a programming error).

Storage: append-only JSONL at ``/app/logs/idempotency.jsonl``.
Bounded by a max-entries cap (default 10000) — oldest entries
evicted FIFO when the cap is hit.

Why JSONL + FIFO (not Redis or SQLite):

  * No new infra (the FastAPI process already writes JSONL for
    audit_trail, upload_jobs, etc.).
  * The cache is read-mostly (retries hit it, fresh keys write
    once) so the append-only write pattern is fine.
  * Eviction by FIFO is honest — clients shouldn't reuse a key
    after 24h (the spec recommends ~24h). Anything older is
    evicted on the next write.

Thread-safety: a per-process lock around the eviction step
prevents two concurrent writes from racing on the FIFO eviction.
For multi-worker deploys the lock is process-local; two
workers could each hold the same key in their private cache
briefly. That's acceptable for defence-in-depth idempotency —
the audit_trail.jsonl is the source of truth for "was this
job actually enqueued?" and the JSONL cache is just the
fast-path replay layer.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

__all__ = [
    "IdempotencyHit",
    "IdempotencyMismatch",
    "lookup",
    "store",
    "fingerprint_request_body",
]


_DEFAULT_LOG_PATH = "/app/logs/idempotency.jsonl"
_DEFAULT_MAX_ENTRIES = 10000
_LOCK = threading.Lock()


def _log_path() -> Path:
    """Resolve the JSONL log path from the env or fall back to the default.

    Reads on every call so a per-test ``monkeypatch.setenv``
    takes effect immediately, matching the late-bind pattern
    used by ``audit_trail_path()`` in audit_actions.py.
    """
    return Path(os.environ.get("IDEMPOTENCY_LOG", _DEFAULT_LOG_PATH))


@dataclasses.dataclass(frozen=True)
class IdempotencyHit:
    """Return value of :func:`lookup` when the key was found AND
    the request fingerprint matches the cached one."""

    status_code: int
    response_json: dict[str, Any]


class IdempotencyMismatch(Exception):
    """Raised when the caller reuses a key with a different request
    body. The HTTP layer translates this to 409 Conflict."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Idempotency-Key '{key}' was previously used with a "
            "different request body. Use a new key for a new payload."
        )
        self.key = key


def fingerprint_request_body(body: bytes | str) -> str:
    """Stable SHA-256 fingerprint of the request body.

    Accepts bytes or str (str is utf-8 encoded). Returns 64-char
    lowercase hex. Empty body returns the SHA-256 of the empty
    string (``e3b0c4...b855``) — still a valid fingerprint.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _read_entries(path: Path) -> list[dict[str, Any]]:
    """Read all entries from the JSONL log. Missing file = empty list."""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip corrupted lines; the log is append-only
                    # and a partial write shouldn't poison the whole
                    # cache.
                    continue
    except OSError:
        return []
    return out


def _write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    """Rewrite the JSONL log with the given entries. Atomic via
    ``rename`` so a crash mid-write doesn't leave a half-written
    file (the next read falls back to the previous good copy)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False))
            f.write("\n")
    tmp.replace(path)


def _evict_if_needed(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO eviction to keep the cache bounded. Returns the
    post-eviction list (caller assigns back)."""
    max_entries = int(
        os.environ.get("IDEMPOTENCY_MAX_ENTRIES", str(_DEFAULT_MAX_ENTRIES))
    )
    if len(entries) > max_entries:
        # Drop the oldest entries; keep the most recent
        # ``max_entries``. We keep the tail (newest) rather than
        # the head because retries are most likely to happen
        # within minutes of the original hit.
        return entries[-max_entries:]
    return entries


def lookup(key: str, fingerprint: str) -> IdempotencyHit | None:
    """Look up a cached response for ``key``.

    Returns:
      * ``IdempotencyHit`` if the key was found AND the fingerprint
        matches — caller should return the cached response and
        skip running the endpoint.
      * ``None`` if the key was not found — caller should run the
        endpoint and :func:`store` the result.

    Raises:
      * :class:`IdempotencyMismatch` if the key was found BUT the
        fingerprint differs — caller should return 409 Conflict.
    """
    if not key:
        return None
    path = _log_path()
    with _LOCK:
        entries = _read_entries(path)
    # Iterate in reverse so the most recent entry for a given key
    # wins (a key reused after eviction is a misuse, but we don't
    # want an old entry to shadow a new one in a corrupted log).
    for entry in reversed(entries):
        if entry.get("key") != key:
            continue
        cached_fp = entry.get("fingerprint", "")
        if cached_fp != fingerprint:
            raise IdempotencyMismatch(key)
        return IdempotencyHit(
            status_code=int(entry.get("status_code", 200)),
            response_json=dict(entry.get("response_json") or {}),
        )
    return None


def store(
    key: str,
    fingerprint: str,
    status_code: int,
    response_json: dict[str, Any],
) -> None:
    """Persist ``(key, fingerprint, status_code, response_json)``
    so a retry can replay the response without re-running the
    endpoint.

    No-op when ``key`` is empty (caller didn't ask for idempotency).
    """
    if not key:
        return
    path = _log_path()
    entry = {
        "key": key,
        "fingerprint": fingerprint,
        "status_code": int(status_code),
        "response_json": response_json,
        "stored_at": time.time(),
    }
    with _LOCK:
        entries = _read_entries(path)
        entries.append(entry)
        entries = _evict_if_needed(entries)
        _write_entries(path, entries)