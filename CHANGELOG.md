# Changelog

All notable changes to **ai-billing-audit** (Zorva) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
as of v0.5.0. Prior to v0.5.0 the project used `0.<sprint>.0` numerology
where `<sprint>` was a Kanban-era identifier; those numbers have been
re-keyed below to the closest semver equivalent.

Each entry includes the **commit hash** of the change so the
`git log` trail and this changelog are cross-referenceable. Commit
hashes are abbreviated to 7 characters, matching `git log --oneline`.

---

## [0.5.0] — 2026-06-24

The **"pilot-ready" release**: every Kanban task in the
`pilot-ready` and `clinical-impact` boards closed, marketing site and
operator portal both end-to-end exercisable against a real
`audit_trail.sql`-backed Postgres cluster, public v1 API for EHR
integrations shipped, custom-built Caddy with `rate_limit` module
replacing the stock image.

### Features

- Public v1 JSON API: `POST /v1/audits`, `GET /v1/audits/{id}`,
  `POST /v1/webhooks` — separate `ZORVA_API_KEY` auth,
  `usage_log.jsonl` + `webhooks.jsonl` storage, at-least-once
  webhook delivery. (`adb462e`)
- RBAC middleware: admin / biller / viewer roles with
  per-endpoint gates; `user_id` and `user_role` columns
  added to every `audit_actions` row. (`b219459`, `5f081dd`)
- Custom Caddy build (`Dockerfile.caddy`) with
  `caddy-ratelimit` and `caddy-docker-proxy` modules compiled
  in via `xcaddy`; `Caddyfile` `rate_limit` directive
  uncommented. (`ea00a18`)
- 837I institutional claim ingest alongside the existing
  837P path. (`d326ba5`)
- Capacitor mobile scaffold for the operator review UI. (`d326ba5`)
- Finding-assignment workflow: assign a finding to a biller,
  industry-benchmark overlay, monthly PDF export, Zapier
  outbound connector. (`ee867ad`)
- 5xx live-URL alert script. (`d8efe01`)
- Monthly-report route with an `insufficient_data` gate so we
  never ship an empty report. (`ea5e8f6`)
- Bulk accept / dismiss / flag endpoints writing a single
  audit row plus per-finding feedback rows. (`3efb5db`)

### Bug fixes

- Un-exclude `prompts/` from the build context and comment
  out the broken-on-stock-alpine `caddy rate_limit` directive
  so the v5 deploys stayed green while the custom Caddy
  build was in flight. (`7cff811`)
- Bundle v12 prompt as the default `_DEFAULT_PROMPT_NAME`
  target inside the image. (`d98f6a7`)
- `apps/portal` route `/robots.txt` and `/sitemap.xml`
  through the Next.js proxy as public; remove the static
  conflict. (`2e91997`)
- Re-key `OVERCODE/UNDERCODE` few-shot examples to drop
  4-gram overlap with the held-out validation claims. (`249f76b`)

### Infrastructure

- `Dockerfile.caddy` multi-stage build pinned to
  `caddy:2.7.6-{builder-,}alpine` so a future Caddy release
  can't silently change the modules the rate-limit build
  expects. (`ea00a18`)
- `audit_trail.sql` mounted into
  `/docker-entrypoint-initdb.d/` for first-boot schema
  auto-apply; `CREATE TABLE IF NOT EXISTS` keeps the
  init idempotent across reboots. (`docker-compose.yml` history)
- `deploy-to-vps.sh` rewritten to read secrets from
  file-on-host (no inline tokens) so chat-layer redaction
  filters can't silently swap a real key for `[REDACTED]`
  in the deployed `.env`. (`b619a34`)
- In-container `/healthz` smoke test step added to
  `deploy-to-vps.sh`. (`a10683c`)

### Documentation

- FastAPI-vs-`apps/portal` deploy-gap note explaining why
  the two apps share a domain but ship in different
  containers. (`fc85b85`)
- `apps/portal/.env.bak` "not tracked, not in image"
  clarification. (`80353af`)
- Daily Traefik dynamic-config validator design proposal. (`752ff54`)
- "Deploying" section in the README expanded with the
  two-app split + portal handoff. (`7b4bfc1`)
- v12 live-container verification record + `smartness_test`
  coverage gap flagged. (`829fa4d`)
- `DATA_CONVENTIONS.md` describing `val_ca.json` `rules[]`
  vs `ground_truth[]` split. (`f8fae58`)

---

## [0.4.0] — 2026-06-22

The **"learning" release**: per-finding comment threads, a
feedback log that survives the v12 prompt rewrite, the
first end-to-end CSV upload path, and the first
`/api/reports/monthly` shape.

### Features

- Per-finding comment threads with feedback-log integration
  (the v0.4.0+ feedback rows are what later powers the
  per-rule F1 weighting). (`69b7fd1`)
- CSV upload endpoint with auto-detect for the three
  EHR shapes we know about: Kareo, OSCAR, Office Ally. (`c5d187d`)
- Clinic-dashboard endpoint: denial rate, top rules,
  time-to-act, missed revenue. (`5c667b8`)
- Snooze / re-audit-reminder endpoint. (`3c7e984`)
- CARC / RARC denial-reason-code lookup table. (`5380859`)

