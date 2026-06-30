# Product gap analysis — what Zorva is missing for real Alberta AHCIP clinics

**Date:** 2026-06-28
**Author:** General agent (P6 track of plan_cc23148d)
**Status:** Hypothesis-flagged draft — runs in parallel with P1–P5, so several findings reference "[hypothesis: verify against P1/P2/P3]" placeholders where teammate research would have informed the score.

## How to read this

This is the **gap analysis** track. It depends on P1 (biller workflow), P2 (AHCIP submission flow), P3 (EMR integration landscape), P4 (competitors), and P5 (customer signal). At the time of writing, those five tracks are running in parallel and have **not yet produced files** under `research/P1-…P5-*.md`. So:

- The **gap inventory itself** is grounded in the **codebase + existing docs** (`apps/portal/src/`, `src/ai_billing_audit/`, `prompts/v12/auditor_prompt.txt`, `docs/ALBERTA_STRATEGY_BRIEF.md`, `docs/ALBERTA_PROSPECT_LIST.md`, `docs/AHCIP_RULE_REFERENCE.md`, `docs/PILOT_OFFER.md`, `docs/ANTI_FEATURES.md`, `docs/EHR_ADVANCEDMD_INTEGRATION.md`). Every gap row points at a concrete page, lib, or backend module so the verifier can re-derive.
- The **demand scores** and **competitive scores** carry the flag **"[verify P1/P3/P4/P5]"** — they should be re-scored once P1 (biller workflow), P3 (EMR landscape), P4 (competitor landscape), and P5 (customer signal) land. The methodology for scoring is fixed; the numbers are best-guess based on the existing strategy docs.

**Scoring rubric** (lower cost = easier to ship):

- **Clinic demand** (1–5): how loudly will a typical 5–10 physician Alberta clinic ask for this on the first pilot call? 1=never asked, 5=blocker for purchase.
- **Engineering cost** (1–5): rough solo-dev weeks. 1=ship in a day, 2=under a week, 3=1–2 weeks, 4=3–6 weeks, 5=2+ months.
- **Competitive pressure** (1–5): if we don't ship this, does a competitor eat our lunch? 1=no competitor does this, 5=a US AI-billing tool will market against it within 6 months.
- **Priority score** = demand × (6 − cost) × competitive. Higher = build sooner.

---

## 1. Current feature inventory

Concise. Codebase pointers only — see `apps/portal/src/app/`, `apps/portal/src/lib/`, and `src/ai_billing_audit/` for the full picture.

### 1.1 Authentication & multi-tenancy
- **Auth.js v5** (NextAuth) with Email provider; SQLite for dev, Postgres-ready (`apps/portal/prisma/schema.prisma:28`).
- **Tenant model** with `slug`, `tier` (small/mid/large), `subscriptionStatus`, Stripe linkage (`schema.prisma:128`).
- **Memberships** with three roles: owner / auditor / viewer (admin kept legacy for back-compat, `apps/portal/src/lib/roles.ts`).
- **Single active tenant per session** (`apps/portal/src/lib/active-tenant.ts`) — user can belong to multiple tenants but the header picks one.
- **Per-tenant isolation** in every Prisma query (via `tenantId` index + tenant-scoped Prisma helpers).

### 1.2 Onboarding
- **Public 5-step wizard** at `/onboarding` (`apps/portal/src/app/onboarding/OnboardingFlow.tsx`) — account → HIA paperwork → import → first audit → first finding.
- **Persistence** via `localStorage` for step state; each "Continue" POSTs to a dedicated route (`/api/onboarding/*`).
- **Per-step skip** with no hard block — clinic can finish setup later.
- **Time-to-first-value** ≈ 10 minutes *if* the user has an 837P sample ready; longer if they wait for SFTP creds.

