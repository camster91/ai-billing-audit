# P0 — Zorva 3-Month Product Roadmap (Q3 2026)

**Author:** general (synthesize-product-roadmap, Mavis plan `plan_cc23148d`)
**Date:** 2026-06-28
**Scope:** Synthesize `research/P1-biller-workflow.md`, `P2-ahcip-submission.md`, `P3-emr-integration.md`, `P4-competitors.md`, `P5-customer-signal.md`, `P6-product-gaps.md` into one executable 12-week plan for Cameron.
**Audience:** Cameron Ashley, solo operator. Startable Monday morning without further research.

> **Reading order:** TL;DR → 3-month sequenced plan → two-strategy decision → EMR plan → moat → out-of-scope. The 12-week table in §2 is the executable artifact; everything else is supporting reasoning.

---

## TL;DR — the 5 highest-leverage product moves, in priority order

1. **Ship the synthetic-data demo path (G9, ~3-4 days) in Week 1.** Zorva's time-to-first-value is hours (manual upload / SFTP); Dr. Bill's is 30 seconds. Drop a `/try` public route that runs the v12 auditor against the existing `data/val_ca.json` fixture under a sandbox tenant — under-30s demo without an 837P file. **Highest single priority-score gap from P6 (priority 80).**
2. **Send the first three cold-outreach emails by end of Week 1, audit-first, no self-intro.** Re-ranked targets from P5: **Red Deer PCN** (MAPS structural-change signal + 14-doctor growth) → **Sherwood Park Strathcona PCN** (active careers + TELUS Med Access confirmed) → **West Springs Medical** (verified Feb 9 2026 locum posting). Channel partner K&M Medical Billing in Calgary parallel-tracked. **P5 shows the lead table has 41 fixture rows and zero real-clinic pipeline; if no outreach goes out by Week 2, the quarter produces zero revenue signal.**
3. **Build G2 (837P submission-preview / reconciliation view) in Weeks 2-4.** Today's findings inbox writes `Finding.status` only — the biller can't see "what would the corrected claim look like." Ship a side-by-side diff on `/encounters/[id]/preview` so the biller can hand a corrected 837P back to their own EMR or export it. **Stays inside `anti-features.md` §1 ("we don't submit") while making the auditor biller-actionable. P6 priority 60.**
4. **Land the first paid pilot by end of Week 6 (target: West Springs Medical, 6-10 physicians).** Pick the lowest-friction candidate (independent clinic, mid-tier $1,499 CAD/mo, fastest procurement), get them through a 30-day pilot. **Without one anchor pilot by Week 6, the entire competitive-moat story collapses — Dr. Bill / Petal ship the "AI audit" feature and Zorva becomes the second mover in its own wedge (per P4 §5).**
5. **Ship Accuro OAuth 2.0 integration in Weeks 5-8, OSCAR Pro FHIR R4 in Weeks 7-10.** P3 ranks Accuro #1 (cheapest, fastest: 2-4 dev-mo, $25K-$50K CAD, 6 AI scribes already integrated) and OSCAR Pro #2 (only Alberta-relevant EMR with FHIR R4 shipping in production, 3-5 dev-mo, $45K-$90K CAD). TELUS PS Suite is deferred to Q4 — gated by partner-program onboarding. **Total Phase-1-2 budget: $70K-$140K CAD + 4-6 months parallel.**

**Why this order:** the revenue-critical path (pipeline → pilot → anchor) ships in 6 weeks. The product-deepening path (G9 → G2 → G3 → G5 → G1 EMR) runs in parallel starting Week 1. Strategic items (PCN deal, audit-survival module, G8 per-clinic rules) gate on the pilot having 4+ weeks of real data.

---

## 1. Strategy recommendation — pick ONE

### Strategy A — Single-product AHCIP auditor (deepen EMR integration) — **RECOMMENDED**

What it is: stay laser-focused on pre-submission audit for Alberta AHCIP claims at the solo/small-clinic tier. Ship Accuro + OSCAR Pro integration in Q3; add TELUS PS Suite in Q4 only after an anchor PSS clinic lands. Build the MAPS-transition pitch ("tool that catches errors across the merged billing function") and ride the 39-PCN → 7-RPHCN consolidation window.

