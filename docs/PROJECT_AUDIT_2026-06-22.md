# Zorva Project Audit — 2026-06-22

**Date:** 2026-06-22
**Scope:** 6 parallel audit agents, full project (code, security, prompts/val, deploy/ops, docs/marketing, kanban)
**Source reports:** `docs/AUDIT_CODE_QUALITY.md`, `AUDIT_SECURITY.md`, `AUDIT_PROMPTS_VAL.md`, `AUDIT_DEPLOY_OPS.md`, `AUDIT_DOCS_MARKETING.md`, `AUDIT_KANBAN.md`
**Read-only:** No source code, prompts, val sets, kanban state, or live VPS was modified.

---

## TL;DR

The product is in better shape than the prior session memory said (791 pytest tests pass, not 72; 4 of 5 conversion-blocking gaps are actually resolved; backup/DR is genuinely well-engineered). But there are **eight real bugs/risks** that need attention before any clinic sees the live URL, and **one statistical finding that invalidates the F1=0.733 number we just shipped**.

**Top 8 risks, in order of severity:**

1. **F1=0.733 is partially inflated by val-set leakage** — v12 prompt's EXAMPLE 6 and EXAMPLE 7 are the verbatim clinical notes from `ca_ahcip_004` and `ca_ahcip_008`, two of the 10 val encounters. (Agent #3)
2. **`deploy-to-vps.sh:5912` writes `audit:***@postgres` literally** — the `***` is the string `***`, not a resolved password. Live container either has the real password hand-edited post-deploy, or it's running with `audit:***` as credentials. (Agent #4)
3. **Ollama cloud key compromised-on-send, not rotated.** Treated as compromised 6 days ago. Still in use. (Agents #2, #6)
4. **Marketing portal claims AWS ca-central-1 in 11+ places** — live is Hostinger VPS. Legal/procurement risk for any real clinic. (Agent #5)
5. **Two parallel hash-chain implementations** — `src/ai_billing_audit/audit_actions.py` (wired, 8 call sites) and `src/audit_log.py` (only used by tests + qa scripts). A bug fix in one won't propagate. (Agents #1, #5)
6. **Dev val data ships to prod** — `Dockerfile:36` `COPY data ./data` bakes 13,758 lines of dev/holdout/Canadian validation data into the production image. (Agent #2)
7. **PHIPA vs HIA confusion** — 12 PHIPA references in `apps/portal/src/`, 6 of them wrong for the Alberta pivot. The Alberta-prospect agent flagged this 6 hours ago and it's still unfixed. (Agents #3, #5, #6)
8. ~~**MAILGUN_API_KEY not set on live container** — all live doctor-summary emails are silently dropping to `/app/logs/doctor_emails.jsonl`. Per agent #4 this is the only conversion gap still open. (Agent #4)~~ **RESOLVED 2026-06-26 by removal**: the doctor-summary module no longer auto-sends and no longer reads this env var. The operator-outbox JSONL is now the ONLY delivery surface (manual outbox dispatch by the biller).

**Plus 1 statistical finding (not a bug, but invalidates a number we just shipped):** The v12 F1=0.733 is over-stated because the prompt's few-shot examples were constructed from val encounters. The real number is probably somewhere between 0.50 and 0.65.

---

## What's actually working

Before the risks, an honest accounting of what's solid:

- **Test coverage is 10x what prior-session memory claimed** — 791 pytest tests pass, not 72. (Agent #1 confirmed via `pytest --collect-only`.)
- **Backup / DR is unusually well-engineered** — `audit-backup.sh` (519 lines) does `pg_dump | age | rclone rcat` streaming, validates the `audit_trail` is in the dump, monthly restore-into-throwaway-DB verify, retention-tiered, idempotent, size-anomaly-detected. The only gap is no full-VPS DR runbook and no DR drill. (Agent #4)
- **5 conversion-blocking gaps from 2026-06-20:** Gaps 1, 2, 4 are resolved in code. Gap 3 (upload portal bypass-synth) is fixed at the upload entry point but the re-audit endpoint (`api.py:2230`) still re-synthesizes. **Gap 5 (MAILGUN_API_KEY) was RESOLVED 2026-06-26 by removal** — the doctor-summary module no longer auto-sends. (Agent #1; resolution noted 2026-06-26)
- **The v12 prompt is structurally correct** — AHCIP-only, drops US -24 modifier, fixes 5 of 8 prior AHCIP rules. The val-set leakage is the only thing dragging the F1 number down (or, more accurately, the only thing that made the F1 number look as high as 0.733).
- **App-store / portal Stripe is real** — `/api/billing/checkout/route.ts:57-174` is properly wired with subscription mode + idempotency + demo-mode fallback. The 3 tiers ($499/$1,499/$2,999 CAD) are real. (Agent #5)
- **The doctor_email module is now an operator-outbox writer** — as of 2026-06-26, `send_doctor_summary` always writes to `/app/logs/doctor_emails.jsonl` (no Mailgun path). The JSONL is the ONLY delivery surface; the biller reads the file and dispatches via their own mail client. Cameron: "we can import and export reports and send emails ourselves."
- **/app/logs is a named volume** — `ai_billing_audit_logs` on both api and worker. Persists across recreates. The prior-session "wiped on recreate" concern is incorrect. (Agent #2)

---

## Top 8 risks (detailed)

### 1. F1=0.733 is partially inflated by val-set leakage

**Source:** Agent #3 (prompts/val). Verified by me with a direct string match.

The v12 prompt's EXAMPLE 6 contains the verbatim clinical note from `ca_ahcip_004`:

> "Office visit, brief assessment for upper respiratory symptoms. Patient reports cough x 5 days, no fever. Lungs clear. Supportive care advised."

The v12 prompt's EXAMPLE 7 paraphrases `ca_ahcip_008`:

> "Productive cough x 1 week, low-grade fever yesterday. Rhonchi bilaterally. Started amoxicillin 500mg TID."

Both encounters are in `val_ca.json` (the val set used to score v12). When the model is asked to audit these encounters during the smartness test, the matching is artificially easy — it has seen them in the few-shot section.

**Real impact:** I don't know the exact inflation. Could be +0.05 F1 or +0.20. We need to either (a) replace EXAMPLE 6 and EXAMPLE 7 with truly-held-out examples and re-run, or (b) accept the inflated number and disclose it in any clinic conversation.

**Fix:** ~30 min of prompt work + one smartness-test run.

### 2. `deploy-to-vps.sh:5912` writes `audit:***@postgres` literally

**Source:** Agent #4 (deploy/ops). Verified by me.

The deploy script's `.env` template contains:
```
DATABASE_URL=postgresql://audit:***@postgres:5432/ai_billing_audit
```

The `***` is the literal string `***`, not a resolved password. Either:
- The live container has the real password hand-edited into the `.env` after the script runs (operational smell — deploys are not reproducible)
- The live container is running with `audit:***` as credentials (live auth may be broken; postgres may be locked out)

**Fix:** Find the actual password-resolved template (probably a `${POSTGRES_PASSWORD}` expansion earlier in the script), or pass the password as an env var from the deploy host's secret store, or fail the deploy if the password can't be resolved.

**Time:** ~1 hour to investigate, ~30 min to fix.

### 3. Ollama cloud key compromised-on-send, not rotated

**Source:** Agents #2, #6.

The Ollama key was sent in Telegram on 2026-06-17 (verbatim, in chat). It's been treated as compromised since. It's still in use on the live container.

This blocks the next deploy (any deploy that re-creates the container will pick up the key from the .env template, and that .env has the compromised key). It also blocks any real pilot clinic from touching the system until the key is rotated.

**Fix:** Generate a new Ollama cloud key, replace it in the live container, replace it in `~/.config/ai-billing/ollama-key`, update the deploy script.

**Time:** 15 min of operator work (you click rotate in the Ollama dashboard), 5 min of plumbing.

### 4. Marketing portal claims AWS ca-central-1 in 11+ places

**Source:** Agent #5.

`apps/portal/src/app/page.tsx:54-61`, `security/page.tsx:7,64-65,287,311,322,352`, `OnboardingWizard.tsx:393-419`, `lib/pricing.ts:50,57,65` all claim the data lives in AWS ca-central-1. Live is Hostinger VPS at 187.77.26.99.

This is a compliance claim that may be false. PHIPA and HIA both have data-residency provisions. If an Alberta clinic is told "your data is in ca-central-1" and it's actually on a Hostinger VPS in Lithuania or wherever, that's a real problem.

**Fix:** Either (a) actually move the data to ca-central-1, or (b) update the marketing to say what the truth is. (a) is a real engineering project (a new VPS region, a Caddy + Coolify redeploy, a data migration). (b) is a 30-min PR.

**Time:** 30 min for option (b), 1-2 weeks for option (a).

### 5. Two parallel hash-chain implementations

**Source:** Agents #1, #5.

`src/ai_billing_audit/audit_actions.py` (wired into 8 API call sites) and `src/audit_log.py` (only used by tests + qa scripts) both implement a SHA-256 hash chain for the audit trail. Same field list, same genesis constant, same wire format. A bug fix in one won't propagate.

The marketing security page cites `src/audit_log.py` but the live code uses `audit_actions.append()`.

**Fix:** Pick one (the wired one, `audit_actions.py`) and delete the other. Update any tests that import `audit_log` to use `audit_actions`. Update marketing copy.

**Time:** ~2 hours including test migration.

### 6. Dev val data ships to prod

**Source:** Agent #2.

`Dockerfile:36` does `COPY data ./data` unconditionally. The `data/` directory contains `val.json` (50 US encounters), `val_ca.json` (10 AHCIP encounters with patient health numbers and clinical notes), `train.json` (100 more), and 14+ other files. ~13,758 lines of PHI-shaped data baked into every production image.

This is a real PHI-in-prod-artifact issue. Even if the data is synthetic, shipping a val set with a 9-digit "patient_health_number" field into a container image creates a real audit trail for any data-protection review.

**Fix:** Split `data/` into `data/synth/` (synthetic, ships in image) and `data/private/` (real PHI, lives in a separate volume, never baked into image). Update Dockerfile to only `COPY data/synth ./data`.

**Time:** ~1 hour including test fixes.

### 7. PHIPA vs HIA confusion still unfixed

**Source:** Agents #3 (Alberta research), #5 (docs/marketing), #6 (kanban).

The Alberta pivot was 2026-06-22. The Alberta research agent flagged "PHIPA → HIA scrub needed" 6 hours ago. 12 sites in `apps/portal/src/` still say PHIPA. 6 of them are wrong for Alberta specifically.

PHIPA is Ontario. Alberta uses the Health Information Act (HIA). Any clinic in Alberta told "PHIPA-compliant" is being lied to.

**Fix:** Find/replace `apps/portal/src/` for "PHIPA" in Alberta context (the OnboardingWizard and the security page are the highest-traffic sites), update the privacy policy, update the data-agreement template.

**Time:** ~1 hour.

### 8. ~~MAILGUN_API_KEY not set on live container~~ — RESOLVED 2026-06-26 by removal

**Source:** Agents #4, #6 (original). Resolution: Mavis, 2026-06-26.

The doctor-summary module was refactored to remove Mailgun auto-send entirely. The module no longer reads `MAILGUN_API_KEY` (or `MAILGUN_DOMAIN`) and no longer imports `requests`. `_send_via_mailgun()` and `_mailgun_configured()` were deleted from `src/ai_billing_audit/doctor_email.py`. `requests==2.32.3` was removed from `pyproject.toml`. The operator-outbox JSONL (`/app/logs/doctor_emails.jsonl`) is now the ONLY delivery surface — manual outbox dispatch by the biller is the chosen model (Cameron: "we can import and export reports and send emails ourselves").

This resolution is strictly better than the original "set the key" fix:
- removes the third-party API dependency from the runtime
- removes the secret-rotation requirement (no more `MAILGUN_API_KEY` to rotate)
- the biller has direct visibility into every email before it leaves the clinic inbox
- import + export of audit reports (already supported) is the primary delivery surface

**No follow-up needed.**

---

## Cross-cutting findings

### Things prior-session memory got wrong (refuted by audit)

- **"72 tests pass"** → **791 tests pass** (Agent #1)
- **"46 over-decomposed tasks archived"** → **119 tasks archived** (Agent #6)
- **"12 prompt versions in MANIFEST.json"** → **2 entries in MANIFEST.json** (Agent #3)
- **"/app/logs wiped on container recreate"** → **named volume, persists** (Agent #2)
- **"audit_actions.py BUILT BUT NOT WIRED"** → **wired into 8 API call sites** (Agent #1)
- **"synth-trap is fixed"** → **upload portal entry fixed; re-audit endpoint still re-synthesizes** (Agent #1, #6)
- **"data-residency: ca-central-1, AWS"** → **live is Hostinger VPS, region unknown** (Agents #2, #5)
- **"PHIPA-compliant"** → **PHIPA is Ontario, Alberta is HIA** (Agents #3, #5)
- **"5 conversion-blocking gaps open"** → **4 of 5 resolved; only MAILGUN key + re-audit endpoint open** → **5 of 5 resolved (2026-06-26 by removing Mailgun entirely); only re-audit endpoint remains** (Agent #1; resolution 2026-06-26)

### Dead code (top 5)

- `src/ai_billing_audit/billing.py` (10 LOC, placeholder)
- `src/ai_billing_audit/audit.py` (11 LOC, placeholder)
- `src/ai_billing_audit/encounter_schema.py` (217 LOC, never imported)
- `src/ai_billing_audit/demo_entries.py` (91 LOC, never imported)
- `src/ai_billing_audit/worker.py` (75 LOC, no-op heartbeat)

Plus: two dead functions in `audit_actions.py` (`read_for_encounter`, `verify_chain`) and the entire `src/audit_log.py` parallel implementation.

### Marketing claim audit (verbatim discrepancies)

| Claim | Reality | Where |
|---|---|---|
| Multi-market Canada + US + MX + CO | 16 AHCIP rules, 0 OHIP, 0 MSP, 0 NOM-024, 0 DIAN | `apps/portal/src/app/page.tsx:54-61` |
| AWS ca-central-1 / us-east-1 data residency | Hostinger VPS, region unknown | `apps/portal/src/app/security/page.tsx:7,64-65,287,311,322,352` |
| PHIPA-compliant (Alberta context) | Alberta uses HIA, not PHIPA | `apps/portal/src/app/OnboardingWizard.tsx:393-419`, `lib/pricing.ts:50,57,65` |
| "Catches 85% of billing errors" | F1=0.733 on 10 AHCIP encounters (and partially inflated) | Not currently in any marketing copy (per agent #5) |
| Tamper-proof audit trail (cites `src/audit_log.py`) | Live code uses `audit_actions.py`; the two are parallel implementations | `apps/portal/src/app/security/page.tsx` |

### Kanban debt

- 423 tasks total across 8 Zorva boards
- 0 in-progress, 0 claimed, 0 blocked (no live work in flight)
- 10 taekwondo-tournament tasks (F1-F10) misfiled as "triage" on `marketing-pages` board (wrong project entirely)
- Zero tasks track: v12 prompt, Alberta pivot, F1=0.733, ~~MAILGUN_API_KEY~~ (RESOLVED 2026-06-26 by removal), v12 deploy
- 119 archived (not 46 as memory said)

---

## 30-day action plan

### Week 1 — Fix the inflation + the security bugs

| Day | Task | Time | Owner |
|---|---|---|---|
| 1 | Replace v12 EXAMPLE 6 and 7 with held-out examples, re-run smartness test | 1 hour | Hermes |
| 1 | Disclose the F1 inflation in any clinic conversation | 0 | Cameron |
| 1 | Move `.tmp_bearer.txt` to ~/.config/ with chmod 600, add to .gitignore | 15 min | Hermes |
| 1 | Delete `apps/portal/.env.bak` (or chmod 600 and gitignore) | 5 min | Hermes |
| 1 | Rotate Ollama cloud key, update .env, redeploy | 30 min | Cameron + Hermes |
| 2 | Investigate `deploy-to-vps.sh:5912` `***` literal, fix the password resolution | 1 hour | Hermes |
| ~~2~~ | ~~Set MAILGUN_API_KEY on live container, verify a test email~~ | ~~30 min~~ | ~~Cameron + Hermes~~ — **RESOLVED 2026-06-26 by removal** |
| 3 | Find/replace PHIPA → HIA in `apps/portal/src/` for Alberta context | 1 hour | Hermes |
| 3 | Update marketing portal to remove AWS ca-central-1 claim, OR move to ca-central-1 | 30 min (option b) | Hermes |
| 3 | Delete dead code: billing.py, audit.py, encounter_schema.py, demo_entries.py, worker.py, src/audit_log.py | 2 hours | Hermes |
| 4 | Split `data/` into synth/ (in image) and private/ (volume-mounted only) | 1 hour | Hermes |
| 4 | Re-run v12 prompt on the cleaned val set, document the real F1 | 30 min | Hermes |
| 5 | Update README.md (currently a v0/MIPROv2/72-tests time capsule) | 1 hour | Hermes |
| 5 | Add security headers to Caddy config (CSP, X-Frame-Options, HSTS) | 1 hour | Hermes |
| 5 | Re-deploy v12 prompt to live (after the EXAMPLE 6/7 fix) | 30 min | Hermes |

### Week 2 — Build the missing pieces

| Day | Task | Time | Owner |
|---|---|---|---|
| 1-2 | Build v13 prompt: fix em_level vs em_level_upcode distinction, refine psychotherapy_time trigger, add more AHCIP encounters to val_ca.json (10 → 25) | 4 hours | Hermes |
| 3-4 | Draft HIA-compliant data agreement template (PIPEDA + HIA, both federal and Alberta) | 4 hours | Cameron (legal) + Hermes (drafting) |
| 4-5 | Draft Strathcona PCN first-contact email (template exists, needs Cameron-signed version) | 1 hour | Cameron |

### Week 3 — Alberta pilot outreach

| Day | Task | Time | Owner |
|---|---|---|---|
| 1 | Run the Strathcona PCN email (if Cameron signs off) | 1 hour | Cameron |
| 2-3 | Wait for response; meanwhile write the Alberta-specific one-pager | 2 hours | Hermes |
| 4-5 | If no response, send to #2 (Bow Valley Medical Clinic) and #3 (Red Deer PCN) | 1 hour | Cameron |

### Week 4 — Prep for first pilot

| Day | Task | Time | Owner |
|---|---|---|---|
| 1-2 | BAA / data agreement signing (once a clinic says yes) | 4 hours | Cameron + clinic |
| 3-4 | SFTP setup for clinic EHR export | 4 hours | Hermes |
| 5 | First real pilot encounter ingestion (1-2 months historical claims) | 2 hours | Hermes |

---

## What I did NOT do (intentionally)

- Did NOT modify any source code, prompts, val sets, kanban state, or live VPS
- Did NOT touch the live URL
- Did NOT ssh into the VPS
- Did NOT rotate any keys (that's an operator action — Cam)
- Did NOT send any emails to any clinic
- Did NOT claim, complete, archive, or move any kanban tasks
- Did NOT deploy any prompts to live

All 6 audit agents were read-only.

---

## What I CAN do right now if you give the word

- Apply the v12 EXAMPLE 6/7 fix and re-run the smartness test (1 hour, see real F1)
- Delete the 6 dead-code files (2 hours)
- Apply the PHIPA → HIA scrub in `apps/portal/src/` (1 hour)
- Add the 6 most-stale tasks to the Alberta-pivot board as tracked work (15 min)
- Apply the `data/` split to `synth/` and `private/` (1 hour)

Tell me which of those to ship.
