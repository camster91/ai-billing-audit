# Portal — Zorva Marketing Site & Checkout

The public marketing portal for Zorva, a pre-submit medical claim auditor.

## What this app does

`apps/portal` is the customer-facing surface of Zorva. It serves the public
marketing site (landing page, pricing, security explainer, contact form), hosts
the Stripe-backed checkout flow, and runs the signed-in clinic workspace
(onboarding wizard, encounters, findings, billing dashboard, team & settings).

The marketing pages (`/`, `/pricing`, `/security`, `/how-it-works`,
`/contact`) and the public legal pages (`/privacy`, `/terms`) are intentionally
unauthenticated — a prospective buyer can read every pricing and compliance
detail without an account. The clinic workspace lives under `/portal/*` and
`/encounters`, `/findings`, `/billing`, `/team`, `/settings` and is gated by
NextAuth.js v5 magic-link sign-in.

Transactional email goes through Resend (magic-link sign-in, lead notifications,
billing receipts, welcome/onboarding drips). Stripe Checkout is invoked from
`POST /api/billing/checkout` and the lifecycle events are reconciled by
`POST /api/billing/webhook`. All persistent state lives in Prisma against the
configured `DATABASE_URL`.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Marketing landing page (value prop, three pillars, CTA to `/contact`). |
| `/pricing` | Three-tier CAD/USD pricing page with `CheckoutButton` per tier. |
| `/security` | Public security & compliance explainer (PIPEDA / AIDA / FFERA). |
| `/how-it-works` | Product walkthrough for prospective clinics. |
| `/contact` | Public lead-capture form (5 fields, posts to `/api/leads`). |
| `/privacy`, `/terms` | Legal pages linked from the footer. |
| `/login` | NextAuth.js v5 magic-link sign-in page. |
| `/portal/onboarding` | Signed-in `OnboardingWizard` (clinic → region → EHR → first encounter). |
| `/portal/billing` | Signed-in billing dashboard (current tier, invoices, change/cancel). |
| `/encounters`, `/findings` | Signed-in audit workspace. |
| `/billing`, `/team`, `/settings`, `/dashboard` | Signed-in management pages. |

## Stack

- **Next.js 15.5.19** (App Router) on **React 19.2.4** — `next dev`, `next build`.
- **Prisma 7.8** with the better-sqlite3 adapter (dev) and Postgres (prod),
  schema in `apps/portal/prisma/schema.prisma`.
- **Stripe 22.2** for Checkout Sessions, the Customer Portal redirect, and
  webhook-driven subscription lifecycle (`/api/billing/*`).
- **Resend 6.12** for transactional email (magic-link auth, leads, billing,
  onboarding drips) — see `src/lib/email.ts` and the templates under
  `src/lib/emails/`.
- **NextAuth.js v5 (beta)** with the Prisma adapter for magic-link sign-in.

## Local dev

```bash
# 1. install
pnpm install

# 2. point Prisma at the dev SQLite DB (copy .env.example to .env)
cp apps/portal/.env.example apps/portal/.env

# 3. apply SQLite migrations + generate both database clients
pnpm --filter portal exec prisma migrate deploy
pnpm --filter portal prisma:generate

# 4. run the app (http://localhost:3000)
pnpm --filter portal dev
```

With no `STRIPE_SECRET_KEY` set, `POST /api/billing/checkout` returns a stub
URL that points back at `/portal/onboarding`, so the full purchase → onboarding
loop works end-to-end without real Stripe keys. With no `AUTH_RESEND_KEY` set,
NextAuth falls back to logging the magic link to the terminal.

## Build

```bash
pnpm --filter portal build      # next build (Prisma generate is pre-build)
pnpm --filter portal start      # next start, defaults to :3000
```

The build step generates both SQLite and PostgreSQL clients automatically.
Production refuses a missing or SQLite `DATABASE_URL`. Apply the committed
PostgreSQL baseline before booting a release:

```bash
DATABASE_URL=postgresql://... pnpm --filter portal prisma:migrate:deploy:postgresql
```

The repository Docker Compose topology performs this through the one-shot
`portal-migrate` service and starts `portal` only after it succeeds.

## Key files

