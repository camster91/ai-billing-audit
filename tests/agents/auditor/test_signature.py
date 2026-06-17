"""Smoke test for the Auditor signature + AuditorModule wiring.

Pins the end-to-end behaviour of the auditor stack against a
:class:`dspy.utils.DummyLM` so the suite stays hermetic (no network,
no API key) while still exercising the real DSPy
``Predict`` -> :class:`dspy.JSONAdapter` -> :class:`dspy.Prediction`
round-trip.

What's pinned
-------------

(a) The :class:`dspy.JSONAdapter` parses the LM's canned response
    into the Python types declared on :class:`AuditClaim`:
    ``has_discrepancy: bool``, ``confidence_score: float``,
    ``findings: list[str]``.

(b) :class:`AuditorModule` returns a :class:`dspy.Prediction` whose
    three declared fields are populated. Covered by both a
    happy-path case (the auditor finds a discrepancy and reports
    findings) and a negative case (the auditor finds no
    discrepancy and reports an empty findings list).

(c) ``confidence_score`` outside the declared ``[0.0, 1.0]`` range
    is not silently coerced into a different type or a different
    numeric range by the adapter or the wrapper. The current
    contract is "what the LM emits is what the caller sees" — this
    test pins that contract so a future change that introduces
    silent normalisation is forced to update the test (and the
    contract) explicitly.

The tests deliberately avoid touching the real LM stack: the
``DummyLM`` is configured with the JSON adapter at construction time
so its canned dicts are rendered as raw JSON object strings, which is
exactly what :class:`dspy.JSONAdapter` expects to parse.
"""

from __future__ import annotations

import dspy  # type: ignore[import-untyped]  # dspy ships no py.typed marker
import pytest

from ai_billing_audit.auditor_module import AuditClaimInput, AuditorModule
from ai_billing_audit.auditor_signature import AuditClaim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wire_dummy_lm(answers: list[dict]) -> dspy.utils.DummyLM:
    """Install a ``DummyLM`` + the global ``JSONAdapter`` for a test.

    Returns the configured :class:`dspy.utils.DummyLM` so individual
    tests can also inspect it (e.g. confirm it was actually called).
    """
    dummy = dspy.utils.DummyLM(answers, adapter=dspy.JSONAdapter())
    dspy.configure(lm=dummy, adapter=dspy.JSONAdapter())
    return dummy


def _sample_input(
    clinical_note: str = "Patient seen for cough and low-grade fever.",
    billed_claim: str = "99213",
    payer_rules: str = "rule: documentation must support E/M level",
) -> AuditClaimInput:
    return AuditClaimInput(
        clinical_note=clinical_note,
        billed_claim=billed_claim,
        payer_rules=payer_rules,
    )


# ---------------------------------------------------------------------------
# (a) Signature: JSONAdapter parses the canned response into the declared types
# ---------------------------------------------------------------------------


def test_json_adapter_parses_dummy_response_into_declared_types() -> None:
    """The :class:`dspy.JSONAdapter` configured on the global ``dspy``
    settings must turn the ``DummyLM``'s canned dict into a JSON
    object string, parse it, and emit a :class:`dspy.Prediction`
    whose attributes carry the Python types declared on
    :class:`AuditClaim`.
    """
    canned = {
        "has_discrepancy": True,
        "confidence_score": 0.85,
        "findings": ["documentation missing for time-based code"],
    }
    _wire_dummy_lm([canned])
    module = AuditorModule()

    result = module.forward(_sample_input())

    assert isinstance(result, dspy.Prediction), (
        f"forward must return a dspy.Prediction; got {type(result).__name__}"
    )
    # The three declared outputs must be present, populated, and
    # carry the Python types the signature promises.
    assert hasattr(result, "has_discrepancy")
    assert hasattr(result, "confidence_score")
    assert hasattr(result, "findings")

    assert isinstance(result.has_discrepancy, bool), (
        f"has_discrepancy must parse as bool; got {type(result.has_discrepancy).__name__}"
    )
    assert isinstance(result.confidence_score, float), (
        f"confidence_score must parse as float; got {type(result.confidence_score).__name__}"
    )
    assert isinstance(result.findings, list), (
        f"findings must parse as list; got {type(result.findings).__name__}"
    )
    assert all(isinstance(f, str) for f in result.findings), (
        f"findings must be list[str]; element types were "
        f"{[type(f).__name__ for f in result.findings]}"
    )

    # Values round-trip unchanged.
    assert result.has_discrepancy is True
    assert result.confidence_score == pytest.approx(0.85)
    assert result.findings == canned["findings"]


def test_signature_declares_three_inputs_and_three_outputs() -> None:
    """The signature's :attr:`fields` dict must expose the three
    inputs and three outputs in the declared order. This guards
    against a refactor that drops a field or reorders them and
    silently changes the LM prompt.
    """
    fields = AuditClaim.fields
    field_names = list(fields.keys())
    assert field_names == [
        "clinical_note",
        "billed_claim",
        "payer_rules",
        "has_discrepancy",
        "confidence_score",
        "findings",
    ], f"AuditClaim.fields order must match the declared order; got {field_names}"