### 1.3 Data ingestion
- **Manual file upload**: 837P / CSV, max 20 MB, multipart form (`apps/portal/src/app/api/onboarding/upload/route.ts`).
- **EHR connection metadata only**: `Tenant.ehrConnectionMode ∈ {sftp, manual, null}` + `ehrSftpHost/Port/Username/PasswordCiphertext` (`schema.prisma:214–236`). Schema-ready for SFTP; **no actual scheduled pull job runs in the portal** — the script lives at `scripts/ehr/advancedmd_pull.sh` and is run by an external cron (per `docs/EHR_ADVANCEDMD_INTEGRATION.md`).
- **CSV ingest** in FastAPI auto-detects PM header (Kareo / OSCAR / Office Ally / athena / eClinicalWorks) and maps to canonical schema (`src/ai_billing_audit/csv_ingest.py`).
- **837P parser** (`src/ai_billing_audit/x12_parser.py`) + **837I institutional parser** (`src/ai_billing_audit/institutional_837i.py`).
- **In-process job queue** (`src/ai_billing_audit/job_queue.py`) — `queued → running → done|failed`, JSONL audit log on every state change. No cancel state.

### 1.4 Encounter workspace
- **Server-paginated list** at `/encounters` (`apps/portal/src/app/encounters/page.tsx`, `apps/portal/src/lib/encounter-list.ts`) — 7 columns, filters by date / provider / payer / status / category, URL-round-tripped state.
- **CSV export** of the current filter set (`apps/portal/src/app/api/encounters/export/route.ts`).
- **Search endpoint** at `/api/encounters/search`.
- **Detail page** at `/encounters/[id]` — split-screen: clinical note (with `<mark>` evidence highlights) + billed claim JSON + AI findings cards (`apps/portal/src/app/encounters/[id]/page.tsx`).
- **Deep-audit panel** on detail page — pulls denial-risk + appeal-letter from FastAPI (`_components/deep-audit-panel.tsx`).

### 1.5 Findings workflow
- **Inbox** at `/findings` (`apps/portal/src/app/findings/page.tsx`, `_components/findings-inbox.tsx`) — multi-select, bulk accept/dismiss with 4 dismiss reasons (`wrong_payer_policy`, `hallucinated_fact`, `too_conservative`, `other_with_text`).
- **Action plan CSV export** (`apps/portal/src/app/api/findings/export/route.ts`).
- **Bulk accept/dismiss routes** at `/api/findings/bulk/{accept,dismiss}` (separate files, both Server Actions).
- **Per-finding accept/dismiss** at `/api/encounters/[id]/findings/[findingId]/{accept,dismiss}` with the same hash-chained audit write (`apps/portal/src/lib/audit-write.ts`).
- **Keyboard shortcuts** for the split-screen review (`_components/keyboard-shortcuts.tsx`).

### 1.6 Audit & compliance
- **SHA-256 hash-chain audit trail** (`apps/portal/src/lib/audit-chain.ts`, `apps/portal/src/lib/audit-write.ts`) — append-only `AuditTrailEntry` rows, GENESIS_PREVIOUS_SIGNATURE = 64 zeros, `verifyChain` walker.
- **Audit log export** to CSV or JSON for the privacy officer (`apps/portal/src/app/api/audit/export/route.ts`).
- **Two-person approval** on destructive / export actions (mentioned in `/security` page copy).
- **Salted SHA-256 patient hashing** before long-term storage (`apps/portal/src/lib/patient-hash.ts`, mirrors `Encounter.patientHash`).
- **Public security posture page** at `/security` — controls matrix (data residency, TLS, AES-256, hash chain, RBAC, PII handling, HIA/PIPEDA/HIPAA/NOM-024 frameworks). PDF download available.
- **Data residency** selectable at signup (`/api/onboarding/region`); locked after first encounter.

