# Zorva brand system

**Status:** reconciled strategic and production reference; external use remains approval-gated
**Owner:** Cameron Ashley
**Last reviewed:** 2026-09-01
**Review cadence:** with every claim-bearing release and at least quarterly

This is the consolidated decision system for Zorva's identity and expression.
It preserves the recognizable name, teal/charcoal palette, quiet editorial
character, and human-control message while aligning them with the current
Alberta-first product plan.

## Authority and conflict order

1. `docs/MASTER_PLAN.md` controls audience, market, offer, product status, and
   business commitments.
2. An approved claim record controls whether an exact statement may be used on
   an exact surface.
3. This book controls brand strategy, verbal identity, visual principles, and
   cross-channel recognition.
4. Per-discipline `docs/BRANDING_*.md` files control production detail only
   where they do not conflict with the first three sources.

A documented design rule does not authorize publication, outreach, pricing,
spending, customer-material use, regulated claims, or sensitive-data access.

## Foundation

### Business objective

Earn qualified Alberta clinic conversations and operate a controlled pilot
without overstating product evidence or weakening human, privacy, and release
controls. The brand must make a complex regulated workflow feel understandable
and accountable, not effortless or automatic.

### Audience

- **Primary champion:** Alberta clinic billing lead or practice manager.
- **Decision-maker:** clinic owner or operating lead.
- **Trust audience:** privacy, security, IT, and where relevant a billing
  consultant.
- **Internal users:** Zorva sales, client-success, support, marketing, analyst,
  and owner roles using Zorva HQ.

The brand does not currently address every Canadian province, US healthcare,
enterprise revenue integrity, autonomous billing, or a mass self-serve market.

### Positioning

For Alberta primary-care billing teams that need a deliberate review step before
submission, Zorva is a human-reviewed AHCIP claim-review workflow that brings
available context and supporting references into one path while keeping the
final decision with the clinic.

### Message system

| Layer | Approved direction |
| --- | --- |
| Category | Human-reviewed pre-submit AHCIP claim review |
| Positioning line | Review Alberta claims with your billing team in control. |
| Promise | Bring the available context into review and keep the final submission decision with the clinic. |
| Proof | Show implemented workflow evidence, exact source scope, and honest limitations. |
| Primary CTA | Start a conversation. |
| Boundary | No autonomous submission, customer outcome promise, pricing implication, or regulated-status claim. |

These are strategic directions, not blanket publication permissions.

### Reasons to believe

- The product has an implemented human accept/dismiss decision workflow.
- The public core explains a pre-submit review path and directs to a reviewed
  contact request.
- Zorva HQ records ownership, next actions, activity, support, client work,
  marketing governance, and company reporting without default PHI access.
- Release and claim processes distinguish local, synthetic, production, and
  customer evidence.

These support the category and operating posture. They do not prove accuracy,
coverage, savings, compliance, reliability, adoption, or product-market fit.

### Desired perception

Use these tensions to make decisions:

- **Clinical, not institutional:** orderly and calm without imitating a hospital
  or making a compliance claim.
- **Confident, not certain:** clear direction with uncertainty and evidence
  boundaries visible.
- **Editorial, not decorative:** hierarchy and purposeful contrast rather than
  visual novelty.
- **Technical, not opaque:** show sources and workflow without overwhelming the
  decision-maker.
- **Helpful, not autonomous:** support accountable work rather than implying the
  person can be removed.

## Verbal identity

`docs/VOICE.md` is the detailed source. The essential rules are:

1. Name the market and workflow before the benefit.
2. Identify who decides and what the next step is.
3. Distinguish available context from guaranteed completeness.
4. Label evidence as synthetic, local, production, or customer-derived.
5. Say unknown, unavailable, proposed, or blocked when that is the truth.
6. Never repair weak evidence with stronger adjectives.

### Safe pattern lines

- “Start with workflow questions, not patient or claim data.”
- “The clinic's authorized biller keeps the final decision.”
- “This is local candidate evidence, not production or customer evidence.”
- “The current step is a reviewed conversation, not self-serve access.”

### Claims that require separate approval

All metrics, prices, terms, guarantees, customer outcomes, testimonials,
certifications, regulatory conclusions, residency, security architecture,
processors, retention/deletion, integrations, availability, service levels, and
competitive comparisons require a source, owner, approval state, allowed
surface, and review/expiry date.

## Visual identity

### Recognition to preserve

- Name: **Zorva**, title case.
- Primary recognition colour: teal.
- Supporting field: charcoal/navy with restrained amber for review attention.
- Character: quiet, clinical, high-contrast, evidence-conscious.
- Layout: generous negative space, visible hierarchy, borders and tone rather
  than decorative shadows.

### Logo status

The repository now contains a deterministic candidate Z-in-rounded-hex mark,
light/dark wordmarks and lockups, favicons, and the documented iOS, Android, and
macOS raster inventory. Sources, hashes, consumers, accessibility treatment,
and approval state are recorded in `docs/BRAND_ASSET_MANIFEST.json`. Human visual
approval, trademark review, ownership acceptance, and production publication
remain separate gates; do not describe these candidates as approved or shipped.

When produced, the mark must retain title-case Zorva, a teal recognition hook,
clear space, small-size legibility, monochrome viability, and documented source
and licence evidence.

### Colour roles

Source: `docs/BRANDING_COLORS.md` and implemented portal tokens.

| Role | Direction |
| --- | --- |
| Action and recognition | Teal; use the darker accessible role for ordinary text on light surfaces |
| Review attention | Amber; never use it to imply revenue gain, urgency, or success |
| Product and marketing field | Charcoal/navy, white, and slate surfaces |
| Status | Use semantic success, warning, error, and information roles with text or icon labels |

