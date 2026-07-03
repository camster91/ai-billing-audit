"""Per-user saved filter presets for the home page (kanban t_66b05d72).

A biller who looks at the same filter every day ("my flagged
encounters", "this week clean", "encounters I dismissed") wants
that to be one click. This module stores named presets of the
query-param dict that drives the home-page filter (status, q,
cpt, icd10, patient_id, provider_npi, sort) so the biller can:

- save the current URL state as a named preset
- pick a preset from a dropdown on / to apply it instantly
- mark one preset as their default (loaded on first paint)
- share a preset via a stable URL (?preset=<name>)

Storage
-------
JSONL at ``/app/logs/saved_filters.jsonl`` (overridable via the
``SAVED_FILTERS_LOG`` env var for tests). Append-only: each save
is one row, and the most-recent row per (user_id, preset_name)
wins. Mirrors the snooze.py store pattern so the project's
storage conventions stay consistent.

Multi-user safety
-----------------
Reads-then-writes within a single process are safe (GIL + the
read-modify-write pattern in ``save_preset()``). For multi-
process writers add the standard ``fcntl`` flock pattern — not
needed today because the dashboard runs as a single uvicorn
worker.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


# Default JSONL path. Overridable for tests via SAVED_FILTERS_LOG.
_DEFAULT_LOG = Path(
    os.environ.get("SAVED_FILTERS_LOG", "/app/logs/saved_filters.jsonl")
)


# The set of query-param keys this store knows about. Anything
# else in the filter dict is ignored at write-time so the file
# stays small and the saved URLs are deterministic. Mirrors the
# search-bar fields on the home page (kanban t_171d24b3).
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"status", "q", "cpt", "icd10", "patient_id", "provider_npi", "sort"}
)


def _normalise_filter(raw: dict[str, Any] | None) -> dict[str, str]:
    """Trim a filter dict down to the keys we know how to round-trip.

    Drops anything not in ``_ALLOWED_KEYS`` so a stray ``?foo=bar``
    query param never poisons the saved state. Empty values are
    dropped too, so a saved preset always contains only the fields
    the biller actively set.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    for k in _ALLOWED_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        out[k] = s
    return out


@dataclass
class SavedFilterEntry:
    """A single save / set-default event for one (user, preset) pair.

    The most recent entry per (user_id, preset_name) wins — older
    rows are kept on disk for audit but are superseded. ``is_default``
    is sticky on the most recent entry that sets it; ``save_preset()``
    defaults to clearing default unless ``set_default=True`` is passed.
    """

    user_id: str
    preset_name: str
    filter: dict[str, str] = field(default_factory=dict)
    is_default: bool = False
    saved_at: float = 0.0
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.saved_at:
            self.saved_at = time.time()
        if not self.event_id:
            self.event_id = uuid.uuid4().hex[:12]