### 1.7 Calibration + KPIs
- **FPAR tile** (first-pass approval rate) on dashboard (`apps/portal/src/components/fpar-tile.tsx`, `apps/portal/src/lib/fpar.ts`) — accepts-divided-by-50 window; shows "Not enough data yet" below 10 acted-on audits; "stale" warning after 30 days.
- **Calibration card** on dashboard (`apps/portal/src/components/calibration-card.tsx`, `apps/portal/src/lib/calibration.ts`) — top-5 overcalled/reviewing/calibrated/uncalibrated rules per tenant; supports specialty tuning.
- **CalibrationSignal Prisma scaffold** (2026-06-27 migration) — portal pre-aggregates, FastAPI is source of truth.

### 1.8 Billing & quota
- **Stripe Checkout** for the three tiers ($499 / $1,499 / $2,999 CAD/mo), `apps/portal/src/lib/stripe.ts`, `apps/portal/src/app/api/billing/checkout`.
- **Customer Portal** for self-serve plan / payment changes (`apps/portal/src/app/api/billing/portal*`).
- **Tier change / cancel** flows.
- **Invoice history** (last 12 months) on `/billing`.
- **Audit quota enforcement** — `Tenant.auditQuotaUsed` vs `auditQuotaLimit`, atomic check-and-increment at 80% warn / 100% block (`apps/portal/src/lib/audit-quota.ts`, `/api/audit/run/route.ts`).
- **Webhook handler** at `/api/billing/webhook` with `ProcessedStripeEvent` dedup table.

### 1.9 Team & settings
- **Team page** at `/team` — owner-only invite form, role change, disable (`apps/portal/src/app/team/page.tsx`, `team-client.tsx`).
- **Settings page** at `/settings` — clinic profile, data residency (locked after first audit), PHI handling (`redactPatientNamesInExports`), EHR SFTP creds.
- **Capability helpers** at `apps/portal/src/lib/roles.ts` — every API route goes through `assertMembershipCapability`.

### 1.10 Denial-risk + appeal-letter (FastAPI side)
- **Denial-risk scorer** (`src/ai_billing_audit/denial_risk.py`) — heuristic weighted severity × rule family; per-finding contribution exposed for the dashboard.
- **Appeal-letter generator** (`src/ai_billing_audit/appeal_letter.py`) — one letter per finding, markdown output, separate temperature from auditor (0 vs 0.4).
- **Doctor-side modules** (`src/ai_billing_audit/doctor_dashboard.py`, `doctor_email.py`) — `doctor_encounters_for`, `doctor_weekly_digest`, `doctor_effectiveness` (the "you're 12% better than last quarter" metric). **Not wired into the portal UI.**
- **Per-clinic F1 + monthly PDF report** (`src/ai_billing_audit/per_clinic_f1.py`, `monthly_report.py`, `monthly_pdf.py`) — single-page A4 PDF with revenue opportunities, top flagged rules, time-to-act, appeal-outcome pie. **No portal route renders this.**

### 1.11 Marketing surface
- Pricing, how-it-works, FAQ, case-studies, demo-request, blog, trust, technical, glossary, pilot, press, careers, compare.
- **Interactive ROI calculator** at `/calculator` (the public-facing "how much are you leaving on the table" tool — `apps/portal/src/app/calculator/roi-calculator.tsx`).
- **Lead capture** at `/api/leads` — persists `Lead` rows, fires email + Slack.
- **Weekly digest cron** at `/api/cron/weekly-digest`.
- **Email suppression** (`/api/email/webhook` + `SuppressListEntry` / `SuppressionEvent` tables) — bounce / complaint / unsubscribe with append-only history.

### 1.12 Eval / regression infrastructure
- **v12 auditor prompt** at `prompts/v12/auditor_prompt.txt` — 16-rule AHCIP catalogue (P=0.647, R=0.846, F1=0.690 on cleaned val_ca.json).
- **Smartness test scripts** `scripts/run_ollama_audit.py` and `scripts/run_7x.py`.
- **Synthetic corpus** at `data/synth/` + **real-ish encounters** at `data/val_ca.json` (10 AHCIP, 13 gold findings).

---

## 2. Gap matrix

Twelve gaps. Each row points at a concrete Zorva feature area. Scores flagged **[verify P1/P3/P4/P5]** are best-effort pending the sibling research tracks.

