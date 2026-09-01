# Zorva marketing and sales plan

**Status:** proposed operating plan; execution and public claims remain gated  
**Owner:** Cameron Ashley  
**Last reconciled:** 2026-08-28  
**Authority:** supporting plan under `docs/MASTER_PLAN.md`

## Objective

Generate and convert a small number of qualified Alberta primary-care clinic
pilots while proving that Zorva can acquire, onboard, support, and retain a
clinic safely and economically. The goal is customer evidence, not maximum
traffic or a broad awareness launch.

## Audience and buying group

- Primary champion: billing lead or practice manager accountable for claim
  quality and rework.
- Economic decision-maker: clinic owner or operating lead.
- Trust reviewers: privacy officer, IT/security reviewer, and where relevant the
  clinic's billing consultant.
- Initial qualification: Alberta primary care, AHCIP billing, meaningful claim
  volume, a named workflow owner, willingness to keep a human reviewer in the
  loop, and ability to complete privacy/onboarding requirements.
- Disqualify for now: requests for autonomous submission, unsupported provinces
  or payers, unapproved PHI handling, guaranteed savings, or enterprise features
  that would derail the controlled pilot.

These criteria are hypotheses until direct customer evidence validates them.

## Positioning and message hierarchy

1. **Category:** human-reviewed, pre-submit AHCIP claim audit.
2. **Promise:** help Alberta clinic billing teams find defensible claim problems
   before submission and retain a traceable decision record.
3. **Why now:** the workflow is difficult to review consistently and existing
   manual effort does not scale across every candidate claim.
4. **Proof:** show the actual workflow, published evaluation method and limits,
   human approval controls, and verified security/operational evidence.
5. **Boundary:** Zorva advises; the clinic's authorized biller decides. It does
   not autonomously bill, guarantee recovery, or replace professional judgment.

The current value proposition and all quantitative wording require claim review
before public promotion. Do not reuse historical North American, AWS-region,
HIPAA, savings, accuracy, or “self-improving” language without current evidence.

## Offer and conversions

- Primary conversion: request a qualified pilot conversation through the
  reviewed `/contact` journey.
- Secondary conversions: review how it works, inspect approved trust evidence,
  and respond to individually approved founder or partner outreach.
- Initial offer: a controlled pilot with defined inputs, human review, privacy
  requirements, success criteria, start/end decision points, and support owner.
- Pricing, pilot duration, included volume, discounts, refunds, service levels,
  and guarantees remain owner decisions and must not be published or sent until
  expressly approved.

## Channel sequence

### 1. Founder-led, evidence-building acquisition

- Warm introductions, existing professional network, and carefully qualified
  one-to-one outreach.
- Use a documented qualification rubric and log every touch in Zorva HQ.
- External messages require owner approval; no automated or bulk sends.

### 2. Billing consultant and referral channel

- Validate whether consultants see Zorva as complementary and can identify
  suitable clinics.
- Define referral ownership, privacy boundary, conflict handling, and any
  commercial terms before commitment.

### 3. High-intent organic discovery

- Promote only evidence-approved pages answering buyer questions about AHCIP
  pre-submit review, workflow, evaluation limits, privacy, onboarding, and pilot
  fit.
- Build comparison, FAQ, methodology, glossary, and case-study content only
  where it is original, useful, and supported by approved evidence.
- Verify conventional search and AI-search discoverability; promise neither
  rankings nor citations.

### 4. Paid acquisition

Deferred until lead routing, attribution, qualified conversion, customer value,
cost-to-serve, consent, and spending approval are proven.

## Website plan

The existing Next.js portal is also the marketing-site codebase. Keep the public
and authenticated information architecture distinct.

1. Maintain the approved core journey: `/` -> `/how-it-works` -> `/contact` ->
   confirmation and operator follow-up.
2. Verify contact delivery, ownership, consent, privacy, abuse controls,
   attribution, duplicate handling, failure alerts, and response operations.
3. Reconcile the homepage and core pages with the approved brand promise and
   real evidence.
4. Promote deferred routes one at a time using
   `docs/MARKETING_PUBLIC_LAUNCH_GATES.md`; do not launch the entire inventory as
   a batch merely because routes exist.
5. Prioritize buyer trust and decision pages before low-intent content: approved
   security/privacy evidence, pilot fit, evaluation methodology, FAQ, and only
   then comparison, educational, or case-study expansion.
6. Validate mobile, keyboard, screen-reader, browser, performance, SEO, consent,
   analytics, form routing, error/recovery, and production release identity.

## Brand-system work

- Preserve the Zorva name, teal recognition, quiet clinical character, and
  confident/specific voice unless customer evidence supports a change.
- Reconcile `docs/BRAND_BOOK.md`, `docs/BRAND_NARRATIVE.md`, `docs/VOICE.md`, and
  implemented tokens against the current Alberta-first position.
- Replace or withdraw unsupported anchor phrases and infrastructure, compliance,
  performance, or customer-result claims.
- Stress-test the system across homepage, product dashboard, Zorva HQ, discovery
  email, pilot one-pager, onboarding checklist, support response, and reporting.
- Record logo/font/imagery licensing and accessibility evidence rather than
  assuming it.

## Funnel ownership and measurement

| Stage | Required record | Primary measure | Owner |
| --- | --- | --- | --- |
| Visit or sourced prospect | source/campaign and consent state | qualified visits or prospects | Marketing |
| Contact | deduplicated Lead and delivery outcome | completion and delivery rate | Marketing / Sales |
| Qualified | rubric, owner, next action, reason | qualification rate and response time | Sales |
| Demo | date, attendees, objections, outcome | qualified-to-demo rate | Sales |
| Pilot approved | approved offer and privacy prerequisites | demo-to-pilot rate | Owner |
| Onboarded | checklist and first-value timestamp | completion and time to first value | Client success |
| Active pilot | usage aggregates, support, outcomes | weekly activity and support burden | Client success |
| Decision | paid, extend, or stop with evidence | pilot-to-paid and reasons | Owner |

Targets remain unset until baselines and a viable sample exist. Zorva HQ should
calculate stage history from immutable events and distinguish unknown from zero.

## First 90-day execution sequence

### Foundation

- Finish release/CI and production-identity gates.
- Verify contact routing and establish the Zorva HQ authorization foundation.
- Reconcile brand, claims, offer, and core website copy.
- Define pilot qualification, consent, success, support, and stop criteria.

### Controlled acquisition

- Assemble a small, evidence-based prospect set from approved sources.
- Obtain approval for exact outreach and send manually in bounded batches.
- Record objections and funnel events; improve qualification and materials.

### Pilot and learning

- Operate the first approved clinic pilot through Zorva HQ.
- Measure activation, first value, finding decisions, workflow burden, support,
  cost, trust concerns, and renewal intent.
- Publish no testimonial, logo, result, or case study without explicit written
  permission and claim review.

### Decision

- Compare evidence with success and stop thresholds.
- Keep, revise, narrow, or abandon the offer; approve pricing and broader
  acquisition only if customer value and economics support it.

## Approval gates

Explicit approval is required before production publication, domains/DNS,
customer-visible offer or pricing changes, external messages, paid campaigns,
purchases or higher spending, customer/logo/testimonial use, legal or regulated
claims, sensitive production-data access, or acceptance of critical/high risk.

## Current blockers

- GitHub Actions runners cannot start because of the account billing/spending
  state.
- Portal production release identity is unproven and `/readyz` returns 404.
- Contact delivery and named ownership are not live-verified.
- Pilot offer, pricing, legal/privacy wording, and customer evidence are not
  approved.
- Zorva HQ is specified but not implemented.
