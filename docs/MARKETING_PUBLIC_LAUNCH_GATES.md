# Zorva public marketing launch gates

## Current release posture

The public marketing release is **not approved for a full marketing launch**.
The indexable surface is deliberately limited to the evidence-conscious core routes below.
All other public marketing URLs temporarily redirect to `/contact` with an
`X-Robots-Tag: noindex, nofollow` response until their published claims are
approved. They are intentionally crawlable so search engines can observe the
noindex redirect, but they are excluded from the sitemap.

| Route | Discovery posture | Reason |
| --- | --- | --- |
| `/` | Indexable | Human-reviewed Alberta workflow and conversation CTA registered in `docs/PUBLIC_CLAIM_REGISTER.md`; no testimonial, performance metric, pricing, compliance, infrastructure, or operational promise. |
| `/how-it-works` | Indexable | Human-reviewed workflow explanation; no promise of integrations, outcomes, or automated submission. |
| `/contact` | Indexable | Request form without a response-time, calendar, or service-level promise. |
| About, blog, calculator, careers, case studies, changelog, comparison, demo request, FAQ, specialty, glossary, legal, pilot, press, pricing, security (including the one-pager), status, technical, trust, and try pages | Temporary noindex redirect | Content requires product-owner, legal, security, operational, or publication evidence before it is served or eligible for search discovery. |

## Production evidence recorded — 2026-08-12

The core surface was deployed on the trusted host from immutable merge commit
`f835efe7308f7a6b8723103087437d70eb4d93a5`.

- `/`, `/how-it-works`, and `/contact` returned HTTPS 200 and remained
  indexable; the sitemap listed exactly those routes.
- `/security`, `/pricing`, and `/security.pdf` returned a 307 to `/contact`
  with `X-Robots-Tag: noindex, nofollow`; `/.git/HEAD` returned 404.
- `robots.txt` permits the deferred redirects to be crawled and blocks
  protected application routes. HTTP redirects to HTTPS. CSP, HSTS,
  `X-Content-Type-Options`, and `X-Frame-Options` were present.
- The portal was healthy from that immutable working directory. The API,
  worker, Caddy, and both PostgreSQL services remained healthy. Fresh logical
  backups were taken, and the portal backup was restored successfully into an
  isolated PostgreSQL 16 rehearsal database. A tagged prior portal image was
  retained for rollback.
- Browser checks on the deployed core routes at 375px and 1440px found exactly
  one H1, no horizontal overflow, English document language, labelled contact
  controls, and no captured browser-console errors.

This is release evidence, not evidence that every deferred route, business
claim, external operational process, or cross-browser accessibility gate is
ready to publish.

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
| Contact and email | Verified recipient workflow, sender domain, delivery/bounce handling, response owner, retention policy, and abuse controls | Partial — `/api/leads` has a bounded per-client application backstop and uses the configured Auth.js Resend key when no dedicated lead key is supplied; verify a managed edge/WAF limit, real delivery/bounce handling, retention policy, and response ownership before launch |
| Status and monitoring | Real monitored source, incident owner, public update process, and evidence-backed uptime history | Partial — a host cron probes `https://ai-billing-audit.ashbi.ca/healthz` every five minutes and records state/logs; configure an alert destination, incident owner, public update process, and uptime history before launch |
| Accessibility | Keyboard, automated accessibility, responsive, and manual browser checks on the deployed public routes | Partial — Chrome-derived responsive/browser checks passed for the three core routes; Safari, Firefox, assistive-technology, and independent automated accessibility evidence remain open |
| Release operations | Restore-verified backups, immutable release SHA, migration gate, deterministic Docker artifact build evidence, container health, trusted HTTPS smoke, and rollback procedure | Passed for the 2026-08-12 portal cutover; repeat for every release |

### Monitoring installation evidence — 2026-08-17

The VPS now runs `/usr/local/bin/zorva-monitor` from `/etc/cron.d/zorva-monitor`
every five minutes. It invokes the committed `monitor_live_url.py` probe against
the authenticated API health endpoint, keeps its failure counter in
`/var/lib/zorva/monitor_state.json`, and appends a heartbeat to
`/var/log/zorva-monitor.log`. The first production check returned HTTP 200.

`/etc/zorva-monitor.env` is root-readable only and intentionally contains an
empty webhook setting. Do not represent this log-only monitor as a page or
incident-notification service until an approved alert destination and owner
are configured and tested.

## Local verification recorded for this change

### Core homepage claim reconciliation - 2026-09-01

- Removed historical revenue-loss, blanket coverage, fee-code, synthetic-dollar,
  pricing, infrastructure, residency, compliance, and contractual statements
  from the indexable homepage.
- Replaced them with the bounded claims in `docs/PUBLIC_CLAIM_REGISTER.md` and
  one conversion journey through `/how-it-works` and `/contact`.
- Added source-level regression tests across all three reviewed routes. Three
  claim/route/illustration tests pass; focused ESLint and the full TypeScript
  project pass under Node 20 after both Prisma clients are generated.
- Local Chromium checks at 1440px and 375px returned one H1, no horizontal
  overflow, no console errors, and no homepage links to deferred routes.
- Axe scanned every public route with zero WCAG 2 A/AA violations; homepage
  and route-level incomplete checks still require manual review. This is local
  candidate evidence, not production release evidence.

- `git diff --check` passes.
- `pnpm --dir apps/portal lint` passes.
- `pnpm --dir apps/portal exec tsc --noEmit` passes.
- An isolated disposable PostgreSQL 16 database was created, migrated with the
  two committed portal PostgreSQL migrations, used for `pnpm --dir
  apps/portal build`, and removed after the check. The production build
  completed successfully, including route-data collection and static-page
  generation.
- `docker build -f apps/portal/Dockerfile -t zorva-portal:marketing-pr64
  apps/portal` completed using its deliberately unreachable build database.
  The resulting local image reached Docker `healthy` and returned HTTP 200
  from `/login` with disposable test configuration.
- The same local image returned HTTP 200 without `X-Robots-Tag` for all three
  reviewed routes and a 307 `X-Robots-Tag: noindex, nofollow` redirect to
  `/contact` for all 22 deferred public URLs. Its `robots.txt` permits those
  redirects to be crawled, disallows protected routes, and its sitemap matched
  the reviewed-route policy.
- A local Chrome check at 375px and 1440px found one H1, no horizontal
  overflow, an English document language, named contact controls, a visible
  skip-link focus target, and no internal links to deferred routes on each
  reviewed page.
- `pnpm audit --prod --json` reports zero production dependency advisories
  after the bounded Next, Auth, Prisma, PostCSS, Fast URI, and Sharp updates.
  The upgraded Next 15.5.21 / Prisma 7.9.1 Docker image also completed its
  healthy-container smoke with the reviewed homepage at HTTP 200 and deferred
  `/security` at a 307 noindex redirect.
- That local container smoke is not production evidence: the production
  trusted host and its real runtime configuration still require an HTTPS
  smoke test after deployment.

## Promotion checklist

1. Approve a deferred route's claim register.
2. Remove that route from `src/lib/marketing-indexing.ts` so middleware serves
   its approved page instead of the temporary noindex redirect.
3. Add the route to `src/app/sitemap.ts` only after its live public smoke and
   accessibility evidence is attached to the release.
4. Build an immutable release, run migrations, verify health, and test the
   trusted public HTTPS route.
5. Record the release SHA, evidence, backup location, rollback image/tag, and
   any remaining gates before describing the route as public.
