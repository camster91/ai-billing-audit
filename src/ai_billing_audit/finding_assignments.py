"""Finding assignment store (kanban t_54262d96).

A "finding assignment" is a biller-level ownership record for a single
finding on a single encounter. The motivating use case: a mid-clinic
account reviews ~2,000 audits/month and a single biller can't own
that workload, so the office manager needs to distribute the queue.
The store records WHO a finding was assigned to, WHEN, and the
optional due date.

Storage model
-------------
The store is append-only JSONL at ``/app/logs/finding_assignments.jsonl``
(overridable via ``FINDING_ASSIGNMENT_LOG`` for tests). Re-assigning
the same ``(encounter_id, finding_id)`` pair writes a new row — the
"current" assignee is the most recent row for that pair. Older rows
are preserved as the audit trail of biller intent (so the activity
view can show "was assigned to A on Monday, reassigned to B on
Wednesday" without a second table).

Clinic scoping
--------------
The workload endpoint is per-clinic. The store itself does not
own a ``clinic_id`` column — clinic scoping is derived at query
time from the feedback log (which records ``biller_id`` for every
accept/dismiss/modify action). This keeps the store schema simple
and means we never need to back-fill clinic_id on historical rows.
The mapping from biller → clinic defaults to ``biller_id or
"default_biller"`` to match the per_clinic_f1 convention.

Concurrency
-----------
Single-writer within one process is safe (GIL + write-then-read
pattern, same as the snooze and audit_actions stores). Multi-process
writers would need ``fcntl`` flock — not needed today because the
dashboard app is a single uvicorn worker.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
)


# Default JSONL path. Overridable via FINDING_ASSIGNMENT_LOG for tests.
_DEFAULT_LOG = Path(
    os.environ.get("FINDING_ASSIGNMENT_LOG", "/app/logs/finding_assignments.jsonl")
)


@dataclass
class FindingAssignment:
    """A single assignment (or re-assignment) event.

    Fields:
        event_id: Stable UUID hex for this row.
        encounter_id: Encounter the finding belongs to.
        finding_id: The finding assigned to a biller.
        assignee_id: Biller who now owns the finding (matches the
            ``biller_id`` field on FeedbackEntry; the per-clinic
            workload rolls up by this key).
        assigned_by: ``user_identifier`` of whoever made the
            assignment (the office manager, in the common case).
            Defaults to the same value as ``assignee_id`` when the
            finding is self-assigned by the biller.
        due_date: ISO-8601 UTC string ``YYYY-MM-DDTHH:MM:SSZ`` or
            empty string if no due date was specified.
        created_at: ISO-8601 UTC timestamp when the row was written.
    """

    event_id: str
    encounter_id: str
    finding_id: str
    assignee_id: str
    assigned_by: str
    due_date: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FindingAssignment":
        return cls(
            event_id=str(raw.get("event_id", "")),
            encounter_id=str(raw.get("encounter_id", "")),
            finding_id=str(raw.get("finding_id", "")),
            assignee_id=str(raw.get("assignee_id", "")),
            assigned_by=str(raw.get("assigned_by", raw.get("assignee_id", ""))),
            due_date=str(raw.get("due_date", "")),
            created_at=str(raw.get("created_at", "")),
        )


class FindingAssignmentStore:
    """JSONL-backed finding-assignment store.

    One append per write, one full read per query. Volume is bounded
    by ``n_billers × n_findings_per_encounter`` per encounter — at
    pilot scale this is hundreds of rows, not thousands, so the
    linear reads are well within budget.
    """

    def __init__(self, log_path: Path | str | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else _DEFAULT_LOG

    # ─── write path ─────────────────────────────────────────────────

    def append(self, entry: FindingAssignment) -> FindingAssignment:
        """Append an assignment row to the JSONL log."""
        append_encrypted_json_record(self.log_path, entry.to_dict())
        return entry

    def assign(
        self,
        encounter_id: str,
        finding_id: str,
        assignee_id: str,
        assigned_by: str | None = None,
        due_date: str = "",
    ) -> FindingAssignment:
        """Record a new assignment (or re-assignment).

        Re-assignment on an already-assigned finding simply writes
        a new row — ``current_assignee_for()`` reads the most recent
        row so the new assignee "wins". Older rows are preserved
        so the biller can ask "when was this last reassigned?" and
        get a full history.
        """
        entry = FindingAssignment(
            event_id=uuid.uuid4().hex,
            encounter_id=encounter_id,
            finding_id=finding_id,
            assignee_id=assignee_id,
            assigned_by=str(assigned_by) if assigned_by else assignee_id,
            due_date=due_date,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return self.append(entry)

    # ─── read path ──────────────────────────────────────────────────

    def all_entries(self) -> list[FindingAssignment]:
        """Return every row in the log, oldest first. Skips malformed lines."""
        if not self.log_path.is_file():
            return []
        return [
            FindingAssignment.from_dict(record)
            for record in read_encrypted_json_records(self.log_path)
        ]
        # Malformed row — skip rather than blow up the
        # whole dashboard render. Real prod would
        # quarantine these; for v0 we just keep going.

    def migrate_plaintext_log(self) -> int:
        """Encrypt this store's legacy plaintext log in place."""
        return migrate_plaintext_jsonl(self.log_path)

    def entries_for(
        self, encounter_id: str, finding_id: str | None = None
    ) -> list[FindingAssignment]:
        """Return rows for an encounter, optionally narrowed to one finding.

        Oldest-first, so callers can either walk the full history or
        take the last element to get the current state.
        """
        return [
            e
            for e in self.all_entries()
            if e.encounter_id == encounter_id
            and (finding_id is None or e.finding_id == finding_id)
        ]

    def current_assignee_for(
        self, encounter_id: str, finding_id: str
    ) -> FindingAssignment | None:
        """Return the most recent assignment for ``(encounter, finding)``,
        or ``None`` if the finding has never been assigned.

        The most recent row wins; older rows are preserved on disk
        but not exposed via this query (callers that need the
        history can use ``entries_for``).
        """
        rows = self.entries_for(encounter_id, finding_id)
        if not rows:
            return None
        return rows[-1]

    def current_assignees_for_encounter(
        self, encounter_id: str
    ) -> dict[str, FindingAssignment]:
        """Return ``{finding_id: FindingAssignment}`` for the current
        assignee of every finding on this encounter.

        Walks the rows oldest-first so the LAST row seen for each
        finding_id is the latest (most-recent) one. Used by the
        encounter detail template to render the per-finding
        "Assigned to <biller>" badge.
        """
        out: dict[str, FindingAssignment] = {}
        for entry in self.entries_for(encounter_id):
            out[entry.finding_id] = entry
        return out

    # ─── workload aggregation ───────────────────────────────────────

    def workload_for_clinic(
        self,
        clinic_id: str,
        *,
        biller_to_clinic: Callable[[str], str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the current per-biller workload for one clinic.

        Each returned entry:
            ``{
                "biller_id": str,
                "n_assigned": int,   # total findings currently assigned
                "n_completed": int,  # of those, how many the biller has
                                     # accepted/dismissed/modified (any
                                     # feedback action)
                "n_overdue": int,    # of the assigned, how many have a
                                     # due_date in the past and no
                                     # feedback action yet
            }``

        The mapping from ``biller_id`` → ``clinic_id`` defaults to
        "the biller_id is the clinic" (matches the per_clinic_f1
        convention for single-clinic billers). Pass a
        ``biller_to_clinic`` callable to override — the call site
        will use the same mapping as the rest of the dashboard.

        "Completed" is a soft signal: any FeedbackEntry whose
        ``biller_id`` matches the assignee and whose ``finding_id``
        appears in their currently-assigned list counts. This means
        a biller who accepted a finding AND is still the current
        assignee has it counted as completed (good — they got
        through it) but a biller who was reassigned AWAY from a
        finding they accepted does NOT get it counted, because the
        finding is no longer in their queue.

        Best-effort: failures reading the feedback log degrade to
        zero completed counts rather than raising, so the workload
        endpoint stays up if feedback is unavailable.
        """
        all_rows = self.all_entries()
        # First, derive the *current* assignment per finding (most
        # recent row per (encounter, finding) pair).
        latest: dict[tuple[str, str], FindingAssignment] = {}
        for row in all_rows:
            key = (row.encounter_id, row.finding_id)
            latest[key] = row

        def _resolve_clinic(biller_id: str) -> str:
            if biller_to_clinic is not None:
                try:
                    return biller_to_clinic(biller_id)
                except Exception:
                    pass
            return biller_id or "default_biller"

        # Group by current assignee.
        per_biller: dict[str, list[FindingAssignment]] = {}
        for (enc_id, fid), row in latest.items():
            per_biller.setdefault(row.assignee_id, []).append(row)

        # Per-biller completion signal from the feedback log.
        completed_by_biller: dict[str, set[tuple[str, str]]] = {}
        try:
            from .feedback import get_default_store  # local import to avoid

            # pulling feedback at module import time (the dashboard
            # tests reload this module; feedback stays usable as long
            # as the env-driven paths resolve).
            store = get_default_store()
            for fe in store.read_all():
                bid = fe.biller_id or ""
                if not bid:
                    continue
                if fe.action not in ("accept", "dismiss", "modify"):
                    continue
                completed_by_biller.setdefault(bid, set()).add(
                    (fe.encounter_id, fe.finding_id)
                )
        except Exception:
            # Feedback module unavailable — leave completion counts
            # at zero. The workload endpoint still renders assigned
            # and overdue, which is enough signal for v0.
            completed_by_biller = {}

        now_ts = time.time()
        out: list[dict[str, Any]] = []
        for biller_id, rows in sorted(per_biller.items()):
            if _resolve_clinic(biller_id) != clinic_id:
                continue
            completed_pairs = completed_by_biller.get(biller_id, set())
            n_completed = sum(
                1 for r in rows if (r.encounter_id, r.finding_id) in completed_pairs
            )
            n_overdue = 0
            for r in rows:
                if not r.due_date:
                    continue
                if (r.encounter_id, r.finding_id) in completed_pairs:
                    continue
                ts = _parse_iso_ts(r.due_date)
                if ts is None:
                    continue
                if ts < now_ts:
                    n_overdue += 1
            out.append(
                {
                    "biller_id": biller_id,
                    "n_assigned": len(rows),
                    "n_completed": n_completed,
                    "n_overdue": n_overdue,
                }
            )
        return out


# ─── helpers ──────────────────────────────────────────────────────


def _parse_iso_ts(s: str) -> float | None:
    """Parse an ISO-8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``) into a
    Unix timestamp. Returns None on malformed input so the caller can
    skip the row without aborting the whole aggregation.
    """
    if not s:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None
