"""Tests for the DSPy wrapper in ``ai_billing_audit.auditor_module``.

The wrapper is the contract the rest of the agent stack calls to
invoke the LLM-driven auditor. These tests pin its behaviour against
a :class:`dspy.utils.DummyLM` so the test suite stays hermetic (no
network, no API key) while still exercising the real DSPy
``Predict`` -> ``JSONAdapter`` -> ``Prediction`` round-trip.

What's pinned
-------------
* :class:`AuditorModule` is a :class:`dspy.Module` subclass.
* ``__init__`` configures :class:`dspy.JSONAdapter` as the global
  DSPy adapter and builds a :class:`dspy.Predict` over
  :class:`AuditClaim`.
* ``forward`` returns a :class:`dspy.Prediction` whose
  ``has_discrepancy`` is ``bool``, ``confidence_score`` is
  ``float``, and ``findings`` is ``list[str]`` — the three outputs
  declared on :class:`AuditClaim`.
* The module is framework-agnostic: it does not import Flask,
  FastAPI, or any web framework.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

import dspy  # type: ignore[import-untyped]  # dspy ships no py.typed marker
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor_module import (  # noqa: E402
    AuditClaimInput,
    AuditorModule,
)
from ai_billing_audit.auditor_signature import AuditClaim  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(
    clinical_note: str = "Patient presents with cough.",
    billed_claim: str = "99213",
    payer_rules: str = "rule 1: documentation must support E/M level",
) -> AuditClaimInput:
    """Build an ``AuditClaimInput`` with the three inputs populated."""
    return AuditClaimInput(
        clinical_note=clinical_note,
        billed_claim=billed_claim,
        payer_rules=payer_rules,
    )


def _wire_dummy_lm(
    answers: list[dict],
) -> None:
    """Install a ``DummyLM`` and the global ``JSONAdapter`` for a test.

    The :class:`dspy.utils.DummyLM` is given the ``JSONAdapter`` at
    construction time so it renders its canned answers as a raw JSON
    object string, which is exactly what ``JSONAdapter`` expects to
    parse.
    """
    dummy = dspy.utils.DummyLM(answers, adapter=dspy.JSONAdapter())
    dspy.configure(lm=dummy, adapter=dspy.JSONAdapter())


def _module_uses_framework(forbidden: str) -> bool:
    """AST-level check whether the module file imports ``forbidden``.

    Scanning the source text would false-positive on words like
    "flask" appearing in docstrings or comments; an AST walk over
    the module's top-level ``Import`` and ``ImportFrom`` nodes is
    exact.
    """
    module = sys.modules[AuditorModule.__module__]
    source_file = inspect.getsourcefile(module)
    assert source_file is not None, "auditor_module must be loaded from a file"
    source_path = Path(source_file)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == forbidden:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root == forbidden:
                return True
    return False


# ---------------------------------------------------------------------------
# Class shape
# ---------------------------------------------------------------------------


def test_auditor_module_is_a_dspy_module_subclass() -> None:
    """The wrapper must subclass ``dspy.Module`` so it composes with the
    rest of the DSPy stack (telemetry, optimisers, async, etc.)."""
    assert issubclass(AuditorModule, dspy.Module), (
        "AuditorModule must subclass dspy.Module so it can be used as "
        "a DSPy program in optimisation and serving."
    )


def test_auditor_module_is_top_level_importable() -> None:
    """The module must expose ``AuditorModule`` at the top level."""
    from ai_billing_audit import auditor_module

    assert "AuditorModule" in auditor_module.__all__, (
        "AuditorModule must be listed in __all__ so star-imports get it"
    )


def test_audit_claim_input_is_exported() -> None:
    """``AuditClaimInput`` must be listed in ``__all__`` so downstream
    callers can import it via ``from ai_billing_audit.auditor_module
    import AuditClaimInput``."""
    from ai_billing_audit import auditor_module

    assert "AuditClaimInput" in auditor_module.__all__


def test_audit_claim_input_is_frozen_dataclass_with_three_string_fields() -> None:
    """``AuditClaimInput`` is the named-argument bundle passed to
    ``forward``; it must carry exactly the three string inputs that
    :class:`AuditClaim` declares."""
    import typing

    # Dataclass ``f.type`` is a forward-ref string under ``from __future__
    # import annotations``; resolve via typing.get_type_hints.
    resolved = typing.get_type_hints(AuditClaimInput)
    assert resolved == {
        "clinical_note": str,
        "billed_claim": str,
        "payer_rules": str,
    }
    # Frozen so callers can't accidentally mutate a shared instance
    # between threads. dataclasses.FrozenInstanceError is an
    # AttributeError subclass, so this is the right exception class
    # to assert.
    with pytest.raises(AttributeError):
        instance = AuditClaimInput(
            clinical_note="x", billed_claim="y", payer_rules="z"
        )
        instance.clinical_note = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Construction: __init__ configures JSONAdapter + builds a Predict over AuditClaim
# ---------------------------------------------------------------------------


def test_init_configures_json_adapter_globally() -> None:
    """``__init__`` must call ``dspy.configure(adapter=dspy.JSONAdapter())``
    so the LM response is parsed as structured JSON."""
    AuditorModule()
    settings = dspy.settings if hasattr(dspy, "settings") else dspy.dsp.settings
    assert isinstance(settings.adapter, dspy.JSONAdapter), (
        f"AuditorModule.__init__ must set the global adapter to "
        f"dspy.JSONAdapter; got {type(settings.adapter).__name__}"
    )


def test_init_builds_a_predict_over_audit_claim() -> None:
    """The module must compose a single ``dspy.Predict(AuditClaim)``."""
    module = AuditorModule()
    assert hasattr(module, "predict"), "AuditorModule must expose a 'predict' attribute"
    assert isinstance(module.predict, dspy.Predict), (
        f"module.predict must be a dspy.Predict; got {type(module.predict).__name__}"
    )
    # DSPy stores the signature on the Predict; verify it matches AuditClaim.
    assert module.predict.signature is AuditClaim, (
        "AuditorModule.predict must be dspy.Predict(AuditClaim)"
    )


# ---------------------------------------------------------------------------
# Forward: returns a Prediction with typed outputs
# ---------------------------------------------------------------------------


def test_forward_returns_dspy_prediction_instance() -> None:
    """``forward`` must return a ``dspy.Prediction``."""
    _wire_dummy_lm(
        [{"has_discrepancy": True, "confidence_score": 0.9, "findings": ["x"]}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert isinstance(result, dspy.Prediction), (
        f"forward must return dspy.Prediction; got {type(result).__name__}"
    )


def test_forward_populates_has_discrepancy_as_bool() -> None:
    _wire_dummy_lm(
        [{"has_discrepancy": True, "confidence_score": 0.9, "findings": ["x"]}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert hasattr(result, "has_discrepancy"), (
        "Prediction must expose 'has_discrepancy' as an attribute"
    )
    assert isinstance(result.has_discrepancy, bool), (
        f"has_discrepancy must be a bool; got {type(result.has_discrepancy).__name__}"
    )
    assert result.has_discrepancy is True


def test_forward_populates_confidence_score_as_float() -> None:
    _wire_dummy_lm(
        [{"has_discrepancy": False, "confidence_score": 0.42, "findings": []}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert hasattr(result, "confidence_score"), (
        "Prediction must expose 'confidence_score' as an attribute"
    )
    assert isinstance(result.confidence_score, float), (
        f"confidence_score must be a float; got {type(result.confidence_score).__name__}"
    )
    assert result.confidence_score == pytest.approx(0.42)


def test_forward_populates_findings_as_list_of_strings() -> None:
    canned = ["rule 1 violated: documentation missing", "rule 2 violated: time not met"]
    _wire_dummy_lm(
        [{"has_discrepancy": True, "confidence_score": 0.88, "findings": canned}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert hasattr(result, "findings"), "Prediction must expose 'findings' as an attribute"
    assert isinstance(result.findings, list), (
        f"findings must be a list; got {type(result.findings).__name__}"
    )
    assert all(isinstance(f, str) for f in result.findings), (
        f"findings must be list[str]; got element types "
        f"{[type(f).__name__ for f in result.findings]}"
    )
    assert result.findings == canned


def test_forward_with_empty_findings_returns_empty_list() -> None:
    """When the LM reports no discrepancy, findings is an empty list (not None)."""
    _wire_dummy_lm(
        [{"has_discrepancy": False, "confidence_score": 0.99, "findings": []}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert result.findings == []
    assert isinstance(result.findings, list)


def test_forward_with_low_confidence_returns_float_in_unit_interval() -> None:
    """The constraint [0.0, 1.0] lives in the signature's desc; the
    JSONAdapter is happy to pass any number through. Pin that the
    wrapper doesn't accidentally reformat the value into a string
    or a normalised float that loses precision."""
    _wire_dummy_lm(
        [{"has_discrepancy": True, "confidence_score": 0.0, "findings": ["x"]}]
    )
    module = AuditorModule()
    result = module.forward(_make_input())
    assert result.confidence_score == pytest.approx(0.0)
    assert isinstance(result.confidence_score, float)


def test_forward_is_repeatable_across_calls() -> None:
    """The wrapper must produce a fresh Prediction on each call (the
    Predict instance is shared, but each forward invocation is
    independent)."""
    answers = [
        {"has_discrepancy": True, "confidence_score": 0.5, "findings": ["a"]},
        {"has_discrepancy": False, "confidence_score": 0.7, "findings": []},
    ]
    _wire_dummy_lm(answers)
    module = AuditorModule()
    r1 = module.forward(_make_input())
    r2 = module.forward(_make_input())
    assert r1.has_discrepancy is True
    assert r2.has_discrepancy is False
    assert r1.findings == ["a"]
    assert r2.findings == []


def test_forward_passes_inputs_through_to_predict() -> None:
    """``forward`` must thread the three inputs from ``AuditClaimInput``
    into the underlying ``dspy.Predict`` call. We replace the
    predict's ``__call__`` with a spy via the instance, then restore
    it."""
    _wire_dummy_lm(
        [{"has_discrepancy": False, "confidence_score": 1.0, "findings": []}]
    )
    module = AuditorModule()
    predict = module.predict
    captured: dict = {}

    class _Spy:
        def __init__(self, inner: dspy.Predict) -> None:
            self._inner = inner

        def __call__(self, **kwargs):
            captured.update(kwargs)
            return self._inner(**kwargs)

    spy = _Spy(predict)
    # Monkey-patch the instance attribute to point at the spy. This
    # works because dspy.Module.__call__ does ``self.forward(...)``
    # and the wrapper's forward does ``self.predict(...)`` — a
    # bound attribute lookup that resolves to the spy instance.
    module.predict = spy  # type: ignore[assignment]
    try:
        module.forward(
            _make_input(
                clinical_note="note-X",
                billed_claim="claim-Y",
                payer_rules="rules-Z",
            )
        )
    finally:
        module.predict = predict  # type: ignore[assignment]

    assert captured.get("clinical_note") == "note-X"
    assert captured.get("billed_claim") == "claim-Y"
    assert captured.get("payer_rules") == "rules-Z"


# ---------------------------------------------------------------------------
# Framework-agnosticism: no web-layer imports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden", ["flask", "fastapi", "starlette", "django"])
def test_module_does_not_import_web_frameworks(forbidden: str) -> None:
    """The wrapper must be framework-agnostic so the rest of the agent
    stack can call it from a worker, a CLI, a web route, or a
    notebook without dragging in a web framework."""
    assert not _module_uses_framework(forbidden), (
        f"AuditorModule's source must not import {forbidden}; the "
        f"wrapper must stay framework-agnostic."
    )


# ---------------------------------------------------------------------------
# Module re-importability: idempotent dspy.configure() in __init__
# ---------------------------------------------------------------------------


def test_module_can_be_reimported_and_reinstantiated() -> None:
    """``dspy.configure`` is process-global, so re-importing the module
    or instantiating it multiple times must not raise. This guards
    against a refactor that accidentally puts a one-shot guard in
    ``__init__`` (e.g. a module-level ``_configured = True`` that
    would break test isolation)."""
    importlib.reload(sys.modules[AuditorModule.__module__])
    module1 = AuditorModule()
    module2 = AuditorModule()
    # Both must be usable; the shared predict instance is fine.
    assert isinstance(module1.predict, dspy.Predict)
    assert isinstance(module2.predict, dspy.Predict)
