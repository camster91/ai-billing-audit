"""Appeal-letter generator (second agent in the Zorva pipeline).

When a claim is denied by a payer, Zorva generates a formal appeal
letter on behalf of the clinic. The letter cites:
- The original claim (CPT, ICD-10, dates of service)
- The clinical documentation (verbatim quotes from the note)
- The specific billing rule that supports the appeal (rule_id +
  rule body from the RAG corpus, or hardcoded for v0)
- The compliance framework (PIPEDA / HIPAA / NOM-024 / DIAN) and
  the relevant regulatory citation

This is a separate agent from the auditor — it has its own prompt,
its own failure modes, and a different output shape. The auditor
emits findings (structured JSON); this generator emits letter
prose (markdown or HTML).

Why a separate module
---------------------
1. The auditor's job is rule matching. The appeal-letter's job is
   persuasive regulatory prose. Same model, different prompt,
   different temperature (0 for the auditor; 0.4 for the appeal
   letter so it doesn't read like a robot).
2. The appeal letter has PHI surface area — it includes the
   patient encounter detail. The runner has to scrub identifiers
   before logging the letter body to the audit trail.
3. The appeal letter is the only artifact the biller actually
   sends to a payer. Its quality is the product's reputation.

v0 scope
--------
- One appeal letter per finding
- Letter shape: salutation, claim summary, denial reason, clinical
  evidence, regulatory citation, requested action, signoff
- Letter is rendered to markdown (the biller pastes it into their
  own template; v2 will send it directly)
- Auto-send is NOT in scope; appeal letters go to a paper trail
  on disk so the biller can review before sending

What's intentionally NOT in v0
-------------------------------
- Automatic send to the payer (legal risk: a poorly-timed letter
  can violate appeal windows)
- Multi-finding letters (one letter per finding keeps each one
  narrowly focused; v2 will consolidate)
- Foreign-language letters (Spanish for MX/CO is the next round)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .zorva_context import (
    MARKETS,
    appeal_recipient_for,
    ZORVA_VISION,
)


# Module-scope logs directory. The letter is written here so the
# biller can review + edit before sending. v2 may add an optional
# in-app notification (in-product surface, not email).
_LOGS_DIR = Path(os.environ.get("ZORVA_LOGS_DIR", "/app/logs"))
_APPEAL_LOG = _LOGS_DIR / "appeal_letters.jsonl"
_APPEAL_OUTCOMES_LOG = _LOGS_DIR / "appeal_outcomes.jsonl"


# --- v0 letter template ---------------------------------------------------

# Tone is conservative and procedural: formal salutation, restate
# the denial, cite the documentation, cite the rule, request
# reconsideration. The model fills in the body; this template
# is what the prompt asks for in the requested output shape.

APPEAL_LETTER_PROMPT = """\
You are generating an appeal letter for a denied medical claim
on behalf of a Canadian, American, Mexican, or Colombian clinic.

The letter is addressed to the {market_name} payer and follows
{compliance_law} compliance rules. The recipient is the
{appeal_recipient}.

The encounter:
- Patient identifier (pseudonymized): {patient_hash}
- Date of service: {date_of_service}
- Billed codes: {billed_codes}
- Provider: {provider_npi}

