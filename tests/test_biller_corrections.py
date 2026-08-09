"""Tests for the biller_corrections view in the feedback log.

The feedback log mixes three action types: ``accept`` (model right),
``dismiss`` (model wrong), ``modify`` (biller corrected a content
field). The ``modify`` rows are qualitatively different — they're the
highest-value training signal because they carry the *specific*
correction the biller made (severity from medium -> low, category
re-classified, etc.). This module exercises the read-side filter
that surfaces that subset as its own view, separate from accept and
dismiss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import (  # noqa: E402
    FeedbackEntry,
    FeedbackStore,
    read_biller_corrections,
    record_biller_correction,
)


@pytest.fixture()
def store(tmp_path: Path) -> FeedbackStore:
    return FeedbackStore(log_path=tmp_path / "fb.jsonl")


def _entry(
    *,
    action: str,
    encounter_id: str = "enc-1",
    finding_id: str = "f-1",
    rule_id: str = "R-X",
    category: str = "documentation_gap",
    severity: str = "medium",
    modify_severity: str | None = None,
    modify_category: str | None = None,
) -> FeedbackEntry:
    return FeedbackEntry(
        encounter_id=encounter_id,
        finding_id=finding_id,
        action=action,  # type: ignore[arg-type]
        severity=severity,
        rule_id=rule_id,
        category=category,
        modify_severity=modify_severity,
        modify_category=modify_category,
    )


def test_structured_correction_is_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    from ai_billing_audit import feedback

    path = tmp_path / "biller_corrections.jsonl"
    monkeypatch.setattr(feedback, "_BILLER_CORRECTIONS_LOG", path)

    record_biller_correction(
        encounter_id="ENC-PHI-SECRET",
        finding_id="finding-1",
        severity="high",
        category="documentation",
        rationale="Patient Jane Doe requires correction",
        biller_id="biller-1",
    )

    assert b"ENC-PHI-SECRET" not in path.read_bytes()
    assert b"Jane Doe" not in path.read_bytes()
    restored = read_biller_corrections()
    assert restored[0].rationale == "Patient Jane Doe requires correction"


# ---------------------------------------------------------------------------
# biller_corrections()
# ---------------------------------------------------------------------------


def test_biller_corrections_returns_only_modify_rows(store: FeedbackStore) -> None:
    store.append(_entry(action="accept", finding_id="f-a"))
    store.append(_entry(action="dismiss", finding_id="f-d"))
    store.append(
        _entry(
            action="modify",
            finding_id="f-m1",
            modify_severity="low",
            modify_category="documentation_gap",
        )
    )
    rows = store.biller_corrections()
    assert len(rows) == 1
    assert rows[0].finding_id == "f-m1"
    assert rows[0].action == "modify"


def test_biller_corrections_excludes_rerun_system_rows(
    store: FeedbackStore,
) -> None:
    # The /encounter/{id}/rerun handler writes a row with action="modify"
    # and finding_id="__rerun__" so the encounter timeline stays
    # complete. Those rows must NOT show up in the biller-corrections
    # view — they are system-tagged, not biller corrections.
    store.append(_entry(action="modify", finding_id="__rerun__", rule_id=""))
    store.append(
        _entry(
            action="modify",
            finding_id="f-m1",
            modify_severity="low",
        )
    )
    rows = store.biller_corrections()
    assert [r.finding_id for r in rows] == ["f-m1"]


def test_biller_corrections_filters_by_encounter_id(
    store: FeedbackStore,
) -> None:
    store.append(_entry(action="modify", encounter_id="enc-A", finding_id="f-1"))
    store.append(_entry(action="modify", encounter_id="enc-B", finding_id="f-2"))
    rows_a = store.biller_corrections(encounter_id="enc-A")
    assert [r.finding_id for r in rows_a] == ["f-1"]
    rows_b = store.biller_corrections(encounter_id="enc-B")
    assert [r.finding_id for r in rows_b] == ["f-2"]
    assert store.biller_corrections(encounter_id="enc-MISSING") == []


def test_biller_corrections_filters_by_rule_id(store: FeedbackStore) -> None:
    store.append(_entry(action="modify", rule_id="R-A", finding_id="f-1"))
    store.append(_entry(action="modify", rule_id="R-B", finding_id="f-2"))
    rows = store.biller_corrections(rule_id="R-B")
    assert len(rows) == 1
    assert rows[0].rule_id == "R-B"


def test_biller_corrections_newest_first(store: FeedbackStore) -> None:
    """Two rows in the same second: tie-broken on event_id, not
    insertion order. We only assert that BOTH rows are present and
    that the second-subsecond sort key (event_id, a uuid4 hex) is
    consistent — i.e. the result is deterministic across calls.
    """
    e1 = _entry(action="modify", finding_id="f-1")
    e2 = _entry(action="modify", finding_id="f-2")
    store.append(e1)
    store.append(e2)
    rows_first = store.biller_corrections()
    # Both rows are present.
    assert {r.finding_id for r in rows_first} == {"f-1", "f-2"}
    # Sort is deterministic — calling again returns the same order.
    rows_second = store.biller_corrections()
    assert [r.finding_id for r in rows_first] == [r.finding_id for r in rows_second]


def test_biller_corrections_orders_by_timestamp_when_distinct(
    store: FeedbackStore,
) -> None:
    """When the two rows have distinct timestamps, the newer one
    comes first — this is the case the biller-facing UI cares about
    ('what did the biller change most recently?')."""
    from dataclasses import replace as dc_replace

    e_old = _entry(action="modify", finding_id="f-old")
    e_new = dc_replace(e_old, finding_id="f-new", timestamp="2099-01-01T00:00:00Z")
    store.append(e_old)
    store.append(e_new)
    rows = store.biller_corrections()
    assert rows[0].finding_id == "f-new"


def test_biller_corrections_empty_when_log_is_empty(
    tmp_path: Path,
) -> None:
    store = FeedbackStore(log_path=tmp_path / "empty.jsonl")
    assert store.biller_corrections() == []


# ---------------------------------------------------------------------------
# corrections_summary()
# ---------------------------------------------------------------------------


def test_corrections_summary_counts_total_and_axes(
    store: FeedbackStore,
) -> None:
    store.append(
        _entry(
            action="modify",
            finding_id="f-1",
            rule_id="R-A",
            category="documentation_gap",
            modify_severity="low",
        )
    )
    store.append(
        _entry(
            action="modify",
            finding_id="f-2",
            rule_id="R-A",
            category="documentation_gap",
            modify_severity="high",
            modify_category="coding_error",
        )
    )
    store.append(
        _entry(
            action="modify",
            finding_id="f-3",
            rule_id="R-B",
            category="modifier_required",
            modify_category="modifier_required",
        )
    )
    # An accept should NOT inflate the corrections total.
    store.append(_entry(action="accept", finding_id="f-x"))

    s = store.corrections_summary()
    assert s["total"] == 3
    assert s["by_rule_id"] == {"R-A": 2, "R-B": 1}
    assert s["by_category"] == {"documentation_gap": 2, "modifier_required": 1}
    # Only f-1 and f-2 carry a modify_severity (f-3 only changed
    # the category, severity override is None).
    assert s["severity_changes"] == 2
    # f-1 didn't change category (modify_category is None).
    # f-2 and f-3 each set a non-None modify_category, so 2 rows
    # count as category changes.
    assert s["category_changes"] == 2
    # All three rows were on enc-1.
    assert s["encounters_affected"] == 1


def test_corrections_summary_respects_encounter_filter(
    store: FeedbackStore,
) -> None:
    store.append(_entry(action="modify", encounter_id="enc-A", finding_id="f-1"))
    store.append(_entry(action="modify", encounter_id="enc-B", finding_id="f-2"))
    s_a = store.corrections_summary(encounter_id="enc-A")
    assert s_a["total"] == 1
    assert s_a["encounters_affected"] == 1
    s_all = store.corrections_summary()
    assert s_all["total"] == 2
    assert s_all["encounters_affected"] == 2


def test_corrections_summary_empty_when_no_modify_rows(
    store: FeedbackStore,
) -> None:
    store.append(_entry(action="accept", finding_id="f-1"))
    store.append(_entry(action="dismiss", finding_id="f-2"))
    s = store.corrections_summary()
    assert s["total"] == 0
    assert s["by_rule_id"] == {}
    assert s["by_category"] == {}
    assert s["severity_changes"] == 0
    assert s["category_changes"] == 0
    assert s["encounters_affected"] == 0
