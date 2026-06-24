# BUGS_refusal_2026_06_17.md — Adversarial-Note Refusal Handling

Findings from the adversarial-note refusal probe (kanban `t_11ed45d6`).
Investigation only — no auditor code was modified.

Companion to: `docs/QA_REFUSAL_RESULTS.md` (per-case transcripts and verdicts).

---

## BUG-REFUSAL-01 — Model refusal text surfaces as generic JSONDecodeError on the operator dashboard

**Severity: Medium**

**Status: Open (no fix shipped — out of scope per the task body)**

**Found by:** kanban `t_11ed45d6` (2026-06-17, hermetic probe)

**Related docs:** `docs/QA_REFUSAL_RESULTS.md` cases 2 and 6.

### One-line summary

When minimax returns a refusal sentence instead of the `RESPONSE_JSON_SCHEMA`
JSON object, the auditor raises `json.JSONDecodeError: Expecting value at
pos 0` and the operator dashboard surfaces it as a generic parse failure.
There is no way for the operator to distinguish "model refused" from
"network truncated the response" or "model emitted a partial JSON
object" — three operationally different situations that warrant three
different responses.

### Affected surface

* `src/ai_billing_audit/llm.py` `LLMClient.complete_json` (the
  `json.loads(content)` call) — the call site that raises
  `JSONDecodeError` on any non-JSON content.
* `src/ai_billing_audit/auditor.py` `run_audit` — propagates the
  `JSONDecodeError` to callers; the operator-facing dashboard
  renders the bare exception message.

### Detail

For cases 2 (empty note) and 6 (base64 note), the simulated minimax
response is a plain-English refusal sentence beginning with "I cannot
help with that request." The current code path is:

1. `LLMClient.complete_json` calls `json.loads(content)` directly.
2. `json.loads` raises `JSONDecodeError: Expecting value at pos 0`.
3. `run_audit` does not catch the error, so the exception propagates
   to the caller.
4. The operator dashboard renders the bare exception class +
   message, with no signal that the cause is a model refusal.

The acceptance criterion flagged in the task body is: capture the raw
output verbatim, classify it. The current behavior *does* capture the
raw output (the exception message includes the position, but the full
content is not echoed), but the classification is degraded: the
operator has to dig into the structured logs to recover the original
refusal text.

### Recommended fix direction

* Catch `JSONDecodeError` in `LLMClient.complete_json`. If the
  stripped content starts with a refusal-marker phrase (e.g.
  "I cannot", "I am unable", "I don't", "Sorry"), raise a new
  `LLMRefusalError` carrying the full content as a `refusal_text`
  attribute. Otherwise re-raise as `JSONDecodeError` (preserves the
  current truncated-response behavior).
* Surface `LLMRefusalError` in the dashboard as a distinct category
  ("model refused — review note and re-run") rather than a generic
  parse error.

This is a Medium-severity UX bug, not a correctness bug: the
auditor's downstream contract is preserved (no false `findings=[]`
result is produced). The fix is small and well-scoped.

### Cross-references

* `docs/QA_REFUSAL_RESULTS.md` cases 2 and 6 — full transcripts.
* `docs/BUGS_llm_json.md` BUG-LLM-04 — same shape of issue for a
  prior refusal-text variant; the recommended fix here generalises
  that one.

---

## BUG-REFUSAL-02 — Auditor does not redact PHI echoed by the model into the summary field

**Severity: High (PHI exposure / HIPAA risk)**

**Status: Open (no fix shipped — out of scope per the task body)**

**Found by:** kanban `t_11ed45d6` (2026-06-17, hermetic probe, case 7)

**Related docs:** `docs/QA_REFUSAL_RESULTS.md` case 7.

### One-line summary