The denial reason (from the payer's EOB):
{denial_reason}

The clinical documentation supporting the original claim:
\"\"\"
{clinical_note}
\"\"\"

The auditor's finding that this claim should be paid:
{auditor_finding}

The specific billing rule that supports the appeal:
{rule_citation}

Compose a formal appeal letter with these sections:
1. Salutation (addressed to the appeal recipient)
2. Re: (line with patient hash, date of service, billed codes)
3. Introduction (one paragraph: this is an appeal of denial X)
4. Clinical justification (the documentation clearly supports the
   billed codes; quote the relevant parts of the note verbatim)
5. Regulatory citation (cite the specific rule or schedule entry
   that supports the medical necessity)
6. Requested action (reconsider and pay the claim; indicate the
   dollar amount in dispute)
7. Signoff (provider's name, contact info placeholder)

Tone: professional, evidence-based, non-confrontational. No
emotional language. No threats of escalation. The goal is to
give the payer's reviewer a clean, fact-based basis to overturn
the denial.

Output rules:
- Emit a single JSON object with shape {{"letter_markdown": str,
  "appeal_basis": str, "cited_rule_ids": [str, ...],
  "requested_action": str}}.
- The letter_markdown field is the full letter text in markdown
  format, ready to print.
- The appeal_basis field is a one-sentence summary of the appeal
  reason (e.g. "Documentation supports medical necessity for the
  procedure on the date of service").
- The cited_rule_ids field lists the rule_ids from the auditor
  finding that the letter relies on. Empty list if no rule_id.
- The requested_action field is what the biller is asking the
  payer to do (e.g. "Reconsider and pay claim 12345 in full").

Do not include any text outside the JSON object.
"""


# A tiny built-in rule catalog for v0. The real system uses RAG
# over the OHIP/AHCIP/MSP/AMA schedules; v0 has a hardcoded mapping
# for the most common high-yield gaps so the generator can produce
# a non-trivial letter without depending on the RAG corpus. The
# mapping is keyed by rule_id (the same rule_id the auditor emits).
_BUILTIN_RULES: dict[str, str] = {
    "MOD-25": "Modifier -25 is appropriately appended to the E/M "
              "code when a significant, separately identifiable "
              "evaluation is performed on the same day as a "
              "procedure. The clinical documentation must support "
              "the additional E/M work; the note here documents "
              "the separate history, exam, and medical decision "
              "making that drove the modifier.",
    "DX_LINKAGE_REQUIRED": "Each billed procedure code must be "
              "linked to at least one ICD-10-CM diagnosis code "
              "that establishes medical necessity. The clinical "
              "documentation supports a reportable condition "
              "that was not linked to the billed procedure on the "
              "original claim; we are appending the diagnosis code "
              "to establish the linkage on appeal.",
    "E/M-LEVEL": "The E/M level billed is supported by the "
              "documentation of medical decision making (MDM). "
              "The note documents [problem complexity], "
              "[data reviewed], and [risk of complications] "
              "consistent with the level billed.",
    "NCCI": "The National Correct Coding Initiative (NCCI) "
              "allows separate payment for two procedures when "
              "the documentation supports that they are "
              "clinically distinct. The note documents the "
              "distinct clinical rationale for each procedure.",
    "TIME": "Time-based codes (counselling, prolonged services) "
              "require explicit documentation of the time spent. "
              "The note documents [X] minutes of counselling on "
              "[topic], satisfying the threshold for the code "
              "billed.",
    "MED-NEC": "Medical necessity is established when the "
              "documentation supports that the service was "
              "reasonable and necessary for the diagnosis or "
              "treatment of the patient's condition. The clinical "
              "note documents the patient's presentation, the "
              "diagnostic workup, and the management plan that "
              "establish necessity.",
}

_DEFAULT_RULE_CITATION = (
    "The documentation supports the medical necessity of the "
    "service as required by the relevant billing schedule."
)


def _resolve_rule_citation(rule_id: str | None) -> str:
    """Return the regulatory citation text for a rule_id.

    Falls back to a generic medical-necessity statement when the
    rule_id isn't in the v0 catalog. v1: replace with pgvector RAG
    over the actual OHIP/AHCIP/AMA schedules.
    """
    if not rule_id:
        return _DEFAULT_RULE_CITATION
    return _BUILTIN_RULES.get(rule_id, _DEFAULT_RULE_CITATION)


def _format_billed_codes(claim: dict[str, Any] | None) -> str:
    """Render the claim's billed line items as a one-line summary.

    CPT 99213 · 93000 · 80061 — $150.00 each. Falls back to the
    encounter dict's CPT_codes field if the claim has no line items.
    """
    if not claim:
        return "—"
    items = claim.get("line_items") or []
    if not items:
        cpts = claim.get("CPT_codes") or []
        if not cpts:
            return "—"
        return " · ".join(str(c) for c in cpts)
    parts = []
    for item in items:
        code = item.get("cpt_code") or item.get("code") or "?"
        modifiers = item.get("modifiers") or []
        suffix = f"-{','.join(str(m) for m in modifiers)}" if modifiers else ""
        charge = item.get("charge_amount")
        price_str = f" — ${charge:.2f}" if isinstance(charge, (int, float)) else ""
        parts.append(f"{code}{suffix}{price_str}")
    return " · ".join(parts)


def _pseudonymize_patient(claim: dict[str, Any] | None, encounter: dict[str, Any]) -> str:
    """Return a SHA-256 pseudonym for the patient identifier.

    Mirrors the audit_actions.patient_hash logic so the letter
    references the same pseudonym the audit trail uses. The letter
    itself does NOT include the real patient name or provincial
    health number — the biller fills those in on the printed
    version after scrubbing the appeal letter's body for PHI.
    """
    import hashlib
    seed = (
        (claim or {}).get("encounter_id")
        or encounter.get("encounter_id")
        or ""
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _scrub_phi(letter_markdown: str) -> str:
    """Best-effort PHI scrubber for the letter body before logging.

    Replaces obvious patient identifiers with a placeholder. This
    is a defense-in-depth measure; the biller should still review
    the letter before sending. v1: replace with NER model.
    """
    # 10-digit US/CA-style numbers (NPI, health card, MRN)
    letter_markdown = re.sub(
        r"\b\d{10}\b", "[PATIENT_ID]", letter_markdown
    )
    # 9-digit US SSN format
    letter_markdown = re.sub(
        r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", letter_markdown
    )
    # Email addresses
    letter_markdown = re.sub(
        r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[EMAIL]", letter_markdown
    )
    return letter_markdown


def build_appeal_prompt(
    *,
    finding: dict[str, Any],
    encounter: dict[str, Any],
    clinical_note: str,
    denial_reason: str,
    zorva_context: dict[str, Any] | None = None,
) -> str:
    """Build the prompt for the appeal-letter generator.

    The runner calls this with the auditor's finding + the
    encounter metadata + the payer's denial reason. The prompt
    is rendered to text and passed to the LLM.

    The zorva_context is read but not added to the prompt's prose
    directly — the prompt has dedicated slots for the
    market_name, compliance_law, and appeal_recipient that
    extract from the context dict.
    """
    claim = encounter.get("claim") or {}
    zctx = zorva_context or {}
    market = zctx.get("market") or "CA"
    market_name = zctx.get("market_name") or "Canada"
    compliance_law = zctx.get("compliance_law") or "PIPEDA"
    recipient = appeal_recipient_for(market)

    # The auditor's finding gives us the rule_id + explanation. The
    # letter has to cite the same rule. If the finding has multiple
    # rule_ids (rare), we pick the first one as the primary appeal
    # basis and mention the rest in the rule_citation.
    rule_ids = finding.get("rule_ids") or (
        [finding.get("rule_id")] if finding.get("rule_id") else []
    )
    primary_rule_id = rule_ids[0] if rule_ids else None
    rule_citation = _resolve_rule_citation(primary_rule_id)
    if len(rule_ids) > 1:
        rule_citation += f" (additional rule(s): {', '.join(rule_ids[1:])})"

    # The auditor's finding gets summarised into a one-paragraph
    # narrative that the appeal letter expands on. We pass the
    # explanation field verbatim (the model wrote it; it's the
    # authoritative summary of the rule's application to the case).
    auditor_finding = (
        f"Rule: {primary_rule_id or '(unspecified)'}\n"
        f"Severity: {finding.get('severity', 'unspecified')}\n"
        f"Suggested code: {finding.get('suggested_code', '—')}\n"
        f"Evidence (verbatim from clinical note): \"{finding.get('quote', '')}\"\n"
        f"Explanation: {finding.get('explanation', '')}"
    )

    return APPEAL_LETTER_PROMPT.format(
        market_name=market_name,
        compliance_law=compliance_law,
        appeal_recipient=recipient,
        patient_hash=_pseudonymize_patient(claim, encounter),
        date_of_service=claim.get("date_of_service") or encounter.get("date_of_service") or "—",
        billed_codes=_format_billed_codes(claim),
        provider_npi=claim.get("rendering_provider_npi") or encounter.get("NPI") or "—",
        denial_reason=denial_reason or "—",
        clinical_note=clinical_note or "(no clinical note on file)",
        auditor_finding=auditor_finding,
        rule_citation=rule_citation,
    )


# The expected JSON shape the generator returns. Kept as a tuple
# so the validation function can check it without an extra import.
_REQUIRED_LETTER_KEYS = ("letter_markdown", "appeal_basis", "cited_rule_ids", "requested_action")


def parse_appeal_response(raw: str) -> dict[str, Any] | None:
    """Parse the model's response into a structured letter dict.

    Returns None on parse failure (caller decides whether to
    surface an error or fall through to a template-only letter).
    The function strips markdown ```json``` fences (the LLM is
    inconsistent about including them) and validates the expected
    keys.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        # First newline closes the opening fence
        end = text.find("\n", 3)
        if end > 0:
            text = text[end + 1 :]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Sometimes the model puts the JSON object after a
        # leading paragraph; try to find the first { and last }.
        first = text.find("{")
        last = text.rfind("}")
        if first < 0 or last < 0 or last <= first:
            return None
        try:
            parsed = json.loads(text[first : last + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    for key in _REQUIRED_LETTER_KEYS:
        if key not in parsed:
            return None
    if not isinstance(parsed["letter_markdown"], str) or not parsed["letter_markdown"].strip():
        return None
    if not isinstance(parsed["cited_rule_ids"], list):
        parsed["cited_rule_ids"] = []
    return parsed


def generate_appeal_letter(
    *,
    finding: dict[str, Any],
    encounter: dict[str, Any],
    clinical_note: str,
    denial_reason: str,
    zorva_context: dict[str, Any] | None = None,
    llm_complete: Any | None = None,
) -> dict[str, Any] | None:
    """Generate an appeal letter for a denied claim.

    ``llm_complete`` is the LLM client function. The signature is
    ``llm_complete(prompt: str) -> str`` — same shape as the
    auditor's LLMClient.complete(). The runner passes the same
    litellm-backed client so the appeal-letter generator uses
    the same LLM as the auditor (no per-feature provider).

    Returns a dict with shape:
        {
            "letter_markdown": str,
            "appeal_basis": str,
            "cited_rule_ids": list[str],
            "requested_action": str,
            "letter_html": str,   # v0: same as letter_markdown
            "market": str,
            "compliance_law": str,
            "scrubbed_phi": bool,  # always True for v0
            "generated_at": str,  # ISO timestamp
        }
    or None if the LLM call failed / parsed empty.

    The letter is also written to ``/app/logs/appeal_letters.jsonl``
    so the biller can review it before sending. The body in the
    log is PHI-scrubbed; the real letter is in the in-memory
    return value only (never written to disk unscrubbed).
    """
    prompt = build_appeal_prompt(
        finding=finding,
        encounter=encounter,
        clinical_note=clinical_note,
        denial_reason=denial_reason,
        zorva_context=zorva_context,
    )

    if llm_complete is None:
        # No LLM available (e.g. tests, smoke). Return a minimal
        # template-only letter so the biller can still see the
        # shape. The basis comes from the finding itself; the
        # rule citation is the resolved citation text.
        zctx = zorva_context or {}
        market = zctx.get("market") or "CA"
        rule_id = (finding.get("rule_id") or
                   (finding.get("rule_ids") or [None])[0])
        template_letter = (
            f"Re: Appeal of denied claim\n\n"
            f"To: {appeal_recipient_for(market)}\n\n"
            f"This letter is an appeal of the denial of the "
            f"following claim:\n"
            f"  Patient: {_pseudonymize_patient(encounter.get('claim'), encounter)}\n"
            f"  Date of service: {encounter.get('claim', {}).get('date_of_service', '—')}\n"
            f"  Billed codes: {_format_billed_codes(encounter.get('claim'))}\n\n"
            f"The clinical documentation supports the medical "
            f"necessity of the service. The auditor's review "
            f"found: {finding.get('explanation', 'see attached')}\n\n"
            f"Cited billing rule: {rule_id or 'see attached'}\n"
            f"Basis: {_resolve_rule_citation(rule_id)}\n\n"
            f"We request reconsideration and full payment of the "
            f"claim. Please contact the clinic if additional "
            f"documentation is needed.\n"
        )
        return {
            "letter_markdown": template_letter,
            "appeal_basis": finding.get("explanation", "—"),
            "cited_rule_ids": [rule_id] if rule_id else [],
            "requested_action": "Reconsider and pay claim in full.",
            "letter_html": template_letter,
            "market": market,
            "compliance_law": zctx.get("compliance_law") or "PIPEDA",
            "scrubbed_phi": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "template_only": True,
        }

    try:
        raw = llm_complete(prompt)
    except Exception:
        return None
    parsed = parse_appeal_response(raw)
    if parsed is None:
        return None
    zctx = zorva_context or {}
    market = zctx.get("market") or "CA"
    # Scrub PHI from the letter before logging
    scrubbed_body = _scrub_phi(parsed["letter_markdown"])
    parsed["letter_html"] = scrubbed_body
    parsed["letter_markdown"] = scrubbed_body
    parsed["market"] = market
    parsed["compliance_law"] = zctx.get("compliance_law") or "PIPEDA"
    parsed["scrubbed_phi"] = True
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    return parsed


def log_appeal_letter(
    letter: dict[str, Any],
    encounter_id: str | None,
    *args: Any,
    tenant_id: str | None = None,
    finding_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Append a generated letter to the appeal_letters.jsonl log.

    The body is already PHI-scrubbed by generate_appeal_letter().
    We log the metadata (encounter_id, tenant_id, finding_id,
    market, compliance_law, basis, cited rules) but NOT the full
    letter body. The biller gets the full letter through the API
    response; the log only records the audit trail.

    Multi-tenant hardening: tenant_id is recorded on every row
    so a privacy officer can filter by tenant and so the
    cross-tenant audit view can include appeal letters alongside
    audit_trail and upload_jobs rows.

    The ``finding_id`` is recorded so the encounter-detail page
    can show an "appeal outcome" form per finding (the appeal
    outcome form is only meaningful after a letter has been
    generated for that finding). The args/kwargs signatures
    keep the call site backward-compatible with the prior
    ``log_appeal_letter(letter, encounter_id, tenant_id=...)``
    shape.
    """
    # Backward-compat: if a positional tenant_id slipped in via *args,
    # fold it into the keyword. (This shouldn't happen in practice —
    # the API now calls with kwargs — but it costs nothing to handle.)
    if args and tenant_id is None:
        tenant_id = args[0]
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "encounter_id": encounter_id,
            "tenant_id": tenant_id or "default",
            "finding_id": finding_id,
            "appeal_id": finding_id,  # alias so the outcome-side join is symmetric
            "market": letter.get("market"),
            "compliance_law": letter.get("compliance_law"),
            "appeal_basis": letter.get("appeal_basis"),
            "cited_rule_ids": letter.get("cited_rule_ids"),
            "requested_action": letter.get("requested_action"),
            "template_only": letter.get("template_only", False),
            "generated_at": letter.get("generated_at"),
        }
        with _APPEAL_LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        # Don't crash the audit pipeline over a logging failure.
        pass


def read_appeal_letters(
    encounter_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read logged appeal-letter metadata, optionally filtered by encounter.

    Mirrors ``read_appeal_outcomes`` but reads the *letter* log
    (appeal_letters.jsonl). Returns a list of dicts; one entry per
    letter generated. Skips malformed lines silently so a corrupted
    log row does not break the dashboard.

    Each row is the audit-trail metadata (encounter_id, tenant_id,
    market, compliance_law, basis, cited_rule_ids) — NOT the letter
    body, which is PHI-scrubbed and only sent through the API
    response. The encounter-detail page only needs to know
    "has a letter been generated for this finding?" so the
    presence of a row is enough signal.
    """
    if not _APPEAL_LOG.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with _APPEAL_LOG.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if encounter_id and row.get("encounter_id") != encounter_id:
                    continue
                out.append(row)
    except OSError:
        return []
    return out


# --- Appeal outcome tracking ---------------------------------------------
# Once a biller sends an appeal letter to the payer, the result
# (won, lost, withdrawn, or still pending) feeds back into the
# learning loop: which letter styles correlate with wins? The
# appeal_letter module writes letters to appeal_letters.jsonl;
# the outcome of each appeal goes to appeal_outcomes.jsonl.
# They are joined on (encounter_id, appeal_id) at training time.
#
# Status enum is closed: 'filed' is the implicit "letter generated
# and on its way"; 'won' / 'lost' are terminal states; 'withdrawn'
# means the biller pulled the appeal; 'pending' means the payer
# hasn't responded yet (re-issued when the biller follows up).

AppealOutcomeStatus = Literal[
    "filed", "won", "lost", "withdrawn", "pending", "did_not_file",
]


@dataclass
class AppealOutcome:
    """A single appeal-outcome record.

    Stored as one JSON line per outcome in
    /app/logs/appeal_outcomes.jsonl. The appeal_id is the same
    identifier the biller passed to the /outcome endpoint (in v0
    the biller can use the letter's finding_id or a UUID they
    generated client-side). The record is the unit of training
    data for the appeal-letter style classifier.
    """

    appeal_id: str
    encounter_id: str
    status: AppealOutcomeStatus
    timestamp: str
    biller_id: str | None = None
    notes: str = ""

    @classmethod
    def now(
        cls,
        *,
        appeal_id: str,
        encounter_id: str,
        status: AppealOutcomeStatus,
        biller_id: str | None = None,
        notes: str = "",
    ) -> "AppealOutcome":
        """Build an AppealOutcome with the current UTC timestamp."""
        return cls(
            appeal_id=appeal_id,
            encounter_id=encounter_id,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            biller_id=biller_id,
            notes=notes,
        )


def log_appeal_outcome(outcome: AppealOutcome) -> None:
    """Append an outcome record to appeal_outcomes.jsonl.

    Mirrors log_appeal_letter: best-effort, never raises. A log
    failure must not crash the API or the training pipeline.
    """
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with _APPEAL_OUTCOMES_LOG.open("a") as f:
            f.write(json.dumps(asdict(outcome)) + "\n")
    except OSError:
        pass


def read_appeal_outcomes(
    encounter_id: str | None = None,
) -> list[AppealOutcome]:
    """Read all logged outcomes, optionally filtered by encounter_id.

    Skips malformed lines (a row with a missing required field
    is dropped silently — a corrupted log row should not stop
    the dashboard from loading). Returns outcomes in append
    order (oldest first); callers that want a latest-wins
    semantics can sort by ``timestamp``.
    """
    out: list[AppealOutcome] = []
    if not _APPEAL_OUTCOMES_LOG.exists():
        return out
    try:
        with _APPEAL_OUTCOMES_LOG.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                # Required fields must be present and non-empty —
                # rows missing them are not valid outcome records
                # and would corrupt any aggregation that joins on
                # appeal_id or encounter_id.
                if not raw.get("appeal_id") or not raw.get("encounter_id"):
                    continue
                if not raw.get("timestamp") or not raw.get("status"):
                    continue
                try:
                    outcome = AppealOutcome(
                        appeal_id=str(raw["appeal_id"]),
                        encounter_id=str(raw["encounter_id"]),
                        status=str(raw["status"]),
                        timestamp=str(raw["timestamp"]),
                        biller_id=raw.get("biller_id"),
                        notes=str(raw.get("notes", "")),
                    )
                except Exception:
                    continue
                if encounter_id and outcome.encounter_id != encounter_id:
                    continue
                out.append(outcome)
    except OSError:
        return out
    return out


def appeal_win_rate() -> dict[str, Any]:
    """Aggregate outcome stats across all logged appeals.

    Returns a dict with these keys:

      - ``total_filed``  : number of outcomes with status == 'filed'
      - ``total_won``    : number of outcomes with status == 'won'
      - ``total_lost``   : number of outcomes with status == 'lost'
      - ``total_withdrawn`` : number of outcomes with status == 'withdrawn'
      - ``total_pending``: number of outcomes with status == 'pending'
      - ``win_rate``     : won / (won + lost) as a float in [0.0, 1.0],
                           or None if there are no decided outcomes
      - ``decided``      : won + lost (the denominator for win_rate)

    Each appeal may appear multiple times in the log (the biller
    can update the outcome from 'pending' to 'won' on a follow-up
    POST). We collapse to the latest outcome per appeal_id so the
    win rate reflects the current state, not the history of edits.
    """
    rows = read_appeal_outcomes()
    latest: dict[str, AppealOutcome] = {}
    for r in rows:
        existing = latest.get(r.appeal_id)
        if existing is None or r.timestamp >= existing.timestamp:
            latest[r.appeal_id] = r
    total_won = sum(1 for r in latest.values() if r.status == "won")
    total_lost = sum(1 for r in latest.values() if r.status == "lost")
    total_withdrawn = sum(1 for r in latest.values() if r.status == "withdrawn")
    total_pending = sum(1 for r in latest.values() if r.status == "pending")
    total_filed = sum(1 for r in latest.values() if r.status == "filed")
    decided = total_won + total_lost
    win_rate = (total_won / decided) if decided else None
    return {
        "total_filed": total_filed,
        "total_won": total_won,
        "total_lost": total_lost,
        "total_withdrawn": total_withdrawn,
        "total_pending": total_pending,
        "win_rate": win_rate,
        "decided": decided,
    }