# Zorva public marketing launch gates

## Current release posture

The public marketing release is **not approved for launch**. The indexable
surface is deliberately limited to the evidence-conscious core routes below.
All other public pages remain reachable for existing recipients but emit an
`X-Robots-Tag: noindex, nofollow` response and are excluded from `robots.txt`
and the sitemap until their published claims are approved.

| Route | Discovery posture | Reason |
| --- | --- | --- |
| `/` | Indexable | Capability-focused homepage; no testimonial, performance metric, pricing, or operational promise. |
| `/how-it-works` | Indexable | Human-reviewed workflow explanation; no promise of integrations, outcomes, or automated submission. |
| `/contact` | Indexable | Request form without a response-time, calendar, or service-level promise. |
| Pricing, security, trust, pilot, status, case studies, comparison, technical, press, FAQ, legal, and specialty pages | Noindex | Content requires product-owner, legal, security, operational, or publication evidence before search discovery. |

## Evidence required before a deferred route can be indexed

1. A named content owner approves exact copy and its intended route.
2. The claim register records a source, approval date, reviewer, and required
   re-review date for every metric, customer story, price, availability promise,
   regulation/compliance statement, support SLA, testimonial, and case study.
3. The route has an owner responsible for keeping the claim current.
4. An accessibility and public-route smoke test passes after the route is
   deployed to the trusted HTTPS host.

## Required launch gates

| Gate | Evidence required | Current state |
| --- | --- | --- |
| Marketing claims | Approved claim register and public-display permission for any customer, outcome, testimonial, or case-study material | Open |
| Security and trust | Architecture review of data residency, encryption, processors, retention/deletion, access controls, and certifications | Open |
| Legal | Approved privacy policy, terms, pilot agreement language, and regional regulatory wording | Open |
| Pricing and payments | Approved offer, Stripe products/keys/webhooks, sandbox checkout/cancel/refund evidence, and an owner for price changes | Open |
| Contact and email | Verified recipient workflow, sender domain, delivery/bounce handling, response owner, retention policy, and abuse controls | Open |
| Status and monitoring | Real monitored source, incident owner, public update process, and evidence-backed uptime history | Open |
| Accessibility | Keyboard, automated accessibility, responsive, and manual browser checks on the deployed public routes | Open |
| Release operations | Restore-verified backups, immutable release SHA, migration gate, container health, trusted HTTPS smoke, and rollback procedure | Open |

## Local verification recorded for this change

- `git diff --check` passes.
- `pnpm --dir apps/portal lint` passes.
- `pnpm --dir apps/portal exec tsc --noEmit` passes.
- `pnpm --dir apps/portal build` compiles and type-checks but cannot complete
  route-data collection without a configured production-compatible
  `DATABASE_URL`; it fails at `/api/audit/export` before a local database is
  available. This is an environment gate, not proof of a releasable build.

## Promotion checklist

1. Approve a deferred route's claim register.
2. Remove that route from the noindex lists in `src/middleware.ts` and
   `src/app/robots.ts`.
3. Add the route to `src/app/sitemap.ts` only after its live public smoke and
   accessibility evidence is attached to the release.
4. Build an immutable release, run migrations, verify health, and test the
   trusted public HTTPS route.
5. Record the release SHA, evidence, backup location, rollback image/tag, and
   any remaining gates before describing the route as public.
