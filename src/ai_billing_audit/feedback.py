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

from .clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
)

Action = Literal["accept", "dismiss", "modify", "comment"]


def feedback_log_path() -> Path:
    """Return the feedback JSONL path (read on every call).

    Resolution order:
    1. ``FEEDBACK_LOG`` env var (set by ``tests/conftest.py`` for
       cross-session consistency, and per-test via
       ``monkeypatch.setenv`` in test fixtures).
    2. Production default ``/app/logs/feedback.jsonl``.

    No module-level cache: each call resolves afresh so test
    fixtures that set ``FEEDBACK_LOG`` after import (the standard
    pattern) take effect immediately. A module-level ``_LOG_PATH``
    attribute would shadow the env var and break the per-test
    tmp path; the conftest's pre-setdefault value at import
    time would persist across the whole test session and
    pollute ``tests/test_clinical_metrics.py`` that expects
    ``os.environ["FEEDBACK_LOG"]`` (not ``_LOG_PATH``) to be
    authoritative for ``feedback_log_path()`` calls.
    """
    return Path(os.environ.get("FEEDBACK_LOG", "/app/logs/feedback.jsonl"))


_GENESIS_SIG = "0" * 64

# Process-local cache of ``FeedbackStore._last_signature()`` results.
# Keyed by ``(str(path), mtime)`` so a rewrite of the file (e.g.
# by a test or by another process) invalidates the cache.
_FEEDBACK_LAST_SIG_CACHE: dict[tuple[str, float], str] = {}

