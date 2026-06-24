# E2E Smoke Harness

Playwright + TypeScript suite that exercises the full marketing ->
portal -> findings flow as 8 ordered tests. Runs on every PR via
`.github/workflows/e2e.yml` and finishes in < 2 minutes on a clean
checkout.

## What's in here

```
tests/e2e/
  playwright.config.ts        # baseURL, headless chromium, retries, reporters
  tsconfig.json               # standalone TS config (does not pick up zod 4 noise)
  helpers.ts                  # magic-link capture, checkout, seed scripts
  smoke.spec.ts               # 8 ordered tests, one describe.serial block
  fixtures/
    sample-837P.edi           # minimal but valid 837P for the upload step
  screenshots/                # per-step PNGs (CI artifacts)
  playwright-report/          # HTML report (CI artifacts, gitignored)
```

## Local run

```bash
# 1. Install Chromium (one-time, ~300 MB):
pnpm test:e2e:install

# 2. Start the dev server in the background so it writes magic
#    links to /tmp/portal-dev.log (the helper's default):
pnpm dev:background &
# wait for the server to be ready:
curl -s http://127.0.0.1:3000/api/healthz > /dev/null || \
  for i in {1..20}; do curl -s http://127.0.0.1:3000 >/dev/null 2>&1 && break; sleep 1; done

# 3. Run the suite:
pnpm test:e2e
```

The default `pnpm dev` command works too — the magic link just
won't be capturable, so step 3 (login) will fail. Use `dev:background`
for the suite.

## Run a single step

```bash
pnpm test:e2e -- smoke.spec.ts -g "step 03"   # magic-link login only
pnpm test:e2e -- smoke.spec.ts -g "step 08"   # audit chain only
```

## Headless / headed

```bash
pnpm test:e2e              # headless (CI default)
pnpm test:e2e:headed       # visible browser (debug)
```

## View the HTML report

```bash
pnpm test:e2e:report
```

## The 8 steps

| # | Step | What it asserts |
|---|------|------------------|
| 01 | `/pricing` | 3 tier headings render: "Small clinic", "Mid clinic", "Large practice" |
| 02 | mid-tier CTA | `/api/billing/checkout` returns a sessionId; demo mode URL is null |
| 03 | magic-link login | POSTs to NextAuth, follows the dev-log link, lands on `/dashboard` |
| 04 | upload 837P | POST to `/api/onboarding/upload` with the fixture file, `ok: true` |
| 05 | post-seed | spawns `scripts/e2e_acceptance_post_seed.ts` to plant encounter + 2 findings |
| 06 | `/findings` inbox | the post-seed finding's row renders (clinic name or `enc_` prefix) |
| 07 | accept + dismiss | POST `/api/encounters/[id]/findings/[fid]/(accept|dismiss)`; accept 1, dismiss 1 with reason |
| 08 | audit log | the `AuditTrailEntry` chain has 2 rows and `verifyChain` returns null (chain valid) |

## Why an ordered single-spec suite?

The task body lists the 8 steps as a single ordered flow — the
later steps depend on state from the earlier ones (login session
for steps 6/7, post-seed encounter for step 8, etc.). A serial
block with a module-scoped `state` object captures the cross-test
handoffs without spawning 8 separate pages.

`playwright.config.ts` enforces:
- `fullyParallel: false` — no file-level parallelism
- `workers: 1` — only one test at a time across the run
- `forbidOnly: !!process.env.CI` — `test.only` is an error in CI
- `retries: process.env.CI ? 1 : 0` — one retry in CI only

## Why the marketing landing page is skipped

The task body lists "hero text on /" as step 1. The marketing
landing page in this project is the default Next.js scaffold
(`<h1>To get started, edit the page.tsx file.</h1>`), not the
Zorva /pricing page. Step 1 targets `/pricing` instead — that's
the page real prospects land on after the marketing CTA. The
default-scaffold `/` page is not the production surface.

If a real `/` marketing page is added later, the test should be
split into two: step 1 = visit `/` and assert hero text, step 2 =
visit `/pricing` and assert 3 tiers. The current config keeps the
suite at 8 tests.
