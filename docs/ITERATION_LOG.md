# Iteration Log

Track every prompt change. Each iteration = one A/B test (3 runs × 2 versions = ~25 min wall).

Format: `<timestamp> — <change> — Δ F1 — promoted?`

## baseline (2026-06-17 16:11)
- 7 runs × 50 encounters with **rule_id-only** scoring
- P = 1.000 ± 0.000
- R = 0.155 ± 0.021
- F1 = 0.268 ± 0.031
- Insight: model is perfectly precise, severely under-recalls. Prompt is the only problem.


## baseline 7x (2026-06-17) — DONE
- 7 runs × 50 encounters with **rule_id-only** scoring
- Mean: P=1.000 ± 0.000, R=0.155 ± 0.021, F1=0.268 ± 0.031
- Insight: scoring bug was 91% of the problem. After fix, model is perfect-precision.

## live URL (2026-06-17) — DONE
- Wired real Ollama to live VPS (was placeholder dev key)
- Fixed LLMClient to pass LLM_BASE_URL + LLM_API_KEY through to litellm
- Fixed RESPONSE_JSON_SCHEMA: top-level additionalProperties=True
- Fixed prompt v0: told model to use rule_ids (array) per finding
- Fixed _default_runner: actually calls run_audit() on synth encounter
- Live e2e test: upload 837P → parse → synth → real LLM → real summary returned
  in 5.4s. `audit_status: "ok"`, model says "no rules violated" for a clean claim.
- Still TODO: bearer-token auth (F-3 from QA_API_HARDENING.md), clinical-note
  upload UI (currently using synth encounter body for the audit).


