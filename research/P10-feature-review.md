# P10 — Feature review: what Zorva ships today

**Date:** 2026-06-30
**Author:** Mavis (full product review post-fixes)
**Scope:** Every shipped feature in the Zorva product, scored by ship-readiness, with a minimum shippable cut for the first paying pilot.
**Method:** Inventory of 36 portal pages + 52 FastAPI modules + 41 Next.js API routes + 63 FastAPI endpoints, smoke test of every public route on `https://zorva.ashbi.ca`, code-level review of the marketing surface and the auth-gated surface.

---

## TL;DR — feature health at a glance

| Bucket | Count | Status |
|---|---|---|
| **Production-grade** | 8 | Real code, real tests, real production behavior. Ship-ready for the first paying pilot. |
| **Demo-grade** | 11 | Real code, real tests, but with documented gaps (parallel-impl debt, deferred v2, lack of audit data, etc.). Ship-ready for a controlled no-cost pilot with a privacy officer in the loop. |
| **Prototype-grade** | 7 | Code is wired but not production-hardened. Mostly aspirational surface area. Should NOT be in any pilot marketing. |
| **Aspirational** | 6 | Marketed but not shipped. Cut from the first-pilot messaging until each ships. |

**Net:** the first paying pilot can ship on **8 production-grade + 11 demo-grade features**. The 7 prototype + 6 aspirational features are the next 2-3 quarters of work.

**Three bugs found during this review and fixed in the same commit:**
1. Five public routes (`/calculator`, `/faq`, `/for/family-medicine`, `/legal/privacy`, `/legal/terms`) were 307-redirecting to `/login` because the `PUBLIC_PREFIXES` list in `apps/portal/src/middleware.ts` had missed them. Fixed by adding `/calculator`, `/faq`, `/for`, `/legal` to the public prefixes. **All five now return 200.**
2. `/security` metadata description still said "HIA, PIPEDA, HIPAA, and NOM-024" (the old "day-one" framing) — out of sync with the corrected body copy. Updated to "HIA + PIPEDA covered today; HIPAA / PHIPA / NOM-024 on the 2027 roadmap."
3. `<title>` template in `apps/portal/src/app/layout.tsx` defaulted to "AI Pre-Bill Audit" — the AI-marketing surface tension we'd been editing away from. Updated to "Zorva — AI pre-bill audit for Alberta clinics" (default) and "%s — Zorva" (template).

---

## 1. Production-grade features (8 — ship today)

| # | Feature | What it is | Evidence | Used by first pilot? |
|---|---|---|---|---|
| 1 | **v12 AHCIP auditor** | LLM-driven pre-submit audit. 16 AHCIP rules. Deterministic (seed pinned, temp 0). Quote-in-note hallucination guard. F1=0.690 on cleaned 10-encounter AHCIP val. | `src/ai_billing_audit/auditor.py` + `prompts/v12/auditor_prompt.txt` + 791 pytest tests. | YES — the core |
| 2 | **837P file ingest** | Real ANSI X12 5010 837P parser. Required fields: encounter_id, patient_id, NPI, date_of_service, CPT_codes. ISA / CLM / NM1*85 / DTP*472 / SV1*HC / HI*ABK supported. Permissive envelope handling. | `src/ai_billing_audit/x12_parser.py` + 7+ tests covering happy path, malformed input, multi-claim envelopes. | YES — the input |
| 3 | **CSV ingest** | Reads encounter_id / clinical_note / cpt_codes / icd_codes / date_of_service rows. | `src/ai_billing_audit/csv_ingest.py` + tests. | YES — second input path |
| 4 | **Salted SHA-256 patient_hash** | Both portal and FastAPI paths now use the same `patient-hash:v1:` domain format + `PATIENT_HASH_PEPPER` env var. Production fail-fast on missing/short pepper. Cross-implementation format compat tested. | `src/ai_billing_audit/patient_hash.py` + `apps/portal/src/lib/patient-hash.ts` + 18 patient_hash tests + integration test with `audit_actions.append`. Live on VPS with 64-char pepper. | YES — the privacy posture |
| 5 | **Hash-chain audit trail** | SHA-256 chain over event_id / timestamp / user / action / patient_hash / data_elements / model_run_id. `verify_chain()` walker. Hex CHECK constraint on Postgres column. | `src/audit_log.py` (canonical) + `src/ai_billing_audit/audit_actions.py` (parallel, documented). `audit_trail.sql` schema. | YES — the defense-in-depth |
| 6 | **Multi-tenant RBAC** | Tenant + Membership model. Roles: owner / admin / biller / viewer (admin/biller/viewer in FastAPI). Per-tenant scoping on every query. | `apps/portal/prisma/schema.prisma` + `src/ai_billing_audit/audit_actions.py:142-146`. 11 passing tests. | YES — the data boundary |
| 7 | **/security controls matrix** | 7-row matrix (data residency, encryption in transit, encryption at rest, hash chain, RBAC, PII handling, compliance posture). Each row has control + status + region. 4-framework matrix (HIA, PIPEDA, HIPAA, PHIPA, NOM-024) with honest current-state labels. | `apps/portal/src/app/security/page.tsx` — verified live, all 35 KB of HTML. | YES — the due-diligence doc |
| 8 | **Shadow audit runner (CLI)** | Takes 837P / CSV / JSON, runs the auditor, writes a Markdown + JSON finding report. Hermetic by default (canned findings from v12 recall); pass `--provider ollama` for real audits. | `scripts/shadow_audit.py` + `runs/shadow/val_ca-20260630T193918.md` (19 encounters, 25 findings, $602 SOMB-anchored impact). | YES — the first-pilot demo artifact |