| File | Purpose |
| --- | --- |
| `src/app/page.tsx` | Marketing landing page (server component, no client hooks). |
| `src/app/pricing/page.tsx` | Three-tier pricing page; reads `getPricingConfig()`. |
| `src/app/pricing/CheckoutButton.tsx` | Client component that POSTs to `/api/billing/checkout`. |
| `src/app/security/page.tsx` | Public security & compliance explainer. |
| `src/app/contact/page.tsx` + `ContactForm.tsx` | Public lead-capture form. |
| `src/app/portal/onboarding/OnboardingWizard.tsx` | Multi-step signed-in onboarding wizard. |
| `src/app/layout.tsx` | Root layout (nav, fonts, metadata, theme). |
| `src/app/api/billing/checkout/route.ts` | `POST` — creates a Stripe Checkout Session (or demo stub). |
| `src/app/api/billing/webhook/route.ts` | `POST` — reconciles Stripe subscription lifecycle events. |
| `src/lib/pricing.ts` | Env-driven 3-tier pricing config (CAD/USD, names, caps, Stripe price IDs). |
| `src/lib/stripe.ts` | Stripe SDK singleton + tier-to-price-ID mapping. |
| `src/lib/email.ts` + `src/lib/emails/` | Resend client and React Email templates. |
| `src/lib/prisma.ts` | Prisma client singleton (better-sqlite3 in dev, Postgres in prod). |
| `prisma/schema.prisma` | Canonical tenant, user, subscription, encounter, finding, and audit-trail models. |
| `prisma/postgresql/migrations/` | Production PostgreSQL migration history. |
| `scripts/prepare-postgresql-schema.mjs` | Derives the PostgreSQL schema/client from the canonical model. |

## Env vars

Defined in `apps/portal/.env.example`. The portal reads:

- **`DATABASE_URL`** — Prisma datasource (SQLite file in dev, Postgres in prod).
- **`AUTH_SECRET`** — signs the NextAuth session cookie.
- **`AUTH_RESEND_KEY`** + **`AUTH_EMAIL_FROM`** — Resend API key and sender used
  for magic-link sign-in and all transactional email.
- **`FASTAPI_BASE_URL`**, **`FASTAPI_BEARER_TOKEN`**, and
  **`FASTAPI_PRINCIPAL_SIGNING_SECRET`** — server-only audit API URL and shared
  credentials used to sign five-minute, tenant-bound principals. Never expose
  the credential variables with a `NEXT_PUBLIC_` prefix.
- **`ZORVA_PHI_ENCRYPTION_KEY`** — URL-safe base64 encoding of exactly 32
  random bytes, used for AES-256-GCM encryption of staged claims and stored EHR
  credentials. The portal fails closed when it is missing or malformed.
- **`STRIPE_SECRET_KEY`**, **`STRIPE_PUBLISHABLE_KEY`**, **`STRIPE_WEBHOOK_SECRET`**
  — Stripe API keys and the webhook signing secret for `/api/billing/webhook`.
- **`PRICING_TIER_{SMALL,MID,LARGE}_{NAME,AUDIT_CAP,PRICE_CAD,PRICE_USD,STRIPE_PRICE_ID_CAD,STRIPE_PRICE_ID_USD}`**
  — per-tier knobs consumed by `src/lib/pricing.ts` so the page copy and
  Stripe price IDs can change without a redeploy.
- **`PATIENT_HASH_PEPPER`** (prod only) — server-side pepper mixed into the
  patient-identifier hash; the app refuses to boot without it in production.

## Tests

```bash
pnpm --filter portal test:onboarding
pnpm --filter portal test:patient-hash
pnpm --filter portal test:email
pnpm --filter portal test:billing-page
pnpm --filter portal test:team-management
pnpm --filter portal test:audit-quota
pnpm --filter portal test:leads-direct
pnpm --filter portal test:contact-form
```

Smoke scripts under `apps/portal/scripts/` cover the end-to-end flows that
aren't unit-testable in isolation: `smoke-billing.ts`, `smoke-billing-lifecycle.ts`,
`smoke-webhook.ts`, `smoke-encounter-flow.ts`, `smoke-encounter-list.ts`,
`smoke-bulk-findings.ts`, and `smoke-purge-canceled-tenants.ts`. Playwright E2E
lives under `apps/portal/tests/e2e/` (run via the top-level
`apps/portal/playwright.config.ts` symlink).
