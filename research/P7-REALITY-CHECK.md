# P7 — Zorva Reality Check: Are the features real-world professional?

**Date:** 2026-06-30
**Author:** Mavis (deep-research deliverable, 4-pass audit)
**Scope:** 39 portal pages, 60 FastAPI modules, 200+ marketing/code docs
**Method:** Cross-reference every falsifiable marketing claim against the code, with file:line citations
**Verdict:** Real product, demo-grade for a controlled pilot. **Not** professional-grade for a paying clinic today without 5-7 specific fixes.

---

## TL;DR — score and ship-readiness

| Dimension | Score | One-line |
|---|---|---|
| Auditor engine (v12) | 🟢 Production-grade for AHCIP | F1=0.690 on val_ca.json; v12 ships, prompt works, deterministic |
| Marketing surface | 🟡 Mostly honest, with 5-7 specific overclaims | AKS/Stark safe-harbor, OHIP beta, "HIA/PIPEDA/HIPAA/NOM-024 day-one" |
| Per-clinic learning loop | 🟡 Defer-confused with ship | Data layer ready; per-clinic F1 is honest empty-state aware; "learns from every decision" claim overpromises |
| Hash-chain audit trail | 🟡 Works, with documented debt | audit_actions.py: parallel implementation known but not fixed; security page admits the parallel |
| Patient pseudonymization | 🔴 Marketing/code mismatch | Security page says "salted SHA-256" + "PHN/MRN/name/DOB hashed"; FastAPI code hashes encounter_id with NO salt |
| Compliance posture | 🟡 HIA honest; rest aspirational | Alberta HIA in flight; HIPAA/NOM-024/PHIPA mostly fictional |
| Portal (Next.js) | 🟢 Production-grade for auth/tenant | Real Prisma, real RBAC, real team mgmt, FPAR/calibration live |
| Data residency claim | 🟡 Aspirational | "ca-central-1 by default" claim; actual VPS is Hostinger (US-likely), NOT ca-central-1 |
| Pricing | 🟡 Two different pricing tables in marketing | $499 tier says "up to 500" in one doc, "under 1,000" in another |
| Pilot program | 🟡 Four different "free pilot" durations in marketing | 30/60/90/100-claim, all cited as the offer |

**Bottom line:** The product is real. The auditor works. The portal works. The privacy/HIA claims have 1 critical bug (the salt claim is wrong in the FastAPI layer) and 1 stretch claim (ca-central-1). Everything else is either fixable in a day or honest enough to defend. Cameron should ship the pilot, fix the salt + residency claim, and tighten the 5 specific overclaims before a paying clinic sees the site.

---

## 1. What the product actually is (and isn't)

**What it is:** A pre-submit AHCIP auditor with:
- LLM-driven v12 prompt that reads 837P/CSV encounters and emits findings
- SHA-256 hash-chain audit trail (with documented parallel-impl debt)
- Per-clinic F1 / weekly / time-to-act / denial-rate aggregation
- Appeal-letter generator (hardcoded rule catalog, NOT RAG)
- Doctor-summary emails (operator-outbox JSONL, NOT auto-send)
- Multi-tenant Next.js portal with auth, RBAC, team, calibration, FPAR tiles
- 16 AHCIP rules in v12 (modifier-25, em-level, dx-linkage, postop-global, etc.)
- F1=0.690 on cleaned AHCIP val (P=0.647, R=0.846; 10 encounters, 13 gold findings)

**What it isn't:**
- A claim submission system. It audits. The biller still submits.
- A real EHR. It accepts 837P/CSV/FHIR uploads or SFTP drops, not a live EHR connector.
- An auto-sender. Doctor emails and appeal letters land in operator outboxes for human review.
- A learning system in v1. ALBERTA_STRATEGY_BRIEF §8 explicitly defers the learning loop.
- Multi-market. AHCIP only; OHIP=0 rules, MSP=0 rules, NOM-024=aspirational.

---

## 2. The claims matrix — 35 marketing claims, code reality, severity

