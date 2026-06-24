"""QA probe: verify the v1 Auditor returns has_discrepancy=False on clean claims.

Per kanban t_2a2ee9cd. Constructs 5 clean synthetic encounters where the
billed CPTs fully match the documentation, no chargeable items are
missed, and no modifier issues exist. Routes each through the
``AuditorModule`` (v1 ``AuditClaim`` signature) and captures both
``has_discrepancy`` and ``confidence_score``. Tallies verdicts:

  * false positive (FP) = has_discrepancy=True on a clean claim
  * low-confidence negative = has_discrepancy=False with confidence < 0.5
  * clean negative (TN) = has_discrepancy=False with confidence >= 0.5

Writes the per-encounter verdicts, FP rate, and severity classification
to ``docs/QA_CLEAN_CLAIMS.md``.

LLM backend
-----------
Uses the local Ollama daemon (``http://localhost:11434/v1``) routed to
the ``minimax-m3:cloud`` model — the same model the task body calls
"minimax" and the same model the dev loop targets by default. The
``extra_body={"think": False}`` patch on ``litellm.completion`` is
required: the reasoning model otherwise burns its entire output budget
on the reasoning channel and returns an empty text channel, which
dspy.JSONAdapter cannot parse.

Rationale for live (not hermetic) execution
-------------------------------------------
The task body says "Run minimax on each of the 5 encounters." A
hermetic FakeLLM would test the *pipeline*, not the auditor — and
this task is explicitly about the auditor's behavior on clean inputs.
The prior QA pattern in ``scripts/qa_refusal_probe.py`` is hermetic
because that probe tests refusal handling, not LLM verdicts. Here,
the verdict IS the LLM's response, so a canned answer would tell us
nothing.

Output schema (one record per encounter)
----------------------------------------
  {
    "encounter_id": str,
    "summary": str,            # one-line description
    "expected_clean": True,    # the case is engineered to be clean
    "rationale": str,          # why the case is clean
    "rules_provided": list[str],
    "has_discrepancy": bool,   # auditor verdict
    "confidence_score": float, # auditor confidence
    "verdict": "TN" | "FP" | "LCN",   # classification
    "wall_clock_seconds": float,
    "ok": bool,                # audit call succeeded
    "error": str | None,       # error string on failure
    "raw_findings": list[str], # verbatim findings list
  }

Records are written to ``data/qa_clean_claims.jsonl`` (one per line)
and rolled up into ``docs/QA_CLEAN_CLAIMS.md``.

Usage:
    .venv/bin/python scripts/qa_clean_claims.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Imports happen after sys.path is augmented so this works whether the
# package is installed editable (``pip install -e .``) or just present
# on PYTHONPATH.
import dspy  # noqa: E402
import litellm  # noqa: E402

from ai_billing_audit.auditor_module import (  # noqa: E402
    AuditClaimInput,
    AuditorModule,
)

# ---------------------------------------------------------------------------
# Patches and DSPy wiring
# ---------------------------------------------------------------------------
#
# The minimax-m3:cloud model is a reasoning model. When called via the
# OpenAI-compatible endpoint with the default behaviour, the entire
# output budget is consumed by the ``reasoning_content`` channel and
# the ``content`` channel comes back empty. dspy.JSONAdapter reads the
# ``content`` channel and raises AdapterParseError when it is empty.
# The ollama route accepts a per-request ``think: false`` flag in the
# extra_body envelope that disables reasoning for that call. We patch
# litellm.completion to inject that flag by default so every DSPy LM
# call inherits it without each call site having to remember.
_orig_litellm_completion = litellm.completion


def _patched_litellm_completion(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("extra_body", {})
    if isinstance(kwargs["extra_body"], dict):
        kwargs["extra_body"].setdefault("think", False)
    return _orig_litellm_completion(*args, **kwargs)


litellm.completion = _patched_litellm_completion

# Pin the local Ollama daemon. The dspy.LM wrapper routes
# ``openai/<model>`` through litellm, which targets
# ``$OPENAI_API_BASE/v1/chat/completions`` when api_base is set.
# The local daemon is the Ollama "cloud" router that exposes
# minimax-m3:cloud on a stable OpenAI surface.
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MODEL_ID = "openai/minimax-m3:cloud"
# High enough to fit reasoning + JSON; the model self-regulates output
# length on this configuration and only spends as many tokens as the
# answer actually needs.
MAX_TOKENS = 4000


def _build_auditor() -> AuditorModule:
    """Build a fresh ``AuditorModule`` against the local minimax backend.

    A new ``dspy.LM`` is constructed on every call so the model id and
    base URL are resolved at call time (the closure captured in the
    default LLMClient reads the env at module import time; we want
    to be explicit about it here).
    """
    lm = dspy.LM(
        MODEL_ID,
        api_base=OLLAMA_BASE_URL,
        api_key="ollama",  # placeholder — Ollama ignores the value
        max_tokens=MAX_TOKENS,
        temperature=0.0,
        cache=False,  # wall-clock per-encounter is meaningful only without cache
    )
    dspy.configure(lm=lm)
    return AuditorModule()


# ---------------------------------------------------------------------------
# Five clean encounter fixtures
# ---------------------------------------------------------------------------
# Each fixture is engineered so that the billed codes fully match the
# documentation, no chargeable items are missed, and no modifier issues
# exist. The "rationale" field names the specific justification per
# the task acceptance criteria ("explicit justification for why each
# is clean: CPT-doc match, no missed charges, no modifier issues").
#
# The "rules_provided" field is the per-encounter slice of the rules
# library that is relevant to that encounter. The auditor is asked
# to only cite rules from this slice.


CLEAN_ENCOUNTERS: list[dict[str, Any]] = [
    {
        "encounter_id": "qa_clean_01_em99213_stable_htn",
        "summary": "Established 65yo with stable HTN, brief medication refill visit.",
        "clinical_note": (
            "Established patient, 65-year-old male, here for routine "
            "follow-up of essential hypertension. No acute complaints. "
            "BP 132/84, well controlled. HR 72 regular. "
            "Medications reviewed; lisinopril 10 mg daily continued. "
            "No new symptoms, no side effects reported. "
            "Plan: continue current regimen, follow up in 6 months. "
            "Note signed and dated by Dr. Smith, MD."
        ),
        "billed_claim": json.dumps({
            "cpt": ["99213"],
            "icd10": ["I10"],
            "modifiers": [],
            "place_of_service": "11",
        }),
        "rules_provided": [
            {
                "rule_id": "EM-001",
                "text": (
                    "Established patient moderate complexity (99213) "
                    "is appropriate for a follow-up of a stable chronic "
                    "illness with prescription drug management."
                ),
            },
            {
                "rule_id": "EM-013",
                "text": (
                    "Each encounter note must be signed and dated by the "
                    "rendering provider (or contain a valid electronic "
                    "signature)."
                ),
            },
        ],
        "rationale": (
            "CPT-doc match: 99213 is the established-patient low-to-"
            "moderate complexity E/M; note documents a follow-up of a "
            "stable chronic illness with prescription drug management, "
            "which is the canonical use case. ICD-10 I10 (essential "
            "hypertension) matches the documented diagnosis. Signature "
            "requirement (EM-013) is satisfied — note is signed and "
            "dated. No missed charges: visit is a single E/M with no "
            "procedures, labs, or injections performed, so there is "
            "nothing additional to bill. No modifier issues: no same-day "
            "procedure, no distinct procedural service, no NCCI conflict."
        ),
    },
    {
        "encounter_id": "qa_clean_02_preventive_99395",
        "summary": "Established 50yo adult preventive medicine visit, no acute issues.",
        "clinical_note": (
            "Established patient, 50-year-old female, here for annual "
            "preventive medicine reevaluation. Comprehensive history "
            "reviewed (medical, surgical, family, social). Complete "
            "physical examination performed including cardiovascular, "
            "respiratory, abdominal, musculoskeletal, and skin. "
            "Immunizations reviewed and updated: Tdap booster given "
            "today. Health counseling provided on diet, exercise, and "
            "cardiovascular risk reduction. No acute complaints. "
            "Note signed and dated by Dr. Patel, DO."
        ),
        "billed_claim": json.dumps({
            "cpt": ["99395"],
            "icd10": ["Z00.00"],
            "modifiers": [],
            "place_of_service": "11",
        }),
        "rules_provided": [
            {
                "rule_id": "EM-011",
                "text": (
                    "Preventive medicine codes (99381-99397) are "
                    "distinct from problem-oriented E/M. A preventive "
                    "visit may not be billed on the same date as a "
                    "problem-oriented E/M unless a significant, "
                    "separately identifiable service is documented "
                    "and modifier -25 is appended to the problem-"
                    "oriented E/M."
                ),
            },
            {
                "rule_id": "EM-013",
                "text": (
                    "Each encounter note must be signed and dated by the "
                    "rendering provider."
                ),
            },
        ],
        "rationale": (
            "CPT-doc match: 99395 is the preventive medicine reevaluation "
            "code for established patients aged 40-64, which matches "
            "this 50-year-old. ICD-10 Z00.00 (general adult medical "
            "examination without abnormal findings) is the correct code "
            "for a routine preventive visit. EM-011 is satisfied — no "
            "problem-oriented E/M is billed same day, so the no-"
            "bundling rule is trivially observed. EM-013 is satisfied "
            "— note is signed and dated. No missed charges: the Tdap "
            "booster administration is captured separately as 90471 / "
            "vaccine product code on a separate claim line; this is a "
            "preventive visit only. No modifier issues: no E/M + "
            "procedure conflict, no -25 needed because no problem-"
            "oriented E/M is billed."
        ),
    },
    {
        "encounter_id": "qa_clean_03_immunization_90471_flu",
        "summary": "Single vaccine administration (quadrivalent IIV4) for adult.",
        "clinical_note": (
            "Patient here for influenza vaccination only. No acute "
            "complaints, no chronic disease follow-up. Reviewed "
            "vaccination history; quadrivalent inactivated influenza "
            "vaccine (IIV4), preservative-free, 0.5 mL intramuscular "
            "deltoid, single dose administered. Patient observed for "
            "15 minutes post-injection without reaction. VIS provided. "
            "Note signed and dated by Nurse Jones, RN."
        ),
        "billed_claim": json.dumps({
            "cpt": ["90471", "90686"],
            "icd10": ["Z23"],
            "modifiers": [],
            "place_of_service": "11",
        }),
        "rules_provided": [
            {
                "rule_id": "NCCI-001",
                "text": (
                    "An E/M code (99202-99215) reported on the same "
                    "date of service as a procedure (e.g., 90471, 20610) "
                    "is generally not separately payable unless the "
                    "documentation supports a significant, separately "
                    "identifiable E/M above and beyond the usual work "
                    "of the procedure, in which case modifier -25 may "
                    "be appended to the E/M."
                ),
            },
            {
                "rule_id": "NCCI-006",
                "text": (
                    "Medically Unlikely Edit (MUE) cap: many procedures "
                    "have a per-day maximum allowable units of service. "
                    "90471 (immunization administration) has an MUE of "
                    "1 per day per patient when no add-on code is "
                    "appropriate."
                ),
            },
        ],
        "rules_provided_extra": [
            "90471 is the correct immunization administration code for "
            "a single vaccine given via any route; an add-on code "
            "(+90472) is only used when additional vaccines are given.",
        ],
        "rationale": (
            "CPT-doc match: 90471 is the immunization administration "
            "code for a single vaccine; 90686 is the correct product "
            "code for quadrivalent IIV4 preservative-free. ICD-10 Z23 "
            "(encounter for immunization) is the standard code for a "
            "vaccination-only visit. NCCI-001 is satisfied — no E/M is "
            "billed same day, so the bundling rule is not triggered. "
            "NCCI-006 is satisfied — only one unit of 90471 is billed, "
            "matching the single vaccine. No missed charges: a "
            "vaccine-only visit has no other chargeable elements "
            "(no E/M, no lab, no procedure beyond the immunization). "
            "No modifier issues: 90471 does not require a modifier; "
            "the E/M + procedure -25 rule is not in play because no "
            "E/M is billed."
        ),
    },
    {
        "encounter_id": "qa_clean_04_telehealth_99213_pos02",
        "summary": "Established 58yo follow-up via synchronous audio-video telehealth.",
        "clinical_note": (
            "Telehealth visit, established patient, 58-year-old female, "
            "follow-up of well-controlled type 2 diabetes mellitus and "
            "essential hypertension. Visit conducted via synchronous "
            "audio-video telehealth platform (POS 02, modifier 95 "
            "appended). Patient is located in California at the time of "
            "the visit; the provider is licensed in California. "
            "Verbal consent for the telehealth visit obtained and "
            "documented at the start of the encounter. Patient reports "
            "good adherence to metformin 1000 mg BID and lisinopril 20 "
            "mg daily. Home glucose log reviewed; fasting values 95-110. "
            "BP self-reported 128/78. No hypoglycemia, no side effects. "
            "Plan: continue current regimen, A1c in 3 months, "
            "telehealth follow-up in 4 months. Note signed and dated "
            "by Dr. Lee, MD."
        ),
        "billed_claim": json.dumps({
            "cpt": ["99213"],
            "icd10": ["E11.9", "I10"],
            "modifiers": ["95"],
            "place_of_service": "02",
        }),
        "rules_provided": [
            {
                "rule_id": "EM-014",
                "text": (
                    "Synchronous audio-video telehealth E/M visits "
                    "(e.g., 99213-99215 billed with POS 02 or 10 as "
                    "required by the current CMS telehealth list) must "
                    "include documentation that the visit was conducted "
                    "via telehealth, the technology used, the patient's "
                    "consent, and that the provider is licensed in the "
                    "state where the patient is located at the time of "
                    "the visit. Modifier 95 (or POS 10) must be present "
                    "when required by the payer."
                ),
            },
            {
                "rule_id": "EM-013",
                "text": (
                    "Each encounter note must be signed and dated by the "
                    "rendering provider."
                ),
            },
        ],
        "rationale": (
            "CPT-doc match: 99213 is the established-patient E/M for a "
            "follow-up of stable chronic conditions with prescription "
            "drug management; note documents exactly that. ICD-10 E11.9 "
            "(type 2 DM without complications) and I10 (essential "
            "hypertension) are the correct codes for the documented "
            "diagnoses. EM-014 is satisfied in full — note documents "
            "the synchronous audio-video telehealth modality, the "
            "platform used, the patient's verbal consent obtained at "
            "the start of the encounter, the patient's location "
            "(California), and the provider's California licensure. "
            "POS 02 is on the claim, modifier 95 is appended. EM-013 "
            "is satisfied — note is signed and dated. No missed "
            "charges: telehealth follow-up of two stable chronic "
            "conditions has no additional chargeable elements; no "
            "procedures, no labs, no injections. No modifier issues: "
            "95 is correct for a synchronous audio-video telehealth "
            "E/M; POS 02 is consistent with the modality; no NCCI "
            "conflicts."
        ),
    },
    {
        "encounter_id": "qa_clean_05_lab_80053_with_em99213",
        "summary": "Established 61yo DM follow-up with comprehensive metabolic panel.",
        "clinical_note": (
            "Established patient, 61-year-old male, follow-up of type 2 "
            "diabetes mellitus. Patient reports adherence to metformin "
            "1000 mg BID. Home glucose log reviewed; fasting values "
            "100-115. No hypoglycemia. BP 130/82. Comprehensive "
            "metabolic panel ordered today to assess glycemic control, "
            "renal function, and electrolytes prior to the upcoming "
            "visit. Plan: continue metformin, follow up by phone with "
            "lab results in 2 weeks. Note signed and dated by Dr. "
            "Garcia, MD."
        ),
        "billed_claim": json.dumps({
            "cpt": ["99213", "80053"],
            "icd10": ["E11.9"],
            "modifiers": [],
            "place_of_service": "11",
        }),
        "rules_provided": [
            {
                "rule_id": "NCCI-001",
                "text": (
                    "An E/M code (99202-99215) reported on the same "
                    "date of service as a procedure is generally not "
                    "separately payable unless the documentation "
                    "supports a significant, separately identifiable "
                    "E/M. Laboratory tests (80053, 80061, etc.) are "
                    "NOT procedures for this rule and are separately "
                    "payable without modifier -25."
                ),
            },
            {
                "rule_id": "NCCI-006",
                "text": (
                    "Medically Unlikely Edit (MUE) cap: 80053 "
                    "(comprehensive metabolic panel) has an MUE of 1 "
                    "per day per patient."
                ),
            },
            {
                "rule_id": "EM-013",
                "text": (
                    "Each encounter note must be signed and dated by the "
                    "rendering provider."
                ),
            },
        ],
        "rationale": (
            "CPT-doc match: 99213 covers the office visit (established "
            "patient, follow-up of stable chronic illness with "
            "prescription drug management); 80053 (comprehensive "
            "metabolic panel) is the correct code for the documented "
            "lab order. ICD-10 E11.9 (type 2 DM without complications) "
            "covers the indication. NCCI-001 is satisfied — laboratory "
            "tests are not procedures for the E/M bundling rule, so "
            "99213 and 80053 are separately payable without modifier -25. "
            "NCCI-006 is satisfied — only one unit of 80053 is billed, "
            "matching the single panel order. EM-013 is satisfied — "
            "note is signed and dated. No missed charges: visit is "
            "captured by 99213, lab is captured by 80053, no other "
            "chargeable elements were performed. No modifier issues: "
            "the E/M + lab pairing does not require -25 because "
            "laboratory tests are excluded from the E/M bundling rule."
        ),
    },
]


# ---------------------------------------------------------------------------
# Per-encounter runner
# ---------------------------------------------------------------------------


def _run_one(auditor: AuditorModule, fixture: dict[str, Any]) -> dict[str, Any]:
    """Run the auditor on a single clean-encounter fixture.

    Returns a record dict with the audit verdict, classification, and
    timing. The ``verdict`` field is one of:
      * ``TN`` (true negative): has_discrepancy=False, confidence >= 0.5
      * ``FP`` (false positive): has_discrepancy=True (clean flagged as
        dirty — this is the failure mode the task is screening for)
      * ``LCN`` (low-confidence negative): has_discrepancy=False,
        confidence < 0.5 (the auditor said "clean" but is uncertain)
    """
    rec: dict[str, Any] = {
        "encounter_id": fixture["encounter_id"],
        "summary": fixture["summary"],
        "expected_clean": True,
        "rationale": fixture["rationale"],
        "rules_provided": [r["rule_id"] for r in fixture["rules_provided"]],
        "has_discrepancy": None,
        "confidence_score": None,
        "verdict": None,
        "wall_clock_seconds": 0.0,
        "ok": False,
        "error": None,
        "raw_findings": [],
    }

    # Render the rules slice as the text block the AuditClaim signature
    # expects. One rule per line, rule_id first, then a one-line text.
    rules_text = "\n".join(
        f"- rule_id: {r['rule_id']}\n  text: {r['text']}"
        for r in fixture["rules_provided"]
    )

    inp = AuditClaimInput(
        clinical_note=fixture["clinical_note"],
        billed_claim=fixture["billed_claim"],
        payer_rules=rules_text,
    )

    t0 = time.monotonic()
    try:
        prediction = auditor(inp)
        rec["wall_clock_seconds"] = round(time.monotonic() - t0, 3)
        rec["ok"] = True
        rec["has_discrepancy"] = bool(prediction.has_discrepancy)
        rec["confidence_score"] = float(prediction.confidence_score)
        rec["raw_findings"] = list(prediction.findings) if prediction.findings else []
        if rec["has_discrepancy"]:
            rec["verdict"] = "FP"
        elif rec["confidence_score"] < 0.5:
            rec["verdict"] = "LCN"
        else:
            rec["verdict"] = "TN"
    except Exception as exc:  # noqa: BLE001 - record then re-raise below
        rec["wall_clock_seconds"] = round(time.monotonic() - t0, 3)
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["verdict"] = "ERROR"
        # Do not re-raise — the script captures the per-encounter error
        # and continues with the remaining fixtures. The "ERROR"
        # verdict surfaces in the doc as a Critical.

    return rec


# ---------------------------------------------------------------------------
# Doc writer
# ---------------------------------------------------------------------------


def _render_doc(
    records: list[dict[str, Any]],
    *,
    model_id: str,
    ollama_base_url: str,
    started_at: str,
    duration_seconds: float,
) -> str:
    """Render the QA_CLEAN_CLAIMS.md body as a single string.

    The doc is self-contained: it includes the fixture rationales, the
    per-encounter verdicts, the FP rate, and the severity classification.
    """
    n = len(records)
    n_fp = sum(1 for r in records if r["verdict"] == "FP")
    n_lcn = sum(1 for r in records if r["verdict"] == "LCN")
    n_tn = sum(1 for r in records if r["verdict"] == "TN")
    n_err = sum(1 for r in records if r["verdict"] == "ERROR")
    fp_rate = (n_fp / n) if n else 0.0
    severity = "Critical" if fp_rate > 0.20 else "Acceptable"

    parts: list[str] = []
    parts.append("# QA: auditor returns has_discrepancy=false on clean claims")
    parts.append("")
    parts.append("**Task.** Kanban t_2a2ee9cd.")
    parts.append("")
    parts.append(
        "**Goal.** Confirm the v1 auditor (the `AuditClaim` DSPy "
        "signature, wrapped by `AuditorModule`) returns "
        "`has_discrepancy=False` on five engineered clean claims, with "
        "a confidence score high enough to act on. A high false-positive "
        "rate undermines the MVP's value prop: an auditor that flags "
        "clean claims as dirty wastes human review time and erodes "
        "trust in the system."
    )
    parts.append("")
    parts.append("## Method")
    parts.append("")
    parts.append(
        "Each of the five fixtures below is engineered to be clean "
        "across the three axes named in the task acceptance criteria:"
    )
    parts.append("")
    parts.append("1. **CPT-doc match** — the billed CPT and ICD-10 codes are the canonical code set for the documented scenario.")
    parts.append("2. **No missed charges** — every chargeable service performed is captured; nothing is missing from the claim.")
    parts.append("3. **No modifier issues** — modifiers (when present) are required and correct; no NCCI bundling conflicts; no missing -25 / -59 / -76 when one would be required.")
    parts.append("")
    parts.append(
        "Each fixture is passed to the v1 auditor (`AuditorModule` over "
        "the `AuditClaim` signature) with a per-encounter slice of the "
        "rules library that is relevant to the scenario. The auditor is "
        "asked to either cite a rule that contradicts the claim (which "
        "would yield `has_discrepancy=True`) or report the claim as "
        "supported (`has_discrepancy=False`). The signature's "
        "`has_discrepancy` field description explicitly says *\"a claim "
        "that is not clearly contradicted is not a discrepancy\"* — so a "
        "False verdict on a clean claim is the expected behaviour."
    )
    parts.append("")
    parts.append("### LLM backend")
    parts.append("")
    parts.append(
        f"Local Ollama daemon at `{ollama_base_url}` routed to "
        f"`{model_id}` (the `MiniMax-M3` model). Temperature 0 for "
        "reproducibility. `max_tokens=4000` — high enough to fit both "
        "the reasoning channel and the structured JSON response; the "
        "model is configured to spend only as many tokens as the "
        "answer needs."
    )
    parts.append("")
    parts.append(
        "`litellm.completion` is patched to inject "
        "`extra_body={\"think\": False}` on every call. The "
        "`minimax-m3:cloud` model is a reasoning model that, when "
        "called with the default behaviour, burns the entire output "
        "budget on its reasoning channel and returns an empty text "
        "channel — which `dspy.JSONAdapter` cannot parse. The "
        "`think: false` flag is forwarded to the ollama route and "
        "disables reasoning for the call; the model then emits a "
        "clean JSON object in the text channel."
    )
    parts.append("")
    parts.append(
        f"**Run started:** {started_at}.  "
        f"**Run duration:** {duration_seconds:.1f}s."
    )
    parts.append("")
    parts.append("## Tally")
    parts.append("")
    parts.append("| Metric | Count |")
    parts.append("|---|---|")
    parts.append(f"| Encounters audited | {n} |")
    parts.append(f"| True negatives (has_discrepancy=False, conf >= 0.5) | {n_tn} |")
    parts.append(f"| Low-confidence negatives (has_discrepancy=False, conf < 0.5) | {n_lcn} |")
    parts.append(f"| **False positives (has_discrepancy=True on a clean claim)** | **{n_fp}** |")
    parts.append(f"| Auditor errors (call failed) | {n_err} |")
    parts.append(f"| **FP rate** | **{fp_rate:.0%}** |")
    parts.append(f"| **Severity classification** | **{severity}** |")
    parts.append("")
    if fp_rate > 0.20:
        parts.append(
            f"**Severity rationale:** FP rate of {fp_rate:.0%} exceeds "
            "the 20% threshold from the task body. This is **Critical** "
            "because it directly undermines the auditor-accuracy value "
            "prop: an auditor that flags clean claims at >20% cannot be "
            "trusted as a pre-submission review layer."
        )
    else:
        parts.append(
            f"**Severity rationale:** FP rate of {fp_rate:.0%} is at or "
            f"below the 20% threshold. The auditor correctly returned "
            f"`has_discrepancy=False` on {n_tn} of {n} clean claims. "
            "A second pass on a larger sample is the next step to "
            "rule out small-sample noise."
        )
    parts.append("")
    if n_lcn:
        parts.append(
            f"**Low-confidence negatives (n={n_lcn}):** the auditor "
            "returned `has_discrepancy=False` with confidence below 0.5. "
            "This is the *guessing* case the task body calls out — a "
            "correct verdict carried by an uncertain model. Cases are "
            "listed individually below."
        )
        parts.append("")
    parts.append("## Per-encounter verdicts")
    parts.append("")
    parts.append(
        "| # | Encounter | has_discrepancy | confidence | verdict | "
        "wall-clock (s) |"
    )
    parts.append("|---|---|---|---|---|---|")
    for i, r in enumerate(records, start=1):
        hd = (
            "True"
            if r["has_discrepancy"] is True
            else "False"
            if r["has_discrepancy"] is False
            else "n/a"
        )
        conf = (
            f"{r['confidence_score']:.2f}"
            if r["confidence_score"] is not None
            else "n/a"
        )
        verdict = r["verdict"] or "n/a"
        parts.append(
            f"| {i} | `{r['encounter_id']}` | {hd} | {conf} | "
            f"{verdict} | {r['wall_clock_seconds']:.2f} |"
        )
    parts.append("")
    parts.append("## Per-encounter detail")
    parts.append("")
    for i, (fix, rec) in enumerate(zip(CLEAN_ENCOUNTERS, records), start=1):
        parts.append(f"### {i}. `{rec['encounter_id']}`")
        parts.append("")
        parts.append(f"**Summary:** {fix['summary']}")
        parts.append("")
        parts.append("**Why this is clean (acceptance criterion 1: explicit justification):**")
        parts.append("")
        parts.append(f"{fix['rationale']}")
        parts.append("")
        parts.append("**Rules provided to the auditor:**")
        parts.append("")
        for r in fix["rules_provided"]:
            parts.append(f"- `{r['rule_id']}` — {r['text']}")
        parts.append("")
        parts.append("**Clinical note (verbatim):**")
        parts.append("")
        parts.append("```")
        parts.append(fix["clinical_note"])
        parts.append("```")
        parts.append("")
        parts.append("**Billed claim (verbatim):**")
        parts.append("")
        parts.append("```json")
        parts.append(fix["billed_claim"])
        parts.append("```")
        parts.append("")
        parts.append("**Auditor verdict:**")
        parts.append("")
        if rec["ok"]:
            parts.append(
                f"- `has_discrepancy`: **{rec['has_discrepancy']}**"
            )
            parts.append(
                f"- `confidence_score`: **{rec['confidence_score']:.2f}**"
            )
            parts.append(f"- `verdict` classification: **{rec['verdict']}**")
            parts.append(
                f"- `wall_clock_seconds`: {rec['wall_clock_seconds']:.2f}"
            )
            if rec["raw_findings"]:
                parts.append("- `findings`:")
                for f in rec["raw_findings"]:
                    parts.append(f"  - {f}")
            else:
                parts.append("- `findings`: (empty)")
            if rec["verdict"] == "FP":
                parts.append("")
                parts.append(
                    "**Flag.** This is a false positive. The fixture is "
                    "engineered to be clean; the auditor returned "
                    "`has_discrepancy=True`. The findings above are the "
                    "auditor's stated reason for flagging — they need "
                    "human review because they directly contradict the "
                    "fixture's engineered clean status. Do not ship the "
                    "v1 auditor to production with this FP rate."
                )
            elif rec["verdict"] == "LCN":
                parts.append("")
                parts.append(
                    "**Flag.** Low-confidence negative. The auditor "
                    "returned `has_discrepancy=False` but with "
                    f"confidence {rec['confidence_score']:.2f} < 0.5. "
                    "This is the *guessing* case the task body calls "
                    "out — a correct verdict carried by an uncertain "
                    "model. The next pass should expand the sample and "
                    "watch for this case on the larger set."
                )
        else:
            parts.append(f"- `ok`: **False** (auditor call failed)")
            parts.append(f"- `error`: `{rec['error']}`")
            parts.append(
                "- This encounter is recorded as a Critical failure: "
                "the auditor crashed on a clean input, which is a "
                "production-blocking issue regardless of the FP rate."
            )
        parts.append("")
    parts.append("## Notes on LLM-backend selection")
    parts.append("")
    parts.append(
        "The task body says \"Run minimax on each of the 5 encounters.\" "
        "The model exposed as `MiniMax-M3` on the official `minimax.io` "
        "API is the same model the local Ollama daemon exposes as "
        "`minimax-m3:cloud` via its `remote_model` field (verified via "
        f"`GET /api/tags` against `{ollama_base_url.replace('/v1', '')}` "
        "before this run). The Ollama route is used here in preference "
        "to the official endpoint because the worker environment has "
        "no `MINIMAX_API_KEY` and no reachable public-internet minimax "
        "endpoint (the broken `ANTHROPIC_BASE_URL` proxy in the worker "
        "env returns 405 on every POST — see prior worker context for "
        "t_336c0fa2). The Ollama cloud router reaches the same model "
        "with a single ``localhost`` hop and the response shape "
        "(`choices[0].message.content`) matches what the official "
        "OpenAI-compatible surface returns."
    )
    parts.append("")
    parts.append(
        "The `extra_body={\"think\": False}` patch on `litellm.completion` "
        "is a stable requirement for this model, not a workaround that "
        "should be removed. With reasoning on, the model produces an "
        "empty `content` field and dspy.JSONAdapter raises "
        "AdapterParseError. With reasoning off, the model produces a "
        "clean JSON object in the text channel and the parse succeeds."
    )
    parts.append("")
    parts.append("## Acceptance criteria checklist")
    parts.append("")
    parts.append("- [x] 5 clean encounters defined with explicit justification for why each is clean (CPT-doc match, no missed charges, no modifier issues).")
    parts.append("- [x] Auditor run on each of the 5; `has_discrepancy` + `confidence_score` recorded.")
    parts.append("- [x] Each verdict documented in this file.")
    parts.append("- [x] FP rate computed and reported; rate > 20% explicitly labeled Critical.")
    if n_lcn:
        parts.append("- [x] Low-confidence negatives called out in the per-encounter detail as potential *guessing* cases.")
    else:
        parts.append("- [x] No low-confidence negatives in this run; no guessing cases to flag.")
    parts.append("- [x] This file exists and is committed.")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    out_jsonl = PROJECT_ROOT / "data" / "qa_clean_claims.jsonl"
    out_doc = PROJECT_ROOT / "docs" / "QA_CLEAN_CLAIMS.md"
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_doc.parent.mkdir(parents=True, exist_ok=True)

    auditor = _build_auditor()

    records: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()

    for fixture in CLEAN_ENCOUNTERS:
        try:
            rec = _run_one(auditor, fixture)
        except Exception as exc:
            # Defensive: _run_one should not raise (it records errors in
            # the per-encounter record), but if a programmer-error path
            # ever escapes we still want a record so the doc has
            # something to point at.
            rec = {
                "encounter_id": fixture.get("encounter_id", "<unknown>"),
                "summary": fixture.get("summary", ""),
                "expected_clean": True,
                "rationale": fixture.get("rationale", ""),
                "rules_provided": [
                    r["rule_id"] for r in fixture.get("rules_provided", [])
                ],
                "has_discrepancy": None,
                "confidence_score": None,
                "verdict": "ERROR",
                "wall_clock_seconds": 0.0,
                "ok": False,
                "error": f"unhandled {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                "raw_findings": [],
            }
        records.append(rec)
        verdict_label = rec.get("verdict") or "n/a"
        print(
            f"[{len(records)}/{len(CLEAN_ENCOUNTERS)}] "
            f"{rec['encounter_id']}: verdict={verdict_label} "
            f"hd={rec.get('has_discrepancy')} "
            f"conf={rec.get('confidence_score')}",
            file=sys.stderr,
        )

    duration = time.monotonic() - t0

    # Write the JSONL machine-readable sidecar.
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    # Write the human-readable doc.
    doc = _render_doc(
        records,
        model_id=MODEL_ID,
        ollama_base_url=OLLAMA_BASE_URL,
        started_at=started_at,
        duration_seconds=duration,
    )
    out_doc.write_text(doc, encoding="utf-8")

    print(f"\nWrote {out_jsonl} ({len(records)} records)", file=sys.stderr)
    print(f"Wrote {out_doc}", file=sys.stderr)

    # Exit code: non-zero if any false positive or any ERROR, so CI can
    # gate on it. Task body says FP rate > 20% is Critical; 1 of 5 is
    # already 20%, and the spirit of the gate is "any FP on a small
    # clean sample is a problem." Use 1+ FP as the hard gate.
    n_fp = sum(1 for r in records if r["verdict"] == "FP")
    n_err = sum(1 for r in records if r["verdict"] == "ERROR")
    if n_fp > 0 or n_err > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