## live URL frontend (2026-06-17 23:50) — DONE
- Added `data/` to the Docker image (was missing — demo encounters 404'd)
- Added bearer-token middleware in api.py (F-3 from QA_API_HARDENING.md)
- AUDIT_BEARER_TOKEN in /opt/projects/ai-billing-audit/.env
- E2E live test (all pass):
  - GET /healthz no-auth → 200
  - GET / no-auth → 401
  - GET / wrong-auth → 401
  - GET / right-auth → 200
  - GET /encounter/enc_0000 right-auth → 200, 13KB, 25 findings, 71 finding mentions
  - POST /encounters/upload/preview right-auth → 200
  - POST /encounters/upload/submit + 30s wait → audit_status=ok, real LLM summary returned
- Live demo is end-to-end functional: 837P upload → real Ollama LLM → real summary
- The runner honors EASY/clean defaults. Adding `difficulty_tier` and `variant`
  overrides to the submit endpoint (defaults field) is a polish item; the
  audit pipeline proves the real LLM integration.
- Still TODO for a true test client: clinical-note upload UI (currently uses
  synth encounter body), encounter detail with accept/dismiss buttons wired
  to audit_trail, MSA/BAA templates, SFTP transfer mechanism.


## live URL home page (2026-06-17 23:58) — DONE
- Added `latest_real_audit` section to the index page
- Reads `/app/logs/upload_jobs.jsonl`, walks back to find the most recent
  `done` line with `audit_status=ok`, and shows its summary inline
- Home page now shows: demo encounter cards (3 of them) + a "Most recent
  real-audit run" panel at the top with the job_id, encounter_id, source,
  tier/variant, findings count, and the LLM-generated summary
- Live verified: home page returns 4588 bytes, contains 'real-audit-panel',
  'Most recent real-audit run', and the live summary text from the most
  recent audit (the 32yo ankle sprain case)
- This is the "wow" for a sales call: open the URL, see real LLM output
  immediately, then click into a demo to see the kind of issues the
  system catches


## live URL encounter detail panel (2026-06-18 00:15) — DONE
- Added `_latest_real_audit_for(encounter_id)` helper that reads
  `/app/logs/upload_jobs.jsonl` and finds the most recent done line
  matching the given encounter_id
- Encounter detail page now has a "Real-audit run" section that
  surfaces the actual LLM output for that encounter
- Home page's `latest_real_audit` block deduplicated into the helper
- Live verification: home page returns 4557 bytes, contains the
  new job_id after a fresh upload, and the LLM summary is rendered
- Encounter detail page renders the panel only if a matching
  job exists; demo encounters (enc_0000, enc_0007, enc_10032) show
  GT findings as before, since no uploads match them yet


## live URL clinical-note upload (2026-06-18 12:30) — DONE
- New endpoint `/encounters/upload/text-note` accepts a plain-text
  clinical note for a given encounter_id. Stores it at
  `/app/logs/uploaded_notes/<safe_id>.<uuid>.txt`.
- Runner reads the latest matching text note and uses it as the
  audit's `clinical_note` field, replacing the synth-generated body.
- BUG: original code referenced `_PKG_DIR` from api.py's closure
  — but the runner is a module-level function so `_PKG_DIR` was
  unbound. Fixed by adding a local `_PKG_DIR = Path(__file__).parent`
  in job_queue.py.
- LIVE TEST (2026-06-18): uploaded a real LBP clinical note for
  ENC001, ran the audit. Result: `ran_via: upload_portal_with_user_note`,
  `used_uploaded_note: True`, audit_status: ok, summary matches the
  uploaded note ("stable chronic problem, low-complexity MDM").
- The MVP is now end-to-end on real clinic data: 837P upload +
  clinical note paste → real LLM audit → real findings.


## v12 prompt + cleaned AHCIP val (2026-06-22) — DONE
- User pivot: "focus on Canada first and Alberta Health." All US
  (CPT/ICD-10-CM) guidance dropped from the prompt; v12 is AHCIP-only.
- New prompt: `prompts/v12/auditor_prompt.txt` — 7 AHCIP pattern
  sections (dx_linkage, non_insured_service, em_level distinction,
  referring_practitioner_id, global_window without -24,
  psychotherapy_time, telehealth, lab-vs-imaging, same_day_conflict,
  CMGP) and 7 few-shot examples (up from v11's 5).
- New cleaned AHCIP val set: `runs/recall/v12_ahcip_clean.json`
  (589 lines), removes the EXAMPLE 6/7 leakage that had been inflating
  v11's recall number.
- Commit `6706b72` — feat(zorva-alberta): v12 prompt + cleaned AHCIP
  val set + 4 research docs.
- Commit `114953c` — fix(zorva-v12): remove EXAMPLE 6/7 val-set
  leakage; report real F1.
- Real F1 on the cleaned AHCIP val:
  P = 0.647, R = 0.846, F1 = 0.733 (vs v11 F1 = 0.588 on the same
  set). See `runs/recall/v12_summary.md`.


## research docs (2026-06-22) — DONE
Four research docs produced in parallel on 2026-06-22 to unblock an
Alberta pilot and feed the v12 rule catalogue. Read-only; no code,
prompts, or val sets were modified.
- `docs/AHCIP_GOLD_AUDIT.md` — read-only audit of `data/val_ca.json`'s
  15 gold findings across 10 AHCIP encounters vs the real Alberta
  Schedule of Medical Benefits (SOMB). Flags US-convention leaks and
  the gaps that an Alberta biller must still sign off on.
- `docs/AHCIP_RULE_REFERENCE.md` — v1 SOMB rule catalogue for the
  Zorva v12 prompt: 16 rules covering assessment, EM levels, time-
  based codes, modifiers, global windows, telehealth, etc.
- `docs/ALBERTA_PROSPECT_LIST.md` — cold-prospect list of real,
  established Alberta clinics sized as anchor-pilot candidates.
  Verification gaps flagged per clinic; no outreach sent.
- `docs/CANADA_BILLING_CROSSREF.md` — AHCIP (AB) vs OHIP (ON) vs
  MSP (BC) cross-reference so v12+ can extend to ON/BC without
  re-deriving the province-by-province deltas.
- `docs/ALBERTA_STRATEGY_BRIEF.md` — Alberta-first strategy brief
  that consolidates the four research docs above into a working
  draft for the v12 prompt and the pilot outreach.


## 6-agent project audit (2026-06-22) — DONE
- Cameron requested "a deep audit of the whole project" on 2026-06-22.
- Six parallel audit agents ran against the full Zorva codebase
  (read-only — no source code, prompts, val sets, kanban state, or
  live VPS was modified):
  - `docs/AUDIT_CODE_QUALITY.md` — dead code, schema drift, import
    cycles, type-safety gaps.
  - `docs/AUDIT_SECURITY.md` — auth, secrets, transport security,
    deployment hardening.
  - `docs/AUDIT_PROMPTS_VAL.md` — prompt/val leakage, scoring
    integrity, few-shot hygiene (this is where the EXAMPLE 6/7
    v12 leakage was caught).
  - `docs/AUDIT_DEPLOY_OPS.md` — Dockerfile, compose, Caddy, log
    rotation, backup/restore.
  - `docs/AUDIT_DOCS_MARKETING.md` — README, portal copy, hash-chain
    references, regulatory claims.
  - `docs/AUDIT_KANBAN.md` — board hygiene, task lifecycle, retry
    policy.
- Consolidated report: `docs/PROJECT_AUDIT_2026-06-22.md` (35
  follow-up tasks, including this one, seeded to the
  `zorva-audit-2026-06-22` kanban board).
- This iteration_log entry itself is one of those 35 tasks
  (t_1112d797).

