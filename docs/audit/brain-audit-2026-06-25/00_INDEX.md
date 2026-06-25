# Brain + Audit Intelligence — Comprehensive Self-Audit
**Date:** 2026-06-25
**Scope:** 29 ready tasks on the `brain-audit` kanban board
**Author:** Subagent of Hermes (kanban batch drain)
**Methodology:** For each task, the audit claim was verified against actual
files in the repo. Counts were taken with `wc -l` / `grep -c`; code presence
verified with `grep -l`. Where evidence is missing, the audit reports the gap.

---

## Executive summary

The `brain-audit` board covers three themes:

1. **Clinical-rule coverage** (15 tasks): modifier families, NCCI, MUE, E/M,
   frequency limits, medical necessity, ground-truth calibration.
2. **DSPy / model engineering** (8 tasks): MIPROv2 wiring, regression
   tracking, few-shot selection, CoT, model routing, caching, cost guardrails,
   streaming.
3. **Adversarial / UX** (6 tasks): refusal handling, contradiction detection,
   uncertainty flags, specialty variants, multi-language, OCR, two-pass.

**Key findings (counts from this repo at HEAD `901aeb0`):**

- `rules/seed_rules.json` contains **269 lines** with 31 modifier-related
  rule hits — Modifier -25 IS represented in seed rules (rules mentioning
  "modifier -25", "modifier -24", "modifier -57", "modifier -59"). This is a
  **gap-mitigated** but **not ground-truthed** coverage.
- `prompts/v12/auditor_prompt.txt` is **761 lines** (largest prompt version)
  and contains 14 modifier hits, 19 NCCI/MUE/modifier hits. Few-shot
  examples are present (11+ EXAMPLE blocks).
- `src/ai_billing_audit/auditor_module.py` uses
  `dspy.configure(lm=dspy.LM("anthropic/claude-sonnet-4-5"))` — DSPy is
  wired with a fixed model, no cheap-model-first routing.
- No `(claim_hash, prompt_version)` cache layer exists. `feedback.py` and
  `demo_registry.py` have a `cache: dict` for parsed JSONL, but no
  response-cache keyed on `(claim_hash, prompt_version)`.
- No streaming path exists in the production auditor; the only streaming
  primitives are dspy-internal (`dspy/streaming/` is a vendored dependency,
  not used by the app).
- Per-prompt-version P/R tracking is partial: `feedback.py`, `grading.py`,
  and `per_clinic_f1.py` exist, but no time-series regression detector.
- No per-tenant cost guardrail code exists (grep for `cost.*alert`,
  `monthly.*budget` returns no production code; `roi.py` exists for
  savings, not spend).
- Multi-language / OCR handling: zero matches in `src/ai_billing_audit/`.
- Specialty variants: `SPECIALTY_TUNING.md` exists in `docs/` but no
  per-specialty prompt files (`prompts/v*-cards.txt` etc. don't exist).

Each of the 29 sections below evidences the gap with a command and a
file/line citation.

---

## Per-task audit findings

See the per-task files in this directory, one per `t_xxxxx` task id.
Each file contains:

- **Audit claim** (verbatim from kanban task body)
- **Evidence** (`grep`/`wc`/`find` output)
- **Verdict**: covered / partial / missing
- **Recommended follow-up**

(Each per-task file is generated below in 01–29.)