| # | Gap | Where in Zorva today | Clinic demand (1–5) | Eng cost (1–5) | Competitive (1–5) | Priority `demand × (6-cost) × competitive` |
|---|---|---|---|---|---|---|
| G1 | **Live EMR data feed (beyond file/SFTP)** — no scheduled pull job in the portal; no HL7/FHIR endpoint; no bidirectional EMR connector | `Tenant.ehrConnectionMode` schema field is set but no portal-side runner; `scripts/ehr/advancedmd_pull.sh` is an external cron only. `csv_ingest.py` is FastAPI-side only. | **5** [verify P1/P3] | **4** (need per-EMR adapter + scheduled job runner) | **5** [verify P3/P4] | 5 × 2 × 5 = **50** |
| G2 | **No "what would my submission look like" preview / reconciliation view** — biller accepts/dismisses but cannot see the corrected claim diff or a draft 837P that incorporates accepted findings | `/findings/_components/findings-inbox.tsx` writes `Finding.status` only; no claim rebuild path; `anti-features.md` says explicitly we don't submit so no 837P output either. | **5** [verify P1] | **3** (claim-rewrite engine + UI) | **4** [verify P4] | 5 × 3 × 4 = **60** |
| G3 | **No "monthly ROI report" view in the portal** — `monthly_pdf.py` + `monthly_report.py` exist in FastAPI but no portal route renders them; dashboard FPAR tile is calibration-only, no $ figure | Dashboard has FPAR + Calibration cards but no `monthly_report.py` route. Public `/calculator` exists but is marketing-only. | **4** [verify P1/P5] | **2** (wire up existing FastAPI module to a portal page) | **3** | 4 × 4 × 3 = **48** |
| G4 | **No multi-clinic / group tenant model** — single `Tenant` per clinic; no roll-up for PCN central billing, corporate chains (Medicentres), or 5-10-clinic groups | `Tenant` has no `parentTenantId`; `Membership` has no `groupId`; `apps/portal/src/lib/active-tenant.ts` is single-active only. | **4** [verify P1/P5] | **4** (parent/group schema + RBAC rewrite) | **3** [verify P4] | 4 × 2 × 3 = **24** |
| G5 | **No HIA patient-data access UI** — privacy officer can pull the audit log but cannot look up "what does Zorva hold for patient X (hashed PHN)" or trigger a deletion workflow | `/api/audit/export` is the only HIA-facing tool. No patient-data-subject-access UI. `Encounter.patientHash` is the only identifier on disk. | **3** [verify P1] | **2** (read-only hash lookup + deletion route + signed workflow) | **4** (Alberta privacy officers ask this on every RFP) | 3 × 4 × 4 = **48** |
| G6 | **No in-app notifications / "new findings" center** — biller must hit the inbox to learn about new audits; email weekly digest is the only signal | `/api/cron/weekly-digest` exists; `first-audit-email` exists; no in-app `Notification` table. | **3** | **1** (add a Notification table + bell icon) | **2** | 3 × 5 × 2 = **30** |
| G7 | **Doctor-side portal view not built** — `doctor_dashboard.py` computes per-provider "what's wrong + how to fix" + effectiveness metric in FastAPI but no portal page renders it | `src/ai_billing_audit/doctor_dashboard.py` has `doctor_encounters_for`, `doctor_weekly_digest`, `doctor_effectiveness` — none wired into `apps/portal/src/app/`. | **3** [verify P1] | **3** (new portal route + provider-scoped queries) | **3** | 3 × 3 × 3 = **27** |
| G8 | **No per-clinic rule suppression / custom rules UI** — the auditor runs the global 16-rule catalogue; biller cannot say "we never bill 03.05A, suppress that rule for our clinic" or add a per-clinic custom rule | `SuppressListEntry` table is for email suppression only; no `PerClinicRuleSuppression` model; no UI for prompt overrides per clinic. | **4** [verify P1] | **3** (Suppression model + lib + UI + fast-path evaluation) | **4** (CodaMetrix and similar already do this) | 4 × 3 × 4 = **48** |
| G9 | **Onboarding time-to-first-value is multi-hour (manual upload or wait for SFTP)** — no "demo with synthetic data" one-click path | `/onboarding` 5-step wizard is the only entry; no `/try` or `/demo-audit` path. | **4** [verify P1/P5] | **1** (synthetic audit button + canned val_ca.json with one fixture) | **4** (every competitor demos in 30 seconds) | 4 × 5 × 4 = **80** |
| G10 | **No per-finding collaboration (comments / @mention / assignment)** — accept/dismiss is the only action; no way for a biller to say "I'm handling this one" or ask the auditor for clarification | `Finding` has `status`, `dismissReason`, `dismissText`; no `comments` table; no `assignedToUserId`. | **2** | **2** (Comments table + thread UI) | **2** | 2 × 4 × 2 = **16** |
| G11 | **No batch / day-end "review all findings" view** — biller clicks encounter-by-encounter to act on findings; no aggregate workbench for a day's worth of claims | `/encounters` list exists; `/findings` inbox exists; no aggregated "today's batch" view that shows 30 encounters × avg 3 findings in one scrollable grid. | **4** [verify P1] | **2** (new view on top of existing Prisma queries) | **3** | 4 × 4 × 3 = **48** |
| G12 | **No AHCIP submission integration / no "file reconsideration" slot** — explicitly out of scope per `anti-features.md` §1, but a PCN ops director will eventually ask "why can't you just hit submit for us?" | `anti-features.md` §1 says we don't submit. `H-Link` integration not started. No appeal-letter auto-send to payer. | **3** [verify P1/P2] | **5** (H-Link requires Alberta Health vendor approval + certification; appeal-letter auto-send is legal-risk territory) | **2** [verify P2/P4] | 3 × 1 × 2 = **6** |

