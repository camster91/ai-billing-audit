"""Tests for the per-rule model-confidence bucket helper.

Verifies the four-bucket contract:
  * high         — > 10 accept decisions for that rule
  * medium       — 3..10 accept decisions
  * low          — 1..2 accept decisions (some signal, not enough)
  * uncalibrated — 0 accept decisions, 0 total decisions
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.feedback import FeedbackEntry, FeedbackStore  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> FeedbackStore:
    return FeedbackStore(log_path=tmp_path / "fb.jsonl")


def _entry(*, rule_id: str = "R-X", action: str = "accept",
           finding_id: str = "f-1") -> FeedbackEntry:
    return FeedbackEntry(
        encounter_id="enc-1",
        finding_id=finding_id,
        action=action,  # type: ignore[arg-type]
        severity="medium",
        rule_id=rule_id,
        category="cat",
    )


def test_uncalibrated_when_no_feedback_for_rule(store):
    # Other-rule accepts shouldn't be counted for this rule.
    store.append(_entry(rule_id="R-OTHER", action="accept", finding_id="f-0"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "uncalibrated"
    assert out["label"] == "Not yet calibrated at this clinic"
    assert out["validations"] == 0


def test_low_bucket_for_few_accepts(store):
    for i in range(2):
        store.append(_entry(rule_id="R-X", action="accept", finding_id=f"f-{i}"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "low"
    assert out["label"] == "LOW"
    assert out["validations"] == 2


def test_medium_bucket_for_three_to_ten_accepts(store):
    for i in range(3):
        store.append(_entry(rule_id="R-X", action="accept", finding_id=f"f-{i}"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "medium"
    assert out["label"] == "MEDIUM"
    assert out["validations"] == 3
    # Top of the medium band is 10.
    store2 = FeedbackStore(log_path=store._path.parent / "fb2.jsonl")  # noqa: SLF001
    for i in range(10):
        store2.append(_entry(rule_id="R-X", action="accept", finding_id=f"g-{i}"))
    assert store2.confidence_for_rule("R-X")["bucket"] == "medium"


def test_high_bucket_for_more_than_ten_accepts(store):
    for i in range(11):
        store.append(_entry(rule_id="R-X", action="accept", finding_id=f"f-{i}"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "high"
    assert out["label"] == "HIGH"
    assert out["validations"] == 11


def test_dismisses_counted_but_do_not_change_bucket(store):
    # 5 accepts + 10 dismisses for the same rule: still MEDIUM.
    for i in range(5):
        store.append(_entry(rule_id="R-X", action="accept", finding_id=f"f-{i}"))
    for i in range(10):
        store.append(_entry(rule_id="R-X", action="dismiss", finding_id=f"d-{i}"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "medium"
    assert out["validations"] == 5
    assert out["dismisses"] == 10
    assert out["total"] == 15


def test_dismisses_alone_yield_low_not_uncalibrated(store):
    # 20 dismisses for the rule: bucket is LOW (we have signal that the
    # model is overcalling, just no positive validation yet). The
    # "uncalibrated" bucket is reserved for the empty-feedback case
    # (no signal of any kind) — see the empty-log test above.
    for i in range(20):
        store.append(_entry(rule_id="R-X", action="dismiss", finding_id=f"d-{i}"))
    out = store.confidence_for_rule("R-X")
    assert out["bucket"] == "low"
    assert out["dismisses"] == 20
