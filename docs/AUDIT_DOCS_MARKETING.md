# Zorva — Docs, Marketing & Positioning Audit

**Date:** 2026-06-23
**Auditor:** Hermes subagent (read-only)
**Scope:** `/docs/` (68 .md files at top level + subdirs), `apps/portal/src/` (all Next.js pages and copy), `src/ai_billing_audit/` (the SRC side that some docs reference), `prompts/MANIFEST.json`, plus README accuracy at project root, src/ root, and apps/portal/ root.
**Constraints observed:** No source/docs/marketing copy modified. apps/portal not deployed. Live URL not touched.

---

## TL;DR

- **Biggest single risk: the marketing portal makes multiple concrete claims that the live codebase does not back up.** `apps/portal/src/app/page.tsx:54-61` says data lives in AWS ca-central-1 / us-east-1 — the live deployment is Hostinger VPS (per prior agent #2 + `AUDIT_DEPLOY_OPS.md`). This claim is the single most likely thing to embarrass Zorva in a privacy-officer conversation.
- **The portal's data-residency framing is also wrong in another way.** The portal has no multi-market claims — Mexico / Colombia are not present. But the portal's PHIPA matrix at `apps/portal/src/app/security/page.tsx:280-299` is silently framed as Ontario-leaning, while the v12 prompt + Alberta pilot outreach (2026-06-22) are Alberta-only. Any Alberta prospect who reads the matrix will notice the wrong provincial statute.
- **The hero product numbers in any docs that should be quoting them are missing or stale.** No F1=0.733 number appears anywhere in `/docs/` or `apps/portal/src/` (the prior session's note about F1=0.733 was likely a mis-quote — the actual v12/AHCIP number is F1=0.588 on 10 encounters per `ALBERTA_STRATEGY_BRIEF.md:32`). Pricing tiers ($499/$1,499/$2,999 CAD) and Stripe checkout wiring are real. The 30-day pilot offer is real but the doc pre-dates the Alberta pivot.
- **The README is a time capsule.** The 722-line project README still describes the v0 prompt / MIPROv2 loop / Phase 0-7 roadmap. None of that is current. The apps/portal/README.md is the create-next-app boilerplate, not project documentation. There is no README at `src/`.
- **The "5 conversion-blocking gaps" status in marketing copy is unsafe.** `apps/portal/src/app/how-it-works/page.tsx` and `pricing/page.tsx` describe an "audit every claim" / "flag under-coded visits" product without disclosing that the 5 conversion-blocking gaps from `docs/AUDIT_CODE_QUALITY.md:140` were only 4/5 resolved, and the remaining gap (re-audit endpoint still re-synthesizes claims) is not user-visible.

**Top 3 things to fix this week:**
1. Change every "AWS ca-central-1" / "AWS us-east-1" in the marketing portal to either the truth (Hostinger VPS, region-unspecified) or deploy on actual AWS. `apps/portal/src/app/page.tsx:54-61`, `apps/portal/src/app/security/page.tsx:7, 64-65, 287, 311, 322, 352`, `apps/portal/src/app/portal/onboarding/OnboardingWizard.tsx:393-419`, `apps/portal/src/lib/pricing.ts:50,57,65`, `apps/portal/src/app/security/page.tsx:280` (the "PHIPA (Ontario)" row).
2. Decide: is the v12 Alberta product the marketing message, or is the multi-jurisdiction OHIP/MSP/Quebec framing still in play? Today the portal's security page and pricing features say PHIPA / PIPEDA / AIDA (Alberta-aligned) but the Alberta pilot outreach on 2026-06-22 is Alberta-only and the v12 prompt drops US conventions. `apps/portal/src/app/pricing/page.tsx` lists USD as a primary currency — there is no US product in v12.
3. Rewrite the project root README to describe v12 + Alberta + the deployed state, not v0 + MIPROv2 + Phase 0-7.

---

## 1. Docs Inventory

`/docs/` contains 68 top-level `.md` files (the "~200" claim in the task body counts subdirs like `audit/`, `a11y/`, `qa-portal-ui/`, `qa_artifacts/`, `screenshots/` and the PDFs/MP4/WebM; total is closer to 80 markdown files, not 200). All file paths below are absolute from project root.

### 1a. The 5 most important docs

| # | Doc | Role | Status |
|---|-----|------|--------|
| 1 | `docs/PILOT_OFFER.md` | The single canonical "what we promise in a 30-day pilot" doc that Eliud uses in conversation. Referenced by `ALBERTA_PROSPECT_LIST.md:236`. | Real, but pre-dates the Alberta pivot — see §5. |
| 2 | `docs/ONE_PAGER_WHAT_WE_DO.md` | The one-page summary (with PDF export at `ONE_PAGER_WHAT_WE_DO.pdf`). Pricing line says "$X/month flat. Final figure set during the pilot conversation." | Real, but pricing is a placeholder string. |
| 3 | `docs/SALES_DEMO.md` | The 63-line sales runbook. Walk-through order, three plans, "Do NOT promise" list. | Real, mostly accurate. |
| 4 | `apps/portal/src/app/pricing/page.tsx` (+ `apps/portal/src/lib/pricing.ts`) | The canonical pricing surface — server component, env-driven tier config. | Real. Stripe checkout wired. |
| 5 | `docs/ALBERTA_STRATEGY_BRIEF.md` | The 2026-06-22 Alberta-first pivot brief (v12 prompt, 12-clinic prospect list, F1=0.588, PHIPA → HIA note). Working draft, not yet feeding a marketing doc. | Real, accurate; has not propagated to marketing copy. |

Notably there is **no ROI calculator doc and no ROI calculator in the portal.** `docs/SALES_DEMO.md` does not compute ROI; the portal has no `/roi` route (verified: `find apps/portal/src -type d -name "roi"` returns empty). `src/ai_billing_audit/roi.py` exists as a Python module but is never linked from any user-facing page.

### 1b. Superseded but not deleted

These docs pre-date the current v12 state and could mislead a reader who hasn't tracked the prompt versioning:

- `docs/BUGS_overfit.md` — references v0 prompt's F1=1.0 on held-out data (Jun 16–17 era). The current pin is v12 at `prompts/MANIFEST.json`.
- `docs/QA_RESEARCH_SUMMARY.md`, `QA_RESEARCH_WHY_MISSED.md`, `QA_RESEARCH_FINDING_BUCKETS.md`, `QA_RESEARCH_GT_QUALITY.md`, `QA_RESEARCH_PARSE_FAILURES.md`, `QA_RESEARCH_COST.md`, `QA_RESEARCH_DSPY_INTEGRATION.md`, `QA_RESEARCH_EHR_INTEGRATION.md` — all 8 written Jun 17, all reference F1=0.021 baseline + v0 prompt. The harness+scoring contract bugs they describe are fixed (F1=0.268 is the new floor per `daily_report_2026-06-23.md:10`), but the QA_RESEARCH_* docs are still labeled as if the bugs were live.
- `docs/CONTINUOUS_QA_SYSTEM.md`, `docs/CALIBRATION.md` — pre-AHCIP. Calibration is a synthetic-data concern; the v12 product is AHCIP-pinned.
- `docs/ACCEPTANCE_RUN.md` — pre-AHCIP acceptance criteria.
- `docs/CODE_REVIEW_*.md`, `docs/BUGS_*.md`, `docs/SEC_REVIEW_*.md`, `docs/UI_REVIEW_*.md`, `docs/A11Y_REPORT.md` — all written Jun 16–17. They are honest snapshots of the codebase at that point but the codebase has moved 6+ days forward. They're historical, not authoritative.
- `docs/iterATION_LOG.md` — labeled as a workflow doc but the file is dated 2026-06-18 and references workflows that may have changed.
- `docs/DOCS_REVIEW.md` — a meta-review of earlier docs. Self-referential; check whether it has been updated since.

### 1c. References to old code

- `README.md:1-722` (project root): describes the v0 baseline harness, MIPROv2 optimizer, Phase 0-7 roadmap, `gpt-4o-mini` as the default model, "75 tests pass," and `scripts/optimize.py` as the primary entry point. None of this is the current state. Current pin: v12 (AHCIP-tuned, Alberta-pinned, see `prompts/v12/auditor_prompt.txt:1-5`). Default model moved off `gpt-4o-mini`. 791 tests now pass (per `AUDIT_CODE_QUALITY.md:179`). The README's own Known Limitations section (`README.md:295-324`) reads as if the project never shipped Phase 5+ — but the dashboard, billing, onboarding, ROI, portal UI are all live.
- `apps/portal/README.md` — boilerplate create-next-app README. Has nothing to do with Zorva. Identical to what `create-next-app` generates. (See §1e.)
- No `src/README.md` exists.
- `docs/PILOT_OFFER.md:18-19` references "R/P validation" terminology that fits the pre-MVP framing; the live product is billing-audit, not R/P recall experiments.
- `docs/ALBERTA_STRATEGY_BRIEF.md:188` correctly notes that the v11 prompt is "live, F1=0.588" but says the v12 prompt is "Not built — 1-2 hours of work." This contradicts `prompts/v12/auditor_prompt.txt` which exists and is the current pin per `prompts/MANIFEST.json`. The brief is stale on this point.

### 1d. Effectively abandoned (last updated >60 days ago, no recent content)

Strictly speaking no doc in the repo is >60 days old — every doc was created or updated between Jun 16–23, 2026. The "abandoned" category therefore doesn't apply by mtime. The closest equivalents are:

- `docs/CODE_REVIEW_*.md` cluster (8 files, all Jun 16, ~722 LOC total) — never re-reviewed. The codebase has changed substantially since.
- `docs/BUGS_*.md` cluster (6 files) — bug findings from Jun 16–17, never closed out as fixed-or-not.
- `docs/QA_RESEARCH_*.md` (8 files) — research passes, never synthesized into a single "current state" doc.
- `docs/SEC_REVIEW_*.md` (3 files) — security reviews never re-run.

### 1e. README accuracy

| README | Exists? | Accurate? |
|--------|---------|-----------|
| `/Users/biancabienaime/projects/ai-billing-audit/README.md` | Yes | **No.** 722 lines. Describes the MVP / Phase 0-7 / `scripts/optimize.py` / v0 prompt / `gpt-4o-mini` / 75 tests. The actual product is v12 (AHCIP), Alberta-pivot, 791 tests, billing portal live. The README's own §Roadmap (§326-388) is a checklist of [x] shipped and [ ] pending items that no longer match what's shipped. |
| `/Users/biancabienaime/projects/ai-billing-audit/src/README.md` | **No** | n/a |
| `/Users/biancabienaime/projects/ai-billing-audit/apps/portal/README.md` | Yes | **No.** It is the default create-next-app boilerplate: "First, run the development server... Open http://localhost:3000... This project uses next/font... Deploy on Vercel." No reference to Zorva, AHCIP, billing, or even the `/pricing`, `/how-it-works`, `/security`, `/contact` routes that are the actual product surface. |

### 1f. Do any docs reference the 5 conversion-blocking gaps as fixed when they aren't?

`docs/AUDIT_CODE_QUALITY.md:140` says the 5 conversion-blocking gaps were "4 OF 5 RESOLVED" — the remaining unresolved gap is the re-audit endpoint at `api.py:2191` that still re-synthesizes the claim from `encounter_id` hash (the user's clinical_note is ignored). No docs/ or apps/portal/ page references the 5 gaps directly, so the specific claim "5 conversion-blocking gaps are fixed" does not appear in marketing copy. But the related marketing claim — "AI audits every claim pre-bill" (`apps/portal/src/app/how-it-works/page.tsx:68-79`) — is partially false: if a user clicks "rerun audit" on an existing encounter, the auditor uses a synth-derived claim, not the original uploaded one. This is a real product defect that marketing copy does not disclose.

---

## 2. Marketing Claim Accuracy (apps/portal/src/)

### Per-claim table

| Claim | Where in code | Reality | Verdict |
|-------|---------------|---------|---------|
| **"Multi-market Canada + US"** | No page explicitly claims this. `apps/portal/src/app/page.tsx:54-61` says "ca-central-1 for Canadian clinics, us-east-1 for US." | Live deployment is Hostinger VPS, not AWS. Pricing page renders both CAD and USD prices (`apps/portal/src/lib/pricing.ts:122-127`). No OHIP/MSP rules in v12. No Mexico/Colombia references in any portal file. | ⚠️ **Misleading.** The portal correctly scopes Canada + US (no Mexico/Colombia leakage), but the "ca-central-1 / us-east-1" data-residency claim is factually wrong about the deployment location. |
| **"AWS ca-central-1"** | `apps/portal/src/app/page.tsx:54-61`, `apps/portal/src/app/security/page.tsx:7, 64-65, 287, 311, 322, 352`, `apps/portal/src/app/portal/onboarding/OnboardingWizard.tsx:403, 418` (`Canada (ca-central-1)` / `United States (us-east-1)`), `apps/portal/src/lib/onboarding.ts:52`, `apps/portal/src/lib/settings.ts:41`, `apps/portal/src/lib/prisma.ts:16-17` | Live is Hostinger VPS (per prior session + `AUDIT_DEPLOY_OPS.md:265` "Hostinger VPS disk... coolify VPS at 187.77.26.99"). `src/llm_client.py` etc. has no AWS integration. | ❌ **Wrong.** The portal tells every prospect that data lives in AWS; it does not. |
| **"AWS us-east-1"** | Same files as above | Same as above. | ❌ **Wrong.** |
| **"F1=0.733"** | **Not present anywhere** in `/docs/` or `apps/portal/src/`. Searched both directories. | The actual current number is F1=0.588 on the cleaned AHCIP val set (`ALBERTA_STRATEGY_BRIEF.md:32`) and F1=0.268 on the multi-run baseline (`daily_report_2026-06-23.md:10`). | ⚠️ **No leak** of F1=0.733 in marketing. The "0.733" number cited in the task prompt does not appear to exist anywhere in the repo. (Possibly a misremembered value from an earlier agent.) The honest F1 number (0.588) is also not in any marketing copy. |
| **"85% of billing errors"** | Not present anywhere. | Not present. | ✅ Not claimed. |
| **"PHIPA / PIPEDA / HIPAA"** | `apps/portal/src/app/page.tsx:58-60` ("PHIPA, HIPAA, and the Washington My Health My Data Act"); `apps/portal/src/app/security/page.tsx:27` (meta description), 116 ("For Ontario and Alberta customers we sign a Health Information Custodian Agent (HIC-Agent) agreement under PHIPA"), 163, 280 (PHIPA row), 292 (HIA row) | Compliance matrix correctly lists both PHIPA (Ontario) and HIA (Alberta) as separate rows. | ⚠️ **Half right.** The matrix is OK; the page-1 landing text lumps PHIPA + Alberta in the wrong combination. For an Alberta prospect, "PHIPA + PIPEDA" is the wrong statute pair (correct: HIA + PIPEDA). |
| **"PHIPA" used where Alberta is the right framing** | `apps/portal/src/app/contact/ContactForm.tsx:214` ("PHIPA / HIPAA / AKS explainer you can forward to your privacy officer"); `apps/portal/src/lib/pricing.ts:50,57,65` ("PHIPA-aligned audit trail with hash-chain" in all 3 tiers); `apps/portal/src/app/security/page.tsx:280-289` (matrix row says "PHIPA (Ontario)" — that's correct as a row but the column header reads "PHIPA-aligned" elsewhere) | Alberta pilot outreach (2026-06-22) targets Alberta AHCIP clinics. The correct Alberta framing is HIA + PIPEDA per `ALBERTA_STRATEGY_BRIEF.md:123`. | ❌ **Wrong for Alberta.** Pricing tiers are advertised with "PHIPA-aligned audit trail" but the customer is being targeted in Alberta where HIA is the provincial law. |
| **"PIPEDA + AIDA"** | `apps/portal/src/app/security/page.tsx:316-326, 328-338` (PIPEDA + AIDA rows in compliance matrix) | PIPEDA is federal Canada (correct). AIDA is Alberta's AI-specific framework (correct for an Alberta-targeted product). | ✅ Correct, but only matters if Alberta is the actual market — which it now is. |
| **"AKS / Stark safe harbor"** | `apps/portal/src/app/pricing/page.tsx:128` ("AKS / Stark safe-harbor compliant"), `apps/portal/src/app/security/page.tsx:206-221` | Pricing model is a flat monthly fee with no %-of-revenue. AKS safe harbor framing is correct in principle. Stark Law doesn't apply outside US Medicare/Medicaid federal programs — referencing "Stark" for a Canada-pinned product is awkward but not factually wrong (Stark is referenced as a parallel concept, AKS is the operative US one). | ⚠️ Mostly correct, slightly inflated. |
| **"AI-powered / AI-driven"** | `apps/portal/src/app/layout.tsx:18, 21-23` ("AI Pre-Bill Audit. AI pre-bill audit catches what your billing team misses. Region-pinned data, hash-chain audit log, AKS-safe-harbor flat-fee pricing.") | The product is genuinely AI-powered (LLM auditor via `apps/portal/src/app/api/audit/run/route.ts`). | ✅ Correct. |
| **"Self-improving"** | Not in portal marketing copy. (DSPy loop is mentioned in `/docs/` only.) | DSPy loop exists in `src/optimize.py` but has not been run on real customer data per the v12 prompt's own scope. | ✅ Not claimed in marketing — accurate by omission. |
| **"Real-time"** | Not in portal marketing copy. | Not claimed. | ✅ Not claimed. |
| **"Audit every claim pre-bill"** | `apps/portal/src/app/page.tsx:44-52`, `apps/portal/src/app/how-it-works/page.tsx:68-79` | Auditor runs in `apps/portal/src/app/api/audit/run/route.ts`. Has a real-data branch keyed on uploaded_note + queued_cpts but the re-audit endpoint (`api.py:2191`, not in portal but referenced via `apps/portal` API surface) still re-synthesizes. | ⚠️ Partially true for the upload path; false for the re-audit path. |
| **Pricing tiers $499 / $1,499 / $2,999 CAD** | `apps/portal/src/lib/pricing.ts:109` (defaults to 499 / 1,499 / 2,999 when env unset); `apps/portal/src/app/pricing/page.tsx` (renders the three tiers) | Tier prices match the SALES_DEMO.md table (`SALES_DEMO.md:24-28`). Stripe checkout is wired at `apps/portal/src/app/api/billing/checkout/route.ts:57-174` and creates a `subscription_mode` session with the configured Stripe price ID. Demo-mode fallback exists when `STRIPE_SECRET_KEY` is unset. | ✅ **Real.** Pricing is real, Stripe checkout is wired. USD price IDs render but env-controlled. |
| **"5-minute onboarding" / "10-minute setup"** | Not present anywhere in `/docs/` or `apps/portal/src/`. | Onboarding wizard is a 5-step client component at `apps/portal/src/app/portal/onboarding/OnboardingWizard.tsx` (steps 0-4 = clinic profile, residency, EHR, first encounter, complete). Each step submits a JSON POST. Realistically takes longer than 5-10 minutes because of clinic profile fields, SFTP credentials, and file upload. | ✅ Not claimed in marketing. |
| **"30-day free pilot"** | `docs/PILOT_OFFER.md:1` title ("Free 30-Day Pilot"). `docs/ONE_PAGER_WHAT_WE_DO.md:11` ("30-day free pilot"). Not on the marketing portal itself. | The pilot is genuinely framed as 30-day free across all docs. SALES_DEMO.md:30 says "start them on Small and let them upgrade after 30 days." | ✅ **Real.** |
| **"Talk to sales" CTA at right place** | `apps/portal/src/app/page.tsx:34-35` (primary CTA "Talk to sales"); `pricing/page.tsx:109-111` (alt path "Talk to sales →"); `how-it-works/page.tsx:30-32` ("Book a 15-min walkthrough") | CTAs route to `/contact`, which has a real contact form. `sales@example.com` placeholder in the contact page (`apps/portal/src/app/contact/page.tsx:43`) is a placeholder. | ⚠️ Routes are real; email is a placeholder. |
| **Self-serve pilot signup** | None. There is no /pilot or /signup route. `/contact` is a contact form, not a pilot signup. | No self-serve flow. | ✅ Not claimed — accurate by omission. |

### PHIPA vs HIA mismatches (per task step #2)

Counted 12 separate places where "PHIPA" appears in apps/portal/src/. In a strictly Alberta-targeted pilot (which is the current reality per the 2026-06-22 pivot), the framing should be HIA:

| File:Line | Exact text | Problem |
|-----------|------------|---------|
| `apps/portal/src/app/contact/ContactForm.tsx:214` | "the security page has the PHIPA / HIPAA / AKS explainer you can forward to your privacy officer" | This is the success message shown to every prospect who fills the contact form. Wrong for Alberta prospects. |
| `apps/portal/src/lib/pricing.ts:50, 57, 65` | "PHIPA-aligned audit trail with hash-chain" (in all 3 tiers' features lists) | Repeated 3× on the /pricing page. |
| `apps/portal/src/app/page.tsx:58-60` | "PHIPA, HIPAA, and the Washington My Health My Data Act are all addressed in the security page." | First thing an Alberta prospect reads on /. Wrong statute pair. |
| `apps/portal/src/app/security/page.tsx:116` | "For Ontario and Alberta customers we sign a Health Information Custodian Agent (HIC-Agent) agreement under PHIPA." | This is factually wrong — HIA is Alberta's health information law, not PHIPA. |
| `apps/portal/src/app/security/page.tsx:280` | Compliance matrix row "PHIPA (Ontario)" | This row is correct in isolation, but the previous row at line 116 contradicts it. |
| `apps/portal/src/app/security/page.tsx:299` | "encryption and residency controls as PHIPA" (in the HIA row) | The HIA row says controls mirror PHIPA, which is fine but the HIA row should describe its own law. |

### AWS ca-central-1 vs Hostinger mismatches (per task step #2)

7 separate code locations in apps/portal/src/ claim AWS ca-central-1 or us-east-1:

| File:Line | Exact text |
|-----------|------------|
| `apps/portal/src/app/page.tsx:54-61` | "ca-central-1 for Canadian clinics, us-east-1 for US. No cross-region replication…" |
| `apps/portal/src/app/security/page.tsx:7` (header comment) | "// 1. Data residency by region (AWS ca-central-1 for CA, us-east-1 for US)" |
| `apps/portal/src/app/security/page.tsx:64-65` | "Canadian customer data lives in AWS ca-central-1 (Montréal). US customer data lives in AWS us-east-1 (N. Virginia)." |
| `apps/portal/src/app/security/page.tsx:287` (PHIPA row) | "region-pinned storage in ca-central-1" |
| `apps/portal/src/app/security/page.tsx:311` (HIPAA row) | "region-pinned storage in us-east-1" |
| `apps/portal/src/app/security/page.tsx:322` (PIPEDA row) | "Data residency in ca-central-1" |
| `apps/portal/src/app/security/page.tsx:352` (US state privacy laws row) | "data residency in us-east-1" |
| `apps/portal/src/app/portal/onboarding/OnboardingWizard.tsx:393-419` | Radio buttons: "Canada (ca-central-1) — Montréal region. PIPEDA-aligned." / "United States (us-east-1) — Virginia region. HIPAA-aligned." |
| `apps/portal/src/lib/onboarding.ts:52` | `export const RESIDENCY_REGIONS = ["ca-central-1", "us-east-1"] as const;` |
| `apps/portal/src/lib/settings.ts:41` | Same RESIDENCY_REGIONS export |
| `apps/portal/src/lib/prisma.ts:16-17` | "// production swap this for @prisma/adapter-pg pointed at the ca-central-1 or us-east-1 Postgres cluster." |

### F1=0.733 without val-set leakage disclosure

**No instance of F1=0.733 found in `/docs/` or `apps/portal/src/`.** The most-cited current number is F1=0.588 on the cleaned AHCIP val set (`ALBERTA_STRATEGY_BRIEF.md:32`), with v11 R=0.769 / P=0.476. The val-set leakage concern (per agent #3 note in the task prompt) — that v12's F1 number is partially inflated because val examples leak into few-shot prompts — is documented nowhere in the public-facing materials because **no F1 number is in the public-facing materials.** That's actually correct: there is no public F1 claim. But it also means a prospect who asks "what's your catch rate?" gets no prepared answer from any public doc.

---

## 3. Pricing + Stripe

**3 tiers are real.** `apps/portal/src/lib/pricing.ts:122-135` returns a `PricingConfig` with 3 tiers. Defaults are 499 / 1,499 / 2,999 CAD and 369 / 1,109 / 2,219 USD. Env vars (`PRICING_TIER_<ID>_PRICE_CAD`, `_USD`, `_STRIPE_PRICE_ID_CAD`, `_STRIPE_PRICE_ID_USD`, `_AUDIT_CAP`) can override.

**Stripe checkout is wired.** `apps/portal/src/app/api/billing/checkout/route.ts:57-174` reads `{tierId, currency}` and:
- Returns a demo-mode stub (`demo: true`) when `STRIPE_SECRET_KEY` is unset (lines 93-103) — useful for dev.
- Otherwise calls `stripe.checkout.sessions.create()` in `subscription` mode with the price ID from `getStripePriceId()` (lines 105, 132-156).
- Idempotency key = `checkout:${tierId}:${currency}:${forwardedFor ?? "anon"}` (line 126).
- success_url = `/portal/onboarding?session_id={CHECKOUT_SESSION_ID}` (line 128-129).
- cancel_url = `/pricing` (line 130).

**Front-end button is wired.** `apps/portal/src/app/pricing/CheckoutButton.tsx:30-52` POSTs to `/api/billing/checkout` and redirects to the returned Stripe URL (or the local demo URL in demo mode).

**"Talk to sales" CTA is at the right place.** `apps/portal/src/app/pricing/page.tsx:103-113` has an "Not sure which tier fits?" section that links to `/contact` with the text "Talk to sales →".

**Self-serve pilot signup: does not exist.** The pilot is offered only via the `/contact` form, which routes to `apps/portal/src/app/api/leads/route.ts`. There is no /pilot or /signup route. (`docs/PILOT_OFFER.md` confirms this is by design: the pilot starts with a 10-minute call and a BAA.)

**Caveat: env-driven pricing can be silently different from the rendered price.** If env vars set non-canonical values, the rendered prices change but the sales demo's "pick the mid tier" rule (`docs/SALES_DEMO.md:30`) may not match. The pricing page itself doesn't surface "if env is unset, defaults are 499/1499/2999" — a developer who runs the dev server without env gets the canonical numbers.

---

## 4. Legal + Compliance

### /legal/privacy page: **Does not exist.** No file or directory in `apps/portal/src/app/` matches `legal`. The only privacy-adjacent public page is `/security`.

### /legal/terms page: **Does not exist.**

### BAA template: **Does not exist in repo.** `docs/ALBERTA_STRATEGY_BRIEF.md:172, 192` lists "BAA / HIA agreement template" as a TBD item not yet started. The portal security page offers to email a draft BAA: `apps/portal/src/app/security/page.tsx:122-125` "send it to legal@ai-billing-audit.ashbi.ca and we will turn it around inside two business days" — but the email address is at a domain the marketing site claims (`ai-billing-audit.ashbi.ca`). The portal has no actual BAA template, draft, or hosted PDF.

### DPO / Privacy Officer designation: **Generic email only.** No DPO named anywhere. `apps/portal/src/app/security/page.tsx:122` uses `legal@ai-billing-audit.ashbi.ca` and line 406 uses `hello@ai-billing-audit.ashbi.ca`. `RUNBOOK.md:1.6` references "Privacy Officer" only as a procedural role for chain-repair, not as a real named position.

### Data retention period: **Partially specified.**
- `apps/portal/src/app/billing/BillingActions.tsx:142-145` references a "30-day" window for some flows but the comment is ambiguous about whether it's data retention or a billing action window.
- `apps/portal/src/app/api/billing/webhook/route.ts:4, 13` references "30-day purge script" — implying 30-day customer data retention.
- `docs/AUDIT_DEPLOY_OPS.md:295` says backups are "4 weeks dailies, 12 months weeklies, 7 years monthlies" — PHIPA-compliant per the same line.
- **No portal page or PILOT_OFFER.md mentions the retention period to the prospect.** PILOT_OFFER.md says "we delete everything you shared with us" within 7 business days of an email request (line 25) but does not specify the default retention period before the delete-on-request is exercised.

### Data-residency claim consistency across docs

**Not consistent.** Marketing portal says AWS ca-central-1/us-east-1 in 7+ places. AUDIT_DEPLOY_OPS.md and the README honestly say Hostinger VPS. `prompts/v12/auditor_prompt.txt` does not specify region (it operates over the LLM API, not on customer data infrastructure). Internal `ALBERTA_STRATEGY_BRIEF.md:126` says "HIA-compliant data residency, ca-central-1" — repeating the same AWS-framing even in an internal doc. So the inconsistency is between (marketing portal) vs (internal README / deploy doc / Hostinger reality).

---

## 5. Pilot Offer — Current State

`docs/PILOT_OFFER.md` is the canonical doc. Verified contents:

- **Length:** 30 days (line 1, line 5, line 11, line 33). Not 60.
- **Scope:** "audit your last 100 claims" (line 11), not "your live claim feed." Not full integration; the pilot is a sample-based shadow run.
- **Timeline:** 4 weeks (lines 30-33). Week 1 = connect + BAA + data, Week 2 = shadow run, Week 3 = review with billing lead, Week 4 = convert or walk away.
- **Catch-rate promise:** None explicit. PILOT_OFFER.md says only "we hand you a paid plan" / "we delete everything." No F1 or "85%" claim. ✅ Defensible.
- **BAA reference:** Line 30 ("We sign the BAA, get a read-only data feed or sample file") and line 38 ("A signed BAA before any data moves. We have a template ready"). But the BAA template referenced does not actually exist in the repo (see §4).
- **Ask:** 10-minute call with billing lead + sample data (line 37). Still reasonable.
- **Alberta / HIA framing:** None. PILOT_OFFER.md is jurisdiction-agnostic — it doesn't mention any province. An Alberta biller reading it would see "PHIPA vs PIPEDA" mentioned nowhere but also wouldn't see "HIA vs PIPEDA." Acceptable but incomplete post-Alberta pivot.
- **Eliud Gonzalez:** Line 44. He's the "one running this pilot for us." No bio, no link, no signature block. Worth noting that `apps/portal/src/app/contact/page.tsx:43` references `sales@example.com` as the fallback email, which doesn't match the Eliud-as-pilot-lead framing in PILOT_OFFER.md.

The Alberta-specific pilot offer has **not been written.** `ALBERTA_STRATEGY_BRIEF.md:190` lists "Alberta-targeted pilot offer" as "TBD — Not started." The general PILOT_OFFER.md is still being sent (per `ALBERTA_PROSPECT_LIST.md:236`).

---

## 6. Sales Demo + ROI Calculator

### Does `docs/SALES_DEMO.md` work against the current live URL?

Mostly yes, with two caveats:

- **"Go to https://ai-billing-audit.ashbi.ca. Sign in with the demo account Cam set up for the call." (line 7-8)** — Per prior session, the apps/portal is not deployed. The FastAPI live URL works (different code path) but the marketing portal URL the sales demo refers to is the same domain with a different app. The sales-demo would need a current working `/login` URL — the `/login` route exists in apps/portal/src/app/login/page.tsx but is the Next.js Auth magic-link page, not a "demo account Cam set up."
- **"Click Upgrade on any plan, Stripe opens a checkout. Use card 4242 4242 4242 4242" (lines 11-18)** — Depends on whether the deployed apps/portal has `STRIPE_SECRET_KEY` configured in test mode. If it's deployed in demo mode, the CheckoutButton returns a demo URL pointing at `/portal/onboarding?demo=1` and Stripe is bypassed. The sales demo would not work as written against a demo-mode portal.
- **"Open `data/val.json`" (line 33)** — This is correct; the file exists at `data/val.json` per repo listing. But the sales demo refers to "the same claims the auditor scored during QA — easy / medium / hard" — `ALBERTA_STRATEGY_BRIEF.md:11` says the live product's val set is now `data/val_ca.json` (10 AHCIP encounters, Alberta-only). The sales demo references the old synthetic-data val.json, not the AHCIP val set. Sales demo is pre-Alberta-pivot.

### ROI Calculator

**Does not exist as a portal route or a doc.** Verified:
- No `/roi` directory under `apps/portal/src/app/` (`find apps/portal/src -type d -name "roi"` returns empty).
- No "ROI" string matches in `apps/portal/src/` (`grep -rn "ROI" apps/portal/src` returns 0 matches).
- `src/ai_billing_audit/roi.py` exists as a Python module but is not linked from any page.

So the task step #6 "Does the ROI calculator use current F1 numbers? Current pricing?" is not answerable because there is no ROI calculator. **This is a missing piece, not a wrong piece.**

### False-positive rate in any formula

Not answerable — no formula is exposed. If the ROI calc is built, it must account for false positives (an over-eager auditor that flags 50 findings per claim and 30 are wrong is worse than one that flags 10 and all are right).

---

## 7. Positioning vs Reality (6 Zorva capabilities)

| Spec capability | Marketing claim location | Code reality | Honest version |
|----------------|--------------------------|--------------|----------------|
| **"Catches billing errors before submission"** | `apps/portal/src/app/page.tsx:44-52` ("Audit every claim, not just the flagged ones") | Partially implemented. v12 prompt (`prompts/v12/auditor_prompt.txt`) is AHCIP-pinned; runs in `apps/portal/src/app/api/audit/run/route.ts`. Real-data branch works on upload path; re-audit endpoint still re-synthesizes (`api.py:2191` per AUDIT_CODE_QUALITY.md). F1=0.588 on 10 AHCIP encounters per `ALBERTA_STRATEGY_BRIEF.md:32`. | "Catches a subset of AHCIP billing errors before submission. F1=0.588 on a 10-encounter test set. Has been measured only on synthetic AHCIP claims, not on a live clinic's data." |
| **"Scores every claim for denial risk in real time"** | `apps/portal/src/app/how-it-works/page.tsx:68-79` implies this via "AI audits every claim pre-bill" but no page claims "denial risk" specifically. | `src/ai_billing_audit/denial_risk.py` exists. Severity+rule-family heuristic per file docstring (lines 1-49). Not deployed as a user-facing feature in apps/portal. | Drop the "real time" framing or wire denial_risk into the portal encounter detail page. |
| **"Generates appeal letters automatically when denials occur"** | Not in portal copy. Mentioned in `src/ai_billing_audit/appeal_letter.py:1-19` docstring. | `src/ai_billing_audit/appeal_letter.py` exists. Refers to itself as "second agent in the Zorva pipeline." Not wired into any API route the portal can call. The portal has no appeal-letter UI. | Honest: "Generates appeal letters in batch for offline review by the biller — the biller still pastes into their own template." Or do not claim. |
| **"Alerts the physician to critical findings"** | Not in portal copy. Mentioned in `src/ai_billing_audit/doctor_email.py:1-25`. | `src/ai_billing_audit/doctor_email.py` exists. Per memory note, live is Mailgun (ashbi.ca domain). Wired into `_default_runner` at `src/ai_billing_audit/job_queue.py:703` per AUDIT_CODE_QUALITY.md:137. Not visible in apps/portal — this is an src-only feature. | Honest: "Sends a 1-sentence plain-English email to the physician for each flag-worthy finding (Mailgun via ashbi.ca)." |
| **"Maintains a tamper-proof audit trail of every action"** | `apps/portal/src/app/security/page.tsx:225-256` describes "hash-chain cryptographic signature" implementation in detail. | **TWO parallel implementations:** `src/audit_log.py` (has `verify_chain()`) and `src/ai_billing_audit/audit_actions.py` (has `append()` + dead `read_for_encounter()` + dead `verify()`). Per `AUDIT_CODE_QUALITY.md:135`, `audit_actions.append()` is wired into 8 `api.py` call sites but `verify_chain()` exists only in `src/audit_log.py`. The portal has its own port at `apps/portal/src/lib/audit-chain.ts` and `apps/portal/prisma/schema.prisma:471-499` ("port of src/audit_log.py"). | Honest: "Writes every action to a hash-chained audit log. The Python backend uses `audit_actions.append()` (8 call sites in `src/api.py`); the Next.js portal uses a Prisma port in `apps/portal/src/lib/audit-chain.ts` and `apps/portal/prisma/schema.prisma`. Two implementations of the same wire format — see `AUDIT_CODE_QUALITY.md` issue #1." |
| **"Learns from every denial pattern across all clients"** | Not in portal copy. `apps/portal/src/lib/pricing.ts:55,62` says "Deterministic runs: seed pinned, temperature=0" — which is the *opposite* of "learns from every denial pattern." | DSPy loop exists in `src/optimize.py` and the v12 manifest entry is in `prompts/MANIFEST.json`. Has never been run on real customer data per the prior-session note. | Honest: "The auditor prompt was tuned against a 10-encounter AHCIP val set via MIPROv2. Per-clinic tuning after the pilot phase is on the roadmap, not in production." Or do not claim. |

### Specific observations

- **The portal marketing copy is more conservative than the Zorva spec** — it does not claim denial risk scoring, appeal letters, doctor emails, or DSPy learning. This is good. The risk is in the `/docs/` and the internal src/ docstrings where these capabilities are described as live when they are not deployed to users.
- **`audit_actions.py` vs `audit_log.py` parallel implementations** is the highest-leverage cleanup. The portal's marketing copy on /security page is honest about what the hash chain does (line 248-251 "Implementation: src/audit_log.py...") but the actual wired code is `audit_actions.py`. If a privacy officer asks "which file?" the marketing says one, the code does another.

---

## 8. Internal vs External Doc Consistency

### Watermarks

- **Internal docs:** The 4 audit files (`docs/AUDIT_CODE_QUALITY.md`, `AUDIT_DEPLOY_OPS.md`, `AUDIT_SECURITY.md`, `AUDIT_PROMPTS_VAL.md`) and the Alberta strategy brief (`docs/ALBERTA_STRATEGY_BRIEF.md`) carry no "INTERNAL" / "DO NOT SHARE" / "DRAFT" watermark. They are written in a candid voice ("the gold was wrong", "this is a measurement artifact, not a product failure") that wouldn't survive a clinic privacy-officer read.
- **External docs:** `docs/PILOT_OFFER.md`, `docs/ONE_PAGER_WHAT_WE_DO.md`, `docs/SALES_DEMO.md`, and all `apps/portal/src/app/**/*.tsx` are external. They are appropriately sanitized.
- **Mixed docs:** `docs/AHCIP_GOLD_AUDIT.md` and `docs/AHCIP_RULE_REFERENCE.md` contain internal-style commentary ("`FIRECRAWL_API_KEY` not set", "I relied on my training-data knowledge of the Alberta SOMB") but are referenced as "Source of truth" in `ALBERTA_STRATEGY_BRIEF.md`. A clinic prospect receiving these in a follow-up email would read internal-process commentary that should have been redacted.

### Accidental internal-doc references in marketing pages

- `apps/portal/src/app/security/page.tsx:248-251` says "Implementation: `src/audit_log.py`, plus the unit test in `tests/test_audit_log.py`..." — `src/` is the internal Python package name. A clinic buyer reading this is being shown internal code paths. This is honest transparency but it leaks the project structure.
- `apps/portal/src/app/security/page.tsx:11-14` (header comment) references internal task IDs: "task t_165297e9; the SHA-256 signature spec lives in src/audit_log.py". Task IDs (`t_165297e9`) are an internal Kanban convention. Comments shouldn't ship to a Next.js render.

### Accidental infrastructure-name leaks

- **No** occurrences of "Hermes", "subagent", "Maton", "Zorva_context" (except in internal audit files), or other agent infrastructure names in `apps/portal/src/` or in the public-facing docs (`PILOT_OFFER.md`, `ONE_PAGER_WHAT_WE_DO.md`, `SALES_DEMO.md`). Searched both directories.
- One mention in a test file (`apps/portal/tests/billing-page.test.ts:8`) references "~/.hermes" in a code comment — not user-visible.
- One mention in `apps/portal/AGENTS.md` — this is an internal agent-rules file, not user-facing. (Confirmed exists.)

---

## 9. Known-Issues Confirmation / Refutation Table

| # | Known issue | Confirmed? | Evidence |
|---|------------|-----------|----------|
| 1 | **Multi-market framing** (CA + US + MX + CO) | **❌ Refuted in portal, confirmed in some internal docs.** Portal has no MX/CO references (`grep -n "Mexico\|Colombia"` in `apps/portal/src/` returns 0 matches). Portal does claim "ca-central-1 / us-east-1" — i.e., CA + US only. Internal `docs/ALBERTA_STRATEGY_BRIEF.md:20` correctly flags the multi-market framing as aspirational. Portal's pricing page renders USD prices which suggests US support, but the v12 prompt is AHCIP-only. | Mixed. |
| 2 | **PHIPA vs HIA confusion for Alberta** | **✅ Confirmed in portal.** 12 PHIPA references in `apps/portal/src/`. 6 are problematic for Alberta prospects (see §2 table). `docs/ALBERTA_STRATEGY_BRIEF.md:123` calls this out. | Confirmed. |
| 3 | **"ca-central-1, AWS" claim** when live is Hostinger | **✅ Confirmed.** 11+ references in `apps/portal/src/`. `AUDIT_DEPLOY_OPS.md:265` confirms live is Hostinger VPS at 187.77.26.99. | Confirmed. |
| 4 | **"F1=0.733" claim without val-set leakage disclosure** | **❌ Refuted — F1=0.733 does not appear in any file.** Searched `/docs/` and `apps/portal/src/`. The current Alberta-pinned F1 is 0.588 (per `ALBERTA_STRATEGY_BRIEF.md:32`) and is also not in any marketing copy. The honest position: no public F1 claim. | Refuted as a leak; the underlying concern (val-set leakage into few-shot examples) is still live per agent #3 note but is not currently a marketing-claim problem. |
| 5 | **`/legal/privacy` and `/legal/terms` pages** | **❌ Refuted — neither exists.** `find apps/portal/src -type d -name legal` returns empty. No privacy policy or terms page in the portal. The closest is `/security`. | Refuted — pages don't exist; this is a missing-pages problem, not a wrong-pages problem. |
| 6 | **"apps/portal not deployed"** | **✅ Confirmed via docs.** `ALBERTA_STRATEGY_BRIEF.md:31` lists live URL as `https://ai-billing-audit.ashbi.ca` with "auth disabled for demo" — that URL is the FastAPI app, not the Next.js portal. The portal pages themselves are runnable locally per `apps/portal/package.json` but are not deployed. | Confirmed. (Per task constraints, I did not test the live URL or attempt to deploy.) |

---

## 10. Risk-Ranked Recommendations

In order of leverage. Each is a concrete next action; all are out of scope for this audit (read-only) but should be the next batch of work.

### 1. Replace every AWS-region claim in the portal with the actual deployment story.
- **Files:** `apps/portal/src/app/page.tsx:54-61`, `apps/portal/src/app/security/page.tsx:7, 64-65, 287, 311, 322, 352`, `apps/portal/src/app/portal/onboarding/OnboardingWizard.tsx:393-419`, `apps/portal/src/lib/onboarding.ts:52`, `apps/portal/src/lib/settings.ts:41`, `apps/portal/src/lib/prisma.ts:16-17`.
- **Risk:** A privacy officer at a clinic reads the page, asks "show me the AWS contract," and the answer is "we don't actually have one."
- **Options:** (a) Switch to "Hosted on Hostinger VPS in [datacenter region]" — honest but may not satisfy enterprise procurement. (b) Actually provision AWS ca-central-1 and us-east-1 deployments and update the docs to match. (c) Move the residency-claim UI behind a "we'll provision a tenant in your preferred region on request" gate, so the default copy doesn't overpromise.

### 2. Fix the Alberta/HIA matrix.
- **Files:** `apps/portal/src/app/security/page.tsx:116, 280, 299`, `apps/portal/src/app/page.tsx:58-60`, `apps/portal/src/lib/pricing.ts:50, 57, 65`, `apps/portal/src/app/contact/ContactForm.tsx:214`.
- **Risk:** The Alberta pilot is the active sales motion (2026-06-22). Every prospect who clicks through reads "PHIPA" and either doesn't notice (lost credibility in detail) or does notice (lost credibility in detail). PHIPA references should be HIA for the Alberta-targeted surface, and the `lib/pricing.ts` feature string should be region-aware or split per region.

### 3. Strip the internal-code references from the portal security page.
- **Files:** `apps/portal/src/app/security/page.tsx:11-14` (header comment with task IDs), 248-251 ("Implementation: src/audit_log.py...").
- **Risk:** Privacy officers ask "which file?" and get pointed at internal Python paths. Either move the implementation-reference sentences into a non-public doc, or replace with a public explanation ("the audit log uses SHA-256 hash chaining — full spec available under MNDA").

### 4. Rewrite the project root README and the apps/portal README.
- **Files:** `README.md:1-722` (entire file), `apps/portal/README.md` (entire file — currently create-next-app boilerplate).
- **Risk:** Anyone (new contributor, prospect's engineer, investor) who reads the README gets a 7-day-stale view of the project.
- **Target:** README should describe v12 + Alberta + billing portal live + 791 tests + 30-day pilot + the live FastAPI URL. apps/portal/README should describe the marketing-site routes (/, /pricing, /how-it-works, /security, /contact, /login, /portal/billing, /portal/onboarding) and the env-var contract for pricing/stripe/auth.

### 5. Write the Alberta-targeted pilot offer.
- **File:** new `docs/PILOT_OFFER_ALBERTA.md` (or revise `docs/PILOT_OFFER.md` in place).
- **Risk:** Today's PILOT_OFFER.md is jurisdiction-agnostic and doesn't mention HIA, AHCIP, or SOMB. Per `ALBERTA_STRATEGY_BRIEF.md:172`, the Alberta-targeted offer is "TBD — Not started." Outreach is being planned (per ALBERTA_PROSPECT_LIST.md) but the offer doc hasn't been written.

### 6. Add a /roi calculator (and an honest one).
- **File:** new `apps/portal/src/app/roi/page.tsx`.
- **Risk:** The sales pitch has no concrete "your clinic could recover $X/year" framing. A prospect who asks "what's the ROI?" gets a verbal answer or a custom spreadsheet, which is slower than a self-serve calculator. The calculator must include a false-positive assumption (e.g., "we assume 50% of flagged findings are real; tune the slider").

### 7. Create the BAA / HIA-affiliate agreement template.
- **File:** new `docs/legal/BAA_HIA_template.md` (or `.pdf`).
- **Risk:** Per `docs/ALBERTA_STRATEGY_BRIEF.md:172, 192`, this is TBD. The portal security page (`apps/portal/src/app/security/page.tsx:122-125, 388-393`) advertises a "draft inside two business days" turnaround but there's no template to send. Either build the template, or remove the promise from the marketing page.

### 8. Pick one hash-chain module and delete the other.
- **Files:** `src/audit_log.py` and `src/ai_billing_audit/audit_actions.py`. Per `AUDIT_CODE_QUALITY.md:148` this is the top recommendation in that audit too. The portal's security page references `src/audit_log.py` (line 248) but the actual wired code is `audit_actions.py` (8 call sites in `src/api.py` per `AUDIT_CODE_QUALITY.md:135`).
- **Risk:** A bug fix in one module doesn't reach the live system if the live system uses the other.

### 9. Add /legal/privacy and /legal/terms pages (or commission them).
- **Risk:** No privacy policy or terms on the marketing site is unusual enough that a procurement officer will flag it during the BAA conversation. PIPEDA requires an "openness" principle (which means publishing what you do with data); HIA and HIPAA require specific data-handling commitments.

### 10. Name a DPO / Privacy Officer and put the name + email in the footer of every page.
- **Risk:** The portal has `legal@ai-billing-audit.ashbi.ca` (legal alias) and `hello@...` (hello alias) but no named human. PIPEDA requires an accountable person for privacy inquiries; HIA requires a designated "custodian." Without a name, the marketing looks under-prepared.

### Bonus (not in the top 10)
- The `docs/QA_RESEARCH_*.md` cluster (8 files, all Jun 17) and `docs/CODE_REVIEW_*.md` cluster (8 files, all Jun 16) are historical snapshots that could mislead a reader who hasn't tracked the prompt versioning. Either archive to `docs/archive/2026-06-16-17/` or annotate each with a "superseded by" footer.
- The `contact/page.tsx:43` placeholder `sales@example.com` should be replaced with the real contact email before the marketing portal is deployed.
- The internal vs external doc boundary for `docs/AHCIP_GOLD_AUDIT.md` and `docs/AHCIP_RULE_REFERENCE.md` should be made explicit (e.g., a "DRAFT — internal only" banner) since both are referenced as source-of-truth in the Alberta strategy brief but contain agent commentary a clinic prospect shouldn't see.

---

## Appendix: Audit Method

- Read `apps/portal/src/app/**/page.tsx` and `apps/portal/src/app/**/*.{tsx,ts}` for all marketing claims.
- Read `docs/PILOT_OFFER.md`, `docs/ONE_PAGER_WHAT_WE_DO.md`, `docs/SALES_DEMO.md`, `docs/ALBERTA_STRATEGY_BRIEF.md`, `docs/ALBERTA_PROSPECT_LIST.md`, `docs/AHCIP_GOLD_AUDIT.md`, `docs/AHCIP_RULE_REFERENCE.md`, `docs/CANADA_BILLING_CROSSREF.md`, `docs/iterATION_LOG.md`, `docs/RUNBOOK.md`, `docs/AUDIT_CODE_QUALITY.md`, `docs/AUDIT_DEPLOY_OPS.md`, `docs/daily_report_2026-06-23.md`.
- Cross-referenced `README.md` (project root), `apps/portal/README.md`, confirmed no `src/README.md`.
- Grepped `/docs/` and `apps/portal/src/` for: PHIPA, HIA, HIPAA, PIPEDA, AIDA, AWS, ca-central-1, us-east-1, Hostinger, F1, 0.733, 85%, multi-market, Mexico, Colombia, ROI, roi, 5-minute, 10-minute, 30-day, real-time, self-improving, AI-powered, Hermes, subagent, Maton, appeal_letter, denial_risk, doctor_email, audit_actions, audit_log, BAA, HIA agreement, affiliate agreement, data agreement, retention, 7-year, 6-year, v0, v11, v12, MANIFEST, 5 conversion-blocking.
- Verified file existence and exact line numbers for every claim cited above.
- No source code, docs, marketing copy, or deployed state was modified. apps/portal not deployed. Live URL not touched.
- 20-minute budget observed.

---

*End of report. Approximately 4,400 words. File ready for review.*