### Math recap (priority descending)

| Rank | Gap | Priority |
|---|---|---|
| 1 | G9 — synthetic-data demo path | 80 |
| 2 | G2 — submission-preview / reconciliation | 60 |
| 3 | G1 — live EMR feed | 50 |
| 4 | G3 — monthly ROI report | 48 |
| 5 | G5 — HIA patient-data UI | 48 |
| 6 | G8 — per-clinic rule suppression | 48 |
| 7 | G11 — batch day-end review | 48 |
| 8 | G6 — in-app notifications | 30 |
| 9 | G7 — doctor portal view | 27 |
| 10 | G4 — multi-clinic / group | 24 |
| 11 | G10 — comments / assignment | 16 |
| 12 | G12 — AHCIP submit integration | 6 |

---

## 3. Top 5 gaps to address in next 90 days

Each gap has a concrete "what we'd build" sentence and references the Zorva feature area it extends.

### G9 — One-click synthetic demo audit (priority 80)
**What we'd build:** A `/try` public route + a "Run sample audit" button on the marketing site that ingests the cleaned `data/val_ca.json` fixture under a sandbox tenant, runs the v12 prompt against it, and renders the same `/encounters/[id]` split-screen with real findings. Time-to-first-value drops from hours to **under 30 seconds**. Closes the "I have to find an 837P file before I can see anything" objection that's killing the demo flow.
- **Touches**: `apps/portal/src/app/try/`, new `/api/try/run-audit`, reuses `OnboardingFlow.tsx` step 3 (the "Run first audit" step).
- **Engineering**: ~3–4 days.

### G2 — Submission-preview / reconciliation view (priority 60)
**What we'd build:** On the `/findings` inbox, an "Apply accepted findings → preview 837P diff" button that rebuilds the claim JSON with accepted code swaps and renders a side-by-side diff (current vs corrected) on a new `/encounters/[id]/preview` page. The diff is read-only — we still don't submit — but the biller can hand the corrected 837P back to their own billing software or export it. The "what changed and why" framing matches what `anti-features.md` §1 already promises.
- **Touches**: `apps/portal/src/app/findings/_components/findings-inbox.tsx`, `apps/portal/src/lib/claim-rewrite.ts` (new), `apps/portal/src/app/encounters/[id]/preview/page.tsx` (new).
- **Engineering**: ~1.5–2 weeks.

