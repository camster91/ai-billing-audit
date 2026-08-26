# Zorva marketing site: public-readiness plan

## Goal

Deliver a credible, accessible, dark-only Zorva marketing experience that can be released publicly **after** product-owner, legal, billing, and operational launch gates are evidenced. This plan does not authorize public launch, payment activation, outbound email, or unverified marketing claims.

## Current context

- The public Next.js portal is served at `zorva.ashbi.ca`; its landing page and core marketing routes are live.
- The portal design system is intentionally dark-only. `apps/portal/AGENTS.md` prohibits a light-theme redesign or a light/dark toggle.
- Legal routes exist at `/legal/privacy` and `/legal/terms`; links must point to those canonical paths.
- PR #62 contains a light editorial homepage redesign. It must not be merged as-is because it conflicts with the dark-only design rule and includes an unverified testimonial.
- Public routes and copy must describe only capabilities, policies, pricing, pilot status, compliance posture, outcomes, and customer feedback supported by approved evidence.

## Success criteria

1. A refreshed homepage and navigation remain visually consistent with the dark-only Zorva system at desktop and mobile widths.
2. Every public CTA, navigation item, legal link, and contact path resolves correctly; an authorized staging magic-link test proves email delivery, callback handling, session creation, and a protected portal database read.
3. Public copy has a reviewed claim register; unsupported performance metrics, customer quotes, compliance certifications, customer names, or availability claims are removed or explicitly approved.
4. Search and sharing metadata, robots directives, canonical URLs, favicon/manifest assets, and social preview assets are complete and verified.
5. The release passes lint, TypeScript, production build, route/link smoke tests, keyboard and automated accessibility checks, responsive visual QA, and a trusted public HTTPS smoke after deployment.
6. A separate launch-gate record shows that billing, transactional email, legal approval, monitoring, support ownership, and rollback are either verified or explicitly held out of the public offer.

## Proposed implementation sequence

### 1. Establish approved marketing inputs

- Create a claim register for every homepage and public-route statement. For each claim capture: source, owner, approval date, intended route, and expiry/re-review date.
- Classify copy as one of: verified product behavior, approved policy/contract language, approved pricing, pilot invitation, or unsupported.
- Remove anonymous testimonials and numerical outcome claims unless a named owner confirms the wording, attribution, permission, and publishing scope.
- Use precise, non-certification language for HIA, PHIPA, PIPEDA, HIPAA, AIDA, AKS, and data residency until legal/compliance approves the applicable statement.
- Decide the public conversion model: contact/demo request only until Stripe and transactional email have passed sandbox and production-readiness checks; do not imply self-serve purchase if it is unavailable.

### 2. Design the refreshed homepage within the existing system

- Rework `apps/portal/src/app/page.tsx` and `page.module.css` using the existing dark palette and typography tokens from `globals.css` and the portal design rules.
- Keep the current information hierarchy: value proposition, how it works, evidence-based trust/security explanation, conversion CTA, and real legal/footer navigation.
- If retaining an audit mockup, label it as illustrative/demo content and make no claim that it represents a real clinic, patient, encounter, or outcome.
- Prefer local, optimized, properly licensed assets. Do not add external Google font CSS; use the project's existing font loading or commit licensed local assets.
- Use semantic sections, a single H1, descriptive headings, native controls, keyboard-visible focus states, and reduced-motion behavior.

### 3. Repair and complete the public route surface

- Audit all public routes: `/`, `/pricing`, `/how-it-works`, `/security`, `/contact`, `/legal/privacy`, `/legal/terms`, `/login`, `/faq`, `/trust`, `/pilot`, `/demo-request`, and any route surfaced by navigation or search metadata.
- Align the shared `layout.tsx` navigation and footer with the actual canonical public routes. Remove dead, duplicate, or premature conversion paths.
- Confirm the contact form has clear success/failure states, accessible field errors, abuse protection decisions, retention disclosures, and an owned recipient workflow before promoting it.
- Add or correct `sitemap.ts`, `robots.ts`, route-level metadata, Open Graph/Twitter previews, canonical URLs, favicon, and manifest assets. Do not index authenticated, internal, preview, or demo-only routes.

### 4. Make pricing and trust language safe to publish

- Validate pricing cards against the currently configured product offer. If live Stripe prices are not configured and tested, use a contact/demo CTA rather than checkout.
- Cross-check security and privacy pages against the approved data-flow, regional hosting, processor list, retention/deletion policy, incident process, and legal documents.
- Make pilot status explicit where appropriate; avoid representing planned features, certifications, customer results, or integrations as currently available.
- Have the product owner approve the final claim register and the legal owner approve privacy, terms, pricing, and security wording before deployment.

### 5. Validate before merge and after staged deployment

- Run portal lint, TypeScript (`tsc --noEmit`), Prisma generation, and production build.
- Add route/link smoke coverage for every public route and every header/footer/primary CTA destination.
- Run the existing keyboard and automated accessibility scripts; add Playwright coverage at 375px, 768px, and 1440px for the homepage, pricing, contact, legal, and login surfaces.
- Check page titles, descriptions, canonical metadata, robots output, sitemap output, images, contrast, focus visibility, headings, landmarks, and reduced-motion behavior.
- In a staged deployment: create backups and rehearse restore; build immutable images; run required migrations; verify the FastAPI `/readyz` on the API host and the portal `/readyz` on the portal host; then run the authorized magic-link flow through delivery, callback, session creation, and a protected database-backed portal read before testing the remaining trusted public HTTPS routes.
- Record deployed SHA, backup location, rollback image/tag, health evidence, public-route evidence, and every remaining launch gate.

## Likely files

- `apps/portal/src/app/page.tsx`
- `apps/portal/src/app/page.module.css`
- `apps/portal/src/app/layout.tsx`
- `apps/portal/src/app/globals.css`
- `apps/portal/src/app/{pricing,security,how-it-works,contact,legal}/...`
- `apps/portal/src/app/robots.ts` and a new/updated `apps/portal/src/app/sitemap.ts`
- `apps/portal/public/` for approved, optimized brand/share assets
- `apps/portal/tests/e2e/` and existing accessibility scripts
- `apps/portal/README.md` and launch/readiness documentation

## Risks and explicit gates

| Risk or gate | Required evidence before public launch |
| --- | --- |
| Marketing claims | Approved claim register and publishing permission |
| Testimonials/case studies | Attribution, permission, exact approved wording, and expiry/review owner |
| Privacy, security, and legal copy | Legal/compliance sign-off against actual architecture and processors |
| Payments | Stripe products, keys, webhook, checkout, cancellation/refund, and sandbox evidence |
| Transactional email | Verified sender/domain plus an authorized staging magic-link test covering delivery, callback, session creation, and a protected portal read; unsubscribe/retention handling and human support owner |
| Accessibility | Automated and keyboard tests plus responsive/manual browser verification |
| Production release | Backup/restore rehearsal, immutable SHA, migration gate, container health, trusted HTTPS smoke, rollback path |

## Decisions needed before implementation

1. Which supported claims, customer stories, logos, and assets have explicit public-display approval?
2. Is the public conversion CTA contact/demo only, or is self-serve checkout intended for this release?
3. Who owns legal/compliance approval and inbound lead response?
4. Should PR #62 be closed, or should its visual ideas be reimplemented in a dark-only follow-up branch after this plan is approved?