class SavedFilterStore:
    """JSONL-backed store for per-user saved filter presets.

    Construct one per request (cheap; no I/O on construction).
    The store is append-only on disk; ``list_for_user`` reads the
    whole file once and indexes in memory. For the demo
    dashboard's handful of presets per user, this is fine.
    """

    def __init__(self, log_path: Path | str | None = None) -> None:
        self.log_path = Path(log_path) if log_path else _DEFAULT_LOG

    # ---- I/O helpers --------------------------------------------------

    def _read_all(self) -> list[SavedFilterEntry]:
        if not self.log_path.is_file():
            return []
        out: list[SavedFilterEntry] = []
        with self.log_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    out.append(SavedFilterEntry(**rec))
                except (TypeError, ValueError):
                    # Skip malformed rows so a partial-write recovery
                    # doesn't take down the read path.
                    continue
        return out

    def _append(self, entry: SavedFilterEntry) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    # ---- public API ---------------------------------------------------

    def save_preset(
        self,
        user_id: str,
        preset_name: str,
        filter: dict[str, Any],
        *,
        set_default: bool = False,
    ) -> SavedFilterEntry:
        """Save (or replace) a preset for a user.

        ``set_default=True`` also marks the preset as the user's
        default. Saving another preset with ``set_default=False``
        does NOT clear the default — only ``set_default=False``
        on a preset named the same as an existing default turns
        off the default flag.
        """
        preset_name = (preset_name or "").strip()
        if not preset_name:
            raise ValueError("preset_name must be non-empty")
        if not user_id:
            raise ValueError("user_id must be non-empty")
        normalised = _normalise_filter(filter)
        # If we're saving the same name and not promoting to default,
        # we need to know whether an existing default exists so we
        # don't accidentally clear it.
        existing = self.list_for_user(user_id)
        existing_default: str | None = None
        for p in existing:
            if p.is_default:
                existing_default = p.preset_name
                break
        # If we're promoting a *different* preset to default, we must
        # also write a clear-default entry for the previously-default
        # preset so ``list_for_user`` returns exactly one default per
        # user (the contract pinned by test_set_default_only_one).
        if set_default and existing_default and existing_default != preset_name:
            clear_entry = SavedFilterEntry(
                user_id=user_id,
                preset_name=existing_default,
                filter=self.get_preset(user_id, existing_default).filter,
                is_default=False,
            )
            self._append(clear_entry)
        # Determine the effective is_default flag.
        if set_default:
            effective_default = True
        else:
            effective_default = preset_name == existing_default
        entry = SavedFilterEntry(
            user_id=user_id,
            preset_name=preset_name,
            filter=normalised,
            is_default=effective_default,
        )
        self._append(entry)
        return entry

    def clear_default(self, user_id: str) -> SavedFilterEntry | None:
        """Remove the default flag from whatever preset holds it.

        Returns the clearing entry (so the caller can echo it back
        in a flash message) or ``None`` if no default was set."""
        existing = self.list_for_user(user_id)
        default_preset: str | None = None
        for p in existing:
            if p.is_default:
                default_preset = p.preset_name
                break
        if not default_preset:
            return None
        # Re-save the same preset with is_default=False.
        current = next(
            p for p in existing if p.preset_name == default_preset
        )
        entry = SavedFilterEntry(
            user_id=user_id,
            preset_name=default_preset,
            filter=current.filter,
            is_default=False,
        )
        self._append(entry)
        return entry

    def list_for_user(self, user_id: str) -> list[SavedFilterEntry]:
        """Return the user's presets, latest-version per name.

        Ordering: most-recently-saved first. ``is_default`` is
        sticky on the most recent entry that sets it.

        Tombstones (the most-recent row for a name has an empty
        ``filter``) are filtered out — the append-only log keeps
        the audit trail intact, but live queries drop tombstoned
        presets so a deleted preset doesn't resurface in the UI.
        """
        latest: dict[str, SavedFilterEntry] = {}
        order: list[str] = []
        for entry in self._read_all():
            if entry.user_id != user_id:
                continue
            if entry.preset_name not in latest:
                order.append(entry.preset_name)
            latest[entry.preset_name] = entry
        # Build the list in latest-write order (the order keys
        # were inserted is the order each preset was last touched).
        # Build the list in latest-write order (skipping tombstones —
        # most-recent row for that preset name has empty ``filter``).
        result: list[SavedFilterEntry] = []
        for name in order:
            e = latest[name]
            if not e.filter:
                continue
            result.append(e)
        return result

    def get_preset(
        self, user_id: str, preset_name: str
    ) -> SavedFilterEntry | None:
        for entry in self.list_for_user(user_id):
            if entry.preset_name == preset_name:
                return entry
        return None

    def get_default(self, user_id: str) -> SavedFilterEntry | None:
        for entry in self.list_for_user(user_id):
            if entry.is_default:
                return entry
        return None

    def delete_preset(self, user_id: str, preset_name: str) -> bool:
        """Mark a preset deleted by writing a tombstone entry with
        an empty filter. Returns True if a tombstone was written.

        We don't actually remove rows (append-only log) so the
        audit trail stays complete; ``list_for_user`` then filters
        out presets whose most-recent row has an empty filter.
        """
        existing = self.get_preset(user_id, preset_name)
        if existing is None:
            return False
        # Default-flag bookkeeping: if the deleted preset was the
        # default, clear the default.
        was_default = existing.is_default
        tombstone = SavedFilterEntry(
            user_id=user_id,
            preset_name=preset_name,
            filter={},
            is_default=False if was_default else False,
        )
        self._append(tombstone)
        return True


__all__ = [
    "SavedFilterEntry",
    "SavedFilterStore",
]