### G1 — Live EMR data feed (priority 50)
**What we'd build:** First a portal-side scheduled pull job that reads `Tenant.ehrConnectionMode = 'sftp'` rows every 15 minutes and runs `scripts/ehr/advancedmd_pull.sh` per tenant (closes the "we configured SFTP and then nothing happened" gap), then a Telus PS Suite file-drop adapter (the modal Alberta EMR per `ALBERTA_PROSPECT_LIST.md`), then — once we have 5+ live pilots — a single FHIR R4 `Claim` endpoint read-only consumer for whichever EMR standardizes first.
- **Touches**: `apps/portal/src/app/api/cron/ehr-pull/route.ts` (new), `apps/portal/src/lib/ehr-puller.ts` (new), `src/ai_billing_audit/csv_ingest.py` (extend with PS Suite column dictionary).
- **Engineering**: ~3–6 weeks for the scheduled pull + PS Suite adapter; 6–8 weeks for FHIR.

### G3 — Monthly ROI report view in the portal (priority 48)
**What we'd build:** A `/reports` portal page (owner role only) that calls the existing FastAPI `monthly_report.compute_monthly_summary()` and `monthly_pdf.render_monthly_pdf()` and renders (a) a web dashboard version with the same numbers and (b) a "Download PDF" button that returns the existing A4 PDF. Pairs with the public `/calculator` ROI tool but is real, per-tenant data. Includes the "you saved $X in the last 30 days" headline the clinic owner asks for on every sales call.
- **Touches**: `apps/portal/src/app/reports/page.tsx` (new), `apps/portal/src/app/api/reports/monthly/route.ts` (new), `src/ai_billing_audit/api.py` (expose `compute_monthly_summary`).
- **Engineering**: ~1 week (most of the math already lives in FastAPI).

### G5 — HIA patient-data access UI (priority 48)
**What we'd build:** A `/compliance/patient-access` page (owner role only) with two flows: (a) "What do we hold for patient X?" — paste a PHN, system returns the salted SHA-256 hash and the count of `Encounter` + `AuditTrailEntry` rows referencing it; (b) "Delete all data for patient X" — generates a signed deletion request that runs the existing `scripts/purge-canceled-tenants.ts` pattern scoped to the patient hash, with a 7-day grace window. Both flows write to the audit trail. Aligns with HIA custodian obligations that any Alberta privacy officer will check for in the BAA review.
- **Touches**: `apps/portal/src/app/compliance/patient-access/page.tsx` (new), `apps/portal/src/app/api/compliance/patient-lookup/route.ts` (new), `apps/portal/src/app/api/compliance/patient-deletion/route.ts` (new), `apps/portal/src/lib/audit-write.ts` (extend to non-finding-bound events per existing TODO).
- **Engineering**: ~1–1.5 weeks; also closes the existing `audit_log_export` self-logging TODO at `apps/portal/src/app/api/audit/export/route.ts`.

---

## 4. Out of scope for the 90-day plan

