"""Per-encounter feedback log for biller accept/dismiss/modify decisions.

This is the "training data" layer of the learning loop. Every biller
accept / dismiss / modify decision on a finding is appended as a
``FeedbackEntry`` so downstream prompts / MIPRO iterations can group
and replay them. Each row is SHA-256-chained (same shape as
``audit_actions``) so the log is tamper-evident — see
``FeedbackStore.verify_chain()``. JSONL storage at
``/app/logs/feedback.jsonl`` (overridable via ``FEEDBACK_LOG``). Column
shape mirrors the spec'd ``biller_feedback`` SQL table.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Action = Literal["accept", "dismiss", "modify"]

_LOG_PATH = Path(os.environ.get("FEEDBACK_LOG", "/app/logs/feedback.jsonl"))
_GENESIS_SIG = "0" * 64

# Fields included in the chain hash. Order matters.
_CHAIN_FIELDS = (
    "event_id", "timestamp", "encounter_id", "finding_id", "action",
    "biller_id", "rule_id", "category", "severity",
)


@dataclass
class FeedbackEntry:
    """One biller decision on one finding. ``action`` is accept|dismiss|modify."""
    encounter_id: str
    finding_id: str
    action: Action
    severity: str
    rule_id: str
    category: str
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    biller_id: str = "default_biller"
    modify_severity: str | None = None
    modify_category: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    previous_signature: str = ""
    cryptographic_signature: str = ""

    def __post_init__(self) -> None:
        if self.action not in ("accept", "dismiss", "modify"):
            raise ValueError(
                f"action must be accept|dismiss|modify, got {self.action!r}"
            )


class FeedbackStore:
    """Append-only JSONL store with SHA-256 chain."""
    def __init__(self, log_path: Path | str | None = None) -> None:
        self._path = Path(log_path) if log_path is not None else _LOG_PATH

    def append(self, entry: FeedbackEntry) -> FeedbackEntry:
        """Append ``entry``, signing it into the chain. Returns the entry."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not entry.previous_signature:
            entry.previous_signature = self._last_signature()
        if not entry.cryptographic_signature:
            row_dict = asdict(entry)
            entry.cryptographic_signature = _sign(entry.previous_signature, row_dict)
        with self._path.open("a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def read_for_encounter(self, encounter_id: str) -> list[FeedbackEntry]:
        return [e for e in self.read_all() if e.encounter_id == encounter_id]

    def read_all(self) -> list[FeedbackEntry]:
        if not self._path.is_file():
            return []
        out: list[FeedbackEntry] = []
        with self._path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(_row_to_entry(json.loads(line)))
                except (json.JSONDecodeError, ValueError):
                    continue
        return out

    def stats(self) -> dict[str, Any]:
        """Counts by action, rule_id, category, biller_id."""
        by_action: Counter[str] = Counter()
        by_rule: Counter[str] = Counter()
        by_cat: Counter[str] = Counter()
        by_biller: Counter[str] = Counter()
        for e in self.read_all():
            by_action[e.action] += 1
            by_rule[e.rule_id or "<unknown>"] += 1
            by_cat[e.category or "<unknown>"] += 1
            by_biller[e.biller_id or "<unknown>"] += 1
        return {
            "total": sum(by_action.values()),
            "by_action": dict(by_action),
            "by_rule_id": dict(by_rule),
            "by_category": dict(by_cat),
            "by_biller_id": dict(by_biller),
        }

    def verify_chain(self) -> bool:
        """True iff every row's signature matches and links to the prior row."""
        if not self._path.is_file():
            return True
        prev = _GENESIS_SIG
        with self._path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    return False
                if row.get("previous_signature") != prev:
                    return False
                expected = _sign(row.get("previous_signature", prev), row)
                if row.get("cryptographic_signature") != expected:
                    return False
                prev = row.get("cryptographic_signature", prev)
        return True

    def _last_signature(self) -> str:
        if not self._path.is_file():
            return _GENESIS_SIG
        last = _GENESIS_SIG
        try:
            with self._path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "cryptographic_signature" in rec:
                        last = rec["cryptographic_signature"]
        except OSError:
            return _GENESIS_SIG
        return last


def compute_signature(previous_signature: str, row: dict[str, Any]) -> str:
    """SHA-256(previous_sig || chain_fields) — same shape as audit_actions."""
    h = hashlib.sha256()
    h.update(previous_signature.encode("utf-8"))
    for name in _CHAIN_FIELDS:
        v = row.get(name, "")
        if isinstance(v, (dict, list)):
            v = json.dumps(v, sort_keys=True, separators=(",", ":"))
        elif v is None:
            v = ""
        h.update(b"|")
        h.update(str(v).encode("utf-8"))
    return h.hexdigest()


# Internal alias so FeedbackStore.append doesn't repeat the body.
_sign = compute_signature


def _row_to_entry(row: dict[str, Any]) -> FeedbackEntry:
    return FeedbackEntry(
        encounter_id=row.get("encounter_id", ""),
        finding_id=row.get("finding_id", ""),
        action=row.get("action", "accept"),
        severity=row.get("severity", ""),
        rule_id=row.get("rule_id", ""),
        category=row.get("category", ""),
        timestamp=row.get("timestamp", ""),
        biller_id=row.get("biller_id", "default_biller"),
        modify_severity=row.get("modify_severity"),
        modify_category=row.get("modify_category"),
        event_id=row.get("event_id", uuid.uuid4().hex),
        previous_signature=row.get("previous_signature", ""),
        cryptographic_signature=row.get("cryptographic_signature", ""),
    )


# Lazy module-level singleton for the API. Tests build their own store.
_default: FeedbackStore | None = None


def get_default_store() -> FeedbackStore:
    global _default
    if _default is None:
        _default = FeedbackStore()
    return _default