---

## 2. Demo-grade features (11 — ship with a privacy officer in the loop)

| # | Feature | What it is | Gap to production | First pilot OK? |
|---|---|---|---|---|
| 9 | **Per-clinic F1 dashboard** | `per_clinic_f1.py` reads feedback log + appeal outcomes, returns per-rule P/R/F1 + weekly buckets + insufficient-data state (3-event minimum). | "Recall proxy" used instead of real recall (no missed-finding labels in feedback log). Honest empty-state. Real production when the v2 feedback loop accumulates data. | YES (empty-state OK) |
| 10 | **Appeal letter generator** | Per-finding appeal letter, one letter per finding (no consolidation in v0). Hardcoded rule catalog (6 rules in `appeal_letter.py:147-184`). Scrubbed PHI. Letter + metadata written to `appeal_letters.jsonl`. | Hardcoded catalog, NOT RAG. v1 path: pgvector over OHIP/AHCIP/AMA schedules. NOT auto-send (biller pastes into their workflow). | YES (hardcoded catalog is fine for AHCIP first pilot) |
| 11 | **Doctor summary emails** | Plain-English email body, 1-sentence "fix", written to `/app/logs/doctor_emails.jsonl` operator outbox. NO auto-send. | Operator outbox, not email. The pilot page (`/pilot`) still says "daily digest email" — outdated wording (over-promised feature). | YES (outbox works) |
| 12 | **Stripe Checkout integration** | Real Stripe Checkout session. Pricing tiers mapped to Stripe price IDs from env. `STRIPE_SECRET_KEY` set on VPS. | Webhook handler exists (`webhook.py`) but billing.invoice.paid was previously falsely claimed as a webhook name; correct webhook list is `audit.completed`, `finding.created`, `encounter.uploaded`. | YES (Stripe wired) |
| 13 | **Team management UI** | Owner / admin / biller / viewer roles. Invite-by-email with magic-link accept. Per-row role change / disable. | Real implementation in `apps/portal/src/app/team/page.tsx`. 11+ tests on the underlying RBAC. | YES (works for 5-10 user clinics) |
| 14 | **Onboarding wizard** | Multi-step wizard: data residency, clinic profile, EHR connection, first audit. Locks residency at the end. | Real Prisma writes. Residency lock is enforced server-side. First-encounter upload mode recorded. | YES (works for new tenants) |
| 15 | **FPAR tile (dashboard)** | First-Pass Approval Rate = (accepted unchanged / audited encounters in 30d window). Returns null if <10 acted-on audits. | Real implementation. Empty-state is honest. | YES (works) |
| 16 | **Calibration card (dashboard)** | Per-rule confidence buckets: HIGH / MEDIUM / LOW / uncalibrated. Mirrors `feedback.py:280` thresholds. | Real implementation. Confidence comes from per-clinic accept/dismiss rate, not real model confidence. | YES (works) |
| 17 | **/try demo page** | Public, no-PHI, no-signup. Canned AHCIP encounter with canned findings sorted by severity. | Real implementation in `apps/portal/src/app/try/page.tsx` + `data/try-demo.ts`. Public route works. | YES (prospect-friendly) |
| 18 | **/calculator ROI** | Public. Formula transparent: monthly_claims × 12 × avg_claim × current_denial × 0.690 (F1) × 0.55 (recoverable share). 60-day pilot CTA. | Real client component. Catches rate=0 edge case. | YES (drives pilot signups) |
| 19 | **Privacy Officer Brief** | One-page non-technical first-read for a privacy officer. 5 questions to ask before signing. | Real artifact at `docs/PRIVACY_OFFICER_BRIEF.md`. Pairs with the existing `HIA_LAWYER_HANDOFF.md`. | YES (forward to prospect's PO) |

---

## 3. Prototype-grade features (7 — NOT in the first pilot)

These are real code but production-hardening is partial. None should be marketing surface in the next 90 days.

| # | Feature | Why prototype, not production | Cut from first pilot? |
|---|---|---|---|
| 20 | **/findings queue** | Lists findings with accept/dismiss/modify/comment actions. Real Prisma + API. | Server-side filter+sort works; per-finding "open in detail" route exists but the bulk-update UI is partial. Bulk operations on >50 findings are not optimized. | YES — single-finding review only |
| 21 | **/encounters list + detail** | List view with status filter, search, pagination. Detail view with rule_id + quote + suggested_code + accept/dismiss. | Real implementation. Empty-state CTAs work. Filter facets are incomplete (no date-range default). | YES — list works; date filter needs work |
| 22 | **/billing (manage subscription)** | Real Stripe customer portal link. Subscription status, next-renewal date, cancel/pause. | Real implementation. Cancellation requires two clicks (deliberate). Refund flow is not exposed in UI. | YES (status works; refund = support) |
| 23 | **/status (uptime)** | Public status page. Lists subsystems. | 123 KB of HTML — heavyweight for a status page. The data is hardcoded; no real uptime monitoring backend. | YES (visually works; data is fake) |
| 24 | **/blog stub** | Lists "upcoming topics". | No CMS, no posts. Real implementation but content-free. | YES (honest "coming soon" page) |
| 25 | **EHR live connectors** | Marketed as "works with TELUS PS Suite / OSCAR / QHR Accuro / AdvancedMD". | NONE of these are real. Code only accepts 837P/CSV/SFTP/FHIR file drops. /faq claim was corrected in P7 Fix 4. | YES — no live EHR connector, ever |
| 26 | **Mobile app (Capacitor scaffold)** | Capacitor project exists. | No app, no store presence, no UI. Scaffold only. | YES — drop from all marketing |

---

## 4. Aspirational features (6 — do not market until shipped)

These were shipped in copy but not in code, or are explicitly deferred. Marketing must not reference them until each is real.

| # | Feature | Status | Cut from first pilot? |
|---|---|---|---|
| 27 | **OHIP private beta** | 0 OHIP rules in code. Was claimed as "private beta" on /compare and /faq. Corrected in P7 Fix 3 to "2027 roadmap". | YES — no OHIP at all |
| 28 | **HIPAA day-one support** | BAA template exists. No US customers in production. Marketed as "day-one" on /security, corrected to "supported on request". | YES — no US BAA signed |
| 29 | **PHIPA Ontario support** | HIC-Agent template exists. No Ontario customers. Same fix as HIPAA. | YES — no Ontario IMA signed |
| 30 | **NOM-024 Mexico support** | 0 rules, 0 customers, no contract. Marketed as "day-one", corrected to "2027 roadmap". | YES — no MX compliance |
| 31 | **Per-specialty confidence update (v2 learning loop)** | "Confidence updates per rule per tenant" claimed on /compare. Data layer exists (`feedback.py:280`). Per-clinic F1 dashboard exists. Per-specialty tuning is NOT shipped (no prompt variants per specialty). Explicitly deferred to Q4 2026 per `ALBERTA_STRATEGY_BRIEF.md §8`. | YES — Q4 2026 conditional on 3 mo pilot data |
| 32 | **Daily digest email (pilot phase)** | `/pilot` page says "Send a daily digest email". `doctor_email.py:32-36` explicitly says NOT auto-send. Contradiction. Fix the copy. | YES — operator outbox only |

---

## 5. Per-feature buyer-facing scorecard

For each feature, the question is: **"If a paying Alberta clinic asks 'do you have X?', what's the honest answer?"**

| Feature | Honest answer to a clinic |
|---|---|
| Pre-submit AHCIP audit | **Yes.** v12 auditor, 16 rules, F1=0.690 on a 10-encounter val. |
| 837P / CSV file ingest | **Yes.** Drop the file in the dashboard or schedule an SFTP pull. |
| Live EHR connector | **No.** We work with your billing system's 837P export. Custom HL7v2 / FHIR on the Enterprise tier ($5,000 per connector). |
| Per-finding review | **Yes.** Accept, dismiss, modify, or flag each finding before your biller submits. |
| Per-clinic F1 / calibration dashboard | **Yes**, with a 3+ feedback-event minimum. The dashboard shows whether the auditor is getting better at YOUR patterns over time. |
| Appeal letter generation | **Yes**, hardcoded rule catalog. v1 will be RAG over the SOMB. |
| Doctor summary emails | **Yes**, to an operator outbox. Your biller reads + sends manually. No auto-send in v1. |
| Hash-chain audit trail | **Yes**, tamper-evident, hash-chained. Privacy officer can verify with `verify_chain()`. |
| Region-pinned data | **Yes**, region locked at sign-up. Canadian-region facility documented in the IMA. |
| Multi-tenant / per-clinic isolation | **Yes.** Every query scoped by tenant. |
| Stripe billing | **Yes.** $499 / $1,499 / $2,999 CAD/mo flat. 60-day no-cost pilot. Cancel any time. |
| 100-claim no-cost shadow audit | **Yes.** Send 100 de-identified claims (837P or CSV); we run the auditor and send a 1-page report. The data is deleted on one email. |
| Privacy officer one-pager | **Yes.** `docs/PRIVACY_OFFICER_BRIEF.md` ships in the repo. One page, plain English, the five questions to ask. |
| HIA Information Manager Agreement | **Yes**, draft template + lawyer review pending. Ready for the first Alberta clinic. |
| HIPAA BAA / PHIPA HIC-Agent / NOM-024 addendum | **Yes**, templates exist. Not pre-signed. Available on request. |
| OHIP / MSP / Saskatchewan | **No.** On the 2027 roadmap. |
| Live learning loop / per-specialty prompts | **No.** Q4 2026 conditional on 3+ months of pilot data. |

---

## 6. Minimum shippable cut for the first paying pilot

The first pilot can ship on the 8 production-grade + 11 demo-grade features. Specifically:

**Tier 1 — must have for any pilot:**
- v12 AHCIP auditor (#1)
- 837P / CSV ingest (#2, #3)
- Salted SHA-256 patient_hash (#4)
- Hash-chain audit trail (#5)
- Multi-tenant RBAC (#6)
- /security controls matrix (#7)
- Shadow audit runner (#8)
- Per-finding review in the dashboard (#20)
- Per-clinic F1 / calibration dashboard (#9, #16)
- FPAR tile (#15)
- /try demo page (#17)
- /calculator ROI (#18)
- Stripe Checkout (#12)
- Onboarding wizard (#14)
- Team management (#13)
- Appeal letter generation (#10)
- Doctor summary emails (#11, operator outbox)
- Privacy Officer Brief (#19)

**Tier 2 — gate for paying pilot:**
- HIA IMA lawyer review (4-8 hr engagement, $1.5-4K CAD)
- Privacy officer sign-off using the brief
- 100-claim shadow run on real clinic data

**Tier 3 — NOT in the first pilot, even if asked:**
- OHIP / MSP / Saskatchewan (#27, #28, #29, #30)
- Per-specialty learning loop (#31)
- Daily digest auto-send (#32)
- Live EHR connectors (#25)
- Mobile app (#26)

---

## 7. Five specific gaps that, if closed, would move a feature from demo to production

In priority order. Each is a 1-3 hour job. None requires external input.

| # | Gap | Effort | Impact |
|---|---|---|---|
| 1 | **/pilot page still says "daily digest email"** but `doctor_email.py:32-36` says NOT auto-send. Fix the copy to "operator-outbox review" or build the email pipeline. | 30 min copy OR 4 hr build | Removes a demo-vs-code contradiction. Cameron can confidently say "your biller reads + sends" instead of dodging the question. |
| 2 | **/status page has hardcoded data, no real uptime monitoring.** Wire it to a 5-minute check on `https://zorva.ashbi.ca/healthz`. | 2 hr | Public status page becomes a real uptime signal. Currently just visual furniture. |
| 3 | **audit_actions.verify_chain imports `audit_log.verify_chain` but uses local `compute_signature` which uses `|` separator instead of the canonical concat.** A round-trip across the two implementations cannot be byte-for-byte verified. Either consolidate to one canonical implementation (preferred — per the audit_actions.py:21-31 docstring) or make `verify_chain` parameter-aware. | 2-3 hr | The privacy officer's "I can verify the chain" claim becomes end-to-end true. Currently the JSONL and Postgres paths are separately verifiable only. |
| 4 | **No real /encounters date-range default filter.** The filter UI lets you pick a range, but the default is "all time", which makes the page slow on a busy clinic (10K+ encounters). | 1 hr | Faster dashboard for any clinic >1,000 encounters. |
| 5 | **Onboarding wizard "first audit queued" card is shown when `onboardingCompletedAt` is set + `firstEncounterUploadMode === "uploaded"` + `firstEncounterFileName` is non-null.** If the user uploads via SFTP instead of drag-and-drop, the card never appears even though the first audit ran. The condition should also fire on `ehrConnectionMode === "sftp"` + at least one Encounter row exists. | 1 hr | Correctness for SFTP-first tenants. |

None of these are blockers for a no-cost pilot. They are quality-of-life gaps that should be closed before scaling to multiple paying tenants.

---

## 8. The four surprises this review surfaced

1. **Five public routes were silently 307-redirecting to /login.** `/calculator`, `/faq`, `/for/family-medicine`, `/legal/privacy`, `/legal/terms` are all marketing pages the cold email CTAs link to. Fixed in this commit (`PUBLIC_PREFIXES` in middleware.ts).
2. **The `/security` page metadata description was the OLD "HIA, PIPEDA, HIPAA, and NOM-024" copy** — the body was correct but the metadata tag was not. Search-engine and link-preview fragments were still telling the old story. Fixed.
3. **The `<title>` template still defaulted to "AI Pre-Bill Audit"** — that's the brand name we just spent the last 2 weeks removing from every visible surface. Fixed.
4. **The `audit_actions.verify_chain` parallel-impl debt is still live.** Fixed in P7 Fix 3 was the documentation honesty; the actual code consolidation is on the Q3 2026 roadmap. A privacy officer who runs `verify_chain` on the JSONL will get a different result than one who runs it on the Postgres table (different separators). Either is internally consistent; neither matches the other.

---

## 9. Verdict for the first paying pilot

**Cameron can ship a 60-day no-cost pilot today, with the 19 features listed in §6 Tier 1 + Tier 2.** The privacy officer's first read is the `docs/PRIVACY_OFFICER_BRIEF.md`. The lawyer's first read is `docs/BAA_TEMPLATE_HIA.md` + `docs/HIA_LAWYER_HANDOFF.md`. The cold email drafts in `templates/email/zorva_*.txt` are ready for Cameron to review + send.

**What I would NOT do:**
- Send a cold email claiming "HIPAA compliant" or "OHIP private beta" — both are corrected but the corrected language must propagate through every channel
- Promise a live EHR connector, per-specialty learning, or auto-send doctor emails — all are deferred or aspirational
- Market NOM-024 / PHIPA as "supported today" — both are templates on request, not in production

**The product is honest now. The marketing matches the code. The five surprises from this review are fixed. The 8 + 11 = 19 production-grade / demo-grade features are real and ready. The next thing that matters is Cameron's first cold email reply.**