# ---------------------------------------------------------------------------
# (b) AuditorModule returns a dspy.Prediction with the three fields populated
# ---------------------------------------------------------------------------


def test_happy_path_discrepancy_found_populates_all_three_fields() -> None:
    """Happy path: the auditor finds a discrepancy, reports
    non-empty findings, and sets ``has_discrepancy=True``.

    Pins that all three output attributes are populated (not None,
    not missing) and carry the right Python types.
    """
    canned_findings = [
        "time threshold not met: 12 minutes documented vs 20 required",
        "medical decision-making not documented",
    ]
    _wire_dummy_lm(
        [
            {
                "has_discrepancy": True,
                "confidence_score": 0.91,
                "findings": canned_findings,
            }
        ]
    )
    module = AuditorModule()

    result = module.forward(_sample_input())

    assert isinstance(result, dspy.Prediction)
    # All three fields populated, none of them None.
    assert result.has_discrepancy is not None
    assert result.confidence_score is not None
    assert result.findings is not None

    # Type contracts.
    assert isinstance(result.has_discrepancy, bool)
    assert isinstance(result.confidence_score, float)
    assert isinstance(result.findings, list)
    assert all(isinstance(f, str) for f in result.findings)

    # Happy-path value contracts.
    assert result.has_discrepancy is True
    assert result.confidence_score == pytest.approx(0.91)
    assert result.findings == canned_findings
    assert len(result.findings) == 2


def test_negative_path_clean_claim_populates_all_three_fields() -> None:
    """Negative case: the claim is clean, ``has_discrepancy=False``,
    and ``findings`` is an empty list (not None, not missing).

    Pins the contract that a clean claim still produces a fully
    populated :class:`dspy.Prediction` — downstream code should be
    able to call ``result.findings`` and ``result.confidence_score``
    unconditionally.
    """
    _wire_dummy_lm(
        [
            {
                "has_discrepancy": False,
                "confidence_score": 0.97,
                "findings": [],
            }
        ]
    )
    module = AuditorModule()

    result = module.forward(_sample_input())

    assert isinstance(result, dspy.Prediction)
    assert result.has_discrepancy is False
    assert result.confidence_score == pytest.approx(0.97)
    # findings must be a list (callers iterate it), and empty for a
    # clean claim.
    assert result.findings == []
    assert isinstance(result.findings, list)


# ---------------------------------------------------------------------------
# (c) confidence_score outside [0,1] is not silently re-typed or normalised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "out_of_range_value",
    [5.0, -0.3, 1.5, 100.0, -1.0],
)
def test_confidence_score_outside_unit_interval_is_not_silently_normalised(
    out_of_range_value: float,
) -> None:
    """Current contract: the wrapper and the JSON adapter pass
    ``confidence_score`` through unchanged. A value outside ``[0, 1]``
    is delivered to the caller as the same float the LM emitted —
    it is **not** silently clamped, retyped, or coerced to a
    different numeric range.

    This test pins that contract deliberately. If a future change
    introduces clamping (which would be a reasonable enhancement —
    the signature's ``desc`` says the value is constrained to
    ``[0.0, 1.0]``), this test will fail and force the contract
    change to be made explicit: update the test to assert the new
    behaviour, and document the new contract in
    :class:`AuditorModule`'s docstring.
    """
    _wire_dummy_lm(
        [
            {
                "has_discrepancy": True,
                "confidence_score": out_of_range_value,
                "findings": ["x"],
            }
        ]
    )
    module = AuditorModule()

    result = module.forward(_sample_input())

    # Type must still be float (no silent retyping to str / int / None).
    assert isinstance(result.confidence_score, float), (
        f"confidence_score must remain a float even when out of range; "
        f"got {type(result.confidence_score).__name__}"
    )
    # Value must round-trip unchanged.
    assert result.confidence_score == pytest.approx(out_of_range_value), (
        f"confidence_score outside [0, 1] is currently passed through "
        f"unchanged; expected {out_of_range_value!r}, got "
        f"{result.confidence_score!r}. If clamping is being introduced, "
        f"update this test and the AuditorModule docstring to reflect "
        f"the new contract."
    )


def test_confidence_score_at_boundary_accepted_unchanged() -> None:
    """The boundary values 0.0 and 1.0 are explicitly allowed by the
    signature's ``[0.0, 1.0]`` constraint and must round-trip
    unchanged.
    """
    for boundary in (0.0, 1.0):
        _wire_dummy_lm(
            [
                {
                    "has_discrepancy": boundary == 1.0,
                    "confidence_score": boundary,
                    "findings": [],
                }
            ]
        )
        module = AuditorModule()
        result = module.forward(_sample_input())
        assert isinstance(result.confidence_score, float)
        assert result.confidence_score == pytest.approx(boundary)
