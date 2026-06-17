"""DSPy wrapper that turns :class:`AuditClaim` into a callable agent.

The :class:`AuditorModule` is the thin adapter the rest of the
ai-billing-audit stack calls when it wants an LLM-driven audit
verdict. It composes a single :class:`dspy.Predict` over
:class:`AuditClaim` and configures the global DSPy settings to use
:class:`dspy.JSONAdapter` so the LM is asked to emit structured
JSON matching the signature's outputs.

A new contributor can wire the auditor into a pipeline with the
10-line canonical call at the end of this docstring (``Canonical
call``); everything between the ``Design notes`` and ``Canonical
call`` sections is context for why the wrapper is shaped this way,
not a prerequisite for using it.

Design notes
------------
* The module is framework-agnostic: it imports nothing from Flask,
  FastAPI, or any web layer. Downstream code wires it into whichever
  transport the application uses.

* The JSON adapter is configured at module-import time via
  :func:`dspy.configure`. This is intentional: it pins the adapter
  used to parse LM responses to :class:`dspy.JSONAdapter` regardless
  of any adapter the caller may have previously configured, so the
  output of ``forward`` is always a :class:`dspy.Prediction` whose
  attributes match :class:`AuditClaim`'s typed outputs.

* The :class:`dspy.Predict` instance is created once in ``__init__``
  and reused across calls. This matches DSPy's intended usage and
  keeps the per-call cost to a single LM invocation.

* The :class:`AuditClaimInput` dataclass is a thin input-only
  container. ``dspy.Signature`` is a pydantic model that validates
  *all* fields (inputs and outputs) on construction, so a caller
  can't build a partially-populated ``AuditClaim`` to pass into
  ``forward``. ``AuditClaimInput`` exists to give downstream code
  a single named argument (``forward(audit_claim=...)``) without
  paying that validation cost or having to supply dummy outputs.

* The module does not configure a concrete :class:`dspy.LM`. The
  caller is expected to ``dspy.configure(lm=...)`` separately
  (typically at application startup), so the same module can be
  exercised in tests with :class:`dspy.utils.DummyLM` and in
  production with the real provider.

Inputs and outputs
------------------
**Inputs** (passed as a single :class:`AuditClaimInput` to
``forward``):

* ``clinical_note`` (``str``) — the full clinical encounter note.
* ``billed_claim`` (``str``) — the claim being submitted
  (CPT/HCPCS + ICD-10-CM + modifiers + place of service + any
  other billing fields).
* ``payer_rules`` (``str``) — the retrieved payer rules for this
  encounter, formatted as one rule per block.

**Outputs** (read as attributes on the returned
:class:`dspy.Prediction`):

* ``has_discrepancy`` (``bool``) — ``True`` when the claim is not
  supported by the documentation under the retrieved rules.
* ``confidence_score`` (``float``) — calibrated confidence in
  :math:`[0.0, 1.0]`.
* ``findings`` (``list[str]``) — one concise discrepancy
  statement per problem; empty list when ``has_discrepancy`` is
  ``False``.

How ``dspy.JSONAdapter`` is configured
--------------------------------------
The adapter is pinned globally in :meth:`AuditorModule.__init__` via::

    dspy.configure(adapter=dspy.JSONAdapter())

:func:`dspy.configure` is idempotent: it replaces whichever adapter
(if any) was previously configured, so constructing two
:class:`AuditorModule` instances in the same process is safe.

``dspy.JSONAdapter`` accepts two optional kwargs:

* ``callbacks`` — list of :class:`dspy.utils.callback.BaseCallback`
  for hooking adapter events; default ``None``.
* ``use_native_function_calling`` (``bool``) — when ``True`` (the
  default) the adapter asks providers that support tool/function
  calling to emit a structured call rather than a raw JSON string;
  when ``False`` it falls back to prompt-then-parse. Override only
  if a specific provider produces malformed function calls; the
  default is correct for Claude, OpenAI, Gemini, and the
  MiniMax-M3 backend used in this project.

Migrating to :class:`dspy.ChainOfThought`
------------------------------------------
The wrapper uses :class:`dspy.Predict` for speed. To trade latency
for higher-quality reasoning (the auditor is the slowest step in the
pipeline and the obvious place to spend extra tokens), swap the
``self.predict = ...`` line in :meth:`__init__` to::

    self.predict = dspy.ChainOfThought(AuditClaim)

:class:`dspy.ChainOfThought` adds a ``reasoning`` output field on
top of the signature's declared outputs, so the returned
:class:`dspy.Prediction` gains a ``reasoning`` (``str``) attribute
that downstream code can log for audit trails. The three
:class:`AuditClaim` outputs (``has_discrepancy``, ``confidence_score``,
``findings``) are unchanged.

Perf/quality tradeoff:

* :class:`dspy.Predict` — one LM call per ``forward``; no reasoning
  preamble; ~1x token cost; faster, cheaper, weaker on ambiguous
  notes.
* :class:`dspy.ChainOfThought` — one LM call per ``forward`` (still
  one round-trip, not two), but the LM is prompted to emit a
  reasoning block *before* the JSON outputs, so prompt token count
  roughly doubles and latency rises ~1.5-2x. Quality improves
  noticeably on borderline encounters where the auditor has to
  weigh conflicting rules; effect is small on clean-cut cases.

The contract tests in ``tests/test_auditor_module.py`` pin the
``Predict`` shape; if you swap to ``ChainOfThought`` you will need
to relax or extend the tests that assert the prediction's exact
attribute set (e.g. ``test_forward_returns_dspy_prediction_instance``,
the ``test_forward_populates_*`` tests, and
``test_forward_passes_inputs_through_to_predict``).

Canonical call
--------------

.. code-block:: python

    import dspy
    from ai_billing_audit.auditor_module import AuditClaimInput, AuditorModule
    dspy.configure(lm=dspy.LM("anthropic/claude-sonnet-4-5"))
    auditor = AuditorModule()  # pins dspy.JSONAdapter() globally
    result = auditor.forward(AuditClaimInput(
        clinical_note=note_text, billed_claim=claim_json, payer_rules=rules_text,
    ))
    # result.has_discrepancy: bool  /  confidence_score: float  /  findings: list[str]
"""