Do not introduce a raw colour where a semantic token exists. Colour is never
the only carrier of meaning. Verify contrast in the rendered context.

### Typography

The implemented system intentionally adapts by channel:

| Channel role | Family | Use |
| --- | --- | --- |
| Product, HQ, forms, long-form body | Inter | Functional clarity and dense UI |
| Marketing editorial display | Fraunces | One dominant headline level; never product tables or controls |
| Marketing evidence/eyebrow labels | IBM Plex Mono | Compact labels only, never long body copy |
| Code and technical traces | JetBrains Mono | Real code, identifiers, and audit traces |

All are loaded through `next/font` in the portal. Repository source proves the
implementation, not independent trademark clearance or a complete licence
inventory; retain the documented licensing review gate for exported assets.
Fallbacks must remain legible. Do not add another family without a brand and
performance review. Never render essential text below 12 px.

### Imagery and product evidence

The homepage uses a code-drawn illustrative review panel. Main now carries the
claim-safe version from PR #101. The contract requires a visible `Illustrative`
label and prohibits patient identity, fabricated fee code, dollar result,
customer outcome, or an implication that the panel is live output.

The nine-illustration inventory in `docs/BRANDING_IMAGERY.md` is proposed, not
present in `apps/portal/public/`. Do not claim those assets exist. Photography
requires source/licence evidence, releases for recognizable people or property,
and a no-PHI background review.

### Motion and interaction

- Motion supports state change; it never manufactures urgency.
- Respect `prefers-reduced-motion`.
- Keep focus visible and keyboard order logical.
- Use the smallest useful transition and avoid parallax or decorative first-paint
  animation.
- Never hide a required limitation, approval state, or recovery action behind
  hover-only interaction.

## Channel adaptation

| Surface | Retained recognition | Adaptation | Must not bend |
| --- | --- | --- | --- |
| Public website | Zorva name, teal, editorial headline, human-control message | More whitespace and narrative sequencing | Approved routes, claims, CTA, and no-sensitive-contact boundary |
| Customer product | Zorva name, teal action, calm hierarchy | Inter-first, dense evidence and decision controls | Tenant isolation, uncertainty, source, status, and human decision |
| Zorva HQ | Same tokens and direct voice | Operational density, owner/due-date emphasis | Platform authorization, no-PHI default, audit and external-action gates |
| Launch material | Positioning, palette, one CTA | Shorter narrative and visible draft state | Claim IDs, approval state, attribution, no invented proof |
| Discovery call | Calm, curious, specific | Questions before assertions | No PHI, unapproved terms, or automatic follow-up |
| Onboarding | Clear sequence and recovery | Reassuring, prerequisite-led | Privacy review before clinic data and no hidden activation |
| Support | Calm accountability | Status, owner, safe summary, next internal action | No invented SLA, diagnosis, blame, or unnecessary clinical detail |
| Company reporting | Evidence labels and restrained colour | Dense metric definitions and unknown/zero states | No vanity success state or unsupported aggregation |

## Representative stress tests

Before approving a new asset, test it in these situations:

1. **Small mobile hero:** audience, workflow, human boundary, and CTA remain
   understandable without secondary sections.
2. **Dense finding or HQ table:** status, owner, evidence, and action remain
   scannable without relying on colour.
3. **High-emotion support state:** the language stays calm, avoids blame, and
   does not promise a resolution time.
4. **Security question:** the response cites current evidence or records the
   question; it never improvises a conclusion.
5. **Sales objection about ROI or price:** the operator states that terms or
   outcomes are unapproved rather than quoting a historical draft.
6. **Exported one-pager/deck:** draft state, reading order, link purpose, source
   IDs, contrast, and text extraction survive export.

## Asset and specification truth

| Artifact | Current state |
| --- | --- |
| Portal colour and font tokens | Implemented; rendered checks remain release-specific |
| Text navigation wordmark | Implemented |
| Z-in-hex logo, favicons, app icons | Candidate source and delivery pack implemented with manifest/tests; human approval, clearance, and publication remain gated |
| Nine line illustrations | Proposed in `docs/BRANDING_IMAGERY.md`; directory not found |
| Icon wrapper inventory | Specification exists; verify each implementation before use |
| Pitch deck | Reconciled approval-gated specification only; no approved source deck/export |
| Case-study template | Template only; no customer evidence or permission implied |

## Governance

- Cameron Ashley owns brand and claim decisions until another accountable owner
  is explicitly assigned.
- Exceptions require a recorded rationale, affected surface, expiry/review date,
  and approval. An exception never weakens legal, privacy, security, or release
  gates.
- Every external asset is versioned. Publication and sending are separate from
  content approval.
- Review this book after a positioning decision, approved customer evidence,
  new market, new visual family, regulated claim, or material implementation
  change.
- Historical assets remain historical. Do not recover copy merely because it
  once appeared in a source-of-truth file.

## Asset acceptance checklist

- [ ] Audience, job, category, and CTA match the master plan.
- [ ] Promise and proof are separated; every claim has current approval.
- [ ] Human decision ownership and key limitations are visible.
- [ ] The exact channel adaptation retains recognition without importing an
  unapproved claim.
- [ ] Typography, colour, imagery, and interaction follow the implemented roles.
- [ ] Contrast, keyboard behavior, reading order, reduced motion, alt text, and
  export behavior are verified in context.
- [ ] Customer or prospect material has permission and contains no PHI.
- [ ] Pricing, spending, publication, send, regulated claims, production access,
  and sensitive-data gates are independently satisfied.
- [ ] The final artifact, source, owner, version, approval, and review date are
  recorded.
