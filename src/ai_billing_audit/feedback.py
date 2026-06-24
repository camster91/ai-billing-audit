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

    def biller_corrections(
        self,
        *,
        encounter_id: str | None = None,
        rule_id: str | None = None,
    ) -> list[FeedbackEntry]:
        """Return only the biller-initiated modify entries.

        The feedback log is the union of three actions: ``accept``,
        ``dismiss``, and ``modify``. The ``modify`` rows are
        qualitatively different — they're not "the model was right" or
        "the model was wrong", they're "the biller changed something
        the model got wrong on the *content* level" (override severity
        from ``medium`` to ``low``, re-classify a finding's category,
        etc.). Training a precision-recall curve against this subset
        would mix two different signals.

        This helper is the read-side filter for that subset:

          * ``action == "modify"``
          * excludes the system-tagged ``__rerun__`` rows that
            :func:`encounter_rerun` writes with action="modify" as a
            marker (so the encounter timeline is complete without
            polluting the corrections view).
          * optionally narrowed by ``encounter_id`` and/or ``rule_id``
            for drill-down views.

        Ordering: most-recent first, so the UI can show "what the
        biller changed today" without a sort step.
        """
        out: list[FeedbackEntry] = []
        for e in self.read_all():
            if e.action != "modify":
                continue
            if e.finding_id == "__rerun__":
                continue
            if encounter_id is not None and e.encounter_id != encounter_id:
                continue
            if rule_id is not None and (e.rule_id or "") != rule_id:
                continue
            out.append(e)
        # Newest first. Tiebreak on event_id (a uuid4 hex) so the
        # ordering is deterministic even when two rows share a
        # 1-second-resolution timestamp (the default strftime format).
        out.sort(key=lambda e: (e.timestamp, e.event_id), reverse=True)
        return out

    def corrections_summary(
        self,
        *,
        encounter_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate rollup of :meth:`biller_corrections`.

        Returns a dict the dashboard can render directly as a small
        "Biller corrections" tile:

            {
              "total":            <int>,   # count of modify entries
              "by_rule_id":       {rule_id: count, ...},
              "by_category":      {category: count, ...},
              "severity_changes": <int>,   # rows where the biller
                                            # changed the severity
              "category_changes": <int>,   # rows where the biller
                                            # changed the category
              "encounters_affected": <int>,# distinct encounter_ids
            }

        The ``severity_changes`` and ``category_changes`` counts let a
        downstream trainer ask "how often does the biller correct
        severity vs. category?" — useful for deciding whether the
        auditor's severity scale or its category taxonomy is the
        bigger source of friction.
        """
        rows = self.biller_corrections(encounter_id=encounter_id)
        by_rule: Counter[str] = Counter()
        by_cat: Counter[str] = Counter()
        encs: set[str] = set()
        sev_changes = 0
        cat_changes = 0
        for e in rows:
            by_rule[e.rule_id or "<unknown>"] += 1
            by_cat[e.category or "<unknown>"] += 1
            if e.encounter_id:
                encs.add(e.encounter_id)
            # ``modify_severity`` is set on the row when the biller
            # actually overrode the severity (the API writes
            # ``None`` when the biller only changed the category).
            if e.modify_severity:
                sev_changes += 1
            if e.modify_category:
                cat_changes += 1
        return {
            "total": len(rows),
            "by_rule_id": dict(by_rule),
            "by_category": dict(by_cat),
            "severity_changes": sev_changes,
            "category_changes": cat_changes,
            "encounters_affected": len(encs),
        }

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

    def confidence_for_rule(self, rule_id: str) -> dict[str, Any]:
        """How much real-world signal do we have for ``rule_id``?

        Returns a small dict the encounter-detail template can render
        directly as a "Model confidence" badge:

            {
              "bucket":   "high" | "medium" | "low" | "uncalibrated",
              "label":    "HIGH" | "MEDIUM" | "LOW" | "Not yet calibrated at this clinic",
              "validations": <int>,   # count of 'accept' decisions
              "dismisses":  <int>,   # count of 'dismiss' decisions
              "total":     <int>,   # accept + dismiss + modify
            }

        Bucket thresholds (per the learning-loop spec):

          * HIGH     — more than 10 accept decisions for this rule
          * MEDIUM   — 3 to 10 accept decisions
          * LOW      — fewer than 3 accept decisions (some signal, not enough)
          * uncalibrated — no accept decisions yet at this clinic

        The "validations" axis is the accept count, not the total, because
        a high dismiss rate is a different signal (the model is wrong,
        not "uncertain") and the per-rule precision panel surfaces that
        separately.  If we later want a "trust" KPI that mixes both,
        compose it on top of this primitive.
        """
        accepts = 0
        dismisses = 0
        for e in self.read_all():
            if (e.rule_id or "") != rule_id:
                continue
            if e.action == "accept":
                accepts += 1
            elif e.action == "dismiss":
                dismisses += 1
        total = accepts + dismisses
        if accepts == 0 and total == 0:
            return {
                "bucket": "uncalibrated",
                "label": "Not yet calibrated at this clinic",
                "validations": 0,
                "dismisses": 0,
                "total": 0,
            }
        if accepts > 10:
            bucket = "high"
            label = "HIGH"
        elif accepts >= 3:
            bucket = "medium"
            label = "MEDIUM"
        else:
            bucket = "low"
            label = "LOW"
        return {
            "bucket": bucket,
            "label": label,
            "validations": accepts,
            "dismisses": dismisses,
            "total": total,
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


# ---- Biller-correction (high-quality training signal) -----------------
# A "biller correction" is the structured record a biller writes when
# they MODIFY an AI finding (change the severity, change the category,
# or both) and optionally add a free-text rationale. The feedback
# log captures the same data as a FeedbackEntry, but the
# BillerCorrection view layers on a `why` field (the free-text
# rationale) and a `biller_id` so the learning-loop can group
# "biller was right, model was wrong" examples per-biller for
# calibration.
#
# Stored as a separate JSONL line per correction in
# /app/logs/biller_corrections.jsonl. The feedback log keeps
# continuing to receive a corresponding FeedbackEntry (with action
# "modify") so the existing chain / aggregation layers don't break.
# The two logs are joined on (encounter_id, finding_id) at training
# time.

import dataclasses  # noqa: E402  (import below the singleton on purpose)


_BILLER_CORRECTIONS_LOG = Path(
    os.environ.get("BILLER_CORRECTIONS_LOG", "/app/logs/biller_corrections.jsonl")
)


@dataclass
class BillerCorrection:
    """Structured record of a single biller-initiated correction.

    The fields mirror the spec'd ``biller_corrections`` SQL table
    (id, finding_id, severity, category, rationale, biller_id,
    created_at). The rationale is the free-text "why" the biller
    enters on the form; it is the highest-quality training signal
    the learning loop gets because it explains *why* the AI was
    wrong, not just *that* it was wrong.
    """

    finding_id: str
    severity: str
    category: str
    rationale: str
    biller_id: str
    encounter_id: str
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    previous_signature: str = ""
    cryptographic_signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sign_correction(previous: str, row: dict[str, Any]) -> str:
    """Hash-chained signature for the biller-corrections log.

    Uses the same SHA-256 + previous_signature shape as the main
    feedback log so a privacy officer can verify the two logs
    together. ``previous`` is the previous row's
    ``cryptographic_signature`` (or the genesis constant for the
    first row). The hash includes the rationale so a tampered
    "why" field is detectable.
    """
    payload = (
        previous + "|" +
        str(row.get("id", "")) + "|" +
        str(row.get("encounter_id", "")) + "|" +
        str(row.get("finding_id", "")) + "|" +
        str(row.get("severity", "")) + "|" +
        str(row.get("category", "")) + "|" +
        str(row.get("rationale", "")) + "|" +
        str(row.get("biller_id", "")) + "|" +
        str(row.get("created_at", ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_correction_signature(path: Path) -> str:
    if not path.exists():
        return _GENESIS_SIG
    last_sig = _GENESIS_SIG
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("cryptographic_signature"):
                    last_sig = row["cryptographic_signature"]
    except OSError:
        return _GENESIS_SIG
    return last_sig


def record_biller_correction(
    *,
    encounter_id: str,
    finding_id: str,
    severity: str,
    category: str,
    rationale: str,
    biller_id: str,
) -> BillerCorrection:
    """Persist a single BillerCorrection and return it.

    Best-effort: a write failure does not raise. Mirrors the
    best-effort pattern used elsewhere in feedback.py so a log
    failure cannot crash the API.

    Severity / category are the *corrected* (post-override) values;
    the original values are still recoverable from the matching
    FeedbackEntry (action="modify" with the original severity /
    category fields).
    """
    correction = BillerCorrection(
        finding_id=finding_id,
        severity=severity,
        category=category,
        rationale=rationale,
        biller_id=biller_id,
        encounter_id=encounter_id,
    )
    try:
        _BILLER_CORRECTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        correction.previous_signature = _last_correction_signature(_BILLER_CORRECTIONS_LOG)
        row = correction.to_dict()
        correction.cryptographic_signature = _sign_correction(
            correction.previous_signature, row
        )
        row["cryptographic_signature"] = correction.cryptographic_signature
        with _BILLER_CORRECTIONS_LOG.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return correction


def read_biller_corrections(
    encounter_id: str | None = None,
) -> list[BillerCorrection]:
    """Read all logged biller-corrections, optionally filtered by encounter.

    Returns a list of BillerCorrection in append order (oldest first).
    Skips malformed lines silently. A privacy officer can iterate
    this list and verify the chain with ``verify_correction_chain``.
    """
    if not _BILLER_CORRECTIONS_LOG.exists():
        return []
    out: list[BillerCorrection] = []
    try:
        with _BILLER_CORRECTIONS_LOG.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if encounter_id and row.get("encounter_id") != encounter_id:
                    continue
                try:
                    out.append(BillerCorrection(**{
                        k: v for k, v in row.items()
                        if k in {f.name for f in dataclasses.fields(BillerCorrection)}
                    }))
                except Exception:
                    continue
    except OSError:
        return []
    return out