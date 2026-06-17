"""Demo encounter registry for the dashboard.

The dashboard (`api.py`) serves whatever is registered here. Each sibling
kanban task (easy / medium / hard) registers its own encounter against
the same registry, and the index page lists them in the order they were
registered.

The contract is intentionally tiny: a `DemoEncounter` is just a stable id
plus a `difficulty` label (EASY / MEDIUM / HARD). The actual record —
clinical note, claim, rules, ground-truth findings — is loaded from
`data/val.json` / `data/train.json` at request time, keyed by
`encounter_id`. This keeps the registry a coordination surface (no data
duplication) and means a new sibling can ship a single
``register_demo_encounter(...)`` call without touching the route code.
"""
from __future__ import annotations

from dataclasses import dataclass
from json import load as _json_load
from pathlib import Path
from typing import Any

__all__ = [
    "DemoEncounter",
    "register_demo_encounter",
    "list_demo_encounters",
    "get_demo_encounter",
    "load_encounter_record",
]


# Repo layout: this file lives at
#   src/ai_billing_audit/demo_registry.py
# so the data dir is ../../../data relative to this file.
_DATA_DIR = (Path(__file__).resolve().parent.parent.parent / "data").resolve()


_Difficulty = str  # "EASY" | "MEDIUM" | "HARD"


@dataclass(frozen=True)
class DemoEncounter:
    """Pointer to an encounter that should appear on the demo dashboard."""

    encounter_id: str
    difficulty: _Difficulty  # "EASY" | "MEDIUM" | "HARD"
    summary: str  # one-line description shown on the index card


# Insertion-ordered: index page renders in this order.
_REGISTRY: list[DemoEncounter] = []


def register_demo_encounter(
    encounter_id: str, difficulty: _Difficulty, summary: str
) -> DemoEncounter:
    """Register an encounter for the demo dashboard.

    Idempotent on `encounter_id`: re-registering the same id is a no-op
    (returns the existing record). Sibling workers can call this at
    import time without worrying about order.
    """
    difficulty = difficulty.upper()
    if difficulty not in {"EASY", "MEDIUM", "HARD"}:
        raise ValueError(
            f"difficulty must be EASY, MEDIUM, or HARD (got {difficulty!r})"
        )
    for existing in _REGISTRY:
        if existing.encounter_id == encounter_id:
            return existing
    record = DemoEncounter(
        encounter_id=encounter_id, difficulty=difficulty, summary=summary
    )
    _REGISTRY.append(record)
    return record


def list_demo_encounters() -> list[DemoEncounter]:
    """All registered demo encounters, in registration order."""
    return list(_REGISTRY)


def get_demo_encounter(encounter_id: str) -> DemoEncounter | None:
    """Look up a registered encounter by id. Returns None if not registered."""
    for entry in _REGISTRY:
        if entry.encounter_id == encounter_id:
            return entry
    return None


def load_encounter_record(encounter_id: str) -> dict[str, Any] | None:
    """Find the full encounter record (note, claim, rules, ground_truth)
    across the train and val splits. Returns None if not found.

    The val and train JSONs are flat arrays. We load them lazily and
    cache the parsed lists in module scope so a request for several
    encounters doesn't re-parse the file.
    """
    cache: dict[str, list[dict[str, Any]]] = getattr(
        load_encounter_record, "_cache", {}
    )
    for split_name in ("val", "train"):
        if split_name not in cache:
            path = _DATA_DIR / f"{split_name}.json"
            if not path.is_file():
                cache[split_name] = []
                continue
            with path.open() as f:
                cache[split_name] = _json_load(f)
        for record in cache[split_name]:
            if record.get("encounter_id") == encounter_id:
                return record
    return None