from __future__ import annotations

from dataclasses import dataclass

import dspy  # type: ignore[import-untyped]  # dspy ships no py.typed marker yet

from ai_billing_audit.auditor_signature import AuditClaim

__all__ = ["AuditorModule", "AuditClaimInput"]


@dataclass(frozen=True)
class AuditClaimInput:
    """The three inputs the auditor needs to run an audit.

    Bundling them in a single immutable container lets the rest of
    the agent stack call ``forward(audit_claim=...)`` with a named
    argument without having to thread the three fields through every
    call site individually.

    Attributes
    ----------
    clinical_note
        The full clinical encounter note, as written by the provider.
    billed_claim
        The claim being submitted (CPT/HCPCS + ICD-10-CM + modifiers
        + place of service + any other billing fields).
    payer_rules
        The retrieved payer rules for this encounter, formatted as
        one rule per block.
    """

    clinical_note: str
    billed_claim: str
    payer_rules: str


class AuditorModule(dspy.Module):
    """Thin DSPy wrapper that runs :class:`AuditClaim` as a Predict step.

    The module exposes the three :class:`AuditClaim` outputs
    (:attr:`has_discrepancy`, :attr:`confidence_score`,
    :attr:`findings`) as attributes on the returned
    :class:`dspy.Prediction`, with their declared Python types
    (``bool``, ``float``, ``list[str]``).

    A single shared :class:`dspy.Predict` is built in ``__init__`` and
    re-used on every call. The JSON adapter is configured globally
    on first import, so consumers don't need to wire it themselves.
    """

    def __init__(self) -> None:
        super().__init__()
        # Pin the global adapter to JSONAdapter so the LM response is
        # parsed as structured JSON matching the AuditClaim outputs.
        # ``dspy.configure`` is idempotent: it replaces whichever
        # adapter (if any) was previously configured.
        dspy.configure(adapter=dspy.JSONAdapter())
        self.predict = dspy.Predict(AuditClaim)

    def forward(self, audit_claim: AuditClaimInput) -> dspy.Prediction:
        """Run the auditor over a single :class:`AuditClaimInput`.

        Parameters
        ----------
        audit_claim
            An :class:`AuditClaimInput` carrying the three inputs
            (:attr:`~AuditClaimInput.clinical_note`,
            :attr:`~AuditClaimInput.billed_claim`,
            :attr:`~AuditClaimInput.payer_rules`).

        Returns
        -------
        dspy.Prediction
            A prediction whose ``has_discrepancy`` (``bool``),
            ``confidence_score`` (``float``), and ``findings``
            (``list[str]``) attributes are populated from the LM's
            structured response.
        """
        return self.predict(
            clinical_note=audit_claim.clinical_note,
            billed_claim=audit_claim.billed_claim,
            payer_rules=audit_claim.payer_rules,
        )