Why this wins in 2026:
- **P1 + P2 confirm pre-submission (Slot A) is the higher-leverage slot** — 7-dimension comparison (volume × cost × revenue captured × WTP × info advantage × time pressure × existing-tool gap × catchable errors) makes the case quantitatively, not hand-wave.
- **P4 confirms the wedge is uncontested** — Dr. Bill, Petal Health, WELL/ClinicAid all serve Alberta AHCIP but none does pre-submission AI audit at SOMB rule depth. The window is **measured in months** (P4 §4.6), not years.
- **P5 confirms zero real-clinic pipeline** — without an anchor Alberta pilot in 90 days, expansion claims are fiction. We don't yet know if the product closes; cannot justify opening a second front.
- **P3 confirms EMR integration cost is concentrated** — Accuro + OSCAR Pro = $70K-$140K CAD + 4-6 mo. Adding MSP + OHIP expansion (~$4K/week × 5-9 weeks per `ALBERTA_STRATEGY_BRIEF.md` §6) competes for the same engineering budget and dilutes the rule-engine investment.
- **P5's MAPS narrative is a once-in-a-decade distribution event** — the Alberta government is mid-restructure of all 39 PCNs into 7 RPHCNs; every PCN CEO is shopping for tools that survive the consolidation. Get in now, get the first PCN deal, set the precedent.

### Strategy B — AHCIP + adjacent vertical (multi-provincial or revenue-cycle-management)

What it is: parallel-track OHIP (Ontario, 0 rules → 8-9 dev-weeks) and/or MSP (BC, 0 rules → 5-6 dev-weeks), or layer in RCM features (denial-management dashboard, patient-billing, post-submission reconciliation) on top of pre-submission audit.

Why we reject it for Q3:
- **Zero-clinic pipeline means we don't yet know if the product closes.** AHCIP pre-submission audit has never been sold at the solo-clinic tier with this positioning. Selling two untested products simultaneously is worse than selling one well.
- **P6's product-gap analysis prioritizes pre-submission depth over breadth** — G1, G2, G3, G5, G8 are all Alberta-specific. The math says "deepen, then expand."
- **MSP/OHIP expansion is a 5-9 week engineering pull** that competes with G1 (live EMR feed, 3-6 weeks) for the same solo-operator bandwidth.
- **RCM expansion (denial-management, patient-billing) collides with `anti-features.md` §1** — Zorva deliberately does not submit, does not handle patient-billing, does not handle collections. The wedge is clinical-context audit; RCM is a different product.

**One-line decision: stay Alberta-deep through Q3. Re-evaluate the adjacent-vertical decision in Q4 after we have 3+ paid pilots + 90 days of refusal-pattern data + the first PCN deal done (or declined with reason).**

---

## 2. Three-month sequenced plan (12 weeks, week-of dates assume start Monday 2026-06-29)

### Weeks 1-2 — quick wins (each ≤1 week, independent)