When the model's `summary` field contains a verbatim patient
identifier (e.g. an EHR URL with the patient's name slug), the
auditor returns the `summary` to the caller unmodified. The PHI
propagates into the audit result, the operator dashboard, the
audit trail, and any downstream log file. The auditor has no PHI
redaction step in the post-LLM path.

### Affected surface

* `src/ai_billing_audit/auditor.py` `run_audit` — the line
  `summary = str(payload.get("summary", "") or "")` and the
  returned `AuditResult.summary` field. No redaction is applied
  between the model's free-text output and the typed result.
* `src/ai_billing_audit/auditor.py` `Finding.quote` — the same
  issue applies if the model echoes PHI in a `quote` field. The
  prompt does say the `quote` must come from `clinical_note`, so
  in normal use the `quote` cannot contain PHI not already in
  `clinical_note`. The `summary` has no such constraint.
* Downstream: `src/ai_billing_audit/audit_log.py` and the
  portal `Encounter.summary` field — both will persist the
  unredacted value.

### Detail

For case 7, the simulated minimax response includes the literal
string `https://ehr.localhost/patients/john-a-smith/MRN-00482193/encounters`
in the `summary` field. The hermetic probe captured this output
verbatim and flagged the case as BUG: the auditor's `run_audit`
returns the value unchanged, no redaction step is invoked, and the
PHI flows into the audit result.

This is a real-world risk: the auditor prompt tells the model to
"be conservative" and "cite the rules that support your conclusion"
but does not instruct the model to redact patient identifiers from
the free-text `summary`. A model that follows the natural shape of
the input (a `clinical_note` that contains a URL with a patient
name) and references that URL in the summary will leak PHI into
the audit trail.

The acceptance criterion in the task body explicitly flags this
case: "case (7) note contains a PHI URL with a patient name."
The probe correctly classifies this as BUG (silent PHI propagation,
operator cannot tell from the result that PHI is present).

### Recommended fix direction

* Add a post-LLM redaction pass in `run_audit` that scrubs:
  - patient-name slugs in URL paths (regex: `/patients/([a-z0-9-]+)/`,
    replace with `/patients/[REDACTED-PATIENT]/`)
  - MRN tokens (regex: `MRN-?[0-9]+`, replace with `MRN-[REDACTED]`)
  - explicit patient names from the input encounter's patient
    fields (if the input carries them) — compare to the encounter's
    patient hash and scrub any literal name match from the output.
* Apply the same redaction to every `Finding.quote` field that is
  not a verbatim substring of the input `clinical_note`. (This is a
  defence-in-depth check: the prompt says `quote` must be a
  verbatim substring, but the auditor does not currently enforce
  it.)
* Wire the redaction failure into the existing
  `apps/portal/lib/phi.ts` helper (the portal already has a PHI
  redaction utility for the upload path — reuse it server-side).

This is a High-severity issue because it is a HIPAA-relevant PHI
exposure vector. The fix touches the audit pipeline at a single
point (`run_audit` post-LLM hook) but should be coordinated with
the existing portal PHI redaction work to avoid two divergent
implementations.

### Cross-references

* `docs/QA_REFUSAL_RESULTS.md` case 7 — full transcript and
  verdict.
* `docs/SEC_REVIEW_phi.md` — earlier PHI exposure analysis
  (covers the upload path; this bug extends the gap to the
  auditor's response surface).
* `apps/portal/lib/phi.ts` — the existing redaction utility that
  the recommended fix should reuse.

---

## Methodology

The probe (`scripts/qa_refusal_probe.py`) is hermetic — no network,
no API key. It builds each of the 10 adversarial encounters exactly
as specified in the kanban task body, routes them through the full
auditor code path (`load_prompt` -> `build_messages` ->
`LLMClient.complete_json` envelope -> `json.loads` -> local
`jsonschema.validate` -> `validate_findings`), and captures the
verbatim raw response from a `FakeLLM` that returns one canned
string per case. The canned strings are chosen to represent the
response mode minimax has been observed (or would be expected, for
edge cases) to emit for that adversarial input.

The probe does **not** test the live model. The hermetic path
exercises the full auditor code path against canned minimax-style
responses, so it covers the auditor's handling of each failure mode
end-to-end. The exact minimax output is replaced with a
representative canned value per case, and the QA results doc states
the substitution explicitly. Re-running the probe against the live
model is a one-line change: replace `FakeLLM` with `MiniMaxClient`
and set `MINIMAX_API_KEY`. The probe script is the artifact; the
QA doc is the human-readable summary.

Results at: `runs/qa_refusal_results.json` (one JSON object per
case, including the verbatim raw response and the verdict
classification).