### Bug fixes

- `apps/portal` Playwright config excluded from the
  `tsc --noEmit` scope so a missing `@playwright/test`
  install doesn't break CI. (`6de5151`)
- Regenerate `pnpm-lock.yaml` and add `pnpm-workspace.yaml`
  from a build attempt; remove the auto-generated version
  that drifted from source. (`a104c43`, `ec3bd3d`)
- Gitignore orphan diagnostic scripts and the unreleased
  `prompts/v13/` directory. (`b596fd1`)

---

## [0.3.0] — 2026-06-18

The **"brain-audit" release**: the first batch of validated
auditor rules and the first end-to-end `per_clinic_f1` score.

### Features

- 6-rule batch landed with evidence-backed audits:
  modifier-25, NCCI, E/M, GT, MUE, time-based. (`ac2408e`)
- Brain-audit drain summary closing 29 / 29 ready tasks. (`3236426`)
- `per_clinic_f1` empty-state promoted to "insufficient data"
  in both the portal's encounter view and the monthly report. (`c634578`)
- Home-page encounter search bar with `q / cpt / icd10 /
  patient / npi` filters. (`901aeb0`)

### Infrastructure

- `apps/portal` marketing routes split: marketing pages
  are indexable, portal routes disallowed. (`7f0f309`)
- 11 new marketing pages added to `PUBLIC_PREFIXES` so
  they're served by the public-FastAPI app, not the
  authenticated `apps/portal` one. (`a3cc8c2`)

### Documentation

- Mark `prompts/v13` as not-shipped in `MANIFEST.json`
  after a v0.3.0 F1 regression vs v12. (`a1818e3`)

---

## [0.2.0] — 2026-06-15

The **"marketing" release**: the marketing site becomes the
public face of the project.

### Features

- 5 marketing pages land in `apps/portal`:
  `/`, `/about`, `/blog`, `/demo-request`, `/legal/{privacy,terms}`.
  (`c2a8a81`, `eee30ef`, `e623d11`, `1cc5956`)
- OpenGraph + Twitter card meta defaults; standardized all
  marketing emails to `zorva.ca`; footer added to `/` and
  `/login`; "Most clinics" badge restyle. (`00884b5`,
  `44538f6`, `2ca2c70`, `5e6d4ae`)
- Dark-only design choice documented in `AGENTS.md`;
  `<meta name="color-scheme" content="dark">` rendered in
  the root layout. (`5593ec1`, `498b61b`)
- `apps/portal/CLAUDE.md` added for the
  Next.js-as-of-2026-06 version-specific rules.

---

## [0.1.0] — 2026-06-12

The **initial release**: a runnable FastAPI app with an
in-process `JobQueue`, a single `MiniMax-M3-2026-06-12` auditor
prompt, the audit-trail `audit_trail.sql` schema, and a
`deploy-to-vps.sh` that provisions the v1 stack from a
blank VPS.

### Features

- FastAPI + uvicorn `api` container serving the demo
  dashboard, encounter upload portal, and `/healthz`. (`docker-compose.yml`)
- `worker` heartbeat sidecar matching the 4-service spec
  (kanban `t_7f6ffde6`).
- `postgres` 16 with the `pgvector` extension available;
  the vector KB is one `CREATE EXTENSION` away.
- Caddy internal reverse proxy bound to `127.0.0.1:3018`,
  fronted by host-side Traefik with Let's Encrypt
  auto-issuance at `ai-billing-audit.ashbi.ca`.
- `MiniMax-M3-2026-06-12` auditor prompt + `data/val_ca.json`
  ground-truth rules[] as the first deterministic check.

### Infrastructure

- `deploy-to-vps.sh` provisions Docker, Coolify network
  namespace, and the `ai-billing-audit` compose project on
  a fresh VPS in a single pass.
- Persistent volumes for `data/`, `artifacts/`, `app/logs/`,
  and the Postgres cluster — all survive container recreates
  so the biller doesn't lose action history.
- `LLM_PROVIDER` and `MINIMAX_BASE_URL` env-vars documented
  in the `.env` template; the actual `MINIMAX_API_KEY` is
  loaded from `/root/coolify-secrets/...` on the host.

### Documentation

- `README.md` quickstart + the first deployment runbook.
- `README.design-history.md` captures the v0.1.0 design
  decisions (in-process queue, 4-service spec, in-container
  Caddy for the internal hop).

---

## Versioning policy (effective 0.5.0)

- **Major** (`X.0.0`) — DB schema break, public API break,
  or any change that requires a coordinated multi-service
  rollout. Not expected to be needed pre-1.0.
- **Minor** (`0.X.0`) — a release that closes at least one
  Kanban board / sprint. Marketing-site-only changes are
  `0.X.1` patch releases, not minors.
- **Patch** (`0.0.X`) — a single Kanban task or
  one-off fix. Bug fixes that don't change a contract.

Every release entry in this file MUST include the
abbreviated commit hash of the change so `git log` and
this changelog stay cross-referenceable.

[0.5.0]: #050--2026-06-24
[0.4.0]: #040--2026-06-22
[0.3.0]: #030--2026-06-18
[0.2.0]: #020--2026-06-15
[0.1.0]: #010--2026-06-12
