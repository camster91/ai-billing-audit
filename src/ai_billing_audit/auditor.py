"""Auditor agent — a thin prompt runner over :class:`LLMClient`.

The Auditor is the LLM-driven counterpart to the deterministic
ground-truth generator. Where the ground-truth library encodes a fixed
set of well-known billing rules in Python, the Auditor asks an LLM to
apply the *retrieved* rules (the citations attached to each encounter)
to the encounter and emit a structured findings list.

Public surface
--------------
``run_audit(encounter, *, llm=None, prompt_path=None) -> AuditResult``
    The single entry point. Builds the messages payload, dispatches the
    LLM call, validates the response, and returns the findings.

``build_messages(encounter, *, prompt) -> list[dict[str, str]]``
    The unit-testable seam. Takes the encounter and a pre-loaded prompt
    string, returns the OpenAI-style messages list. Tests can assert
    shape without invoking any LLM.

``load_prompt(path=None) -> str``
    Loads the auditor prompt. ``None`` falls back to the bundled
    default prompt shipped with the package.

``AuditResult``, ``Finding``, ``AuditValidationError``
    The typed result and the typed error.

Design constraints
------------------
* No LLM-specific code lives in this module. It depends only on
  :class:`LLMClient`.
* The function is pure-ish: the only state read at call time is the
  process environment (resolved by the LLMClient's own env reads) and
  the optional ``prompt_path`` argument. The default prompt is loaded
  from disk once and cached at module import.
* Every structured finding is validated against the findings schema
  (``Finding`` dataclass) before being returned. Mismatches raise
  :class:`AuditValidationError`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from ai_billing_audit.llm import LLMClient

__all__ = [
    "AuditResult",
    "Finding",
    "AuditValidationError",
    "run_audit",
    "build_messages",
    "load_prompt",
    "validate_findings",
]

_DEFAULT_PROMPT_NAME = "auditor_prompt.txt"
_DEFAULT_PROMPT_CACHE: str | None = None


# The response schema the LLM is asked to conform to. Mirrors AuditResult
# and Finding shape (one level of nesting; arrays of strings).
#
# We deliberately allow additionalProperties and have minimal required
# fields. The model produces rich, varied responses (sometimes rule_id
# singular, sometimes rule_ids plural, sometimes an explanation field,
# sometimes a missing suggested_code if the finding is documentation
# rather than code). Crashing the audit because the model added an
# "explanation" string would discard good signal. We capture what we
# can and surface the rest in the audit-trail audit_log.
RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["findings"],
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                # quote is no longer jsonschema-required — we synthesize
                # one in the validator from explanation/rationale if the
                # model omits it. severity stays required.
                "required": ["severity"],
                "properties": {
                    "category": {"type": "string"},
                    "suggested_code": {"type": "string"},
                    "quote": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high", "critical"],
                    },
                    "rule_id": {"type": "string"},
                    "rule_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "explanation": {"type": "string"},
                },
            },
        },
    },
}


# P11 round-3 (2026-07-02): canonical rule_id + alias map.
#
# The v12 prompt instructs the LLM to emit rule_ids in the
# ``rule_ahcip_*`` namespace. In practice the model emits generic
# labels (MOD-25-*, DX-MATCH-*, MEDICARE_AWV_*) because the JSON
# schema permits any string and the few-shot examples aren't strict
# enough. We canonicalize post-validation so the 1-page report and
# the SOMB dollar mapping in shadow_audit.py can recognize the
# finding. Keys are LOWER-CASE for case-insensitive matching; values
# are the canonical rule_id (always ``rule_ahcip_*``).
#
# Pattern matching uses regex. Order matters: more specific patterns
# first (e.g. MOD-25-SAME-DAY -> same_day_conflict, not
# modifier_25_unlock) so the canonicalization picks the right
# bucket.
_RULE_ID_ALIASES: list[tuple[str, str]] = [
    # --- Same-day conflict family -> rule_ahcip_same_day_conflict ---
    # (must come BEFORE the generic MOD-25 wildcard below)
    (r"MOD-25-SAME-DAY", "rule_ahcip_same_day_conflict"),
    (r"same_day_conflict", "rule_ahcip_same_day_conflict"),
    # --- Modifier-25 family -> rule_ahcip_modifier_25_unlock ---
    (r"^MOD-25", "rule_ahcip_modifier_25_unlock"),
    (r"^E_M_PROCEDURE_MODIFIER", "rule_ahcip_modifier_25_unlock"),
    (r"^MOD-STD-001", "rule_ahcip_modifier_25_unlock"),
    # --- CMGP / chronic-disease family -> rule_ahcip_cmgp ---
    (r"CMGP", "rule_ahcip_cmgp"),
    (r"chronic.disease.management", "rule_ahcip_cmgp"),
    # --- Annual physical / preventive / non-insured ---
    (r"^MEDICARE_AWV", "rule_ahcip_non_insured_service"),
    (r"^CMS-AWV", "rule_ahcip_non_insured_service"),
    (r"^AWV-", "rule_ahcip_non_insured_service"),
    (r"^Z00_", "rule_ahcip_non_insured_service"),
    (r"^ZCODE-", "rule_ahcip_non_insured_service"),
    (r"z00_00_no_abnormal", "rule_ahcip_non_insured_service"),
    (r"non.insured", "rule_ahcip_non_insured_service"),
    (r"annual.physical", "rule_ahcip_non_insured_service"),
    (r"^PREV-", "rule_ahcip_non_insured_service"),
    (r"^PREV-DX-", "rule_ahcip_non_insured_service"),
    (r"^DOC_REQ_COMPREHENSIVE_ANNUAL", "rule_ahcip_non_insured_service"),
    (r"^DOC-REQ-ANNUAL", "rule_ahcip_non_insured_service"),
    # --- Missing procedure / in-office service not billed ---
    (r"missing_procedure", "rule_ahcip_missing_procedure"),
    # --- Same-day conflict (variant spellings) ---
    (r"^SAME-DAY-MOD", "rule_ahcip_same_day_conflict"),
    (r"^SAME_DAY", "rule_ahcip_same_day_conflict"),
    (r"^SAME-DAY", "rule_ahcip_same_day_conflict"),
    # --- Global window / 90-day post-op ---
    (r"^SCOPE-OF-PRACTICE", "rule_ahcip_global_window"),
    (r"global.window", "rule_ahcip_global_window"),
    (r"post.op", "rule_ahcip_global_window"),
    # --- Lab coverage / imaging in-office ---
    (r"lab.coverage", "rule_ahcip_lab_coverage"),
    # --- Telehealth premium ---
    (r"telehealth.premium", "rule_ahcip_telehealth_premium"),
    (r"^TELEHEALTH", "rule_ahcip_telehealth"),
    # --- Psychotherapy time ---
    (r"psychotherapy.time", "rule_ahcip_psychotherapy_time"),
    (r"08\.19", "rule_ahcip_psychotherapy_time"),
    # --- Consultation / referring NPI ---
    (r"REFERRING.NPI", "rule_ahcip_referring_npi"),
    (r"referring.provider", "rule_ahcip_referring_npi"),
    (r"consultation.missed", "rule_ahcip_consultation_missed"),
    (r"^CONS-REF", "rule_ahcip_referring_npi"),
    (r"^CONS-REFERRAL", "rule_ahcip_referring_npi"),
    (r"^CONSULT-REF", "rule_ahcip_referring_npi"),
    (r"^CONS-EXAM", "rule_ahcip_em_level_upcode"),  # consult-exam-comprehensive
    # --- E/M level / upcode / undercode ---
    (r"^som_b_", "rule_ahcip_em_level"),
    (r"^SOM-", "rule_ahcip_em_level"),  # generic SOM-* codes (e.g. SOM-012)
    (r"em_level_upcode", "rule_ahcip_em_level_upcode"),
    (r"undercoded|undercode", "rule_ahcip_em_level_upcode"),
    (r"procedure.code.accuracy", "rule_ahcip_em_level_upcode"),
    # --- Diagnosis linkage / matching (DX-MATCH family → em_level) ---
    (r"^DX-MATCH", "rule_ahcip_em_level"),
    (r"^DX-CODE-SUPPORT", "rule_ahcip_em_level"),
    (r"^DX-DOC-SUPPORT", "rule_ahcip_em_level"),
    (r"^DX-PROC", "rule_ahcip_em_level"),
    (r"^DX-PROCEDURE", "rule_ahcip_em_level"),
    (r"^DX_PROCEDURE", "rule_ahcip_em_level"),
    (r"^DX_PROC", "rule_ahcip_em_level"),
    (r"^DX-CONSIST", "rule_ahcip_em_level"),
    (r"^DX_GENDER", "rule_ahcip_em_level"),
    (r"^DX_SEX", "rule_ahcip_em_level"),
    (r"^DX_GENDER_CONSISTENCY", "rule_ahcip_em_level"),
    (r"^DX-MUST-REFLECT", "rule_ahcip_em_level"),
    (r"^DX-SUPPORT-", "rule_ahcip_em_level"),
    (r"^DX_SUPPORT", "rule_ahcip_em_level"),
    (r"^DX-CLINICAL", "rule_ahcip_em_level"),
    (r"^DX_CLINICAL", "rule_ahcip_em_level"),
    (r"^DX-MEDICAL-NECESSITY", "rule_ahcip_em_level"),
    (r"^DX-CODE-MATCH", "rule_ahcip_em_level"),
    (r"^DX-CODE-ACCURACY", "rule_ahcip_em_level"),
    (r"^DX-SECONDARY", "rule_ahcip_em_level"),
    (r"^DX-PRIMARY-REFLECT", "rule_ahcip_em_level"),
    (r"^DX_CODE_CHRONIC", "rule_ahcip_em_level"),
    (r"^dx-clinical-appropriateness", "rule_ahcip_em_level"),
    (r"^dx-demographic-consistency", "rule_ahcip_em_level"),
    (r"^DX-DOC-MATCH", "rule_ahcip_em_level"),
    (r"^DIAG-", "rule_ahcip_em_level"),
    (r"^RULE-DX-", "rule_ahcip_em_level"),
    (r"^RULE-MULTI-DX", "rule_ahcip_em_level"),
    (r"^PROC-DX-MATCH", "rule_ahcip_em_level"),
    (r"^PRIMARY-DX-", "rule_ahcip_em_level"),
    (r"^PRIMARY-DX-002", "rule_ahcip_em_level"),
    (r"diagnosis-encounter-alignment", "rule_ahcip_em_level"),
    (r"dx-clinical-encounter-support", "rule_ahcip_em_level"),
    (r"primary_reason_for_visit", "rule_ahcip_em_level"),
    # --- ICD-10 specific (→ em_level; sex/age/lesion-type families) ---
    (r"^ICD10-", "rule_ahcip_em_level"),
    (r"^ICD10-CM", "rule_ahcip_em_level"),
    (r"^ICD-CLINICAL-MATCH", "rule_ahcip_em_level"),
    (r"^ICD-CM", "rule_ahcip_em_level"),
    # --- dx_linkage (separate from em_level — DX_DOCUMENTATION family) ---
    (r"^DX_DOCUMENTATION_SUPPORT", "rule_ahcip_dx_linkage"),
    (r"^DX_DOCUMENTATION", "rule_ahcip_dx_linkage"),
    (r"^DX-DOCUMENTATION-", "rule_ahcip_dx_linkage"),
    (r"^DX-COMPLETE", "rule_ahcip_dx_linkage"),
    (r"^DX-COMPLETENESS", "rule_ahcip_dx_linkage"),
    (r"^PROC-DX-LINK", "rule_ahcip_dx_linkage"),
    (r"^DOC-SUPPORT-", "rule_ahcip_dx_linkage"),
    (r"dx.linkage", "rule_ahcip_dx_linkage"),
    (r"E78\.5-REQUIRE", "rule_ahcip_dx_linkage"),
    (r"^DIAGNOSIS_CODE_DOCUMENTATION_SUPPORT", "rule_ahcip_dx_linkage"),
    (r"^DIAGNOSIS_DOCUMENTATION_REQUIREMENT", "rule_ahcip_dx_linkage"),
    (r"^DIAGNOSIS_DOCUMENTATION", "rule_ahcip_dx_linkage"),
    (r"^DIAGNOSIS_CODE_MUST_MATCH", "rule_ahcip_dx_linkage"),
    (
        r"^CA-MEDI-CAL-DX-MATCH",
        "rule_ahcip_em_level",
    ),  # California-style; treat as DX family
    (r"PROCEDURE_DIAGNOSIS_LINKAGE", "rule_ahcip_dx_linkage"),
    (r"PROCEDURE_REQUIRES_APPROPRIATE_DIAGNOSIS", "rule_ahcip_dx_linkage"),
    (r"^EOM_DIAGNOSIS_COVERAGE", "rule_ahcip_dx_linkage"),
    # --- Same-day conflict: variant spellings ---
    (r"^E_M_PROCEDURE_SAME_DAY_MODIFIER", "rule_ahcip_same_day_conflict"),
    (r"SAME.DAY.MOD", "rule_ahcip_same_day_conflict"),
    (r"modifier.25.same.day", "rule_ahcip_same_day_conflict"),
    # --- Annual physical / preventive (additional variants) ---
    (r"^DOC-SUFFICIENCY-AWV", "rule_ahcip_non_insured_service"),
    (r"^PREVENTIVE-EXAM-DOC", "rule_ahcip_non_insured_service"),
    (r"^AGE-MEDICARE-PREVENTIVE", "rule_ahcip_non_insured_service"),
    (r"^medicare-age-eligibility", "rule_ahcip_non_insured_service"),
    (r"^preventive-vs-acute-visit-type", "rule_ahcip_non_insured_service"),
    (r"^ICD-Z00\.00", "rule_ahcip_non_insured_service"),
    # --- E/M level: variant spellings ---
    (r"^REQ-PRIMARY-DX", "rule_ahcip_em_level"),
    (r"^cpt-encounter-service-alignment", "rule_ahcip_em_level"),
    (r"diagnosis-encounter-reason-alignment", "rule_ahcip_em_level"),
    (r"^procedure-code-coverage", "rule_ahcip_missing_procedure"),
    (r"^DX-SEX-", "rule_ahcip_em_level"),
    (r"^SOMB-", "rule_ahcip_em_level"),  # generic SOMB-* codes (e.g. SOMB-03.04A)
    # --- Cross-payer LLM leaks (WA-MCD, CA-SOM, CA-MEDI are US/state
    # payer codes the model sometimes emits for AHCIP encounters; treat
    # them as em_level / dx_linkage based on the suffix) ---
    (r"^WA-MCD-", "rule_ahcip_em_level"),  # Washington Medicaid
    (r"^CA-SOM-", "rule_ahcip_em_level"),  # California SOM
    (r"^CA-MEDI-CAL-", "rule_ahcip_em_level"),
    (r"^DOC-PREV-", "rule_ahcip_non_insured_service"),  # DOC-PREVENTIVE family
    (r"^MODIFIER-CHECK", "rule_ahcip_modifier_25_unlock"),
    (r"^PROC-DX-CORRELATION", "rule_ahcip_dx_linkage"),
    (r"^PROC-DX-MATCH", "rule_ahcip_dx_linkage"),
    (r"^PROC-MINOR-SAME-VISIT", "rule_ahcip_same_day_conflict"),
    (r"^PROC-", "rule_ahcip_em_level"),  # generic PROC-* family
    (r"^CARD-MI-FOLLOWUP", "rule_ahcip_em_level"),  # cardiac followup
    (r"^CARD-", "rule_ahcip_em_level"),
    (r"^DX-PERTINENT-PRIMARY", "rule_ahcip_em_level"),
    (r"^DX-PRINCIPAL-MATCH", "rule_ahcip_em_level"),
    (r"^DX-SYMPTOM-CODING", "rule_ahcip_em_level"),
    (r"^DOC-CODE-ALIGNMENT", "rule_ahcip_dx_linkage"),
    (r"^WORKUP-PENDING", "rule_ahcip_em_level"),
    (r"^ICD10_GENDER_CONFLICT", "rule_ahcip_em_level"),
    (r"^ICD10_DIAGNOSIS_PROCEDURE_MATCH", "rule_ahcip_em_level"),
    (r"^ICD10_DX_MATCH", "rule_ahcip_em_level"),
    (r"^ICD10_EXCLUDES", "rule_ahcip_em_level"),
    (r"^DX-DOC-", "rule_ahcip_dx_linkage"),
    (r"^DX_DOC", "rule_ahcip_dx_linkage"),
    (r"^DX_CODE_", "rule_ahcip_dx_linkage"),
    (r"^DX-COMPLETE", "rule_ahcip_dx_linkage"),
    (r"^DX-COMPLETENESS", "rule_ahcip_dx_linkage"),
    (r"^DX_COMPLETE", "rule_ahcip_dx_linkage"),
    (r"^DX_COMPLETENESS", "rule_ahcip_dx_linkage"),
    (r"^OAR-", "rule_ahcip_em_level"),  # Oregon admin rule prefix
    (r"DIAGNOSIS_COMPLETENESS", "rule_ahcip_dx_linkage"),
    (r"^PROC_MULTIPLE", "rule_ahcip_em_level"),
    (r"^PREC-PREVENTIVE", "rule_ahcip_non_insured_service"),
    (r"^DX-SYMPTOM-PRIMARY", "rule_ahcip_em_level"),
    (r"^dx-visit-support", "rule_ahcip_em_level"),
    (r"^DX-GENDER-", "rule_ahcip_em_level"),
    (r"^DX-SCOPE-", "rule_ahcip_em_level"),
    (r"^REF-NPI-", "rule_ahcip_referring_npi"),
    (r"^DX-COMPLETENESS-", "rule_ahcip_dx_linkage"),
    (r"^DX-PRIMARY", "rule_ahcip_em_level"),
    (r"^EM-DX-SUPPORT", "rule_ahcip_em_level"),
    (r"^e-m-level-support", "rule_ahcip_em_level"),
    (r"^procedure-documentation-adequacy", "rule_ahcip_em_level"),
    (r"^DX-MUST-MATCH-DOCUMENTATION", "rule_ahcip_dx_linkage"),
    (r"^DX-PRIMARY-MUST-REFLECT", "rule_ahcip_em_level"),
    (r"^DIAGNOSIS_MUST_REFLECT", "rule_ahcip_em_level"),
    (r"^PROC-REQUIRES-SUPPORTING-DX", "rule_ahcip_dx_linkage"),
    (r"^diagnosis-procedure-nexus", "rule_ahcip_dx_linkage"),
    (r"^MODIFIER-25-REQUIRED", "rule_ahcip_modifier_25_unlock"),
    (r"^modifier-distinct-procedural-service", "rule_ahcip_modifier_25_unlock"),
    (r"^DX-PATIENT-MATCH", "rule_ahcip_em_level"),
    (r"^DX-CORRESPONDENCE", "rule_ahcip_em_level"),
    (r"^DOC-COMPLETENESS", "rule_ahcip_dx_linkage"),
    (r"^diagnosis_code_support", "rule_ahcip_dx_linkage"),
    # --- Lab order no draw ---
    (r"lab.order.no.draw", "rule_ahcip_lab_order_no_draw"),
    # --- 03.05A alternative ---
    (r"03.05A.alternative", "rule_ahcip_03_05A_alternative"),
    # --- Age matching ---
    (r"^CODE-MATCH-PATIENT-AGE", "rule_ahcip_em_level"),
    # --- ICD-10 sex-age consistency ---
    (r"ICD.10.SEX.AGE", "rule_ahcip_em_level"),  # generic DX
]


def _canonicalize_rule_id(rule_id: str) -> str:
    """Map an LLM-emitted rule_id string back to the canonical
    ``rule_ahcip_*`` form via the alias map. Returns the input
    unchanged if no alias matches (the validator accepts any string,
    so unknown rule_ids still pass through — they just don't get
    SOMB-specific render treatment in the 1-page report).
    """
    if not rule_id:
        return rule_id
    rid_lower = rule_id.strip().lower()
    # First check if it's already canonical (rule_ahcip_*) — pass through
    if rid_lower.startswith("rule_ahcip_"):
        return rule_id  # preserve original casing
    for pattern, canonical in _RULE_ID_ALIASES:
        if re.search(pattern, rid_lower, re.IGNORECASE):
            return canonical
    return rule_id  # unknown — pass through


class AuditValidationError(ValueError):
    """Raised when the LLM response does not match the findings schema."""


@dataclass(frozen=True)
class Finding:
    """A single auditor finding as emitted by the LLM and validated."""

    category: str
    suggested_code: str
    quote: str
    severity: str
    rule_ids: tuple[str, ...] = field(default_factory=tuple)
    finding_id: str = ""
    explanation: str = ""


@dataclass(frozen=True)
class AuditResult:
    """The result of a single ``run_audit`` call."""

    encounter_id: str
    findings: tuple[Finding, ...]
    summary: str


def load_prompt(path: str | Path | None = None) -> str:
    """Load the auditor system prompt.

    ``path=None`` returns the bundled default, loaded from package data
    and cached at module import. A custom path is read fresh every call.
    """
    if path is None:
        global _DEFAULT_PROMPT_CACHE
        if _DEFAULT_PROMPT_CACHE is None:
            try:
                _DEFAULT_PROMPT_CACHE = (
                    resources.files("ai_billing_audit")
                    .joinpath(_DEFAULT_PROMPT_NAME)
                    .read_text(encoding="utf-8")
                )
            except (FileNotFoundError, ModuleNotFoundError):
                # Editable install fallback: read the file relative to this
                # module's parent package directory.
                pkg_root = Path(__file__).resolve().parent
                _DEFAULT_PROMPT_CACHE = (pkg_root / _DEFAULT_PROMPT_NAME).read_text(
                    encoding="utf-8"
                )
        return _DEFAULT_PROMPT_CACHE.rstrip("\n")

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Auditor prompt not found at {p}")
    return p.read_text(encoding="utf-8").rstrip("\n")


def _encounter_context(encounter: Mapping[str, Any]) -> str:
    """Render the encounter as a plain-text context block for the LLM."""
    clinical_note = str(encounter.get("clinical_note", "") or "")
    is_flagged = bool(encounter.get("is_flagged", False))
    claim = encounter.get("claim", {}) or {}
    rules = encounter.get("rules", []) or []

    parts: list[str] = []
    parts.append(f"encounter_id: {encounter.get('encounter_id', '<unknown>')}")
    parts.append(f"is_flagged: {is_flagged}")
    if claim:
        parts.append("claim:")
        parts.append(json.dumps(claim, indent=2))
    if rules:
        parts.append("rules:")
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            parts.append(
                f"  - rule_id: {rule.get('rule_id', '')}\n"
                f"    snippet: {rule.get('snippet', '')}"
            )
    parts.append("clinical_note:")
    parts.append(clinical_note)
    return "\n".join(parts)


def build_messages(
    encounter: Mapping[str, Any], *, prompt: str
) -> list[dict[str, str]]:
    """Build the OpenAI-style messages list sent to the LLM.

    The system message is the loaded auditor prompt; the user message
    is the rendered encounter context (claim + rules + clinical_note).
    """
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": _encounter_context(encounter)},
    ]


def _quote_in_note(quote: str, clinical_note: str) -> bool:
    """Return True iff ``quote`` appears in ``clinical_note`` (best-effort).

    A token-based subsequence check: every whitespace-separated token of
    the quote must appear, in order, in the note. This is intentionally
    lenient: a strict substring check rejects every OCR'd note (which
    have different whitespace, line breaks, and punctuation than the
    source). The point is to catch fabricated quotes, not to require
    exact whitespace / punctuation fidelity.

    Examples that PASS:
      quote="chest pain"          note="Patient has chest pain today"   -> OK
      quote="CHEST  PAIN"         note="patient has chest pain today"   -> OK (case)
      quote="chest\\n   pain"     note="patient has chest pain today"   -> OK (whitespace)
      quote="HbA1c 6.8 eGFR 78"   note="...HbA1c 6.8, eGFR 78..."        -> OK (subsequence, ignores comma)

    Examples that FAIL:
      quote="headache"            note="Patient has chest pain today"   -> NOT IN NOTE
      quote=""                    note="anything"                       -> NOT IN NOTE
      quote="anything"            note=""                               -> NOT IN NOTE
    """
    if not quote or not clinical_note:
        return False
    # Strip punctuation so "6.8," in the note matches "6.8" in the quote.
    # Punctuation is irrelevant to whether the auditor is citing real
    # evidence; what matters is the tokens (medical terms, codes,
    # numbers) actually appearing in the source.
    import string

    punct = set(string.punctuation)

    def _clean(s: str) -> list[str]:
        return " ".join(ch for ch in s.lower() if ch not in punct).split()

    q_tokens = _clean(quote)
    n_tokens = _clean(clinical_note)
    if not q_tokens:
        return False
    # Subsequence match: every quote token must appear in the note, in
    # order. We don't require the tokens to be contiguous.
    q_idx = 0
    for n_tok in n_tokens:
        if q_idx < len(q_tokens) and n_tok == q_tokens[q_idx]:
            q_idx += 1
    return q_idx == len(q_tokens)


def validate_findings(
    payload: Any,
    clinical_note: str = "",
) -> tuple[Finding, ...]:
    """Parse + validate the ``findings`` array from the LLM response.

    When ``clinical_note`` is non-empty, every finding's ``quote`` must
    appear (case-insensitive, whitespace-normalised) in the note. Findings
    whose quote is not in the note are dropped with an
    :class:`AuditValidationError` (a hard failure: the auditor fabricated
    evidence, which is the line between 'audit' and 'fraud' under Stark /
    AKS / Health Information Acts).

    Raises :class:`AuditValidationError` if the payload is not a dict,
    if ``findings`` is missing or not a list, or if any individual
    finding violates the schema. ``finding_id`` is optional and defaults
    to ``""``.
    """
    if not isinstance(payload, Mapping):
        raise AuditValidationError(
            f"response is not a JSON object (got {type(payload).__name__})"
        )

    raw = payload.get("findings")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AuditValidationError(
            f"'findings' must be a list (got {type(raw).__name__})"
        )

    findings: list[Finding] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise AuditValidationError(
                f"findings[{i}] is not a JSON object (got {type(item).__name__})"
            )
        # Required: severity (so the dashboard can colour-code).
        # category and suggested_code are optional. quote is also
        # optional now — the model sometimes emits findings without
        # a verbatim quote (e.g. it summarises the note in explanation
        # instead). If quote is missing, we synthesise a placeholder
        # from the explanation / rationale so the rest of the
        # pipeline can render the finding without crashing.
        for key in ("severity",):
            if key not in item:
                raise AuditValidationError(
                    f"findings[{i}] missing required field '{key}'"
                )
        # Normalize severity to lowercase. Different models echo
        # back "CRITICAL" vs "critical"; we only care about the value.
        sev_raw = str(item.get("severity", "")).strip().lower()
        if sev_raw not in {"info", "low", "medium", "high", "critical"}:
            raise AuditValidationError(
                f"findings[{i}].severity not in "
                f"[info, low, medium, high, critical]: got {item.get('severity')!r}"
            )
        # Accept the rule id in either of two shapes:
        #   - rule_id:  "rule_em_001"
        #   - rule_ids: ["rule_em_001", "rule_em_002"]
        # Some models use one, some the other; we accept both.
        rule_ids_raw = item.get("rule_ids")
        if rule_ids_raw is None:
            single = item.get("rule_id")
            rule_ids = [single] if isinstance(single, str) and single else []
        else:
            rule_ids = list(rule_ids_raw)
        if not all(isinstance(r, str) for r in rule_ids):
            raise AuditValidationError(
                f"findings[{i}].rule_ids must be a list of strings"
            )
        # Synthesize a quote if the model omitted it. We pull a
        # 1-sentence excerpt from the explanation / rationale and
        # check it against the clinical note. If we can't find a
        # substring match, we fall back to the model's own quote
        # verbatim — even an unsynthesized quote is better than
        # dropping the finding on the floor.
        quote = str(item.get("quote", "") or "").strip()
        if not quote:
            for source_field in ("explanation", "rationale"):
                src = str(item.get(source_field, "") or "").strip()
                if not src:
                    continue
                # Try the first sentence of the source field.
                first_sentence = re.split(r"[.\n!?]", src, maxsplit=1)[0].strip()
                if not first_sentence:
                    continue
                if not clinical_note or _quote_in_note(first_sentence, clinical_note):
                    quote = first_sentence
                    break
            else:
                # No usable quote from any source field. Use the
                # model's explanation as the quote verbatim — it's
                # better than nothing for the dashboard display.
                quote = str(item.get("explanation", "") or "")[:500]
        # P11 round-3 (2026-07-02): canonicalize the rule_ids. The LLM
        # often emits a generic / slightly-off label (e.g.
        # "MOD-25-SAME-DAY-001" instead of the prompt's canonical
        # "rule_ahcip_modifier_25_unlock") because the JSON schema
        # permits any string. Without canonicalization the 1-page
        # report + downstream SOMB dollar mapping don't recognize
        # the finding. The alias map (defined above) catches the
        # patterns the LLM actually emits on MiniMax-M3 + maps them
        # back to the canonical SOMB-aware rule_id.
        canonical_rule_ids = tuple(_canonicalize_rule_id(r) for r in rule_ids)
        # Hallucination guardrail: if we have a clinical note to check against,
        # reject any finding whose quote is not in the note. The whole
        # finding (suggested_code + severity + rule_ids) is suspect when the
        # supporting evidence is fabricated, so we drop the whole row.
        if clinical_note and quote and not _quote_in_note(quote, clinical_note):
            raise AuditValidationError(
                f"findings[{i}].quote does not appear in the clinical note "
                f"(quote={quote[:80]!r}): fabricated evidence rejected"
            )
        findings.append(
            Finding(
                category=str(item.get("category", "")),
                suggested_code=str(item.get("suggested_code", "")),
                quote=quote,
                severity=str(item["severity"]),
                rule_ids=canonical_rule_ids,
                finding_id=str(item.get("finding_id", "") or ""),
                explanation=str(item.get("explanation", "")),
            )
        )
    return tuple(findings)


def run_audit(
    encounter: Mapping[str, Any],
    *,
    llm: LLMClient | None = None,
    prompt_path: str | Path | None = None,
    max_retries: int = 1,
) -> AuditResult:
    """Run the auditor on a single encounter.

    Builds the messages, dispatches them through ``llm`` (a default
    :class:`LLMClient` is constructed when ``None``), validates the
    response, and returns a typed :class:`AuditResult`.

    Passes the encounter's ``clinical_note`` into :func:`validate_findings`
    so fabricated quotes are rejected at the validator layer (Stark / AKS
    / HIA hallucination guardrail).

    ``max_retries`` (default 1) re-invokes the model with a slightly
    stronger directive when the response has zero findings AND a
    non-empty clinical note (a known calibration regression on the
    pinned minimax-m3 model where the long prompt + JSON-schema
    envelope flips the model into "summarize" mode and emits no
    findings even on encounters with a known SOMB issue). The retry
    appends a short follow-up message: "Re-check: the previous
    response contained zero findings. SOMB rules commonly missed
    on this encounter shape are <rule list>. Re-emit findings as
    JSON." This nudges the model back into "find issues" mode
    without modifying the prompt (which would invalidate the v12
    recall number).
    """
    # Default 60s is too tight for the v7 prompt + Ollama cloud path
    # (mean=41s, p95=60s on the 50-encounter val set, 23/50 timed out
    # at the 60s ceiling). 180s gives the cloud model enough headroom
    # for the few-shot examples + multi-market framing without flapping.
    client = llm if llm is not None else LLMClient(timeout=180.0)
    prompt = load_prompt(prompt_path)
    messages = build_messages(encounter, prompt=prompt)
    # Default to a low (deterministic-ish) temperature for the
    # auditor. Higher temps push the model toward creative
    # generation, which for a structured JSON-schema task adds
    # noise without lifting recall. 0.2 is a known-good middle
    # ground: deterministic enough for stable recall/P across
    # runs but non-zero so identical prompts don't always emit
    # the same word. Caller can override by passing
    # ``temperature=`` via LLMClient construction or by
    # wrapping ``client.complete``.
    payload = client.complete_json(messages, RESPONSE_JSON_SCHEMA, temperature=0.2)
    # Retry-on-empty: if the model returned 0 findings AND a clinical
    # note was provided (i.e. the model had something to work with),
    # re-prompt with a follow-up nudge that asks for re-emission.
    # This protects recall against the calibration regression
    # observed on the pinned model in 2026-07-03 smoke tests.
    if (
        max_retries > 0
        and not (payload.get("findings") or [])
        and str(encounter.get("clinical_note", "") or "").strip()
    ):
        for attempt in range(max_retries):
            messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        "Re-check the previous response: it returned zero "
                        "findings. AHCIP SOMB rules commonly missed on "
                        "encounters of this shape include: dx-linkage "
                        "(empty/missing diagnosis codes), modifier-25 "
                        "unlock (same-day E/M + procedure), CMGP "
                        "eligibility (T2DM/HTN/CKD/COPD/CHF with no "
                        "modifier claimed), telehealth premium (visit "
                        "by phone/video), and consultation code when a "
                        "referring practitioner ID is present. Re-emit "
                        "any applicable findings as JSON."
                    ),
                }
            ]
            retry_payload = client.complete_json(
                messages, RESPONSE_JSON_SCHEMA, temperature=0.2
            )
            if retry_payload.get("findings"):
                payload = retry_payload
                break
    # Normalize severity to lowercase. Different models echo
    # back "CRITICAL" vs "critical"; the jsonschema enum requires
    # lowercase but the model prompt often writes uppercase.
    # We accept both shapes by lowercasing before validation.
    for f in payload.get("findings") or []:
        if isinstance(f, dict) and "severity" in f:
            f["severity"] = str(f["severity"]).strip().lower()
    clinical_note = str(encounter.get("clinical_note", "") or "")
    findings = validate_findings(payload, clinical_note=clinical_note)
    summary = str(payload.get("summary", "") or "")
    return AuditResult(
        encounter_id=str(encounter.get("encounter_id", "") or ""),
        findings=findings,
        summary=summary,
    )
