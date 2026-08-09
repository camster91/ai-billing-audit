"""Unit tests for the legacy demo registry.

The dashboard no longer reads from this module — the home page
lists the parsed-837P cache (the job queue), not the demo
registry — but the registry helpers are still exported and
called from scripts and one-off tooling, so we keep the
contract tests alive.
"""

from __future__ import annotations

import pytest

from ai_billing_audit import demo_registry
from ai_billing_audit.demo_registry import (
    get_demo_encounter,
    list_demo_encounters,
    load_encounter_record,
    register_demo_encounter,
)


def test_registry_is_idempotent_on_encounter_id() -> None:
    probe_id = "enc_test_probe_idempotent_xyz"
    demo_registry._REGISTRY[:] = [
        e for e in demo_registry._REGISTRY if e.encounter_id != probe_id
    ]
    a = register_demo_encounter(encounter_id=probe_id, difficulty="EASY", summary="dup")
    b = register_demo_encounter(
        encounter_id=probe_id, difficulty="EASY", summary="dup-again"
    )
    assert a.encounter_id == b.encounter_id == probe_id
    matches = [e for e in list_demo_encounters() if e.encounter_id == probe_id]
    assert len(matches) == 1
    demo_registry._REGISTRY[:] = [
        e for e in demo_registry._REGISTRY if e.encounter_id != probe_id
    ]


def test_registry_rejects_unknown_difficulty() -> None:
    with pytest.raises(ValueError, match="EASY, MEDIUM, or HARD"):
        register_demo_encounter(encounter_id="enc_bogus", difficulty="WAT", summary="x")


def test_load_encounter_record_finds_known_id() -> None:
    rec = load_encounter_record("enc_10032")
    if rec is None:
        pytest.skip("data/synth/val.json not available in this environment")
    assert rec["encounter_id"] == "enc_10032"
    assert "clinical_note" in rec
    assert "ground_truth" in rec


def test_load_encounter_record_returns_none_for_missing() -> None:
    assert load_encounter_record("enc_does_not_exist") is None


def test_get_demo_encounter_returns_none_for_missing() -> None:
    assert get_demo_encounter("enc_does_not_exist") is None
