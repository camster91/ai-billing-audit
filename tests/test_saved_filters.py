"""Tests for the per-user saved-filter presets store (kanban t_66b05d72).

The store is JSONL-backed and lives at ``/app/logs/saved_filters.jsonl``
by default; tests redirect to a tmp file via the constructor arg.
"""

from __future__ import annotations

import pytest

from ai_billing_audit.saved_filters import SavedFilterStore


@pytest.fixture
def store(tmp_path):
    return SavedFilterStore(log_path=tmp_path / "saved_filters.jsonl")


def test_save_and_list(store):
    store.save_preset("user_a", "my queue", {"status": "flagged"})
    store.save_preset("user_a", "this week", {"patient_id": "PATIENT-SECRET"})
    assert b"PATIENT-SECRET" not in store.log_path.read_bytes()
    presets = store.list_for_user("user_a")
    names = [p.preset_name for p in presets]
    assert "my queue" in names
    assert "this week" in names


def test_save_replaces_same_name(store):
    store.save_preset("u1", "today", {"status": "flagged"})
    store.save_preset("u1", "today", {"status": "clean"})
    presets = store.list_for_user("u1")
    assert len(presets) == 1
    assert presets[0].filter["status"] == "clean"


def test_set_default_only_one(store):
    store.save_preset("u1", "a", {"status": "flagged"}, set_default=True)
    store.save_preset("u1", "b", {"status": "clean"}, set_default=True)
    presets = store.list_for_user("u1")
    defaults = [p for p in presets if p.is_default]
    assert len(defaults) == 1
    assert defaults[0].preset_name == "b"


def test_clear_default(store):
    store.save_preset("u1", "main", {"status": "flagged"}, set_default=True)
    out = store.clear_default("u1")
    assert out is not None
    assert store.get_default("u1") is None


def test_get_preset_missing_returns_none(store):
    assert store.get_preset("u1", "nope") is None


def test_delete_preset(store):
    store.save_preset("u1", "dropme", {"status": "flagged"})
    assert store.delete_preset("u1", "dropme") is True
    assert store.get_preset("u1", "dropme") is None


def test_users_isolated(store):
    store.save_preset("alice", "mine", {"status": "flagged"})
    store.save_preset("bob", "yours", {"status": "clean"})
    assert len(store.list_for_user("alice")) == 1
    assert len(store.list_for_user("bob")) == 1
    assert store.list_for_user("alice")[0].preset_name == "mine"


def test_save_rejects_empty_name(store):
    with pytest.raises(ValueError):
        store.save_preset("u1", "", {"status": "flagged"})
    with pytest.raises(ValueError):
        store.save_preset("", "name", {"status": "flagged"})