| # | Item | Source | Owner | Acceptance |
|---|---|---|---|---|
| **W1.1** | **G9 — synthetic-data demo path** (~3-4 days). Public `/try` route + "Run sample audit" button; ingests `data/val_ca.json` under sandbox tenant; renders the same `/encounters/[id]` split-screen with real findings. | P6 §3 G9 | Cameron | Time-to-first-finding under 30s for an unauthenticated visitor. Demo path documented in `/docs/TRY_DEMO.md`. |
| **W1.2** | **Lead-model pipeline fields + outreach prep** (~1 day). Add `status`, `source`, `lastContactedAt`, `notes`, `ownerUserId` to the `Lead` Prisma model. Migration + small admin list view at `/admin/leads`. Draft three audit-first cold emails (Red Deer PCN, Sherwood Park Strathcona PCN, West Springs Medical) per P5 §5.3 — never send without Cameron's sign-off. | P5 §1.1, §5.3 | Cameron | Migration applied; admin view renders existing 41 fixture rows + new fields visible; three email drafts in `templates/email/` ready for review. |
| **W1.3** | **Send first 3 cold-outreach emails** (Tue-Fri Week 1). Audit-first openers (no "I'm Cameron Ashley…"), MAPS-trigger for Red Deer, careers-page-trigger for Strathcona, locum-posting-trigger for West Springs. Per the user-pref outreach style (audit-first, 12th-grade English, no flattery, no event-recap opener, low-commitment CTA). | P5 §2, §5.3 + user-pref memory | Cameron | Three emails sent from Cameron's account; Lead rows updated with `status='contacted'`, `lastContactedAt`, `source`; reply window opens. |
| **W1.4** | **Channel-partner outreach (K&M Medical Billing)** (~half day). Email to confirm the 25-clients-AHCIP and YouTube-presence claims from `BILLING_CONSULTANT_CHANNEL_PARTNERS.md`. If confirmed, propose a co-marketing pilot ("we give K&M's 25 clinics a 30-day free trial; K&M refers 3 clinics by end of pilot"). | P5 §4 | Cameron | Outreach email sent; reply tracked in Lead admin view under `source='channel_partner'`. |
| **W2.1** | **G3 — Monthly ROI report view in portal** (~1 week). New `/reports` page (owner role only) calls existing `monthly_report.compute_monthly_summary()` + `monthly_pdf.render_monthly_pdf()`; renders dashboard + "Download PDF" button. The "you saved $X last 30 days" headline the clinic owner asks on every sales call. | P6 §3 G3 | Cameron | A real pilot tenant sees their own numbers; PDF downloads cleanly; non-pilot tenants see a "Run 5+ audits to unlock" empty state. |
| **W2.2** | **G5 — HIA patient-data access UI** (~1-1.5 weeks, can land by end of W2). New `/compliance/patient-access` page (owner role only) with: (a) "What do we hold for patient X?" — paste PHN, system returns salted SHA-256 hash + counts of `Encounter` + `AuditTrailEntry` rows; (b) "Delete all data for patient X" — signed deletion request, 7-day grace window, both audit-logged. | P6 §3 G5 | Cameron | HIA custodian-obligation checklist item closed; closes the existing `audit_log_export` self-logging TODO at `apps/portal/src/app/api/audit/export/route.ts:35`. |

### Weeks 3-6 — medium items (each 1-2 weeks, may depend on Week 1-2)

