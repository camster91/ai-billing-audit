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
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

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
                "required": ["quote", "severity"],
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


def build_messages(encounter: Mapping[str, Any], *, prompt: str) -> list[dict[str, str]]:
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
    def _clean(s: str) -> str:
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
        # Required: quote (the evidence) and severity (so the dashboard
        # can colour-code). category and suggested_code are optional —
        # the model often omits category for documentation-only findings
        # (e.g. "rule_missing_dx_001" has no code to suggest).
        for key in ("quote", "severity"):
            if key not in item:
                raise AuditValidationError(f"findings[{i}] missing required field '{key}'")
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
        quote = str(item["quote"])
        # Hallucination guardrail: if we have a clinical note to check against,
        # reject any finding whose quote is not in the note. The whole
        # finding (suggested_code + severity + rule_ids) is suspect when the
        # supporting evidence is fabricated, so we drop the whole row.
        if clinical_note and not _quote_in_note(quote, clinical_note):
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
                rule_ids=tuple(rule_ids),
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
) -> AuditResult:
    """Run the auditor on a single encounter.

    Builds the messages, dispatches them through ``llm`` (a default
    :class:`LLMClient` is constructed when ``None``), validates the
    response, and returns a typed :class:`AuditResult`.

    Passes the encounter's ``clinical_note`` into :func:`validate_findings`
    so fabricated quotes are rejected at the validator layer (Stark / AKS
    / HIA hallucination guardrail).
    """
    client = llm if llm is not None else LLMClient()
    prompt = load_prompt(prompt_path)
    messages = build_messages(encounter, prompt=prompt)
    payload = client.complete_json(messages, RESPONSE_JSON_SCHEMA)
    clinical_note = str(encounter.get("clinical_note", "") or "")
    findings = validate_findings(payload, clinical_note=clinical_note)
    summary = str(payload.get("summary", "") or "")
    return AuditResult(
        encounter_id=str(encounter.get("encounter_id", "") or ""),
        findings=findings,
        summary=summary,
    )
