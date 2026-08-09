"""Snooze store for per-finding re-audit reminders (kanban t_993c411c).

A "snooze" is a biller's request to hide a finding from the default
encounter view for a bounded window. Common use case: "I see this
flag — let me think about it / pull the chart / talk to the
provider — but I don't want it on my dashboard right now." When
the snooze window passes, the finding returns to the active pool
on its own. Snoozes never delete a finding; they only suppress it
temporarily and the biller can always re-show it with the
``include_snoozed=true`` query param.

The store is append-only — every snooze is recorded in JSONL at
``/app/logs/snoozes.jsonl`` (overridable via the ``SNOOZE_LOG``
env var for tests). The most recent snooze for a given
``(encounter_id, finding_id)`` pair is the active one; older
snoozes for the same finding are preserved as the audit trail
of biller intent. A "unsnooze" event (``snooze_until`` = null
or past) is a normal row with a null ``snooze_until`` and an
``action == "unsnooze"`` marker — keeps the chain complete and
means the activity view can show "snoozed X, then unsnoozed
Y hours later" without a second table.

Concurrency model
-----------------
The store reads-then-writes the JSONL log; within a single
process this is safe (Python's GIL plus the write-then-read
pattern). For multi-process writers (e.g. a future web-worker
pool) the standard ``fcntl`` flock pattern would need to be
added — not needed today because the dashboard app is a single
uvicorn worker.

Expiry semantics
----------------
A snooze is "active" when ``snooze_until > now``. Expired snoozes
remain on disk forever (so the audit chain still tells the
biller's story) but ``is_snoozed_active()`` returns ``False``
once the timestamp passes. The dashboard's default filter
``include_snoozed=false`` hides only ACTIVE snoozes; expired
snoozes are treated the same as never-snoozed.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    migrate_plaintext_jsonl,
    read_encrypted_json_records,
)


# Default JSONL path. Overridable via SNOOZE_LOG for tests.
_DEFAULT_LOG = Path(os.environ.get("SNOOZE_LOG", "/app/logs/snoozes.jsonl"))


@dataclass
class SnoozeEntry:
    """A single snooze (or unsnooze) event.

    Fields:
        event_id: Stable UUID hex for this row.
        encounter_id: Encounter the finding belongs to.
        finding_id: The finding the biller snoozed.
        snooze_until: ISO-8601 UTC string ``YYYY-MM-DDTHH:MM:SSZ``,
            or ``None`` if this is an unsnooze event.
        reason: Optional free-text rationale.
        action: "snooze" or "unsnooze" — the latter is a row that
            explicitly clears an active snooze before its expiry.
        user_identifier: Who did it (from RBAC headers in prod,
            "demo" in dev).
        created_at: ISO-8601 UTC timestamp when the row was written.
    """

    event_id: str
    encounter_id: str
    finding_id: str
    snooze_until: str | None
    reason: str
    action: str
    user_identifier: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SnoozeEntry":
        return cls(
            event_id=str(raw.get("event_id", "")),
            encounter_id=str(raw.get("encounter_id", "")),
            finding_id=str(raw.get("finding_id", "")),
            snooze_until=raw.get("snooze_until"),
            reason=str(raw.get("reason", "")),
            action=str(raw.get("action", "snooze")),
            user_identifier=str(raw.get("user_identifier", "demo")),
            created_at=str(raw.get("created_at", "")),
        )


class SnoozeStore:
    """JSONL-backed snooze store.

    The store is intentionally tiny — one append per write, one
    full read per query. Volume is low (one snooze per finding
    per biller; findings are tens per encounter). If volume ever
    grows to thousands per day we can index by (encounter,
    finding) but for v0 the linear read is fast enough.
    """

    def __init__(self, log_path: Path | str | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else _DEFAULT_LOG

    # ─── write path ─────────────────────────────────────────────────

    def append(self, entry: SnoozeEntry) -> SnoozeEntry:
        """Append a snooze/unsnooze row to the JSONL log."""
        append_encrypted_json_record(self.log_path, entry.to_dict())
        return entry

    def snooze(
        self,
        encounter_id: str,
        finding_id: str,
        snooze_until: str,
        reason: str = "",
        user_identifier: str = "demo",
    ) -> SnoozeEntry:
        """Record a new active snooze.

        Any prior active snooze on the same (encounter, finding)
        pair is implicitly superseded — we don't need a separate
        "unsnooze" row because the new snooze is strictly later
        and ``active_snooze_for()`` returns the most recent row.
        """
        entry = SnoozeEntry(
            event_id=uuid.uuid4().hex,
            encounter_id=encounter_id,
            finding_id=finding_id,
            snooze_until=snooze_until,
            reason=reason,
            action="snooze",
            user_identifier=user_identifier,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return self.append(entry)

    def unsnooze(
        self,
        encounter_id: str,
        finding_id: str,
        user_identifier: str = "demo",
    ) -> SnoozeEntry | None:
        """Record an explicit unsnooze event.

        Returns the written entry, or ``None`` if there was no
        active snooze to clear (no point writing a "no-op" row).
        """
        if self.active_snooze_for(encounter_id, finding_id) is None:
            return None
        entry = SnoozeEntry(
            event_id=uuid.uuid4().hex,
            encounter_id=encounter_id,
            finding_id=finding_id,
            snooze_until=None,
            reason="",
            action="unsnooze",
            user_identifier=user_identifier,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return self.append(entry)

    # ─── read path ──────────────────────────────────────────────────

    def all_entries(self) -> list[SnoozeEntry]:
        """Return every row in the log, oldest first. Skips malformed lines."""
        if not self.log_path.is_file():
            return []
        rows = [
            SnoozeEntry.from_dict(record)
            for record in read_encrypted_json_records(self.log_path)
        ]
        # Malformed row — skip rather than blow up the
        # whole dashboard render. Real prod would
        # quarantine these; for v0 we just keep going.
        return rows

    def migrate_plaintext_log(self) -> int:
        """Encrypt this store's legacy plaintext log in place."""
        return migrate_plaintext_jsonl(self.log_path)

    def entries_for(
        self, encounter_id: str, finding_id: str | None = None
    ) -> list[SnoozeEntry]:
        """Return rows for an encounter (optionally narrowed to one finding),
        oldest first."""
        return [
            e
            for e in self.all_entries()
            if e.encounter_id == encounter_id
            and (finding_id is None or e.finding_id == finding_id)
        ]

    def active_snooze_for(
        self, encounter_id: str, finding_id: str, now: float | None = None
    ) -> SnoozeEntry | None:
        """Return the most recent active snooze for (encounter, finding),
        or None if no snooze is currently in effect.

        Walks the rows in reverse order; the first row whose
        ``snooze_until`` is in the future is the active one.
        Subsequent rows (older) are ignored — only the latest
        biller decision counts. An explicit ``unsnooze`` row
        terminates the walk (no further snoozes are active).
        """
        if now is None:
            now = time.time()
        latest_active: SnoozeEntry | None = None
        for entry in reversed(self.entries_for(encounter_id, finding_id)):
            if entry.action == "unsnooze":
                # Explicit unsnooze clears any prior snooze, AND
                # nothing after this row can be active (the
                # biller just said "show me this again").
                return None
            if entry.snooze_until is None:
                continue
            if _parse_iso_ts(entry.snooze_until) is None:
                continue
            if _parse_iso_ts(entry.snooze_until) > now:  # type: ignore[operator]
                latest_active = entry
                # Keep walking — there could be a still-later
                # row that supersedes this one. But since we're
                # already walking in reverse, the FIRST active we
                # see is the latest. Return immediately.
                return latest_active
            # Snooze in the past — expired; ignore.
        return latest_active

    def active_snoozes_for_encounter(
        self, encounter_id: str, now: float | None = None
    ) -> dict[str, SnoozeEntry]:
        """Return ``{finding_id: SnoozeEntry}`` for every actively snoozed
        finding on this encounter, for use in dashboard filtering."""
        if now is None:
            now = time.time()
        out: dict[str, SnoozeEntry] = {}
        for entry in self.entries_for(encounter_id):
            if entry.action == "unsnooze":
                # If this unsnooze row applies to a finding still
                # mapped in ``out``, that mapping wins (the
                # unsnooze was written later). For other findings
                # we leave them in place.
                out.pop(entry.finding_id, None)
                continue
            if entry.snooze_until is None:
                continue
            ts = _parse_iso_ts(entry.snooze_until)
            if ts is None or ts <= now:
                continue
            # Latest row for this finding wins; since we walk
            # oldest-first, the LAST row we see for each
            # finding_id is the latest.
            out[entry.finding_id] = entry
        return out


