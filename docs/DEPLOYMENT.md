# Deployment architecture

> Captured 2026-06-24 after the first VPS deploy. The two sides of
> Zorva are deployed separately; the marketing site is not yet wired
> up to the deploy pipeline. See the audit task
> `zorva-post-deploy-2026-06-24 / t_c63938d1` for the gap.

This repo ships two distinct applications:

| Side | What it is | Location | Status |
| ---- | ---------- | -------- | ------ |
| **FastAPI / API** | The auditor, denial-risk scorer, missed-revenue detector, SOMB fees, hash-chained audit trail, demo dashboard. | repo root (`src/ai_billing_audit/`, `Dockerfile`, `docker-compose.yml`) | **Deployed** to `https://ai-billing-audit.ashbi.ca` via `deploy-to-vps.sh` |
| **Next.js marketing portal** | The user-facing marketing site — hero ("Find the revenue..."), `/pricing` with CAD tiers, `/what-zorva-finds` with 8 finding cards, `/security` controls matrix, `/robots.txt` with split rules, plus `/contact`, `/pilot`, `/how-it-works`, etc. | `apps/portal/` (Next.js 15 + Tailwind + shadcn) | **Built locally**, **not deployed** — the rsync step in `deploy-to-vps.sh` excludes `apps/` |

## Why the gap exists

The VPS deploy (`deploy-to-vps.sh`) rsyncs the FastAPI source tree to
`/opt/projects/ai-billing-audit/` on the host, then `docker compose
build` + `up -d` runs the four services (api, worker, postgres,
caddy). The marketing portal in `apps/portal/` is a separate Next.js
15 application with its own build pipeline (`pnpm install` +
`pnpm build`) and a different runtime (Node.js + a Prisma-managed
SQLite DB). It requires its own port (the dev server runs on 3000,
the production build on 3000 or 3020 depending on config), its own
Traefik router, and its own upstream — it does not sit behind the
FastAPI `/api` routes.

The deploy script explicitly excludes `apps/` from the rsync:

```
--exclude='apps/'
```

so even the marketing-side source isn't on the VPS host, let alone
running. There is no second service in `docker-compose.yml` for the
Next.js app.

## What lives at `https://ai-billing-audit.ashbi.ca` today

Only the FastAPI app. The HTML at `/` is the demo dashboard
rendered by the FastAPI templates (not the polished Next.js
marketing pages). Anyone landing on the public URL right now sees
the working dashboard, not the marketing pitch.

## The marketing site's current state

`apps/portal/` is fully built and tested locally. The route tree
includes:

- `/` — marketing hero, "Find the revenue..." pitch
- `/pricing` — three CAD tiers ($499 / $1,499 / $2,999)
- `/what-zorva-finds` — 8 finding cards
- `/security` — controls matrix
- `/how-it-works`, `/compare`, `/case-studies`, `/careers`
- `/pilot`, `/contact` — lead-capture forms
- `/robots.ts` — split rules (allows crawlers on marketing,
  disallows on portal)
- `/dashboard`, `/billing`, `/encounters`, `/findings`, `/settings`,
  `/team` — authenticated portal pages (separate from the FastAPI
  dashboard; would consume the FastAPI `/api/...` endpoints)
- `/portal-nav.tsx` — the auth-aware nav

It depends on `@auth/prisma-adapter`, `@prisma/adapter-better-sqlite3`,
and a local SQLite file for its own auth session store. None of that
is wired into the current docker-compose stack.

## Possible paths to close the gap

Three approaches, ranked by how clean they are:

1. **Second service in docker-compose.yml.** Add a `portal` service
   that builds `apps/portal/` (multi-stage Dockerfile: `pnpm
   install` → `pnpm build` → `next start` on port 3020), expose
   `127.0.0.1:3020` on the host loopback, and add a Traefik router
   for `portal.ai-billing-audit.ashbi.ca` (or a path prefix on the
   existing host). Keep the FastAPI dashboard at the apex or under
   `/app/`. Pros: single repo, single deploy script. Cons: the
   Next.js build (pnpm + Prisma generate) needs to run inside the
   Docker build, which is slower than the current FastAPI-only
   image; SQLite + Prisma in a container needs a named volume.

2. **Static export of the marketing pages only.** Run
   `pnpm build` + `next export` for just the marketing routes
   (`/`, `/pricing`, `/what-zorva-finds`, `/security`,
   `/how-it-works`, `/compare`, `/careers`, `/robots.txt`) and
   serve the static `out/` directory via Traefik's file provider
   or a tiny `caddy file_server` block. The authenticated portal
   routes (`/dashboard`, `/billing`, `/encounters`, ...) move to a
   separate `portal.ai-billing-audit.ashbi.ca` host or stay
   un-deployed for now. Pros: no Node runtime needed on the VPS,
   fastest cold-start, smallest image. Cons: dynamic routes (auth,
   contact form, lead capture) become client-only and need a
   small API for any server actions; the portal's Prisma auth
   store needs to either move to the FastAPI Postgres or be
   dropped.

3. **Move `apps/portal/` to a separate repo (`camster91/zorva-web`)
   and deploy independently.** The marketing site gets its own
   CI/CD, its own Vercel/Hosting account, its own preview deploys
   per PR. Pros: cleanest separation of concerns, marketing
   iteration speed decoupled from auditor release cadence.
   Cons: two repos, two deploy pipelines, harder to keep the
   pricing copy in sync with the auditor capabilities.

The current kanban doesn't have an acceptance criterion for which
path to take; this doc captures the trade-offs so the decision is
explicit when picked up.

## Until the gap is closed

- The FastAPI dashboard at `/` is the only public surface.
- The marketing site at `apps/portal/` runs locally for design
  review (`cd apps/portal && pnpm dev`).
- The 12-clinic prospect list (`docs/ALBERTA_PROSPECT_LIST.md`) gets
  a demo URL pointing at the dashboard, with a footnote that the
  marketing site is "coming soon".
- All pricing copy, finding-card copy, and security-control copy is
  reviewed against `apps/portal/` source, not against what is live.

## Related

- `deploy-to-vps.sh` — the FastAPI-only deploy script
- `docker-compose.yml` — the four-service stack (no Next.js yet)
- `apps/portal/package.json` — the marketing-side build config
- `docs/PROJECT_AUDIT_2026-06-22.md` — the audit that surfaced the
  marketing / API two-sided architecture
- kanban: `zorva-post-deploy-2026-06-24 / t_c63938d1`
