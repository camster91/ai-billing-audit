"""DSPy signatures for the billing-audit Auditor agent.

The Auditor compares a clinical encounter to the claim being submitted
and the retrieved payer rules, then emits a structured discrepancy
report. ``AuditClaim`` is the thin declarative contract the LM is asked
to honour; the prompt-runner in :mod:`ai_billing_audit.auditor` is
responsible for wiring concrete encounters and rules into instances of
this signature and parsing the LM's response back into a typed
``AuditResult``.
"""

from __future__ import annotations

import dspy  # type: ignore[import-untyped]  # dspy ships no py.typed marker yet

__all__ = ["AuditClaim"]


class AuditClaim(dspy.Signature):
    """Audit a single billed claim against the clinical note and retrieved payer rules.

    Given a clinical note, the claim being submitted, and the
    payer-specific rules retrieved for this encounter, decide whether
    the claim is justified by the documentation. When it is not, list
    each discrepancy as a concise statement grounded in the note and
    the rules.
    """

    clinical_note: str = dspy.InputField(
        desc=(
            "The full clinical encounter note for the visit, as written "
            "by the provider. Verbatim — do not summarise, paraphrase, "
            "or omit sections. The LM will quote from this text in its "
            "findings, so it must be present in full."
        ),
    )
    billed_claim: str = dspy.InputField(
        desc=(
            "The claim being submitted, serialised as a JSON object or a "
            "human-readable summary. Must include the procedure codes "
            "(CPT/HCPCS), diagnosis codes (ICD-10-CM), units, "
            "modifiers, place of service, and any other billing fields "
            "the payer needs to adjudicate the claim."
        ),
    )
    payer_rules: str = dspy.InputField(
        desc=(
            "The retrieved payer rules for this encounter, formatted as "
            "one rule per block with each block containing a stable "
            "rule_id and the rule text. These are the only rules the "
            "auditor is allowed to cite — do not invent or generalise "
            "from outside this set."
        ),
    )

    has_discrepancy: bool = dspy.OutputField(
        desc=(
            "True if the documentation does not justify the billed "
            "claim under the retrieved rules, or if any rule's required "
            "element is missing or contradicted. False if the claim is "
            "supported by the encounter. Be conservative: a claim that "
            "is not clearly contradicted is not a discrepancy."
        ),
    )
    confidence_score: float = dspy.OutputField(
        desc=(
            "Calibrated confidence in the audit verdict, constrained to "
            "the closed interval [0.0, 1.0]. 1.0 means the auditor is "
            "fully certain (a rule is directly contradicted by the "
            "note, or the note unambiguously supports the claim). "
            "0.0 means the auditor is certain the encounter does not "
            "bear on this claim. Use values near the extremes only "
            "when the evidence is decisive; mid-range values are "
            "appropriate when the documentation is ambiguous."
        ),
    )
    findings: list[str] = dspy.OutputField(
        desc=(
            "Concise, one-sentence discrepancy statements, one per "
            "problem. Each statement must name the specific rule or "
            "requirement that is violated and the supporting fact from "
            "the clinical note. Empty list when has_discrepancy is "
            "False. Do not restate the encounter, the claim, or the "
            "rules in the findings — only the discrepancies."
        ),
    )
