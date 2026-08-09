"""Unit tests for the smartness-test smoke assertion.

These tests verify the *assertion logic* of the smoke test added to
``scripts/smartness_test.main()``. They do NOT call the LLM — they
exercise ``_assert_smoke_test_passes`` with synthetic prediction lists
to pin the contract:

* exact set equality on rule_ids is required (both directions)
* missing-rule and extra-rule failures are reported distinctly
* the failure message identifies the encounter, the diff, and the
  likely cause (LLM config drift)
* a passing prediction list raises no error

The end-to-end smoke (load fixture + run LLM + assert) is exercised
in CI by ``scripts/smartness_test.main()`` itself and is not in scope
for these unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from smartness_test import (  # noqa: E402
    SMOKE_ENC_ID,
    SMOKE_EXPECTED_RULE_IDS,
    SmokeTestError,
    _assert_smoke_test_passes,
)


def _finding(rule_id: str, rule_ids: list[str] | None = None) -> dict:
    """Build a minimal prediction dict matching the real shape."""
    return {
        "finding_id": "f",
        "category": "test",
        "severity": "low",
        "suggested_code": "",
        "rule_id": rule_id,
        "rule_ids": rule_ids if rule_ids is not None else [rule_id],
        "quote": "x",
        "explanation": "",
    }


# ---------- The known answer is what we expect ----------


def test_expected_rule_ids_is_complete_set() -> None:
    """The smoke fixture must cover all 4 of enc_10000's gold rule_ids.

    If the fixture changes, update ``SMOKE_EXPECTED_RULE_IDS``
    deliberately — don't let it silently desync from val.json.
    """
    assert SMOKE_EXPECTED_RULE_IDS == frozenset(
        {
            "rule_em_002",
            "rule_icd_002",
            "rule_ecg_001",
            "rule_missing_dx_001",
        }
    )
    assert SMOKE_ENC_ID == "enc_10000"


# ---------- Passing cases ----------


def test_exact_match_passes() -> None:
    """When the model emits exactly the expected rule_ids, no error."""
    preds = [_finding(r) for r in sorted(SMOKE_EXPECTED_RULE_IDS)]
    _assert_smoke_test_passes(preds)  # must not raise


def test_exact_match_with_rule_id_only_singular_passes() -> None:
    """The harness also accepts rule_id as a string and rule_ids as a list.

    The assertion must read both forms (mirroring ``_findings_match``).
    """
    # Two findings: one with rule_id only, one with rule_ids list only.
    preds = [
        {"rule_id": "rule_em_002", "rule_ids": [], "quote": "x"},
        {"rule_id": "", "rule_ids": ["rule_icd_002"], "quote": "x"},
        {"rule_id": "rule_ecg_001", "rule_ids": ["rule_ecg_001"], "quote": "x"},
        {
            "rule_id": "rule_missing_dx_001",
            "rule_ids": ["rule_missing_dx_001"],
            "quote": "x",
        },
    ]
    _assert_smoke_test_passes(preds)


def test_extra_unrelated_predictions_pass() -> None:
    """Extra rule_ids outside the expected set cause failure.

    (This documents the strict contract: the smoke test catches the
    'model now overcalls' regression too, not just the 'model now
    undercalls' one.)
    """
    preds = [_finding(r) for r in sorted(SMOKE_EXPECTED_RULE_IDS)] + [
        _finding("rule_spurious_999"),
    ]
    with pytest.raises(SmokeTestError) as ei:
        _assert_smoke_test_passes(preds)
    assert "rule_spurious_999" in str(ei.value)
    assert "unexpected" in str(ei.value).lower()


# ---------- Failing cases ----------


def test_missing_rule_raises() -> None:
    """If a known-good rule_id is dropped, smoke fails loudly."""
    preds = [
        _finding("rule_em_002"),
        _finding("rule_icd_002"),
        _finding("rule_ecg_001"),
        # rule_missing_dx_001 missing
    ]
    with pytest.raises(SmokeTestError) as ei:
        _assert_smoke_test_passes(preds)
    msg = str(ei.value)
    assert "rule_missing_dx_001" in msg
    assert "missing" in msg.lower()
    assert "LLM config" in msg or "LLM_MODEL" in msg or "drift" in msg.lower()


def test_wrong_rule_id_raises() -> None:
    """If a known rule_id is replaced with a different one, smoke fails."""
    preds = [
        _finding("rule_em_002"),
        _finding("rule_icd_002"),
        _finding("rule_ecg_001"),
        _finding("rule_missing_dx_002"),  # wrong — should be _001
    ]
    with pytest.raises(SmokeTestError) as ei:
        _assert_smoke_test_passes(preds)
    msg = str(ei.value)
    assert "rule_missing_dx_001" in msg
    assert "rule_missing_dx_002" in msg
    assert "missing" in msg.lower()
    assert "unexpected" in msg.lower()


def test_empty_predictions_raises_with_all_missing() -> None:
    """Zero predictions → all expected rule_ids reported as missing."""
    with pytest.raises(SmokeTestError) as ei:
        _assert_smoke_test_passes([])
    msg = str(ei.value)
    for rid in SMOKE_EXPECTED_RULE_IDS:
        assert rid in msg
    assert SMOKE_ENC_ID in msg


def test_error_message_includes_known_fix_hint() -> None:
    """Failure message must point the operator at the fix path."""
    with pytest.raises(SmokeTestError) as ei:
        _assert_smoke_test_passes([])
    msg = str(ei.value)
    # Operator guidance — these tokens must all be present.
    assert "ZORVA_SKIP_SMOKE=1" in msg
    assert "LLM_MODEL" in msg or "prompts/" in msg
    assert SMOKE_ENC_ID in msg


def test_smoke_error_is_runtime_error_subclass() -> None:
    """SmokeTestError must subclass RuntimeError for generic-except safety.

    Callers that catch RuntimeError should still distinguish smoke
    failures, but the type must be a RuntimeError so the harness can
    surface it through a single broad except if needed.
    """
    assert issubclass(SmokeTestError, RuntimeError)


def test_custom_expected_set_overrides_default() -> None:
    """The ``expected_rule_ids`` parameter lets tests pin bespoke fixtures.

    This is the hook future audits will use to add more smoke
    fixtures without rewriting the assertion.
    """
    custom = frozenset({"rule_a", "rule_b"})
    # Match against custom
    _assert_smoke_test_passes(
        [_finding("rule_a"), _finding("rule_b")], expected_rule_ids=custom
    )
    # Mismatch against custom (would have passed against the default)
    with pytest.raises(SmokeTestError):
        _assert_smoke_test_passes([_finding("rule_em_002")], expected_rule_ids=custom)
