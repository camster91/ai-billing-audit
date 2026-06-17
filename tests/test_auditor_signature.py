"""Tests for the DSPy signature in ``ai_billing_audit.auditor_signature``.

The signature is the declarative contract the LM is asked to honour.
These tests pin its shape so a refactor can't quietly drop a field,
reorder inputs, or weaken the field descriptions that drive LM
behaviour.

The signature doesn't need an LLM to validate — DSPy introspects
``AuditClaim.fields`` at class-definition time, so we can assert the
full surface (input/output, order, types, desc strings) without
making any network call.
"""

from __future__ import annotations

import sys
import typing
from pathlib import Path

import dspy
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor_signature import AuditClaim  # noqa: E402


# ---------------------------------------------------------------------------
# Acceptance: signature exists, is a dspy.Signature subclass, and exposes the
# three declared inputs and three declared outputs in the expected order.
# ---------------------------------------------------------------------------


def test_audit_claim_is_a_dspy_signature_subclass() -> None:
    assert issubclass(AuditClaim, dspy.Signature), (
        "AuditClaim must subclass dspy.Signature so it can be used with "
        "dspy.Predict / dspy.ChainOfThought in the auditor module."
    )


def test_audit_claim_fields_in_expected_order() -> None:
    """The three inputs first, then the three outputs, in the order
    declared on the class. DSPy uses the declaration order both for
    prompt rendering and for the LM's expected output order, so this
    is part of the public contract.
    """
    assert list(AuditClaim.fields.keys()) == [
        "clinical_note",
        "billed_claim",
        "payer_rules",
        "has_discrepancy",
        "confidence_score",
        "findings",
    ]


def test_audit_claim_has_exactly_three_inputs_and_three_outputs() -> None:
    fields = AuditClaim.fields
    inputs = [n for n, f in fields.items() if f.json_schema_extra["__dspy_field_type"] == "input"]
    outputs = [n for n, f in fields.items() if f.json_schema_extra["__dspy_field_type"] == "output"]
    assert inputs == ["clinical_note", "billed_claim", "payer_rules"]
    assert outputs == ["has_discrepancy", "confidence_score", "findings"]


# ---------------------------------------------------------------------------
# Contract: each input has the right type and a non-trivial desc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected_type",
    [
        ("clinical_note", str),
        ("billed_claim", str),
        ("payer_rules", str),
    ],
)
def test_input_field_annotations(name: str, expected_type: type) -> None:
    field = AuditClaim.fields[name]
    assert field.annotation is expected_type, (
        f"input {name!r}: expected annotation {expected_type!r}, got {field.annotation!r}"
    )


@pytest.mark.parametrize("name", ["clinical_note", "billed_claim", "payer_rules"])
def test_input_field_has_meaningful_desc(name: str) -> None:
    desc = AuditClaim.fields[name].json_schema_extra.get("desc", "")
    assert desc and len(desc) > 20, (
        f"input {name!r} desc must be a meaningful sentence (>20 chars) so the "
        f"LM receives clear instructions; got {desc!r}"
    )


# ---------------------------------------------------------------------------
# Contract: each output has the right type and a non-trivial desc
# ---------------------------------------------------------------------------


def test_has_discrepancy_is_bool() -> None:
    field = AuditClaim.fields["has_discrepancy"]
    assert field.annotation is bool
    desc = field.json_schema_extra["desc"]
    # The LM is told to be conservative — guard against a future edit
    # that drops the "conservative" cue.
    assert "conservative" in desc.lower(), (
        "has_discrepancy desc should instruct the LM to be conservative; "
        "otherwise the auditor will over-flag."
    )


def test_confidence_score_is_float_and_constrained_to_unit_interval() -> None:
    field = AuditClaim.fields["confidence_score"]
    assert field.annotation is float
    desc = field.json_schema_extra["desc"]
    # The desc must communicate the 0.0-1.0 bound to the LM — DSPy
    # doesn't enforce numeric ranges, so the constraint lives in the
    # prompt text.
    assert "0.0" in desc and "1.0" in desc, (
        f"confidence_score desc must explicitly state the [0.0, 1.0] range; got {desc!r}"
    )


def test_findings_is_list_of_string() -> None:
    field = AuditClaim.fields["findings"]
    origin = typing.get_origin(field.annotation)
    args = typing.get_args(field.annotation)
    assert origin is list, f"findings annotation should be list[X], got {field.annotation!r}"
    assert args == (str,), f"findings should be list[str], got list[{args}]"
    desc = field.json_schema_extra["desc"]
    # Findings must be concise and grounded — guard the two cues.
    assert "concise" in desc.lower() or "one-sentence" in desc.lower(), (
        f"findings desc should require concise, one-sentence entries; got {desc!r}"
    )


# ---------------------------------------------------------------------------
# Contract: class docstring describes the contract
# ---------------------------------------------------------------------------


def test_audit_claim_has_a_descriptive_one_sentence_docstring() -> None:
    assert AuditClaim.__doc__, "AuditClaim needs a docstring describing the contract"
    first_line = AuditClaim.__doc__.strip().split("\n")[0]
    assert first_line.endswith("."), (
        f"docstring should open with a single sentence ending in a period; got {first_line!r}"
    )
    # The opening sentence should mention the inputs/outputs the
    # signature actually has.
    lower = first_line.lower()
    assert "claim" in lower, f"docstring should mention 'claim'; got {first_line!r}"
    assert "clinical note" in lower or "documentation" in lower or "encounter" in lower, (
        f"docstring should mention the clinical note / documentation; got {first_line!r}"
    )
    assert "rule" in lower or "payer" in lower, (
        f"docstring should mention the retrieved rules; got {first_line!r}"
    )


# ---------------------------------------------------------------------------
# Contract: module exposes AuditClaim at the top level (no extra plumbing)
# ---------------------------------------------------------------------------


def test_audit_claim_is_top_level_importable() -> None:
    from ai_billing_audit.auditor_signature import AuditClaim as Imported  # noqa: F401

    assert Imported is AuditClaim


def test_auditor_signature_exports_audit_claim() -> None:
    from ai_billing_audit import auditor_signature

    assert "AuditClaim" in auditor_signature.__all__, (
        "AuditClaim must be listed in __all__ so star-imports get it"
    )