| Item | Why out |
|---|---|
| **G4 — multi-clinic / group tenant model** | Only the top 1–2 prospects (Strathcona PCN, Medicentres corporate) need this today; the rest of the prospect list is single-clinic. Adding it before we have even one paying clinic is premature. Revisit after first 3 paid pilots. |
| **G6 — in-app notifications** | "Refresh the page" is acceptable at our current volume; the weekly-digest email is the right channel for now. In-app adds engineering surface for marginal UX gain. |
| **G7 — doctor portal view** | `doctor_dashboard.py` modules exist but no doctor has logged into the portal in any pilot scenario; doctors currently get findings via the biller. Adding a doctor role is a deeper RBAC + onboarding rewrite. Re-evaluate after we have a clinic where the doctor (not the biller) is the buyer. |
| **G10 — comments / assignment** | Low demand (priority 16). Accept/dismiss is sufficient for current solo-biller workflow. If we add a second-biller team later, this becomes a 6-month item. |
| **G12 — AHCIP submission / appeal-letter auto-send** | Explicitly out of scope per `anti-features.md` §1 + §3. H-Link integration requires Alberta Health vendor approval (months of legal + cert); appeal-letter auto-send to a payer carries insurance + appeal-window legal risk. The reconciliation UI in G2 is the safer half-step. |
| **MSP / OHIP expansion** | Per `ALBERTA_STRATEGY_BRIEF.md` §5: "deferred until Alberta pilot ships." MSP first ($1,560 USD / 5–6 weeks), OHIP second ($2,340 / 8–9 weeks), but those costs don't compete with the 90-day Alberta-execution budget. |
| **SOC 2 / ISO 27001** | On the certification roadmap per `/security` page copy; not currently held. We're transparent about this. Procurement cycle at the first Medicentres / Covenant Health will tell us whether to accelerate. |
| **Live RAG over per-clinic rules** | The auditor already does retrieval over the static `rules/` folder at audit time; per-clinic rule overrides (G8 priority 48) is a UI surface for the same data, not a new model. The "live retrieval" gap is a different (much larger) feature. |

---

## 5. Notes for the verifier (and for the P0 roadmap track)

- Every gap row in §2 points at a concrete file (page, lib, or backend module). The verifier can grep the pointers and confirm the gap exists in the codebase.
- **Three gaps are flagged "must verify against P1/P5"** (G1 demand, G5 demand, G11 demand). When the biller-workflow and customer-signal tracks land, re-score demand for those rows. The methodology is unchanged.
- **G3 (monthly ROI report)** and **G9 (synthetic demo path)** are the two highest-leverage quick wins; G9 is the bigger leverage per the math (priority 80 vs 48) but G3 has the existing FastAPI module to lean on.
- **G2 (reconciliation preview)** is the half-step that lets Zorva stay inside `anti-features.md` §1 ("we don't submit") while still giving the biller a usable artifact. The pitch stays intact; the product gets closer to the biller's daily workflow.
- **G1 (live EMR)** is the biggest engineering commitment and the most competitive. Wait for P3 (EMR landscape) to land before locking the sequencing — the document may change the order (e.g., OSCAR might be quicker to integrate than Telus PSS despite PSS's larger market share).
- **G5 (HIA UI)** is also a compliance-quality-of-life fix that closes the existing `audit_log_export` self-logging TODO at `apps/portal/src/app/api/audit/export/route.ts:35` — engineering it kills two birds.
- This document does NOT include a "what comes after 90 days" section; that's P0's job. The 5 picked gaps here should be the input P0 prioritizes into Week 1–2 / Week 3–6 / Week 7–12 buckets.

---

## 6. Changed files / pointers

- **This file**: `research/P6-product-gaps.md`
- **Plan output dir**: `/Users/biancabienaime/.mavis/plans/plan_cc23148d/outputs/research-product-gaps/`
- **Codebase references audited**: `apps/portal/src/app/{dashboard,encounters,findings,billing,settings,team,security,onboarding,api}/`, `apps/portal/src/lib/`, `apps/portal/prisma/schema.prisma`, `src/ai_billing_audit/{auditor,denial_risk,appeal_letter,feedback,doctor_dashboard,monthly_report,monthly_pdf,per_clinic_f1,csv_ingest,job_queue,carc_rarc}.py`, `prompts/v12/auditor_prompt.txt`, `docs/{ALBERTA_STRATEGY_BRIEF,ALBERTA_PROSPECT_LIST,AHCIP_RULE_REFERENCE,PILOT_OFFER,SALES_DEMO,ANTI_FEATURES,EHR_ADVANCEDMD_INTEGRATION}.md`.