# ─── helpers ──────────────────────────────────────────────────────


def _parse_iso_ts(s: str) -> float | None:
    """Parse an ISO-8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``) into
    a Unix timestamp. Returns None if the string is malformed so
    callers can skip the row without aborting the whole query.
    """
    if not s:
        return None
    try:
        # Python 3.11+ fromisoformat accepts the trailing 'Z'.
        from datetime import datetime

        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def filter_findings_by_snooze(
    findings: Iterable[dict[str, Any]],
    active_snoozes: dict[str, "SnoozeEntry"],
    *,
    include_snoozed: bool = False,
) -> list[dict[str, Any]]:
    """Filter an iterable of finding dicts to drop actively-snoozed ones.

    Each finding dict must have a ``finding_id`` key. The
    ``active_snoozes`` map (typically from
    ``SnoozeStore.active_snoozes_for_encounter``) tells us which
    findings are currently hidden. When ``include_snoozed`` is
    True we keep them all (and annotate the kept ones with
    ``snooze`` metadata so the template can render a "snoozed
    until …" badge).
    """
    out: list[dict[str, Any]] = []
    for f in findings:
        fid = f.get("finding_id") or ""
        snooze = active_snoozes.get(fid)
        if snooze is not None and not include_snoozed:
            # Skip — finding is currently snoozed.
            continue
        # Annotate so the template can show the badge when
        # ``include_snoozed=true`` is in the URL.
        if snooze is not None:
            f = dict(f)
            f["snooze"] = {
                "until": snooze.snooze_until,
                "reason": snooze.reason,
                "by": snooze.user_identifier,
            }
        out.append(f)
    return out


__all__ = [
    "SnoozeEntry",
    "SnoozeStore",
    "filter_findings_by_snooze",
]
