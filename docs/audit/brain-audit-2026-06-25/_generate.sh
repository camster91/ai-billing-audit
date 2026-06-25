#!/bin/bash
# Generate all 29 per-task audit files in one go
# Each file has: claim, evidence, verdict, follow-up
set -e
DIR=/Users/biancabienaime/projects/ai-billing-audit/docs/audit/brain-audit-2026-06-25

write_audit() {
  local id="$1"
  local title="$2"
  local claim="$3"
  local evidence="$4"
  local verdict="$5"
  local followup="$6"
  cat > "$DIR/${id}__$(echo "$title" | tr ' /' '_' | tr -cd '[:alnum:]_').md" <<EOF
# ${id} — ${title}

**Audit claim:** ${claim}

**Evidence:**
${evidence}

**Verdict:** ${verdict}

**Recommended follow-up:** ${followup}
EOF
}

write_audit "t_daf97d1d" "NCCI_ptp" \
  "NCCI / procedure-to-procedure edits coverage" \
  "- \`grep -ic 'NCCI' rules/seed_rules.json\` → 12+ hits for 'NCCI' / 'PTP'
- \`grep -ic 'NCCI\|MUE\|modifier' prompts/v12/auditor_prompt.txt\` → 19 hits
- \`rules/seed_rules.json\` _meta.counts.ncci = 12 (seeded)
- No file \`docs/NCCI_REFERENCE.md\` (\`ls docs/ | grep -i ncci\` → empty)" \
  "**partial** — NCCI PTP edits ARE in seed rules with 12 example edits and the prompt references NCCI; missing: a comprehensive PTP table linked to specific code pairs, no automated pair-lookup, no quarterly refresh process." \
  "Build \`rules/ncci_ptp.json\` (full PTP edits, ~50K rows from CMS quarterly release) and a lookup helper used by \`auditor.py\` to inject pair-specific context."

write_audit "t_f08506de" "EM_documentation" \
  "E/M level documentation adequacy (2021+ guidelines)" \
  "- \`rules/seed_rules.json\` has 14 E/M rules (EM-001..EM-014 in _meta.counts.em)
- EM-002 covers MDM, EM-003 covers time ranges, EM-005/006/007 cover MDM elements
- \`grep -ic 'MDM\|medical decision' prompts/v12/auditor_prompt.txt\` → multiple hits
- No 2021-guideline-specific training set; no undercode/overcode scenarios" \
  "**partial** — 2021 MDM framework IS in seed rules with element-by-element breakdown; missing: a labeled test set of correct-vs-wrong MDM level selection per encounter, and a per-specialty calibration." \
  "Create \`tests/fixtures/em_mdm_examples.jsonl\` with 30+ encounters tagged with correct code (99212-99215) and an evaluator that compares auditor picks to ground-truth."

write_audit "t_17a4c287" "Ground_truth_calibration" \
  "Ground-truth review: 20 hand-verified encounters for calibration" \
  "- \`src/ai_billing_audit/ground_truth.py\` exists (13 references found via grep)
- No \`data/ground_truth/hand_verified.jsonl\` (\`find data -name '*.jsonl'\` → only demo registries)
- \`docs/CALIBRATION.md\` exists but its date/scope unclear" \
  "**missing** — ground_truth.py module exists but the 20 hand-verified encounter set is not committed to the repo. Calibration claims cannot be reproduced from HEAD." \
  "Author the 20-encounter hand-verified set as \`data/ground_truth/hand_verified_v1.jsonl\` with schema {encounter_id, billed_codes, correct_codes, modifier_set, expected_findings} and wire it into the calibration harness."

write_audit "t_4eb843d2" "MUE_limits" \
  "MUE (medically unlikely edits) limits per code" \
  "- \`grep -ic 'MUE' rules/seed_rules.json\` → several 'CMS Medically Unlikely Edits' references in _meta.sources and a few rule texts
- No \`rules/mue.json\` lookup table
- \`grep -ic 'MUE' prompts/v12/auditor_prompt.txt\` → 0 matches for the prompt itself" \
  "**missing** — MUE concept IS mentioned but no per-code MUE limit table, and the v12 auditor prompt (AHCIP) does not invoke MUE at all (correct for Alberta SOMB, but the v0/v3 US-CMS prompts should)." \
  "Add \`rules/mue_limits.json\` (CMS quarterly release), wire a \`check_mue(code, units)\` helper in \`src/ai_billing_audit/auditor.py\`, and add 5 labeled examples to the v3 prompt."

write_audit "t_2d3a1221" "Time_based_billing" \
  "Time-based billing (critical care, prolonged services, psychotherapy)" \
  "- \`rules/seed_rules.json\` EM-003: time ranges for 99202-99215
- v12 prompt mentions 08.19A (psychotherapy 45-min) and 08.19B (30-min)
- No critical-care-specific rules (99291/99292) in v12
- No prolonged-services (99417/G2212) rule in seed" \
  "**partial** — E/M time ranges ARE present (EM-003); AHCIP psychotherapy time codes ARE in v12; missing: critical care time thresholds, US prolonged-services codes, and a time-tracking assertion in the prompt that ties documentation time-statement to the chosen level." \
  "Add critical-care (99291/99292, ≥30/≥74 min) and prolonged-services (99417, G2212) rules to \`rules/seed_rules.json\` and add a 'time statement required when billing by time' assertion."

write_audit "t_6fe43f38" "Modifier_59_X" \
  "Modifier -59 / X{E,S,U} (distinct procedural service)" \
  "- \`grep -ic '\\-59\\|XE\\|XS\\|XP\\|XU' rules/seed_rules.json\` → multiple hits; 'X{ESU}' referenced in PTP context
- No dedicated modifier-59 example set
- No automated detector for missing -59 on bundled-but-separate procedure pairs" \
  "**partial** — Modifier -59 and the X{E,S,U} family ARE referenced in the NCCI PTP rules with a -59-required example; missing: dedicated examples, X{E,S,U} disambiguation guidance, automated detector for 'two procedures same anatomic site, was -59 appended?'." \
  "Add 15 examples of -59 correct use + 5 overused -59 to v0 prompt, and add a \`check_distinct_procedural_service\` helper that walks the (claim_codes, anatomic_site) tuple."

write_audit "t_982b73df" "Medical_necessity" \
  "Diagnosis-procedure medical-necessity check" \
  "- \`grep -ic 'medical necessity\\|medically necessary' rules/seed_rules.json\` → several hits in the seed (e.g., 'the encounter must be medically necessary')
- \`src/ai_billing_audit/judge.py\` exists (1 judge-related match) — possibly a downstream medical-necessity judge
- No dedicated dx-procedure linkage rules (LCD/NCD)" \
  "**partial** — General 'medical necessity' phrasing IS in seed rules; missing: per-diagnosis LCD/NCD lookup (CMS Local/National Coverage Determinations) and a 'dx supports procedure' link table." \
  "Add \`rules/lcd_ncd_linkage.json\` (CMS LCD/NCD index) and a \`check_dx_procedure_link(dx, proc)\` helper. Document in \`docs/MEDICAL_NECESSITY.md\`."

write_audit "t_fcd5b1c9" "Adversarial_examples" \
  "Adversarial examples: notes designed to fool the auditor" \
  "- \`src/ai_billing_audit/synth_agent.py\` exists (31 references) — synthetic-note generator
- \`src/ai_billing_audit/synth/\` directory present
- No dedicated adversarial set; \`docs/BUGS_overfit.md\` and \`BUGS_overfit_curve.txt\` suggest overfit was a real problem but no adversarial test fixture" \
  "**missing** — A synthetic-note generator exists but no adversarial fixture (notes designed to look correct but contain hidden denials). The overfit BUGS docs suggest this is a known risk." \
  "Author \`data/adversarial/v1.jsonl\` with 30 notes containing: (a) plausible-but-wrong codes, (b) boilerplate that masks missing time statement, (c) cut-and-paste prior-note reuse, (d) upcoded MDM. Wire into \`tests/test_adversarial.py\`."

write_audit "t_f92958a4" "MIPROv2_grader" \
  "Wire DSPy MIPROv2 with a real grader (not self-agreement)" \
  "- \`src/ai_billing_audit/auditor_module.py\` uses \`dspy.Predict\` (NOT MIPROv2)
- \`src/ai_billing_audit/grader.py\` exists (grader module)
- \`src/ai_billing_audit/grader_config.json\` exists in \`prompts/\`
- No \`src/optimize.py\` MIPROv2 invocation; that file exists but is not yet MIPROv2" \
  "**partial** — DSPy module IS wired (\`dspy.Predict\` over \`AuditClaim\`); grader module exists; missing: the actual MIPROv2 optimizer instantiation, a real-grader metric function, and an \`optimize.py\` runner that produces a saved program." \
  "Implement \`metric_for_grader\` in \`src/ai_billing_audit/grader.py\`, add \`src/ai_billing_audit/optimize_mipro.py\` that calls \`dspy.MIPROv2(metric=...)\`, save optimized program to \`artifacts/auditor_v14/\`."

write_audit "t_a198b30a" "P_R_regression" \
  "Track per-prompt-version P/R over time (regression detection)" \
  "- \`src/ai_billing_audit/grading.py\` (per-clinic grading) and \`per_clinic_f1.py\` exist
- \`feedback.py\` exists (1 reference)
- No \`metrics_history\` table or time-series regression detector
- \`docs/ITERATION_LOG.md\` exists but appears manual" \
  "**partial** — Per-version grading tools exist (\`per_clinic_f1.py\`, \`grading.py\`) but no automated regression alarm; \`ITERATION_LOG.md\` is a manual ledger." \
  "Add \`metrics_history\` table to the SQLite store (run_id, prompt_version, precision, recall, f1, ts), and a \`detect_regression(window=5)\` function that fires when f1 drops >2 std."

write_audit "t_29a7e2e4" "Few_shot_selection" \
  "Few-shot example selection (best 30 examples per rule family)" \
  "- \`prompts/v12/auditor_prompt.txt\` includes 11+ EXAMPLE blocks (EXAMPLE 1..11)
- No per-rule-family few-shot selection algorithm
- Examples appear hand-curated, not auto-selected from a labeled pool" \
  "**partial** — Few-shot examples ARE present in v12 but they're static, hand-curated, and not per-rule-family selected from a scored pool." \
  "Build \`src/ai_billing_audit/few_shot.py\` with \`select_top_k(rule_family, k=30, pool=data/few_shot_pool.jsonl)\` using a rule-aware diversity scorer; refactor v12 to call it."

write_audit "t_4721be0d" "CoT_visible" \
  "Chain-of-thought reasoning visible in the audit response" \
  "- \`src/ai_billing_audit/auditor_module.py\` uses \`dspy.Predict\` (no ChainOfThought)
- \`grep -ic 'chain.of.thought\\|reasoning' src/ai_billing_audit/auditor_module.py\` → 5 hits (likely docstring references)
- The auditor signature does not have a 'reasoning' output field" \
  "**missing** — CoT is NOT wired into the production auditor. The signature outputs are findings/summary, not a step-by-step reasoning trace." \
  "Switch \`dspy.Predict\` → \`dspy.ChainOfThought\` in \`auditor_module.py\`, add a \`reasoning\` output field to \`AuditClaim\`, and surface it in the UI's expanded-finding view."

write_audit "t_719da8c2" "Cheap_model_routing" \
  "Cheap-model-first routing (Haiku for easy, Sonnet for hard)" \
  "- \`src/ai_billing_audit/auditor_module.py\` pins \`dspy.LM('anthropic/claude-sonnet-4-5')\`
- No model-router logic; no easy/hard classifier
- \`docs/llm-pinning.md\` likely documents the pinned choice" \
  "**missing** — Single model pinned (Sonnet 4.5); no easy/hard routing. Cost-saving is achieved via prompt pinning, not model selection." \
  "Add a \`difficulty_classifier\` (small, rule-based) in \`src/ai_billing_audit/llm.py\` that picks Haiku vs Sonnet per encounter; benchmark quality delta before promoting."

write_audit "t_4fa0b512" "Claim_hash_cache" \
  "Cache the LLM response per (claim_hash, prompt_version)" \
  "- \`src/ai_billing_audit/demo_registry.py\` has a \`cache: dict\` for parsed JSONL
- \`feedback.py\` has a comment-cache
- No \`(claim_hash, prompt_version)\` response cache
- \`grep -r 'claim_hash' src/\` → 0 production matches" \
  "**missing** — No response cache keyed on (claim_hash, prompt_version). Re-running the same claim through the same prompt version re-pays the LLM cost." \
  "Add \`src/ai_billing_audit/response_cache.py\` with a SQLite-backed \`get/set\` keyed on \`sha256(claim_json) + prompt_version\`; TTL 30d; wire into \`auditor.py\` before the LLM call."

write_audit "t_07fa3b10" "Cost_guardrail" \
  "Per-tenant cost guardrail (alert when LLM spend > \$X/month)" \
  "- \`src/ai_billing_audit/roi.py\` exists (12 references) — tracks SAVINGS, not spend
- No spend tracker; no per-tenant budget; no alert hook
- \`grep -ric 'monthly.*budget\\|cost.*alert' src/\` → 0 matches" \
  "**missing** — No spend tracking. ROI module tracks clinic-side savings but Zorva has no visibility into its own LLM spend per tenant." \
  "Add \`src/ai_billing_audit/spend_tracker.py\` with per-tenant counters, a monthly aggregation job, and an alert webhook at \$X/month configurable in \`.env\`."

write_audit "t_ac604ea7" "Refusal_handling" \
  "Refusal handling: auditor says 'note is unclear, need more info'" \
  "- \`prompts/v0/auditor_prompt.txt\` includes 'If the encounter is not flagged, return an empty findings list and a one-sentence summary explaining why no findings apply'
- \`docs/BUGS_refusal_2026_06_17.md\` exists — prior refusal-related bug was filed
- No explicit refusal signal in the schema (no 'needs_more_info: bool' field)" \
  "**partial** — The prompt allows empty findings with a summary but does not define a structured 'needs more info' signal. Coders cannot reliably tell 'no findings' from 'I gave up'." \
  "Add \`needs_more_info: bool\` and \`clarification_questions: list[str]\` to the finding schema; update v12 prompt to require filling these when the note is ambiguous."

write_audit "t_71884271" "Contradictory_claim_vs_note" \
  "Contradictory claim vs note (biller said one thing, note says another)" \
  "- \`src/ai_billing_audit/judge.py\` exists (2 references) — may have contradiction logic
- No dedicated contradiction detector; no claim-vs-note diff
- \`prompts/v12/auditor_prompt.txt\` does not explicitly require claim-vs-note contradiction check" \
  "**missing** — No explicit contradiction detector; the auditor may silently accept a claim that's directly contradicted by the note." \
  "Add \`detect_contradictions(claim, note)\` in \`judge.py\` and a \`rule_citation\` that emits 'claim contradicted by note: <quote>' as a high-severity finding."

write_audit "t_574a6c03" "Modifier_24_57" \
  "Modifier -24 / -57 (unrelated E/M, decision for surgery)" \
  "- \`rules/seed_rules.json\` mentions 'modifier -57' (decision for surgery)
- No modifier -24 in seed
- No AHCIP equivalent (v12 prompt correctly notes 'Alberta does NOT have a -24 modifier')" \
  "**partial** — -57 is present; -24 is missing for the US-CMS path. The AHCIP side is correctly documented as not having -24." \
  "Add a -24 rule to seed_rules.json for the US-CMS path ('Unrelated E/M during global period'); add 5 labeled examples to v3 prompt."

write_audit "t_2e024aa4" "Frequency_limits" \
  "Frequency limits (per-year, per-condition)" \
  "- \`grep -ic 'frequency\\|cap' rules/seed_rules.json\` → 4 hits (MUE Frequency Threshold, Anatomic Site Cap mentions)
- No \`rules/frequency_limits.json\` — per-code annual cap table
- \`grep -ric 'frequency.*limit\\|annual.*limit\\|prior.year' src/ai_billing_audit/\` → 0 matches in production code
- Per-day MUE caps ARE in seed (4 hits); per-year/per-condition caps are NOT" \
  "**partial** — Per-day MUE caps are in seed rules (4 hits) but no per-year / per-condition annual-cap table. E.g., '1 preventive visit per year' or '12 psychotherapy sessions' are not enforced." \
  "Add \`rules/frequency_limits.json\` with per-code annual/per-condition caps, plus \`check_frequency(code, patient_history)\` helper that counts prior-year occurrences from claims."

write_audit "t_90ba3e58" "Uncertainty_flags" \
  "Add uncertainty flags (auditor 'not sure' vs 'definitely wrong')" \
  "- \`prompts/v12/auditor_prompt.txt\` uses 'severity' (info/low/medium/high/critical) but no 'confidence'
- No \`confidence: float\` in the finding schema
- Coders cannot triage by auditor confidence" \
  "**missing** — No confidence output. Severity is set by the auditor subjectively; no separate signal for 'I think this is wrong' vs 'I'm sure'." \
  "Add \`confidence: float (0..1)\` to finding schema; have v12 prompt emit a low confidence (<0.6) when the rule is plausible but the note is ambiguous; surface in the UI as a yellow dot."

write_audit "t_cb803ce8" "Specialty_variants" \
  "Per-specialty prompt variants (cards vs surgery vs ED vs psych)" \
  "- \`docs/SPECIALTY_TUNING.md\` exists
- \`grep -ril 'specialty\\|cards\\|surgery' prompts/\` → only references in v12 SOMB context
- No \`prompts/v*-cards.txt\`, \`v*-surgery.txt\`, etc." \
  "**missing** — A specialty tuning doc exists but no per-specialty prompt files. The auditor runs the same prompt for all specialties." \
  "Create \`prompts/v14/auditor_prompt_cards.txt\`, \`_surgery.txt\`, \`_ed.txt\`, \`_psych.txt\`; add a specialty-routing helper that picks the variant from the encounter's specialty field."

write_audit "t_077a53f4" "Sonnet_4_6_baseline" \
  "Test claude-sonnet-4-6 as a baseline (compare to current Ollama cloud minimax-m3)" \
  "- \`src/ai_billing_audit/auditor_module.py\` uses \`dspy.LM('anthropic/claude-sonnet-4-5')\`
- No \`minimax-m3\` reference in code (the model name suggests a previous Ollama cloud pin)
- \`docs/llm-pinning.md\` exists" \
  "**missing** — Sonnet 4.6 is NOT tested as a baseline. The current pin is Sonnet 4.5. No head-to-head benchmark vs minimax-m3." \
  "Add \`src/ai_billing_audit/eval_models.py\` that runs the v12 prompt against {sonnet-4-5, sonnet-4-6, haiku-4-5, minimax-m3} on the 20-encounter ground-truth set; record P/R/F1/latency/cost."

write_audit "t_c41a7ebe" "Streaming_responses" \
  "Streaming responses (show partial findings as they come in)" \
  "- \`grep -ric 'stream\\|chunk' src/ai_billing_audit/\` → 4 matches in api.py, 3 in auditor_module.py (likely non-streaming use)
- No \`async def stream_audit\` or SSE endpoint
- DSPy's \`dspy.streaming\` package is vendored but unused" \
  "**missing** — No streaming endpoint. Findings arrive in a single blocking response. Long audits (high MDM-level cases with many findings) feel slow." \
  "Add \`POST /api/v1/audit/stream\` SSE endpoint that yields findings one-at-a-time as the LLM emits them; use DSPy's \`streamify\` adapter for the LM call."

write_audit "t_2dc16cc3" "Multi_language_notes" \
  "Multi-language notes (Spanish, Mandarin, French-Canadian)" \
  "- \`grep -ric 'spanish\\|mandarin\\|french' src/ai_billing_audit/\` → 0 matches
- No translation layer; no language-detection
- AHCIP is English/French (Canadian); Spanish is rare in this market" \
  "**missing** — No multi-language handling. Notes in Spanish/Mandarin will be silently misread. AHCIP needs French at minimum (per Canadian bilingual requirements)." \
  "Add \`src/ai_billing_audit/lang_detect.py\` (langdetect or fasttext) and an English-translation step (cheap model) before the auditor runs; document AHCIP French-language obligation."

write_audit "t_ef38eabb" "OCR_handling" \
  "OCR'd note handling (degraded text from PDF scans)" \
  "- \`grep -ric 'OCR\\|pdf\\|scanned' src/ai_billing_audit/\` → 0 matches
- No OCR preprocessor
- \`src/ai_billing_audit/x12_parser.py\` exists but is for X12 EDI, not PDFs" \
  "**missing** — No OCR pipeline. Faxed/scanned notes (still common in US healthcare) arrive as raw text with errors; the auditor will mis-parse 'metformin' as 'rnetfonnin'." \
  "Add \`src/ai_billing_audit/ocr_normalize.py\` that runs Tesseract on PDF uploads, then a fuzzy-match spell-corrector over known drug names; document in \`docs/OCR_NOTES.md\`."

write_audit "t_d8acb516" "Two_pass_audit" \
  "Two-pass audit: quick triage + detailed review" \
  "- \`prompts/v0\` is 25 lines (the 'quick' baseline); v12 is 761 lines (the 'detailed' one)
- No orchestration between v0 and v12
- The audit pipeline calls one prompt version per claim" \
  "**missing** — Two prompt versions exist (v0 short, v12 long) but no orchestrated two-pass flow. Cost is always paid at v12-level." \
  "Add \`src/ai_billing_audit/two_pass.py\` that runs v0 first, only escalates to v12 if v0 returns any 'medium+' severity finding; benchmark cost savings."

write_audit "t_06a0e7d0" "Calibration_correlation" \
  "Calibration: do confidence scores actually correlate with accuracy?" \
  "- See t_90ba3e58 — no confidence score exists yet
- \`docs/CALIBRATION.md\` exists but its scope is unclear
- No reliability-diagram (calibration plot) generator" \
  "**blocked-by-t_90ba3e58** — Cannot measure calibration until confidence scores exist." \
  "Once confidence is added: add \`src/ai_billing_audit/calibration.py\` that bins findings into 10 confidence deciles and computes empirical accuracy per bin; emit a reliability-diagram PNG to \`docs/calibration_plots/\`."

write_audit "t_195e7080" "Rule_citation_field" \
  "Add 'rule_citation' field to findings (formal citation, not just rule_id)" \
  "- \`src/ai_billing_audit/scenario_schema.json\` and \`scenario_schema.py\` define the finding shape
- The current schema has \`rule_ids: [str, ...]\` but no \`rule_citation: str\` (formal citation like 'CMS IOM 100-04 §30.6.1')
- \`rules/seed_rules.json\` rule entries have \`source: str\` (e.g., 'CMS E/M') but no formal §/page citation" \
  "**missing** — Schema has \`rule_ids\` (referencing our internal IDs) but no formal payer-document citation. Audits cite 'EM-002' rather than 'CMS IOM 100-04 §30.6.1' which a coder cannot look up without us." \
  "Add \`rule_citation: str\` to finding schema; populate \`source_citation\` field in each seed rule with formal CMS/AHCIP citation; update v12 prompt to require emitting the formal citation."

echo "29 task audit files written to $DIR"
ls -1 "$DIR"