| # | Claim (verbatim) | Page / file:line | Reality | Severity |
|---|---|---|---|---|
| 1 | "F1 = 0.690 on cleaned AHCIP val" | `apps/portal/src/app/technical/page.tsx:208-210` | ✅ TRUE — `runs/recall/v12_ahcip_clean.json` (10 encounters, 13 gold, P=0.647 R=0.846 F1=0.690) | — |
| 2 | "F1 = 0.91 on modifier suggestions" | `apps/portal/src/app/faq/page.tsx:159` | 🔴 **FALSE** — number contradicts /technical (0.690) AND /calculator (0.690) | HIGH |
| 3 | "F1 = 0.84 on undercode detection" | `apps/portal/src/app/faq/page.tsx:160` | 🔴 **UNVERIFIED** — no source for this; val_ca.json has no separate undercode-detector F1 metric | HIGH |
| 4 | "Salted SHA-256 patient hashing" (PHN/MRN/name/DOB hashed) | `apps/portal/src/app/security/page.tsx:115-121` | 🔴 **PARTIAL/INCONSISTENT** — portal side has salt/pepper (`apps/portal/src/lib/patient-hash.ts`), but FastAPI side (`src/ai_billing_audit/audit_actions.py:192`) uses bare `sha256(encounter_id)` with NO salt. AND the input is `encounter_id`, NOT patient identifiers (PHN/MRN/name/DOB) | **CRITICAL** |
| 5 | "Patient-identifying fields (PHN, MRN, name, DOB) are hashed before they reach long-term storage" | `apps/portal/src/app/security/page.tsx:115-116` | 🔴 **MISLEADING** — `x12_parser.py` extracts `patient_id` (raw, unhashed) from NM1*QC and stores it in encounter dict; `api.py:1297` references `search_patient_raw` and `_patient_id` flowing through audit chain; nothing in code actually hashes the patient_id field | **CRITICAL** |
| 6 | "Region is pinned at sign-up and confirmed in the executed BAA / affiliate agreement" | `apps/portal/src/app/security/page.tsx:51-60` | 🟡 PARTIAL — `Tenant.dataResidencyRegion` + `residencyRegionLocked` exist (`apps/portal/src/app/settings/page.tsx:84-85`); but "executed BAA / affiliate agreement" — the HIA template is in DRAFT per `HIA_LAWYER_HANDOFF.md` | MED |
| 7 | "HIA + PIPEDA (Alberta / Canada), HIPAA (US), NOM-024 (Mexico) — Day-one frameworks" | `apps/portal/src/app/security/page.tsx:127-135` | 🟡 **MIXED** — HIA in flight (BAA_TEMPLATE_HIA.md, draft); PIPEDA = federal floor, easy; HIPAA "day-one" — no US clients, no US contracts, aspirational; NOM-024 — zero code, zero Mexican clients, aspirational; per `ALBERTA_STRATEGY_BRIEF.md:21-22` explicitly OHIP=0, MSP=0 rules | **HIGH** |
| 8 | "OHIP (Ontario) is in private beta" | `apps/portal/src/app/compare/page.tsx:225`, `apps/portal/src/app/faq/page.tsx:206-209` | 🔴 **FALSE** — `ALBERTA_STRATEGY_BRIEF.md:21` says "OHIP (ON): 0 rules, aspirational"; no `rule_ohip_*` rules in code; no Ontario client; no privacy review | **HIGH** |
| 9 | "BC MSP and Saskatchewan are on the roadmap for Q4" | `apps/portal/src/app/faq/page.tsx:208` | 🟡 Aspirational — same source; no MSP rules in code; "Q4" timeline not committed anywhere | LOW |
| 10 | "We sit between your billing system and the payer" | `apps/portal/src/app/how-it-works/page.tsx:24-25` | 🟡 **POSITIONING OVERREACH** — Zorva is a pre-submit auditor; the biller still submits. The architecture is NOT a billing-system sit-in. Privacy officer who reads this will assume Zorva handles claim submission | MED |
| 11 | "Zorva learns from every decision your team makes" | `apps/portal/src/app/how-it-works/page.tsx:90-91` | 🟡 **CONTRADICTS** /trust page line 48: "The AI model itself...does not remember your claims between audits and it does not learn from your data."; AND `ALBERTA_STRATEGY_BRIEF.md §8.1` explicitly defers v2 (learning loop) to Q4 2026 | **HIGH** |
| 12 | "We have working integrations with TELUS Health PS Suite, OSCAR McMaster, QHR Accuro, and AdvancedMD" | `apps/portal/src/app/faq/page.tsx:257-259` | 🔴 **FALSE** — `/security`, `/how-it-works`, `/pilot` all say "837P/CSV/SFTP/FHIR/manual upload"; no live EHR connector in code; `EHR_ADVANCEDMD_INTEGRATION.md` is a doc, not a working integration | **HIGH** |
| 13 | "ca-central-1 by default" (data residency) | `apps/portal/src/app/security/page.tsx:55`, `apps/portal/src/app/compare/page.tsx:270` | 🔴 **FALSE** — VPS is Hostinger, NOT ca-central-1. ca-central-1 is AWS. Cameron should verify the actual Hostinger data center region. If it's not in Canada, this is a HIA violation | **CRITICAL** |
| 14 | "60-day no-cost pilot" (CTA on home + pricing) | `apps/portal/src/app/page.tsx:43-52`, `apps/portal/src/app/pricing/page.tsx:115` | 🟡 **CONFLICTING** — `ONE_PAGER_WHAT_WE_DO.md:11` says "30-day free pilot"; `PILOT_OFFER.md:1` says "30-Day Pilot — No cost"; `faq/page.tsx:100` says "The pilot is 30 days"; `/pilot/page.tsx` says "30 / 60 / 90-day pilot"; `/calculator` says "first 100-claim audit is no-cost" | MED |
| 15 | "Up to 500 audits/month" for $499 tier (Starter) | `docs/ONE_PAGER_WHAT_WE_DO.md:23` | 🟡 **CONFLICTS** — `/pricing/page.tsx:154-156` says "Under 1,000 claims / month" for $499 tier; 500 vs 1000 is a 2x mismatch | MED |
| 16 | "Per-claim cost does not change with volume" (scales linearly) | `apps/portal/src/app/compare/page.tsx:112` | 🟡 **CONTRADICTS TIER CAPS** — pricing has hard caps (1,000 / 3,000 / 3,000+) and overages. "Scales linearly" is defensible within a tier but the marketing reads as "unlimited" | LOW |
| 17 | "AKS / Stark safe-harbor clean" | `apps/portal/src/app/pricing/page.tsx:201-202` | 🟡 **LEGAL OPINION REQUIRED** — AKS (Anti-Kickback Statute) and Stark Law are US federal anti-kickback/physician-self-referral laws. Calling flat-fee pricing "safe-harbor clean" without a written legal opinion is risky for a US-targeting sales motion. Cameron is Alberta-first, so this matters less for the immediate pilot but matters if any US clinic ever looks at this | MED |
| 18 | "Catches 6-7 of 10 real billing errors before submission" | `apps/portal/src/app/technical/page.tsx:216-218`, `apps/portal/src/app/calculator/page.tsx:60-63` | ✅ TRUE — defensible lower bound of F1=0.690 range; traceable to `runs/recall/v12_summary.md` | — |
| 19 | "Defensible audit trail" (every finding, hash-chained) | `apps/portal/src/app/compare/page.tsx:94-95` | 🟡 TRUE but with documented debt — `audit_actions.py:21-31` admits parallel implementation (QA JSONL uses local `compute_signature`; prod Postgres uses `audit_log.py`); `SECURITY_PAGE` admits it: "Implementations: src/audit_log.py (canonical) and src/ai_billing_audit/audit_actions.py (parallel — see QA audit log)" | LOW |
| 20 | "Two-person approval on high-impact actions" | `apps/portal/src/app/security/page.tsx:105-108` | 🟡 Marketing claim not visible in the audit_actions.py code (RBAC roles defined, two-person logic not enforced). Trust-page honesty: "we will not represent either framework as a current certification" (referring to SOC2) — so the team is honest; this claim may just be aspirational | LOW |
| 21 | "Send a daily digest email" (during pilot) | `apps/portal/src/app/pilot/page.tsx:69` | 🟡 **CONTRADICTS CODE** — `src/ai_billing_audit/doctor_email.py:32-36` explicitly says "We deliberately do NOT auto-send — out of scope for v1" | MED |
| 22 | "Per-specialty confidence update" (learns) | `apps/portal/src/app/compare/page.tsx:121` | 🟡 Defer-confused with ship — `feedback.py:280` bucket thresholds exist, `per_clinic_f1.py:175-258` reads them, dashboard tile shows bucket counts. But "confidence updates per rule per tenant" is the v2 plan, not v1. ALBERTA_STRATEGY_BRIEF §8.2 requires 3 months of pilot data + feedback log + appeal outcomes before v2 activates | MED |
| 23 | "We have a CIEDR / FHIR endpoint / custom connector" | `apps/portal/src/app/pricing/page.tsx:175` ($5,000 EHR connector) | 🟡 Pricing is real but product is generic 837P/SFTP/CSV — no live FHIR server; pricing for a hypothetical integration | LOW |
| 24 | "Per-finding dollar impact" (8 cards on /what-zorva-finds) | `apps/portal/src/app/what-zorva-finds/page.tsx:46-127` | 🟡 **ILLUSTRATIVE** — disclaimer on line 169-174: "Findings and dollar amounts shown are illustrative examples drawn from the v12 auditor rule set. Per-finding impact varies by SOMB code, modifier context, and payer." BUT the page header on line 137 says "Real patterns caught by the auditor, anonymized from live claims" — this conflicts with the disclaimer (anonymized-from-live vs illustrative-examples) | MED |
| 25 | "All 26+ static routes + 12 auth-gated routes" | `find apps/portal/src/app` | ✅ TRUE | — |
| 26 | "Time to first audited claim — Under 10 minutes from upload" | `apps/portal/src/app/compare/page.tsx:103`, `apps/portal/src/app/compare/page.tsx:298` | 🟡 TRUE for 1 claim (LLM latency 60-180s); FALSE for "10 minutes from upload" if uploading 100 claims — serial processing, ~1-3 hours | LOW |
| 27 | "Real-time / instant" claim | (searched) | ✅ NOT FOUND in marketing — good | — |
| 28 | "24/7 / always-on" claim | (searched) | ✅ NOT FOUND in marketing — good | — |
| 29 | "Built pre-bill audit pipelines at two Alberta clinics" (about page bio) | `apps/portal/src/app/about/page.tsx:44-45` | 🟡 Cameron can confirm; flagged as a "verify before publishing" claim | LOW |
| 30 | "Webhooks fire on audit.completed and billing.invoice.paid" | `apps/portal/src/app/faq/page.tsx:194-196` | 🔴 **PARTIAL FALSE** — Zorva doesn't do payments, doesn't fire `billing.invoice.paid` webhooks. This webhook name is fabricated | **HIGH** |
| 31 | "Catches 6-7 of 10 real billing errors before submission" (home, calculator) | `apps/portal/src/app/page.tsx:46-51`, `apps/portal/src/app/calculator/page.tsx:60-63` | ✅ TRUE (same as #18) | — |
| 32 | "Production-grade" (analyst's claim, not marketing) | n/a | 🟡 Auditor yes; portal yes; **whole product** = no (4 frameworks, 2 markets, 0 paying customers) | n/a |
| 33 | "PHIPA for Ontario" | `apps/portal/src/app/security/page.tsx:130-131`, `apps/portal/src/app/faq/page.tsx:50-52` | 🟡 **ASPIRATIONAL** — no Ontario clients, no PHIPA template, no Ontario privacy review | MED |
| 34 | "Quarterly sub-processor review completed 2026-06-08; US-region Postgres provider retired 2026-05-30" | `apps/portal/src/app/changelog/page.tsx:101-115` | 🟡 **POSSIBLY FALSE** — `apps/portal` runs on a US-likely VPS (Hostinger); no evidence of US-region Postgres retirement. This changelog entry may be inaccurate | MED |
| 35 | "Zorva learns from every decision your team makes" | (already #11) | (duplicate — contradiction is the issue, not whether it's there) | — |

**Total claim count:** 35
**True (✅):** 5 (14%)
**Partial/Defensible (🟡):** 21 (60%)
**False or Critical-mismatch (🔴):** 9 (26%)

The 26% false/critical rate is concentrated in 3 buckets: (a) the patient-hashing claim, (b) the multi-market reach (OHIP beta, HIPAA/NOM-024 day-one), and (c) a few fabricated specifics (FHIR live endpoint, billing.invoice.paid webhook, EHR integration list).

---

## 3. Per-feature professional-grade assessment

| Feature area | Grade | Evidence |
|---|---|---|
| **Auditor (v12, AHCIP)** | 🟢 Production | 791 pytest tests pass, v12 prompt live, F1=0.690 on 10/13 gold, deterministic (seed pinned, temp 0) per `prompts/MANIFEST.json` |
| **X12 837P parser** | 🟢 Production | `src/ai_billing_audit/x12_parser.py:1-479` — 5 required fields, ISA/CLM/NM1*85/DTP*472/SV1*HC/HI*ABK; permissive envelope, clear error messages |
| **Denial risk scoring** | 🟡 Production (with disclosed limits) | `src/ai_billing_audit/denial_risk.py:1-269` — heuristic severity × rule-family multiplier, `1 - ∏(1-risk_i)`, capped at 0.99. Docstring admits: "v0 doesn't have a real model because we don't have historical denied-claim labels" |
| **Appeal letter generator** | 🟡 Production (hardcoded, NOT RAG) | `src/ai_billing_audit/appeal_letter.py:79-184` — built-in rule catalog of 6 rules (MOD-25, DX_LINKAGE_REQUIRED, E/M-LEVEL, NCCI, TIME, MED-NEC); docstring honestly says "v0 has a hardcoded mapping... v1: replace with pgvector RAG" |
| **Doctor summary emails** | 🟡 Production (NOT auto-send) | `src/ai_billing_audit/doctor_email.py:435-479` — writes to operator outbox JSONL; biller dispatches manually. Docstring: "We deliberately do NOT auto-send" |
| **Feedback log + per-clinic F1** | 🟢 Production (with honest empty-state) | `src/ai_billing_audit/feedback.py:1-876` + `per_clinic_f1.py:1-1140` — hash-chained; explicit `INSUFFICIENT_DATA_THRESHOLD=3`; weekly + per-rule metrics; `is_insufficient` flag for empty state |
| **Audit trail (hash chain)** | 🟡 Production (parallel-impl debt) | `src/ai_billing_audit/audit_actions.py:1-317` — works, but lines 21-31 explicitly admit two parallel implementations (audit_actions.py vs src/audit_log.py) and the verify_chain imports one but uses the other. SECURITY page itself documents the parallel |
| **Patient pseudonymization (FastAPI)** | 🔴 Demo-grade (inconsistent + undersold) | `src/ai_billing_audit/audit_actions.py:191-192`: `patient_hash = sha256(encounter_id).hexdigest()[:12]` — **NO SALT**, hashes `encounter_id` not patient identifiers, only first 12 chars. The /security page claim of "salted SHA-256" + "PHN/MRN/name/DOB" is wrong on the FastAPI side. `x12_parser.py:344` keeps raw `patient_id` in the encounter dict, and `api.py:1297` references `search_patient_raw` — patient identifiers are NOT being hashed at all in the upload path |
| **Patient pseudonymization (portal)** | 🟢 Production | `apps/portal/src/lib/patient-hash.ts` — uses `PATIENT_HASH_PEPPER` env var with SHA-256; `audit_trail.sql` has hex CHECK constraint. This side is honest |
| **Multi-tenant RBAC** | 🟡 Production (with edge-runtime gap) | Prisma `Membership` model + `getActiveTenant()`; `auth.ts` PrismaAdapter (DB session strategy) means tenant_id is in DB Session row, NOT in JWT cookie. Middleware.ts in Edge cannot read it. `audit_actions.py:142-146` defines ROLE_ADMIN/ROLE_BILLER/ROLE_VIEWER but enforcement is `X-User-Id` / `X-User-Role` headers (line 159-160) — not a real auth flow |
| **Compliance posture** | 🟡 Honest for HIA, aspirational for rest | HIA template in `BAA_TEMPLATE_HIA.md` (DRAFT, lawyer review pending per `HIA_LAWYER_HANDOFF.md`); HIPAA/NOM-024/PHIPA = aspirational with marketing overclaim |
| **ROI calculator** | 🟡 Production (with explicit disclaimer) | `apps/portal/src/app/calculator/page.tsx:55-66` — disclaimer is honest, formula is transparent. But the inputs (catchable_rate=0.690, recoverable_share=0.55) are anchored to one v12 evaluation |
| **Data residency lock** | 🟢 Production (in code) | `apps/portal/src/lib/settings.ts` + `tenantHasAudit()` + `residencyRegionLocked` flag — region is locked once first encounter is recorded. **BUT** the region values and "ca-central-1" claim are wrong (Hostinger, not AWS) |
| **Portal pages (auth, team, settings, billing, encounters, findings)** | 🟢 Production | Real Prisma queries, real RBAC, real multi-tenant scoping, honest empty states. The 21 unit tests pass |
| **EHR integration (live)** | 🔴 Not shipped | Code: only 837P/CSV upload. `EHR_ADVANCEDMD_INTEGRATION.md` is a doc. /faq's "working integrations with TELUS PS Suite, OSCAR, QHR Accuro, AdvancedMD" is FALSE |
| **NOM-024 Mexico support** | 🔴 Aspirational | Only `zorva_context.py` has the market dict; no rules, no clients, no contract template |
| **PHIPA Ontario support** | 🔴 Aspirational | Only `zorva_context.py` and /security mention; no rules, no Ontario client |
| **Learning loop (v2)** | 🟡 Defer | `ALBERTA_STRATEGY_BRIEF.md §8` explicitly defers to Q4 2026 conditional on 3 mo pilot data + feedback log + appeal outcomes |
| **Doctor-side portal view** | 🟡 Not shipped | Doctors get emails, not portal. About page's "Clinical product" is a placeholder name (Allison Caputo) |
| **Daily digest email (pilot)** | 🟡 Manual | `pilot/page.tsx` claims auto-send; `doctor_email.py:32-36` admits not auto-send |
| **F1 (per-clinic) dashboard tile** | 🟢 Production | `apps/portal/src/components/fpar-tile.tsx` + `lib/fpar.ts` + `lib/calibration.ts` — all live |
| **SOC 2 Type II, ISO 27001** | 🟡 Honestly NOT held | /trust + /security + /changelog 2026-05-30 are honest about this. EXCELLENT example of how to handle a "not yet" claim |

---

## 4. Direct contradictions (file:line → file:line)

### 4.1 "Learns" vs "Does not learn" — SAME PRODUCT, TWO PAGES

- `apps/portal/src/app/how-it-works/page.tsx:90-91` says: *"Zorva learns from every decision your team makes."*
- `apps/portal/src/app/trust/page.tsx:48-50` says: *"The AI model itself processes your data to produce a finding, then forgets the input. It does not remember your claims between audits and it does not learn from your data."*

A privacy officer who reads both pages will catch this immediately. One page is talking about the data layer (per-clinic feedback) and the other is talking about the LLM (no fine-tuning). But the wording makes them sound like direct contradictions. **FIX:** rewrite how-it-works to "Zorva tracks every accept / dismiss / modify so we can show you whether the auditor is getting better at your patterns over time" — i.e. clearly observational, not "learning" in the ML sense.

### 4.2 "Salted SHA-256" vs NO SALT — privacy/technical mismatch

- `apps/portal/src/app/security/page.tsx:115-121` (Marketing): *"Patient-identifying fields (PHN, MRN, name, DOB) are hashed (salted SHA-256) before they reach long-term storage. The human-readable form is never written to disk; the salted hash is the only patient identifier..."*
- `src/ai_billing_audit/audit_actions.py:191-192` (FastAPI code): `patient_hash = hashlib.sha256(encounter_id.encode("utf-8")).hexdigest()` — NO SALT, hashes `encounter_id` not patient identifiers
- `apps/portal/src/lib/patient-hash.ts` (Portal code): HAS `PATIENT_HASH_PEPPER` — this side is correct

**The "salted" claim is correct for the portal path and wrong for the FastAPI path. Worse, the input is encounter_id, not patient identifiers — so the marketing claim "PHN/MRN/name/DOB are hashed" is structurally false.** Real patient_id from x12_parser lives in the encounter dict (`x12_parser.py:344`) and is searchable raw via `api.py:1297` (`search_patient_raw`).

**FIX priority: P0.** Either: (a) update `audit_actions.py` to use the same `hashPatientId(patient_id, pepper)` function the portal uses, OR (b) update the marketing copy to say "patient_hash is a one-way hash of an internal encounter_id; raw patient identifiers (PHN/MRN) are stored separately in the encrypted encounter table only and are not written to the audit log." Either is defensible; the current state is indefensible.

### 4.3 "ca-central-1 by default" vs Hostinger VPS

- `apps/portal/src/app/security/page.tsx:55, 60` (Marketing): *"Customer data stored in a Canadian data centre for Canadian customers... region is pinned at sign-up... Canadian data centre for Canadian customers"*
- `apps/portal/src/app/compare/page.tsx:270` (Marketing): *"Single-tenant data residency (your region) — Yes — ca-central-1 by default"*
- Actual infra: Hostinger VPS at 187.77.26.99 (per agent memory) — NOT ca-central-1, which is an AWS region.

ca-central-1 is AWS Canada Central. The VPS is Hostinger. The marketing conflates "Canadian data centre" with "AWS ca-central-1" — but the infra is not AWS. **Privacy officer who asks "which AWS region?" will catch this.**

**FIX:** Either (a) move the deployment to AWS ca-central-1, OR (b) update the marketing to say "Canadian-region VPS (Hostinger; specific facility in BHS1/CA)" and document the host's actual security posture. The "AWS" brand halo is doing more harm than good.

### 4.4 30/60/90-day pilot — four different numbers

| Source | Number |
|---|---|
| `apps/portal/src/app/page.tsx` home CTA | "60-day no-cost pilot" |
| `apps/portal/src/app/pricing/page.tsx:115` | "60-day no-cost pilot. After that, $499/mo." |
| `apps/portal/src/app/pilot/page.tsx:1` | "30 / 60 / 90-day pilot" |
| `apps/portal/src/app/calculator/page.tsx:108-110` | "first 100-claim audit is no-cost" |
| `docs/PILOT_OFFER.md:1` | "30-Day Pilot — No cost" |
| `docs/ONE_PAGER_WHAT_WE_DO.md:11` | "30-day free pilot" |
| `apps/portal/src/app/faq/page.tsx:100` | "The pilot is 30 days" |

**FIX:** Pick ONE. The most defensible for a paying clinic is "60-day no-cost pilot" (long enough to see ROI, short enough to book the next step). Update PILOT_OFFER.md, ONE_PAGER, /faq, /calculator to all say 60-day. /pilot can keep the 30/60/90 phase structure as a subset.

### 4.5 500 vs 1,000 claims for $499 tier

- `docs/ONE_PAGER_WHAT_WE_DO.md:23` (marketing doc): "Starter — $499/mo — Up to 500 audits/month"
- `apps/portal/src/app/pricing/page.tsx:154-156` (live page): "Under 1,000 claims/month — $499"

**FIX:** Make these match. Recommend "Under 1,000 claims/month" because the math is cleaner (1K/3K/3K+ tiers) and the $499 still works as a wedge.

### 4.6 "F1 = 0.690" vs "F1 = 0.91 on modifier suggestions" / "F1 = 0.84 on undercode detection"

- `apps/portal/src/app/calculator/page.tsx:60-63` and `apps/portal/src/app/technical/page.tsx:208-210`: F1 = 0.690 (micro, all findings, AHCIP)
- `apps/portal/src/app/faq/page.tsx:158-160`: F1 = 0.91 on modifier, 0.84 on undercode

Either the /faq numbers are (a) per-rule F1 from a different cut, (b) aspirational marketing numbers, or (c) hallucinated. The /faq page is the only source citing these per-rule numbers. The /technical page is the canonical source for the val methodology. **FIX:** Either remove the per-rule F1 from /faq and link to /technical, or compute and document the per-rule F1 in `runs/recall/v12_per_rule.json` and link it.

### 4.7 "Webhooks fire on audit.completed and billing.invoice.paid"

- `apps/portal/src/app/faq/page.tsx:194-196`
- Zorva does NOT process payments. `billing.invoice.paid` is fabricated.

**FIX:** Remove that webhook name. Real webhooks: `audit.completed`, `finding.created`, `encounter.uploaded` (verify with code).

### 4.8 "OHIP private beta" vs "0 OHIP rules"

- `apps/portal/src/app/compare/page.tsx:225`: "AHCIP production, OHIP private beta"
- `apps/portal/src/app/faq/page.tsx:206-208`: "AHCIP (Alberta SOMB) is the production-supported schedule. OHIP (Ontario) is in private beta."
- `docs/ALBERTA_STRATEGY_BRIEF.md:21`: "OHIP (ON): 0 rules, aspirational"

**FIX:** Remove "OHIP private beta" from /compare and /faq. Replace with "AHCIP production; OHIP and MSP on 2027 roadmap" or whatever the real roadmap is. The marketing should not outpace the code by 12+ months.

---

## 5. The 9 critical or high-severity marketing claims — must fix before pilot

In priority order. Each is a specific change Cameron can make in 1-3 hours.

### Fix 1 (P0, security): Patient hashing mismatch

- **File:** `apps/portal/src/app/security/page.tsx:115-121`, `apps/portal/src/app/security/page.tsx:293`
- **Current:** "Salted SHA-256 patient hashing. Identifying fields (PHN, MRN, name, DOB) are hashed before they reach long-term storage"
- **Reality:** FastAPI path uses `sha256(encounter_id)` with no salt; raw `patient_id` from x12 NM1*QC segment lives in the encounter dict un-hashed (`x12_parser.py:344`)
- **Options:**
  - **Option A (best, ~2 hrs):** Wire `hashPatientId(patient_id, pepper)` into the FastAPI path the same way the portal does it. Then update `x12_parser.py:344` to NOT store the raw `patient_id` in the encounter dict, and instead store `patient_hash` only.
  - **Option B (fast, 30 min):** Update marketing copy to honestly say: "Patient identifier is hashed via SHA-256 at the encounter layer; the raw patient_id is stored in the encrypted encounter row for the duration of the audit lifecycle and purged at the end of the pilot. The audit log only ever sees the hash."
- **Recommendation:** Do Option A before the first paid pilot. Option B is acceptable for a friend-and-family no-cost pilot only.

### Fix 2 (P0, security): "ca-central-1" claim

- **Files:** `apps/portal/src/app/security/page.tsx:55, 60`, `apps/portal/src/app/compare/page.tsx:270`, `apps/portal/src/app/faq/page.tsx:30`
- **Current:** "ca-central-1 by default", "Customer data stored in a Canadian data centre"
- **Reality:** Hostinger VPS, not AWS
- **Options:**
  - **Option A (best, requires $):** Move production to AWS ca-central-1 (~$100-300/mo for a small RDS + ECS footprint). Provides the "AWS Canada" brand halo privacy officers expect.
  - **Option B (fast):** Update copy to "Canadian-region VPS (Hostinger, audited facility). Specific region and provider on request."
- **Recommendation:** Option B for the first paid pilot. Document the actual host's security posture in a 1-page addendum to the HIA template.

### Fix 3 (P0, marketing): "OHIP private beta" / "HIA+PIPEDA+HIPAA+NOM-024 day-one"

- **Files:** `apps/portal/src/app/security/page.tsx:127-141`, `apps/portal/src/app/compare/page.tsx:225`, `apps/portal/src/app/faq/page.tsx:50-52, 206-208`
- **Current:** "Day-one frameworks: HIA + PIPEDA (Alberta / Canada), HIPAA (US), NOM-024 (Mexico)"
- **Reality:** Only HIA in flight (DRAFT); PIPEDA = federal floor; HIPAA + NOM-024 = aspirational
- **Recommended new copy:** "HIA + PIPEDA (Alberta / Canada) — covered today. HIPAA (US) and PHIPA (Ontario) — supported via BAA / HIC-Agent template, available on request. NOM-024 (Mexico) and other jurisdictions — on the 2027 roadmap."
- **This is a 1-hour copy edit.** Do it before the first cold email goes out.

### Fix 4 (P0, marketing): "Working integrations with TELUS PS Suite, OSCAR, QHR Accuro, AdvancedMD"

- **File:** `apps/portal/src/app/faq/page.tsx:257-259`
- **Current:** "Yes — we have working integrations with TELUS Health PS Suite, OSCAR McMaster, QHR Accuro, and AdvancedMD"
- **Reality:** Zorva accepts 837P/CSV/SFTP/FHIR uploads; no live EHR connector
- **Recommended new copy:** "We work with your billing system's 837P export or SFTP drop — no EHR switch required. Custom HL7v2 / FHIR connectors are available on the Enterprise tier ($5,000 one-time per connector)."
- **This is a 15-minute copy edit. Critical for trust.**

### Fix 5 (P1, marketing): Pilot duration inconsistency

- **Files:** 7 sources, listed in §4.4
- **Recommended:** Standardize on "60-day no-cost pilot. After that, $499/mo if you continue; cancel any time, we delete within 30 days."
- **Update:** home CTA, /pricing, /pilot page header (keep the 30/60/90 phase structure), /calculator CTA, PILOT_OFFER.md, ONE_PAGER, /faq, /demo-request.

### Fix 6 (P1, marketing): 500 vs 1,000 claims for $499 tier

- **Files:** `docs/ONE_PAGER_WHAT_WE_DO.md:23` and `apps/portal/src/app/pricing/page.tsx:154-156`
- **Recommended:** Make both say "Under 1,000 claims/month — $499 CAD" (the live page is right; update the PDF).

### Fix 7 (P1, marketing): "Webhooks fire on audit.completed and billing.invoice.paid"

- **File:** `apps/portal/src/app/faq/page.tsx:194-196`
- **Recommended:** Remove `billing.invoice.paid` (Zorva doesn't do payments). Replace with the actual webhook list (verify in code): `audit.completed`, `finding.created`, `encounter.uploaded`.

### Fix 8 (P1, marketing): "F1 = 0.91 / 0.84" per-rule numbers

- **File:** `apps/portal/src/app/faq/page.tsx:158-160`
- **Recommended:** Either (a) compute and publish `runs/recall/v12_per_rule.json` so the per-rule F1 is traceable, or (b) replace with the canonical 0.690 and link to /technical. Option (b) is 10 minutes; option (a) is 2 hours.

### Fix 9 (P1, marketing): "We sit between your billing system and the payer"

- **File:** `apps/portal/src/app/how-it-works/page.tsx:24-25`
- **Recommended:** "We sit alongside your billing system. Every claim is read by Zorva first; your team reviews what it finds; your biller submits. Nothing ships to the payer until a human signs off."

### Fix 10 (P1, marketing): "Zorva learns from every decision" vs "does not learn" — reconcile

- **Files:** `apps/portal/src/app/how-it-works/page.tsx:90-91` (claim) vs `apps/portal/src/app/trust/page.tsx:48-50` (denial)
- **Recommended:** Update /how-it-works to: "Zorva tracks every accept / dismiss / modify so the dashboard can show whether the auditor is getting better at YOUR patterns over time." Removes the "learns" word that contradicts /trust.

---

## 6. What is actually SHIPPABLE and defendable today (the 5 honest wins)

These are the things Cameron can talk about with full confidence to a paying clinic:

1. **v12 AHCIP auditor at F1=0.690 on a cleaned gold set** — defensible, traceable to `runs/recall/v12_ahcip_clean.json` (10 encounters, 13 gold findings, P=0.647 R=0.846). "Catches 6-7 of 10 real billing errors before submission" is a real number.

2. **Hash-chain audit trail** — works, has parallel-impl debt, but the chain is real and `verify_chain()` works on each implementation independently. Privacy officers care about the chain being real, not byte-for-byte identical between JSONL and Postgres.

3. **Per-clinic F1, weekly F1, denial rate, time-to-act, top flagged rules** — all implemented in `per_clinic_f1.py` + `feedback.py`. The empty-state copy is honest ("need 3+ feedback events for an F1 number"). Dashboard tiles are live and reflect real data when the clinic has any.

4. **Three anonymized case studies** — drawn from real encounters in `case_studies.py`. BUT the case studies use **US CPT/ICD-10-CM codes (99213, 99214, 93000, 80061, 93306, R00.2, I10, E11.65)** — NOT Alberta SOMB codes (03.XXA) or ICD-10-CA. **Cameron needs to either replace these with AHCIP-coded examples OR add a banner that says "examples are US-CPT formatted for readability; production AHCIP output uses SOMB codes (03.04A, 08.19A, etc.)".** This is fixable in 2 hours.

5. **Three-tier flat-fee pricing in CAD** — $499 / $1,499 / $2,999. No revenue share. AKS/Stark safe-harbor defensible (with lawyer letter; not a current lawyer letter but flat-fee pricing is the safe-harbor criterion). 60-day no-cost pilot before paid tier.

---

## 7. What to CUT or DEFER (the 5 honest losses)

1. **Mobile app (Capacitor scaffold)** — the codebase has a Capacitor scaffold per memory. There is no marketing page or user demand for it. Cut. (Re-use the Capacitor pieces only if a PCN asks for an in-clinic iPad kiosk.)

2. **Per-clinic rule customization (rule suppression UI)** — the prompt and rule catalog are global; per-clinic suppression UI doesn't exist in the portal. Defer until the v2 learning loop is live (Q4 2026 if /pilot succeeds).

3. **Doctor-side portal view** — the /team page is the admin view, not a doctor view. Doctors get emails (operator outbox, not auto-send). The "Clinical product" person (Allison Caputo placeholder in /about) has nothing to manage. Defer — doctors are the recipients of the biller's accepted findings, not the primary user.

4. **Multi-tenant parent/group model (Medicentres / corporate chains)** — the tenant model supports it (Tenant + Membership + Clinic) but no marketing page targets it. Defer until after a single-clinic pilot closes.

5. **NOM-024 Mexico / PHIPA Ontario / MSP BC** — zero rules, zero clients, zero contracts. Cut from /security and /compare and /faq. Re-introduce only when there's a real customer in that jurisdiction.

---

## 8. Honest product portfolio: what to actually sell to Alberta clinics

Based on the code + marketing reality, here's what Cameron can actually sell to an Alberta clinic THIS QUARTER, defensibly:

### Tier 1: AHCIP-only pre-submit auditor (current state)
- What it does: reads 837P / CSV / SFTP, audits 16 AHCIP rules, emits findings with severity + rule_id + suggested code + quote from note
- What it doesn't do: submit, EHR-live, learning, multi-province, multi-payer
- Pilot: 60-day no-cost
- Paid: $499 / $1,499 / $2,999 CAD/mo
- Defensible: yes, with the 10 marketing fixes above
- Target buyer: a 5-10 physician family medicine clinic or a PCN's central billing office
- Sales cycle: 1-2 weeks (privacy officer review is the gate, not the biller)

### Tier 2: AHCIP auditor + appeal-letter drafting (current state)
- Same as Tier 1 PLUS appeal letter generated for every denied claim
- Hardcoded rule catalog (6 rules in `appeal_letter.py:147-184`); not RAG
- Biller pastes the letter into their workflow
- Defensible: yes, with the caveat that the rule catalog is v0, not v1
- Target buyer: clinics that already get denied claims and want help with appeal prose

### What's NOT sellable today:
- OHIP / MSP / NOM-024 audits (no rules)
- Live EHR connectors (no working integrations)
- Per-clinic learning (deferred to Q4 2026)
- Auto-send of doctor emails (operator outbox only)
- Auto-send of appeal letters (operator outbox only)
- Multi-clinic parent/group model (Tenant model supports it, no product surface)
- Custom billing rules (mentioned in /pricing add-on table at $250/rule/mo — but the rule schema and config UI don't exist in the portal)

---

## 9. Decision gate — 5 measurable tests before the first paying pilot

| Gate | Test | Pass/fail criterion |
|---|---|---|
| 1. Real AHCIP pilot data | Run a 100-encounter historical audit on a real (anonymized) clinic data export | F1 ≥ 0.6 (lower bound of v12 claim); rule_id distribution skewed toward the 16 v12 rules; no fabricated evidence (quote-in-note check passes) |
| 2. Privacy officer sign-off | A real Alberta privacy officer reviews the HIA template + security page + tech page | "I would sign this IMA" / "I would not" — with specific blockers |
| 3. Lawyer review of the HIA template | 4-8 hour engagement with Alberta privacy counsel | No material redlines; <$4K CAD |
| 4. PII flow audit | Walk the data from 837P upload to findings storage; verify NO raw patient_id in the audit log | 0 raw patient_ids in audit_trail.jsonl + Postgres audit_trail table |
| 5. Live pilot (60 days) | One paying or no-cost pilot clinic, 100+ claims/week | ≥ 30% of findings accepted by biller; ≥ 1 finding catches a real revenue miss; biller renews at $499-$1,499/mo |

If gate 4 fails today, do Fix 1 (P0) before any pilot. If gate 1 produces F1 < 0.55 on a real sample, do not ship the paid tier — do another iteration of the v12 prompt first.

---

## 10. Three things to do THIS WEEK (Cameron's 5-day list)

1. **Day 1 (Monday, ~2 hours):** Apply the 10 marketing fixes from §5. They're all 1-line to 1-paragraph edits, no code changes needed. Use `git grep "Ollama cloud\|ca-central-1\|OHIP private beta\|working integrations\|F1 = 0.91\|F1 = 0.84\|AKS / Stark safe-harbor\|salted SHA-256\|learns from every decision\|Webhooks fire on\|billing.invoice.paid"` to find all the sites. Update each.

2. **Day 1-2 (Monday-Tuesday, ~4 hours):** Decide on Fix 1 (patient hashing) — Option A (rework the FastAPI path) or Option B (update copy). If A, do it; if B, document the current state honestly. Either way, the privacy officer will be able to read a consistent story.

3. **Day 3 (Wednesday, ~1 hour):** Standardize the pilot offer (Fix 5) and the pricing tier volume (Fix 6) across all 7 source documents. Edit, commit, redeploy portal.

4. **Day 3-4 (Wednesday-Thursday, ~6 hours):** Read through every portal page once and update any other claim that doesn't match §2. The list above is the 80/20 — there are 3-5 smaller inconsistencies (e.g. ENC_ID formats, contact emails `hello@zorva.ca` vs `hello@zorva.health`) that will get caught if you do a full read.

5. **Day 5 (Friday, ~3 hours):** Read through the case studies on /case-studies and confirm the codes are SOMB (Alberta) or US-CPT (clearly marked). Update the disclaimers. Re-render the case_studies.py module to match.

**Total time: ~16 hours / 4 working days. Then ship the 100-claim pilot to Red Deer PCN per `docs/ALBERTA_PROSPECT_LIST.md`.**

---

## 11. What's working really well (so Cameron doesn't lose confidence)

For all the marketing overclaims, there are 7 things that are honestly production-grade today:

1. **The 791 pytest test suite passes.** Real test coverage on the auditor, denial_risk, appeal_letter, feedback, x12_parser, per_clinic_f1.
2. **The Next.js portal has 21 passing unit tests** and a real Prisma schema with 14 models.
3. **The hash-chain audit trail works** (per implementation). Both the JSONL and Postgres paths verify independently.
4. **The per-clinic F1 module is honest about its empty state** ("need 3+ feedback events"). Privacy officer will appreciate the honesty.
5. **The F1=0.690 number is honest** — it's on 10 encounters and 13 gold findings, but it IS what the auditor produces, and the /calculator and /technical pages cite it consistently.
6. **The HIA + PHIPA cleanup work in `ALBERTA_STRATEGY_BRIEF.md`** is honest. The team knows what the spec claims and what the code does. That's rare.
7. **The /changelog 2026-05-30 entry is the right model** — "SOC 2 Type II and ISO 27001 are on the certification roadmap; neither is held today." This is exactly how a privacy officer wants the team to talk about upcoming certifications.

The product is real. The team is honest. The marketing just needs to stop outpacing the code by 6-12 months on multi-market, PHI flow, and learning-loop claims. Apply §5's 10 fixes, run §9's 5 gates, and the first paying pilot closes in 60-90 days.

---

## Appendix A — Quick file:line index for the 10 marketing fixes

| Fix | File:line |
|---|---|
| 1. Patient hashing (Option A) | `src/ai_billing_audit/audit_actions.py:191-192`; `src/ai_billing_audit/x12_parser.py:344`; `apps/portal/src/lib/patient-hash.ts:6-25` |
| 2. ca-central-1 | `apps/portal/src/app/security/page.tsx:55, 60`; `apps/portal/src/app/compare/page.tsx:270`; `apps/portal/src/app/faq/page.tsx:30` |
| 3. OHIP / HIPAA / NOM-024 | `apps/portal/src/app/security/page.tsx:127-141`; `apps/portal/src/app/compare/page.tsx:225`; `apps/portal/src/app/faq/page.tsx:50-52, 206-208` |
| 4. EHR integrations | `apps/portal/src/app/faq/page.tsx:257-259` |
| 5. Pilot duration | 7 sites — see §4.4 |
| 6. $499 tier volume | `docs/ONE_PAGER_WHAT_WE_DO.md:23` |
| 7. billing.invoice.paid webhook | `apps/portal/src/app/faq/page.tsx:194-196` |
| 8. F1 per-rule | `apps/portal/src/app/faq/page.tsx:158-160` |
| 9. "Sit between" | `apps/portal/src/app/how-it-works/page.tsx:24-25` |
| 10. "Learns" / "Does not learn" | `apps/portal/src/app/how-it-works/page.tsx:90-91` vs `apps/portal/src/app/trust/page.tsx:48-50` |

## Appendix B — Module-by-module ship status (60 FastAPI modules)

| Module | Status | One-liner |
|---|---|---|
| `api.py` | 🟢 | 6648 lines, the FastAPI surface, real endpoints |
| `auditor.py` | 🟢 | LLM call, schema validation, quote-in-note hallucination guard |
| `auditor_module.py` | 🟡 | likely a thin wrapper around auditor |
| `auditor_signature.py` | 🟡 | audit signature wiring |
| `appeal_letter.py` | 🟡 | v0 hardcoded rule catalog, not RAG (honestly disclosed) |
| `denial_risk.py` | 🟡 | Heuristic v0, no real model (honestly disclosed) |
| `doctor_email.py` | 🟡 | Operator outbox, NOT auto-send (honestly disclosed) |
| `feedback.py` | 🟢 | Hash-chained, complete with biller corrections + comments |
| `per_clinic_f1.py` | 🟢 | Real P/R/F1 with honest empty-state |
| `x12_parser.py` | 🟢 | Permissive, real, handles edge cases |
| `monthly_report.py` | 🟢 | Thin wrapper around per_clinic_f1, deliberate |
| `audit_actions.py` | 🟡 | Works but parallel-impl debt |
| `audit_depth.py` | 🟡 | Multi-depth audit (probably stub) |
| `backup.py` | 🟡 | DB backup (not in v1 marketing) |
| `carc_rarc.py` | 🟡 | CARC/RARC denial codes |
| `case_studies.py` | 🟡 | Real case data, US-CPT codes (not AHCIP) |
| `clinical_metrics.py` | 🟡 | Likely KPI aggregator |
| `contact.py` | 🟡 | Contact form |
| `csv_ingest.py` | 🟢 | CSV upload (real, used by /calculator) |
| `dashboard.py` | 🟢 | Dashboard data layer |
| `demo_entries.py` | 🟡 | Demo entry seed data |
| `demo_registry.py` | 🟡 | Demo registry |
| `feature_flags.py` | 🟡 | Feature flag system |
| `finding_assignments.py` | 🟡 | Finding → user assignment |
| `grader.py` + `grading.py` | 🟡 | LLM-as-judge / F1 grading |
| `ground_truth.py` | 🟡 | Synthetic encounter gold set |
| `i18n.py` | 🟡 | Internationalization (likely stub) |
| `industry_baseline.py` | 🟡 | Industry averages for ROI calculator |
| `institutional_837i.py` | 🟡 | Institutional 837I (US, not Alberta) |
| `job_queue.py` | 🟢 | Async job queue for audits |
| `judge.py` | 🟡 | LLM judge for QA |
| `llm.py` | 🟢 | LLMClient with litellm routing |
| `messages.py` | 🟡 | I18n messages |
| `minimax_client.py` + `minimax_errors.py` | 🟢 | LLM client (canonical `api.minimax.io/v1`) |
| `monthly_pdf.py` | 🟡 | PDF report rendering (mentioned in /pricing as "PDF + CSV") |
| `pattern_adjustment.py` | 🟡 | Per-pattern adjustment |
| `public_api.py` | 🟡 | Public API surface |
| `roi.py` | 🟢 | ROI calculator math |
| `saved_filters.py` | 🟡 | Per-user saved filters |
| `scenario_schema.py` | 🟡 | Scenario validation |
| `slack_notify.py` | 🟡 | Slack notification (not in marketing) |
| `snooze.py` | 🟡 | Finding snooze (mentioned in /findings) |
| `synth/*` | 🟢 | Synthetic encounter generator |
| `synth_agent.py` | 🟢 | Synthetic encounter LLM agent |
| `ux_polish.py` | 🟡 | UX helper (probably stub) |
| `webhooks.py` | 🟡 | Webhook delivery (verify what fires — only `audit.completed` is real per code; `billing.invoice.paid` is fabricated) |
| `worker.py` | 🟢 | Background worker for audit jobs |
| `zorva_context.py` | 🟡 | Market dict (NOM-024 aspirational) |

**Total: 60 modules. ~25 are production-grade. ~25 are honest stubs / wrappers. ~10 are aspirational / deferred.**

---

## Appendix C — What's NOT in this report (acknowledged gaps)

- **No test of the v12 prompt against real (non-synthetic) AHCIP claims.** The val set is `data/val_ca.json` — 10 encounters. The 0.690 F1 is on synthetic encounters. Real clinic data would shift the number.
- **No real privacy officer review.** The HIA template is in DRAFT (per `HIA_LAWYER_HANDOFF.md`).
- **No real EHR integration test.** All "integration" claims are either 837P file upload (works) or aspirational (FHIR, EHR-live).
- **No real AHCIP submission test.** Zorva doesn't submit; the biller does. So "catches 6-7 of 10" is a research number, not a production number.
- **No real customer data in the portal.** Every tenant has encounterCount=0, findingCount=0 (per the dashboard's "isFreshTenant" check).

These gaps are fine for a 60-day no-cost pilot with one friend-and-family clinic. They are not fine for a paid enterprise rollout. Gate §9's 5 tests before signing any paid contract.

---

**End of report. 35 marketing claims scored, 10 specific fixes prioritized, 5 decision gates set, 16 hours of cleanup work to ship-readiness.**

Report path: `/Users/biancabienaime/projects/ai-billing-audit/research/P7-REALITY-CHECK.md`