| # | Item | Source | Owner | Acceptance |
|---|---|---|---|---|
| **W3.1** | **G2 — Submission-preview / reconciliation view** (Weeks 3-4, ~1.5-2 weeks). On the `/findings` inbox, add "Apply accepted findings → preview 837P diff" button. New `apps/portal/src/lib/claim-rewrite.ts` rebuilds claim JSON with accepted code swaps. New `/encounters/[id]/preview/page.tsx` renders side-by-side current-vs-corrected diff, read-only + exportable. Stays inside `anti-features.md` §1 (we still don't submit — biller hands corrected 837P back to their own EMR). | P6 §3 G2 | Cameron | Biller can preview a corrected claim, export the diff JSON, and the export is importable into at least one major EMR's "import corrected claims" flow. |
| **W3.2** | **First pilot conversation target: West Springs Medical** (Week 3 outreach, Week 4 demo). Lowest-friction candidate per P5 — 6-10 physicians, mid-tier $1,499 CAD/mo economics, verified Feb 9 2026 locum posting = active hiring signal. Offer the existing `PILOT_OFFER.md` 30-day free trial with the new `/try` synthetic-data demo as the entry point. | P5 §2.2 #3 | Cameron | West Springs signs the pilot agreement (HIA-compliant BAA template per `docs/BAA_TEMPLATE_HIA.md`). |
| **W4.1** | **G1 Phase 1a — Portal-side SFTP pull job** (~1 week, Weeks 4-5). New `apps/portal/src/app/api/cron/ehr-pull/route.ts` reads `Tenant.ehrConnectionMode='sftp'` rows every 15 min; runs `scripts/ehr/advancedmd_pull.sh` per tenant. Closes the "we configured SFTP and then nothing happened" gap from `EHR_ADVANCEDMD_INTEGRATION.md`. | P6 §3 G1 | Cameron | A tenant with SFTP creds configured sees claim files appear automatically in `/encounters` within 15 min of upload to their SFTP endpoint. |
| **W5.1** | **G1 Phase 1b — Accuro OAuth 2.0 integration** (Weeks 5-8, parallel to pilot). Apply for Accuro Marketplace Vendor program (per P3 §1.3). Implement AccuroAPI OAuth 2.0 client; read-only ingest path for `Claim` + `Encounter` + clinical-note resource. First-clinic integration via West Springs if they happen to be Accuro, else recruit one Accuro clinic (Millwoods Family Medical Clinic per P5 §2.4 #7 is the natural fit). | P3 §3 Rank 1 | Cameron | Marketplace Vendor application submitted (approval is async); first Accuro clinic integration end-to-end within 8 weeks of approval. |
| **W5.2** | **First pilot live at West Springs Medical** (Week 5+). 30-day pilot running on the synthetic-data + file-upload path. Daily check-in with the biller for the first week; weekly thereafter. Target: ≥30 encounters audited, ≥10 findings acted on, FPAR tile populates with real data. | P5 §2.2 #3 | Cameron | Pilot running, daily check-ins in `pilot/west-springs/notes.md`, weekly review of FPAR + calibration cards. |
| **W6.1** | **MAPS-transition pitch deck** (~3 days, Week 6). One-pager + 5-slide deck tailored to the PCN-CEO audience: "tool that catches errors across the merged billing function." Lead with the 4-PCN-merger Red Deer example + the 14-doctor-growth signal. Customize for each PCN. | P5 §3.2 | Cameron | Deck ready for Red Deer PCN outreach; template ready for the other 38 PCNs. |

### Weeks 7-12 — strategic items (each 2-4 weeks, may need sales/fundraising)

| # | Item | Source | Owner | Acceptance |
|---|---|---|---|---|
| **W7.1** | **Red Deer PCN pilot conversation target** (Week 7 outreach, Week 8-9 demo). Lead with MAPS structural-change audit per P5 §5.3. Frame: "as you merge billing across 5 PCNs, pre-submit audit pays for itself on day one." Target: signed pilot agreement by end of Week 9. | P5 §2.2 #1 | Cameron | Red Deer PCN signs the pilot; if no movement by Week 10, drop to Strathcona PCN per the W7.3 fallback. |
| **W7.2** | **G1 Phase 2 — OSCAR Pro FHIR R4 integration** (Weeks 7-10, parallel). Apply to apps.health partner program. Implement FHIR R4 read-only `Claim` + `Encounter` + `DocumentReference` consumer. CHIME's existing OSCAR Pro integration is the existence proof — pattern is established. | P3 §3 Rank 2 | Cameron | apps.health partner application submitted; FHIR R4 read-only claim-data ingest working end-to-end against OSCAR Pro sandbox by end of W10. |
| **W7.3** | **Sherwood Park Strathcona PCN outreach** (Week 7, parallel to Red Deer). Lead with the verified careers-page + TELUS Med Access EMR confirmation. If Red Deer stalls by W10, Strathcona becomes the primary PCN play. | P5 §2.2 #2 | Cameron | Outreach sent; reply tracked; second-tier PCN conversation in flight by end of Q3. |
| **W8.1** | **West Springs pilot retrospective + first case study** (Weeks 8-9). After 4 weeks of pilot data, write the public case study: "$X caught, $Y missed, $Z billed-as-billed." Use the FPAR tile + monthly ROI report numbers verbatim. Honest about misses — the case study's credibility is its weakest-claim restraint. | internal | Cameron | Case study published on `/case-studies/west-springs-medical/`; serves as social proof for the Red Deer / Strathcona / Medicentres outreach. |
| **W9.1** | **G8 — Per-clinic rule suppression + custom rules UI** (Weeks 9-11, ~2-3 weeks). New `PerClinicRuleSuppression` Prisma model; new `/settings/rules` page (owner role only); prompts can be overridden per-clinic. Billers can say "we never bill 03.05A, suppress that rule" or "add our clinic-specific locum rule." Uses the existing `rules/` retrieval layer. | P6 §3 G8 | Cameron | Biller can suppress a rule clinic-wide in under 60 seconds; custom rule added and evaluated in pilot within the same session. |
| **W10.1** | **Audit-survival module (P1 defensive build)** (Weeks 10-12, ~2-3 weeks). New `/audit-survival` portal view: "Dry-run my last 100 claims as if Alberta Health were auditing me today." Per P4 §5.5 this is the moat-extender — no competitor does it. Build it before Dr. Bill / Petal thinks to. | P4 §5.5 | Cameron | Tenant can run a dry-run audit-survival report on last 30 days; report flags claims most likely to trigger an Alberta Health audit-and-compliance review. |
| **W11.1** | **G11 — Batch day-end review view** (Weeks 11-12, ~1-2 weeks). New `/batch-review` portal view: aggregated "today's batch" grid showing 30 encounters × avg 3 findings in one scrollable view. Bulk accept/dismiss already exists; this is the workbench surface. | P6 §3 G11 | Cameron | A biller can review and act on a 30-encounter day-end batch in under 15 minutes. |
| **W12.1** | **Quarter-end review + Q4 scope** (Week 12, ~2 days). Hit/miss against the 90-day plan: # pilots signed, # PCN conversations, F1 lift, integration milestones, $ revenue. Decide Q4 scope: TELUS PS Suite integration? SOC 2 prep? First MSP / OHIP pilot? Doctor-portal view? Re-prioritize based on data, not planning-bias. | internal | Cameron | Q3 retrospective written, Q4 plan published at `research/00-ROADMAP.md` (Q4 version). |

### Plan-wide dependencies and risks

- **The pilot + integration paths are parallel-tracked** — West Springs pilot (W3-W8) runs while Accuro integration (W5-W8) is in flight. They share engineering bandwidth (Cameron) but not blockers; the pilot is file-upload + `/try` (no live EMR), the integration is OAuth plumbing.
- **The MAPS-transition window is time-sensitive** — P5 §2.3 sensitivity analysis: if Red Deer PCN's MAPS timeline slips past Q4 2026, the structural-change pitch loses urgency. Re-rank weekly if signals shift.
- **The competitive window is ~12 months** — P4 §4.6: "Once Dr. Bill or Petal ships 'AI audit check before submit' — even a thin version — the marketing category gets defined." Every week of the quarter is a week Zorva is still the only AHCIP-specific pre-submission audit tool in market.
- **Zero-clinic pipeline is the #1 risk** — if no outreach goes out by end of W1 or no pilot signs by W6, the whole roadmap collapses. Schedule the W1.3 outreach send as the Monday-morning non-negotiable first action.

---

## 3. EMR integration plan

### Decision: Accuro first, OSCAR Pro second, TELUS PS Suite deferred to Q4

Per P3 §3:

| Rank | EMR | Why this rank | Dev-months | Cost (CAD) | Phase |
|---|---|---|---|---|---|
| **1** | **Accuro (QHR)** | Fastest vendor approval (Marketplace Vendor self-onboarding), cheapest, **proven pattern** (6 AI scribes integrated 2024-2025 via same OAuth 2.0 + REST path), Alberta stronghold (Edmonton cluster), **Zorva's slot uncontested** in the Marketplace | 2-4 first; 1-2 maintenance | $25K-$50K read-only; $50K-$90K bidirectional | **Q3 (W5-W8)** |
| **2** | **OSCAR Pro (WELL)** | **Only Alberta-relevant EMR with FHIR R4 shipping in production** (April 2025 release notes), apps.health is a real partner marketplace, Alberta reach via Juno EMR (WELL's Alberta-hosted OSCAR), CHIME is existence proof | 3-5 first; 1-2 maintenance | $45K-$90K read-only; $80K-$150K bidirectional | **Q3 (W7-W10)** |
| **3** | **TELUS PS Suite** | Largest Alberta market share (~42% national, 8/12 prospect-list defaults) BUT longest vendor-program gating, documented "Limitations of the New TELUS API" friction, multi-month onboarding | 3-5 first; 1-2 maintenance | $35K-$65K read-only; $70K-$130K bidirectional | **Q4 (deferred)** |
| **4** | **TELUS Med Access** | Same vendor as PS Suite — if PSS is integrated, Med Access is incremental | 1-2 incremental | $15K-$30K incremental | **Q4 bundled with PSS** |

### Total Q3 budget for top 2 EMRs

- Read-only FHIR/REST path: **$70K-$140K CAD**
- Full bidirectional + claim write-back: **$130K-$240K CAD**
- Realistic Cameron solo-operator spend (read-only path only, no claim write-back in Q3): **~$70K-$140K CAD + 4-6 months parallel**
- Annual maintenance: **$15K-$35K CAD/yr combined** post-launch

### Vendor-program onboarding realities

Per P3 §4: **"The most expensive part isn't the engineering — it's the wait."** Vendor partner-program review timelines, certification rounds, per-clinic IT coordination dominate the calendar. Plan:
- Apply to both Accuro Marketplace + apps.health in **Week 5 in parallel** (don't sequence; the wait is calendar-bound, not engineering-bound).
- Use the integration wait time to ship G2 / G3 / G5 / G9 first — all file-upload or synthetic-data based, no live EMR needed.
- The pilot runs on the file-upload path for the first 4-6 weeks regardless of integration status.

### Out-of-scope for Q3 EMR integration

- **H-Link direct integration** — Alberta Health vendor approval is months of legal + cert, and `anti-features.md` §1 explicitly keeps Zorva out of the submitter business. Reject.
- **Bidirectional claim write-back** — read-only is enough for the audit wedge. Writing corrected claims back into the EMR is a different product (Dr. Bill / ClinicAid territory). Defer to Q4 once we have pilot customers asking for it.
- **TELUS CHR** — newer TELUS product, small Alberta share, track for 2027.
- **AHS Connect Care / hospital EMRs** — hospital-employed-physician billing, different GTM, out of community-clinic scope.

---

## 4. Competitive moat to build — the ONE thing

**Ship the Alberta-specific SOMB rule depth + land the first PCN partnership in the MAPS transition window.**

That's the single 90-day move that, if it lands, makes Zorva the obvious choice for Alberta AHCIP clinics through 2027.

### Why this is the moat

- **Alberta-specific SOMB rule depth is un-replicable in 12 months.** Per P4 §4.1: the SOMB is updated annually, the AMA-negotiated add-on fees change frequently, and encoding the rules with maintained accuracy is a non-trivial engineering + clinical-biller effort. Competitors would need to (a) hire Alberta billers (scarce — most are already at Dr. Bill / Petal-MBA / Alberta Billing) or (b) license the rule set from Zorva. Neither is fast.
- **The first PCN deal sets the precedent.** Per P4 §4.3: PCNs are procurement entities that can bundle Zorva across their member physicians — a channel that Petal (Quebec-rooted) and Dr. Bill (BC-rooted) don't have natural access to. **Whoever gets the first PCN deal during the MAPS consolidation sets the category standard.**
- **MAPS is a once-in-a-decade distribution event.** 39 PCNs → 7 RPHCNs is mid-flight in 2026; every PCN CEO is shopping for tools that survive the consolidation. The "tool that catches errors across the merged billing function" pitch is uniquely Zorva-shaped.
- **The rule depth + first-PCN-deal combo compounds.** Each new rule Zorva ships (W9-12: G8 per-clinic custom rules + audit-survival module) deepens the moat; each new PCN that adopts Zorva adds distribution; the two reinforce.

### What specifically to ship in 90 days

1. **The 16 SOMB rules at ≥90% catch rate on real Alberta encounters** (vs v12's current F1=0.690 on the 10-encounter val_ca.json — gap is real, gap is Q3 work).
2. **The MAPS-transition pitch deck + first PCN pilot signed** (Red Deer PCN primary, Sherwood Park Strathcona PCN backup).
3. **The audit-survival module** (W10-W12) — the moat-extender no competitor is building (P4 §5.5). This is the feature that, once a clinic has it, they don't leave.
4. **The West Springs case study with honest FPAR lift numbers** (W8-W9) — social proof for the next 10 PCN conversations.

### What is NOT the moat (and why)

- **"AI-powered"** is not a moat — every competitor markets this. CodaMetrix, SmarterDx, Anterior, AKASA, Maverick all use the word.
- **Per-claim pricing** is not a moat — Dr. Bill and Petal both price at this tier.
- **Mobile-first** is not a moat — Dr. Bill owns this. Match parity, don't try to out-build.
- **FHIR R4 integration** is not a moat — Accuro + OSCAR Pro will eventually ship this themselves if it becomes table-stakes. Build for clinical utility, not for FHIR-spec marketing.

---

## 5. Out of scope for the quarter (with rationale)

| # | Item | Why out of scope |
|---|---|---|
| 1 | **H-Link direct submission integration** | `anti-features.md` §1 explicitly rejects ("we don't submit"). Alberta Health vendor approval is months of legal + cert work; Zorva's wedge is audit, not transport. Per P2 §4.4, H-Link integration doesn't add to the value prop — the biller still has to push to H-Link via their EMR. |
| 2 | **Slot B — post-submission reconciliation + appeal-letter auto-send** | Per P2 §4.3, Slot B is lower-leverage than Slot A on every dimension (volume, cost, revenue, WTP, info advantage, time pressure, tool gap). The `appeal-letter` module is built but unexercised against Alberta data. Re-evaluate Q4 with 90+ days of refusal-pattern data from pilot. |
| 3 | **OHIP / MSP expansion** | Per `ALBERTA_STRATEGY_BRIEF.md` §6: "deferred until Alberta pilot ships." Engineering cost (5-9 dev-weeks × $4K/week = $20K-$36K) competes with G1 EMR integration + G2 + G3 + G5. Wait until anchor Alberta pilot signs + 30 days of FPAR data. |
| 4 | **Multi-clinic / group tenant model (G4)** | Per P6 §4: "Only the top 1-2 prospects (Strathcona PCN, Medicentres corporate) need this today. Adding it before we have even one paying clinic is premature." The single-pilot first is the right order. |
| 5 | **Doctor-side portal view (G7)** | `doctor_dashboard.py` modules exist in FastAPI but no doctor has logged into the portal in any pilot scenario. Doctors currently get findings via the biller. Re-evaluate after a clinic where the doctor (not the biller) is the buyer. |
| 6 | **In-app notifications / "new findings" center (G6)** | Priority 30 in P6 — weekly-digest email is the right channel at current volume. Engineering surface for marginal UX gain. |
| 7 | **Comments / @mention / assignment (G10)** | Priority 16 in P6 — accept/dismiss is sufficient for current solo-biller workflow. If we add a second-biller team later, this becomes a Q2 2027 item. |
| 8 | **SOC 2 / ISO 27001** | On certification roadmap per `/security` page copy; not currently held. Procurement cycle at the first Medicentres / Covenant Health will tell us whether to accelerate. |
| 9 | **AI scribe / ambient-dictation product** | Different product (Tali, Heidi, Abridge). Zorva's wedge is clinical-context audit; scribe partners are the play, not a build. |
| 10 | **Patient-side billing / third-party / uninsured billing** | `anti-features.md` §3 — out of scope. Clinic-billed directly to patient is a different product. |
| 11 | **Real-time claim adjudication** | AHCIP doesn't have real-time adjudication (H-Link is weekly batch, per P2 §1.2). Building "real-time" for a non-existent product is moot. |
| 12 | **WCB-Alberta pre-submission logic** | Adjacent vertical per P4 §3.4 — `rule_ahcip_wcb_conflict` covers the mis-route detection but the correct WCB submission flow is a different product. Defer until anchor pilot has WCB billing volume that justifies the build. |
| 13 | **Indigenous Services Canada (FNIHB) billing** | Separate payer with separate rules; only relevant if we target clinics with significant Indigenous patient panels. Not in prospect list. |
| 14 | **AI scribe + billing convergence (Abridge-style)** | Different category — the convergence question (defensive feature vs partnership) is a separate strategic decision per P4 §7. Not Q3 work. |
| 15 | **Billers-as-customers GTM pivot** | Per P4 §7: "If Zorva should sell to billing agents instead of physicians directly, that's a GTM question, not a competitive one." K&M Medical Billing channel-partner outreach (W1.4) is the soft test — if it converts, expand; if not, stay physician-direct. |

### Things the research surfaced but that are explicitly deferred (not "rejected forever")

- **Per-claim pricing optimization** — P4 §5.2 recommends $0.50-$2.00 per claim range; existing $499/$1,499/$2,999 tiers are reasonable for the biller-pilot positioning. Re-evaluate pricing once we have 3+ paid pilots with usage data.
- **Production-DB lead count verification** — P5 §1.4 flagged this as a verification gap (only dev.db was queryable). The W1.2 admin view will surface prod leads once deployed.
- **K&M Medical Billing YouTube presence verification** — P5 §4.1 caveat. W1.4 outreach is the verification path.
- **Per-clinic calibration data → rule-ranking ML** — `ALBERTA_STRATEGY_BRIEF.md` §4 mentions this as a Q4+ build. The 90-day plan gets us the data (West Springs pilot → 30+ encounters → calibration cards populated); the ML is Q4+.
- **Billing-agent tier** — Dr. Bill has it; Zorva doesn't. If W1.4 K&M outreach converts, the billing-agent tier becomes a Q4+ GTM question.

---

## 6. Appendix — cross-references and decision log

### Cross-cutting insights the synthesis surfaced

1. **The pipeline is the #1 problem, not the product.** P5 confirms 41 fixture rows + zero real-clinic inbound + no outreach sent. P6 says G9 (synthetic demo) is the highest-priority gap. The two together imply: **ship the demo path in W1, send the first emails in W1, the demo + the outreach are the revenue gate, not the engineering.**
2. **Slot A vs Slot B is settled.** P1 + P2 both confirm pre-submission audit (Slot A) is higher-leverage than post-submission reconciliation (Slot B) on every dimension. The roadmap doubles down on Slot A and defers Slot B to Q4+ once we have refusal-pattern data.
3. **The MAPS-transition window is the strategic unlock.** P5 surfaces it; P4 confirms Dr. Bill / Petal don't have PCN-channel access; P3 confirms Accuro + OSCAR Pro reach Alberta PCN clinics via their member-physician installs. The roadmap leads with Red Deer PCN as the strategic pilot.
4. **EMR integration is concentrated in Phase 1 (Accuro + OSCAR Pro).** P3's cost analysis ($70K-$140K CAD combined) is realistic for a solo operator. Phase 1 = $70K-$140K; Phase 2 (TELUS, deferred) is additional $35K-$65K + partner-program wait.
5. **Competitive window is ~12 months.** P4 §4.6: every week without an anchor Alberta pilot is a week Dr. Bill / Petal might ship their own "AI audit check." The W1.3 outreach and W6 anchor-pilot target are urgency-pacing.

### Sources (all in `research/`)

- `P1-biller-workflow.md` (350 lines) — Alberta biller day-in-the-life, H-Link weekly batch, Slot A vs Slot B
- `P2-ahcip-submission.md` (284 lines) — H-Link operator, batch cadence, 90-day reconsideration, Slot A higher-leverage with 7-dim table
- `P3-emr-integration.md` (280 lines) — per-EMR profiles, FHIR adoption matrix, quickest-to-market ranking, cost table
- `P4-competitors.md` (226 lines) — 5 US AI billing tools (LOW threat), 4 Canadian competitors (Dr. Bill HIGH, Petal HIGH, WELL/ClinicAid MEDIUM), 7 competitive blind spots, 6-item moat inventory, 9-item defensive-build list
- `P5-customer-signal.md` (357 lines) — zero real-clinic pipeline, Lead-model gap, top-3 re-ranked (Red Deer PCN → Sherwood Park Strathcona PCN → West Springs Medical), channel-partner pull, audit-first outreach templates
- `P6-product-gaps.md` (207 lines) — 12 gaps with priority scoring, top-5 deep dives, out-of-scope list

### Decision log (for Q4 retrospectives)

| Decision | Date | Why | Revisit when |
|---|---|---|---|
| Single-product Alberta AHCIP auditor (Strategy A) | 2026-06-28 | P1+P2 confirm Slot A is higher-leverage; P4 confirms wedge uncontested for 12-18 months; P5 confirms zero pipeline = can't justify opening second front yet | After 3+ paid pilots + 90 days refusal-pattern data, Q4 review |
| Accuro first, OSCAR Pro second, TELUS PSS deferred to Q4 | 2026-06-28 | P3 §3 fastest-to-market ranking + cost concentration ($70K-$140K for top 2) | After first anchor PSS clinic signs; if no PSS clinic in pipeline by Q4, defer further |
| Synthetic-data demo path (G9) as Week 1 priority | 2026-06-28 | P6 priority 80, P5 zero pipeline, P4 §5.1 mobile onboarding bar | After first 10 demo-runs convert or don't |
| Red Deer PCN as primary PCN pilot target | 2026-06-28 | P5 §2.2 — MAPS structural-change signal + 14-doctor growth = strongest Rule-2 reason; PCN-leverage math (one deal = 60-80 physicians) | After W10 if no Red Deer movement; drop to Sherwood Park Strathcona PCN |
| West Springs Medical as first paid-pilot target | 2026-06-28 | P5 §2.2 — verified Feb 9 2026 locum posting = active hiring, mid-tier economics, fastest procurement | After W6 if West Springs stalls; pivot to other 6-10 physician candidates in P5 §2.4 |
| Out-of-scope: H-Link, Slot B, OHIP/MSP, multi-clinic tenant, doctor portal | 2026-06-28 | P1+P2+P4+P6 all point away; engineering budget cannot stretch | Q4 review with 90 days of real data |

---

*End of P0 roadmap. 12-week plan is executable starting Monday 2026-06-29. The single most important Monday-morning action: send the first three audit-first cold-outreach emails before doing any other Week 1 work. The pipeline gate is more important than the product gate.*