# Fields included in the chain hash. Order matters.
_CHAIN_FIELDS = (
    "event_id",
    "timestamp",
    "encounter_id",
    "finding_id",
    "action",
    "biller_id",
    "rule_id",
    "category",
    "severity",
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
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    biller_id: str = "default_biller"
    modify_severity: str | None = None
    modify_category: str | None = None
    # Optional "what should this have been" label supplied when a
    # biller dismisses a finding (and labels what the right finding
    # would have been). Mirrors the spec'd ``correct_finding`` field
    # on the dismiss endpoint. Stored as a free-form dict so the
    # biller can label a corrected severity, category, suggested
    # code, or any combination. Persists to the FeedbackStore
    # without breaking the hash chain (added to the row but NOT
    # to the signed payload — see ``compute_signature``).
    correct_finding: dict[str, Any] | None = None
    note: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    previous_signature: str = ""
    cryptographic_signature: str = ""

    def __post_init__(self) -> None:
        if self.action not in ("accept", "dismiss", "modify", "comment"):
            raise ValueError(
                f"action must be accept|dismiss|modify|comment, got {self.action!r}"
            )


class FeedbackStore:
    """Append-only JSONL store with SHA-256 chain."""

    def __init__(self, log_path: Path | str | None = None) -> None:
        self._path = Path(log_path) if log_path is not None else feedback_log_path()

    def append(self, entry: FeedbackEntry) -> FeedbackEntry:
        """Append ``entry``, signing it into the chain. Returns the entry."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not entry.previous_signature:
            entry.previous_signature = self._last_signature()
        if not entry.cryptographic_signature:
            row_dict = asdict(entry)
            entry.cryptographic_signature = _sign(entry.previous_signature, row_dict)
        append_encrypted_json_record(self._path, asdict(entry))
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

    def correct_finding_pairs(self) -> list[dict[str, Any]]:
        """Return training pairs for dismissals that carry a ``correct_finding``.

        Each row of the return is::

            {
              "encounter_id":    <str>,
              "finding_id":      <str>,
              "original":        {severity, rule_id, category, ...}  # from
                                                                  # FeedbackEntry
              "correct_finding": {severity?, category?, suggested_code?, ...}
                              # what the biller says it should have been
              "biller_id":       <str>,
              "dismissed_at":    <iso timestamp>,
            }

        Skips dismissals without a ``correct_finding`` label (those are
        the existing flow — unchanged). The result is the data the
        training pipeline reads as the new "dismiss+correct" class
        (a dismissed finding paired with the biller-supplied correct
        label). Trainers can join ``original`` to the audit trail /
        original prediction via ``(encounter_id, finding_id)``.

        Order: most-recent first, deterministic on event_id tiebreak.
        """
        out: list[dict[str, Any]] = []
        for e in self.read_all():
            if e.action != "dismiss":
                continue
            if not e.correct_finding:
                continue
            out.append(
                {
                    "encounter_id": e.encounter_id,
                    "finding_id": e.finding_id,
                    "original": {
                        "severity": e.severity,
                        "rule_id": e.rule_id,
                        "category": e.category,
                    },
                    "correct_finding": dict(e.correct_finding),
                    "biller_id": e.biller_id,
                    "dismissed_at": e.timestamp,
                }
            )
        out.sort(
            key=lambda r: (
                r["dismissed_at"],
                r["encounter_id"] + ":" + r["finding_id"],
            ),
            reverse=True,
        )
        return out

    def read_all(self) -> list[FeedbackEntry]:
        if not self._path.is_file():
            return []
        return [_row_to_entry(row) for row in read_encrypted_json_records(self._path)]

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

    def confidence_for_rule(
        self,
        rule_id: str,
        *,
        _entries: list[FeedbackEntry] | None = None,
    ) -> dict[str, Any]:
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

        Pass ``_entries`` to avoid re-reading the JSONL when attaching
        confidence to many findings on one page (N+1 fix).
        """
        accepts = 0
        dismisses = 0
        for e in _entries if _entries is not None else self.read_all():
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
        for row in read_encrypted_json_records(self._path):
            if row.get("previous_signature") != prev:
                return False
            expected = _sign(row.get("previous_signature", prev), row)
            if row.get("cryptographic_signature") != expected:
                return False
            prev = row.get("cryptographic_signature", prev)
        return True

    def _last_signature(self) -> str:
        # swarm-audit H-Perf-1: this used to walk the whole
        # feedback log on every FeedbackStore.append() (every
        # accept / dismiss / modify). With 10k+ rows that's a
        # full read + JSON parse per click. Now caches by file
        # path + mtime — a no-op fast path on the hot path. The
        # cache key includes the path so a different FeedbackStore
        # pointing at a different log doesn't see stale data.
        cache_key = (
            str(self._path),
            self._path.stat().st_mtime if self._path.is_file() else 0.0,
        )
        cached = _FEEDBACK_LAST_SIG_CACHE.get(cache_key)
        if cached is not None:
            return cached
        if not self._path.is_file():
            last = _GENESIS_SIG
        else:
            last = _GENESIS_SIG
            for rec in read_encrypted_json_records(self._path):
                if "cryptographic_signature" in rec:
                    last = rec["cryptographic_signature"]
        _FEEDBACK_LAST_SIG_CACHE[cache_key] = last
        return last

    def migrate_plaintext_log(self) -> int:
        """Encrypt this store's legacy plaintext JSONL in place."""
        return migrate_plaintext_jsonl(self._path)


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
        correct_finding=row.get("correct_finding"),
        note=row.get("note"),
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
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
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
        previous
        + "|"
        + str(row.get("id", ""))
        + "|"
        + str(row.get("encounter_id", ""))
        + "|"
        + str(row.get("finding_id", ""))
        + "|"
        + str(row.get("severity", ""))
        + "|"
        + str(row.get("category", ""))
        + "|"
        + str(row.get("rationale", ""))
        + "|"
        + str(row.get("biller_id", ""))
        + "|"
        + str(row.get("created_at", ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_correction_signature(path: Path) -> str:
    if not path.exists():
        return _GENESIS_SIG
    last_sig = _GENESIS_SIG
    for row in read_encrypted_json_records(path):
        if row.get("cryptographic_signature"):
            last_sig = row["cryptographic_signature"]
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
        correction.previous_signature = _last_correction_signature(
            _BILLER_CORRECTIONS_LOG
        )
        row = correction.to_dict()
        correction.cryptographic_signature = _sign_correction(
            correction.previous_signature, row
        )
        row["cryptographic_signature"] = correction.cryptographic_signature
        append_encrypted_json_record(_BILLER_CORRECTIONS_LOG, row)
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
    for row in read_encrypted_json_records(_BILLER_CORRECTIONS_LOG):
        if encounter_id and row.get("encounter_id") != encounter_id:
            continue
        try:
            out.append(
                BillerCorrection(
                    **{
                        k: v
                        for k, v in row.items()
                        if k in {f.name for f in dataclasses.fields(BillerCorrection)}
                    }
                )
            )
        except Exception:
            continue
    return out


# ---- Per-finding comment thread ---------------------------------------
# A "comment" is a biller's free-form note attached to a finding:
# "why is this flagged?", "I disagree — the appeal basis is…", or just
# a follow-up to another biller. Comments are also the cheapest
# training signal we collect (anything a biller says about a finding
# is data), so every comment is ALSO written to the feedback log as a
# ``FeedbackEntry(action="comment")`` — the per_clinic_f1 rollup and
# the audit_actions chain treat the two writes as one event.
#
# Comments never expire: they live with the finding forever. Storage
# is a separate JSONL at /app/logs/finding_comments.jsonl so the
# thread can be read independently from the feedback log and the
# comment body is not constrained by the FeedbackEntry schema (which
# was designed for the accept/dismiss/modify triad).
_COMMENTS_LOG = Path(
    os.environ.get("FINDING_COMMENTS_LOG", "/app/logs/finding_comments.jsonl")
)


@dataclass
class Comment:
    """One biller-authored note attached to a finding.

    Threads are 1-level deep: ``parent_comment_id`` is set on a
    reply and is None on a top-level comment. Deeper nesting is
    accepted by the store (so a future UI can choose to render it)
    but the spec says the dashboard UI only renders 2 levels.
    """

    comment_id: str
    encounter_id: str
    finding_id: str
    author_id: str
    body: str
    created_at: str
    parent_comment_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_comment(row: dict[str, Any]) -> Comment:
    """Re-hydrate a Comment from a stored JSONL row, tolerating extra fields."""
    valid = {f.name for f in dataclasses.fields(Comment)}
    return Comment(**{k: v for k, v in row.items() if k in valid})


class CommentStore:
    """Append-only JSONL store for per-finding comment threads.

    The FeedbackStore methods :meth:`add_comment` and
    :meth:`list_comments` are the integration point — they create a
    CommentStore on demand so callers don't have to manage two
    separate log files. Most tests and the API should go through
    FeedbackStore; CommentStore is here for the case where a test
    needs an isolated comment log.
    """

    def __init__(self, log_path: Path | str | None = None) -> None:
        self._path = Path(log_path) if log_path is not None else _COMMENTS_LOG

    def add(
        self,
        *,
        encounter_id: str,
        finding_id: str,
        author_id: str,
        body: str,
        parent_comment_id: str | None = None,
    ) -> Comment:
        """Append one comment and return it.

        ``comment_id`` is a fresh uuid4 hex so two replies posted in
        the same second still get distinct IDs. ``created_at`` is
        ISO 8601 UTC at second granularity (matches FeedbackEntry
        for sort stability across the two logs).
        """
        if not encounter_id or not finding_id:
            raise ValueError("encounter_id and finding_id required")
        if not body or not body.strip():
            raise ValueError("comment body required")
        c = Comment(
            comment_id=uuid.uuid4().hex,
            encounter_id=str(encounter_id),
            finding_id=str(finding_id),
            author_id=str(author_id or "default_biller"),
            body=str(body),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            parent_comment_id=str(parent_comment_id) if parent_comment_id else None,
        )
        append_encrypted_json_record(self._path, c.to_dict())
        return c

    def list_for_finding(
        self,
        encounter_id: str,
        finding_id: str,
    ) -> list[Comment]:
        """Return the thread for one finding, oldest first.

        Skips malformed lines and rows that don't match
        ``(encounter_id, finding_id)``. Order: ``created_at`` ascending
        so the UI can render the thread in chronological order
        without an extra sort. Ties on ``created_at`` break on the
        file's append order (a monotonic counter) so two comments
        posted in the same second still come back in the order
        they were added — a uuid4 hex tiebreak would be random.

        Named ``list_for_finding`` (not ``list``) to avoid shadowing
        the builtin ``list`` inside the class body — mypy interprets
        ``list[Comment]`` in a class that defines ``list`` as
        ``(self.list)[Comment]``, which is not a valid type.
        """
        if not self._path.is_file():
            return []
        out: list[tuple[int, Comment]] = []
        for idx, row in enumerate(read_encrypted_json_records(self._path)):
            if row.get("encounter_id") != encounter_id:
                continue
            if row.get("finding_id") != finding_id:
                continue
            try:
                out.append((idx, _row_to_comment(row)))
            except Exception:
                continue
        out.sort(key=lambda ic: (ic[1].created_at, ic[0]))
        return [c for _i, c in out]

    def read_all(self) -> list[Comment]:
        """Return every comment in append order (oldest first).

        Used by tests; not called by the API (the API only lists
        one finding's thread at a time).
        """
        if not self._path.is_file():
            return []
        out: list[Comment] = []
        for row in read_encrypted_json_records(self._path):
            try:
                out.append(_row_to_comment(row))
            except Exception:
                continue
        return out

    def migrate_plaintext_log(self) -> int:
        """Encrypt this comment store's legacy plaintext JSONL in place."""
        return migrate_plaintext_jsonl(self._path)


# Wire comments through the FeedbackStore so callers only have to
# manage one object. The feedback log keeps accepting the
# ``FeedbackEntry`` (action="comment") variant unchanged; the
# dedicated comments log is the source of truth for the body /
# threading / ordered read path.
_feedback_comment_stores: dict[str, CommentStore] = {}


def _get_comment_store(log_path: Path | str | None = None) -> CommentStore:
    """Return a CommentStore for the given log path (cached)."""
    key = str(log_path) if log_path is not None else "__default__"
    if key not in _feedback_comment_stores:
        _feedback_comment_stores[key] = CommentStore(log_path)
    return _feedback_comment_stores[key]


def add_comment(
    store: FeedbackStore,
    *,
    encounter_id: str,
    finding_id: str,
    author_id: str,
    body: str,
    parent_comment_id: str | None = None,
    comments_log: Path | str | None = None,
) -> tuple[Comment, FeedbackEntry]:
    """Persist a comment AND write a paired FeedbackEntry.

    Two writes happen in this order:

    1. Append a ``Comment`` to ``comments_log`` (default
       ``/app/logs/finding_comments.jsonl``). The comment is the
       source of truth for the body, threading, and ordered read.
    2. Append a ``FeedbackEntry(action="comment", ...)`` to the
       store's chain so the comment shows up in
       ``per_clinic_f1`` rollups and the audit trail. The body's
       first 500 chars are folded into the entry's ``note`` so a
       privacy officer reading the chain can see the gist without
       joining the comments log.

    Returns ``(comment, feedback_entry)`` so the API can echo the
    comment_id and the event_id of the feedback row that was
    written for it.
    """
    # Use the same parent directory as the feedback log when no
    # explicit comments_log was given — keeps the dev / test / prod
    # log directories co-located.
    if comments_log is None:
        comments_log = store._path.parent / "finding_comments.jsonl"  # noqa: SLF001
    cstore = _get_comment_store(comments_log)
    comment = cstore.add(
        encounter_id=encounter_id,
        finding_id=finding_id,
        author_id=author_id,
        body=body,
        parent_comment_id=parent_comment_id,
    )
    # Fold the body into a feedback note (truncated to keep the
    # chain payload reasonable). action="comment" is the spec'd
    # signal that this row is a paired comment, not a biller
    # judgment on accuracy.
    note = (body or "").strip()[:500]
    # Comments are also a biller interaction, so we record the
    # biller_id — the same field used by accept/dismiss/modify.
    entry = FeedbackEntry(
        encounter_id=encounter_id,
        finding_id=finding_id,
        action="comment",  # type: ignore[arg-type]
        severity="",
        rule_id="",
        category="",
        biller_id=author_id or "default_biller",
        note=note or None,
    )
    store.append(entry)
    return comment, entry


def list_comments(
    store: FeedbackStore,
    encounter_id: str,
    finding_id: str,
    *,
    comments_log: Path | str | None = None,
) -> list[Comment]:
    """Read the thread for one finding.

    ``store`` is the FeedbackStore whose parent directory holds
    the comments log when ``comments_log`` is not given. The
    FeedbackStore is used only to locate the default comments log;
    the read goes straight to :class:`CommentStore`.
    """
    if comments_log is None:
        comments_log = store._path.parent / "finding_comments.jsonl"  # noqa: SLF001
    cstore = _get_comment_store(comments_log)
    return cstore.list_for_finding(encounter_id, finding_id)


def migrate_feedback_logs() -> tuple[int, int, int]:
    """Encrypt legacy decision, correction, and comment logs in place."""
    return (
        migrate_plaintext_jsonl(feedback_log_path()),
        migrate_plaintext_jsonl(_BILLER_CORRECTIONS_LOG),
        migrate_plaintext_jsonl(_COMMENTS_LOG),
    )
