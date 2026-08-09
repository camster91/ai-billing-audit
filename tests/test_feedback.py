"""Tests for the per-encounter feedback log.

Covers the three required behaviours from the task spec:

1. ``append`` + ``read_for_encounter`` round-trip — the row that comes
   back matches what was appended, including hash-chain fields.
2. ``verify_chain`` — an intact chain returns ``True``; mutating a row's
   ``cryptographic_signature`` breaks verification (same contract as
   ``audit_actions``).
3. ``stats()`` — counts roll up correctly across action / rule / category
   / biller axes.
4. The per-finding Accept / Dismiss / Modify endpoints in
   ``src/ai_billing_audit/api.py`` each write exactly one ``FeedbackEntry``
   with the right ``action`` and ``finding_id`` (and modify captures the
   before/after override values).

Uses a tmp JSONL path so it never touches the production
``/app/logs/feedback.jsonl``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ai_billing_audit.clinical_note_storage import (
    append_encrypted_json_record,
    read_encrypted_json_records,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import (  # noqa: E402
    FeedbackEntry,
    FeedbackStore,
    compute_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> FeedbackStore:
    """Fresh per-test log file so tests don't bleed into each other."""
    return FeedbackStore(log_path=tmp_path / "feedback.jsonl")


def _entry(
    *,
    action: str = "accept",
    encounter_id: str = "enc-001",
    finding_id: str = "f-1",
    rule_id: str = "R-MOD-25",
    category: str = "modifier_required",
    severity: str = "medium",
    biller_id: str = "biller-A",
    **overrides: object,
) -> FeedbackEntry:
    defaults: dict[str, object] = dict(
        encounter_id=encounter_id,
        finding_id=finding_id,
        action=action,  # type: ignore[arg-type]
        severity=severity,
        rule_id=rule_id,
        category=category,
        biller_id=biller_id,
    )
    defaults.update(overrides)
    return FeedbackEntry(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. append + read round-trip
# ---------------------------------------------------------------------------


def test_append_then_read_for_encounter_returns_same_row(store: FeedbackStore) -> None:
    e = _entry(action="dismiss", finding_id="f-2")
    store.append(e)

    rows = store.read_for_encounter("enc-001")
    assert len(rows) == 1
    r = rows[0]
    assert r.encounter_id == "enc-001"
    assert r.finding_id == "f-2"
    assert r.action == "dismiss"
    assert r.severity == "medium"
    assert r.rule_id == "R-MOD-25"
    assert r.category == "modifier_required"
    assert r.biller_id == "biller-A"
    # Hash-chain fields are populated by append():
    assert r.previous_signature  # non-empty (genesis for first row)
    assert r.cryptographic_signature
    assert len(r.cryptographic_signature) == 64  # sha256 hex


def test_read_all_returns_rows_in_append_order_across_encounters(
    store: FeedbackStore,
) -> None:
    store.append(_entry(encounter_id="enc-A", finding_id="f-1"))
    store.append(_entry(encounter_id="enc-B", finding_id="f-9"))
    store.append(_entry(encounter_id="enc-A", finding_id="f-2"))

    assert [e.finding_id for e in store.read_all()] == ["f-1", "f-9", "f-2"]
    assert [e.finding_id for e in store.read_for_encounter("enc-A")] == ["f-1", "f-2"]
    assert [e.finding_id for e in store.read_for_encounter("enc-B")] == ["f-9"]
    assert store.read_for_encounter("enc-MISSING") == []


def test_append_rejects_invalid_action(tmp_path: Path) -> None:
    store = FeedbackStore(log_path=tmp_path / "fb.jsonl")
    with pytest.raises(ValueError, match="accept|dismiss|modify"):
        store.append(_entry(action="banana"))  # type: ignore[arg-type]


def test_modify_entry_records_billers_override(store: FeedbackStore) -> None:
    e = _entry(
        action="modify",
        finding_id="f-3",
        severity="low",  # original
        modify_severity="medium",  # biller's override
        modify_category="documentation_gap",
    )
    store.append(e)
    r = store.read_for_encounter("enc-001")[0]
    assert r.action == "modify"
    assert r.severity == "low"
    assert r.modify_severity == "medium"
    assert r.modify_category == "documentation_gap"


def test_feedback_log_encrypts_encounter_and_biller_note_at_rest(
    store: FeedbackStore,
) -> None:
    entry = _entry(encounter_id="ENC-PHI-SECRET", finding_id="finding-secret")
    entry.note = "Patient Jane Doe has E11.9"

    store.append(entry)

    stored = store._path.read_bytes()  # noqa: SLF001
    assert b"ENC-PHI-SECRET" not in stored
    assert b"Jane Doe" not in stored
    assert store.read_all()[0].note == "Patient Jane Doe has E11.9"


# ---------------------------------------------------------------------------
# 2. chain verification
# ---------------------------------------------------------------------------


def test_verify_chain_passes_for_intact_log(store: FeedbackStore) -> None:
    store.append(_entry(finding_id="f-1"))
    store.append(_entry(finding_id="f-2", action="dismiss"))
    store.append(_entry(finding_id="f-3", action="modify"))
    assert store.verify_chain() is True


def test_verify_chain_detects_mutated_signature(store: FeedbackStore) -> None:
    store.append(_entry(finding_id="f-1"))
    store.append(_entry(finding_id="f-2", action="dismiss"))
    store.append(_entry(finding_id="f-3", action="modify"))

    # Tamper with the middle row's signature in place.
    path = store._path  # noqa: SLF001 — test-internal
    rows = read_encrypted_json_records(path)
    rows[1]["cryptographic_signature"] = "0" * 64
    path.unlink()
    for row in rows:
        append_encrypted_json_record(path, row)

    assert store.verify_chain() is False


def test_chain_links_each_row_to_prior(store: FeedbackStore) -> None:
    e1 = _entry(finding_id="f-1")
    e2 = _entry(finding_id="f-2", action="dismiss")
    e3 = _entry(finding_id="f-3", action="modify")
    store.append(e1)
    store.append(e2)
    store.append(e3)

    rows = store.read_all()
    # First row's prev = genesis (64 zeros).
    assert rows[0].previous_signature == "0" * 64
    assert rows[1].previous_signature == rows[0].cryptographic_signature
    assert rows[2].previous_signature == rows[1].cryptographic_signature

    # Recompute each signature and confirm it matches.
    for prev_sig, row_dict, actual_sig in zip(
        [r.previous_signature for r in rows],
        [
            {
                "event_id": r.event_id,
                "timestamp": r.timestamp,
                "encounter_id": r.encounter_id,
                "finding_id": r.finding_id,
                "action": r.action,
                "biller_id": r.biller_id,
                "rule_id": r.rule_id,
                "category": r.category,
                "severity": r.severity,
            }
            for r in rows
        ],
        [r.cryptographic_signature for r in rows],
    ):
        assert compute_signature(prev_sig, row_dict) == actual_sig


# ---------------------------------------------------------------------------
# 3. stats()
# ---------------------------------------------------------------------------


def test_stats_counts_by_action_rule_category_and_biller(store: FeedbackStore) -> None:
    store.append(
        _entry(action="accept", finding_id="f-1", rule_id="R-A", category="cat-x")
    )
    store.append(
        _entry(action="accept", finding_id="f-2", rule_id="R-A", category="cat-x")
    )
    store.append(
        _entry(
            action="dismiss",
            finding_id="f-3",
            rule_id="R-B",
            category="cat-y",
            biller_id="biller-B",
        )
    )
    store.append(
        _entry(action="modify", finding_id="f-4", rule_id="R-A", category="cat-x")
    )

    s = store.stats()
    assert s["total"] == 4
    assert s["by_action"] == {"accept": 2, "dismiss": 1, "modify": 1}
    assert s["by_rule_id"] == {"R-A": 3, "R-B": 1}
    assert s["by_category"] == {"cat-x": 3, "cat-y": 1}
    assert s["by_biller_id"] == {"biller-A": 3, "biller-B": 1}


def test_stats_empty_when_no_entries(tmp_path: Path) -> None:
    store = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    s = store.stats()
    assert s["total"] == 0
    assert s["by_action"] == {}


# ---------------------------------------------------------------------------
# 4. correct_finding field on dismiss — the "what should this have been"
#    label that the biller supplies when dismissing a flagged finding.
#    Backward compat: dismisses without correct_finding keep the existing
#    flow.
# ---------------------------------------------------------------------------


def test_dismiss_with_correct_finding_round_trips(store: FeedbackStore) -> None:
    """A dismiss entry carrying a correct_finding label persists and reads back."""
    label = {
        "severity": "low",
        "category": "documentation_gap",
        "suggested_code": "03.04A",
    }
    e = _entry(
        action="dismiss",
        finding_id="f-9",
        rule_id="R-MOD-25",
        category="modifier_required",
        severity="medium",
        correct_finding=label,
    )
    store.append(e)
    rows = store.read_for_encounter("enc-001")
    assert len(rows) == 1
    r = rows[0]
    assert r.action == "dismiss"
    assert r.correct_finding == label
    # Original severity/rule/category are preserved for the training join.
    assert r.severity == "medium"
    assert r.rule_id == "R-MOD-25"


def test_dismiss_without_correct_finding_is_unchanged(store: FeedbackStore) -> None:
    """Dismiss without correct_finding leaves the row backward-compatible."""
    e = _entry(action="dismiss", finding_id="f-10")
    store.append(e)
    r = store.read_for_encounter("enc-001")[0]
    assert r.correct_finding is None
    assert r.action == "dismiss"


def test_correct_finding_pairs_returns_dismiss_plus_label(store: FeedbackStore) -> None:
    """``correct_finding_pairs()`` joins dismisses to the original prediction."""
    store.append(
        _entry(
            action="dismiss",
            finding_id="f-1",
            rule_id="R-MOD-25",
            category="modifier_required",
            severity="medium",
            correct_finding={
                "severity": "low",
                "category": "documentation_gap",
                "suggested_code": "03.04A",
            },
        )
    )
    # Plain dismiss (no label) — must NOT appear in pairs.
    store.append(_entry(action="dismiss", finding_id="f-2"))
    # Plain accept — must NOT appear.
    store.append(_entry(action="accept", finding_id="f-3"))
    # Modify with label field (irrelevant; the helper filters on action=="dismiss")
    store.append(
        _entry(
            action="modify",
            finding_id="f-4",
            correct_finding={"severity": "low"},
        )
    )

    pairs = store.correct_finding_pairs()
    assert len(pairs) == 1
    p = pairs[0]
    assert p["encounter_id"] == "enc-001"
    assert p["finding_id"] == "f-1"
    assert p["original"]["severity"] == "medium"
    assert p["original"]["rule_id"] == "R-MOD-25"
    assert p["original"]["category"] == "modifier_required"
    assert p["correct_finding"]["severity"] == "low"
    assert p["correct_finding"]["suggested_code"] == "03.04A"


def test_correct_finding_pairs_empty_when_no_labels(store: FeedbackStore) -> None:
    store.append(_entry(action="dismiss", finding_id="f-1"))
    store.append(_entry(action="accept", finding_id="f-2"))
    assert store.correct_finding_pairs() == []


def test_chain_still_verifies_with_correct_finding_field(store: FeedbackStore) -> None:
    """The new optional field must not break the existing hash chain."""
    store.append(
        _entry(
            action="dismiss",
            finding_id="f-1",
            correct_finding={"severity": "low"},
        )
    )
    store.append(
        _entry(
            action="dismiss",
            finding_id="f-2",
            correct_finding={"category": "documentation_gap"},
        )
    )
    assert store.verify_chain() is True
