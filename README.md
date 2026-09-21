# Zorva

Pre-submit medical-billing auditor for Alberta clinics — flags AHCIP (Schedule of Medical Benefits) claims that will be denied before they're sent to Alberta Health.

## Current state

Zorva is on **v12 AHCIP** (a 7-section AHCIP-only prompt that drops the US `-24` modifier and adds 5 AHCIP rules). On the cleaned AHCIP val set (10 encounters, 13 gold findings) v12 scores **F1 = 0.690, R = 0.769, P = 0.625** with 0 errors (micro over the cleaned gold, 2026-06-23 post-leakage-fix). The auditor, denial-risk scorer, appeal-letter generator, doctor-summary emailer, hash-chained audit trail, and self-improving loop are implemented in `src/ai_billing_audit/`. Local validation and live deployment are separate gates; see `docs/DEPLOYMENT.md` for the repository-backed topology and production verification requirements.

**Alberta pivot (2026-06-22).** The product was US/Mexico/Colombia multi-market on v0–v11; v12 is Alberta-first. The intended compliance context is PIPEDA plus Alberta's *Health Information Act* (HIA, not Ontario's PHIPA), subject to legal/privacy approval. The go-to-market is a controlled pilot with Alberta clinics. **The offer itself is still an open owner decision** (issues #76 and #108): `docs/PILOT_OFFER.md` describes a 60-day no-cost pilot, `apps/portal/src/app/pricing/page.tsx` describes 60 days free then $499/mo, and `docs/DATA_AGREEMENT_TEMPLATE.md` describes the pilot as free of charge. Treat any single one of those as authoritative only after #76/#108 close. See `docs/LAUNCH_GOAL_2026-10-20.md`.

## Quick start

```bash
git clone <repo> ai-billing-audit && cd ai-billing-audit
python3.11 -m venv .venv && source .venv/bin/activate   # 3.11 is the supported baseline
pip install -e ".[dev]"
pytest                                # hermetic suite; provider integration skips without its API key
```

To exercise the live AHCIP auditor against a real LLM, set the provider env var and run the dev loop:

```bash
export LLM_PROVIDER=minimax           # one of: minimax, claude, openai, gemini
export MINIMAX_API_KEY=...            # the matching key for that provider
python run.py                         # thin shim → scripts/optimize.py
```

`LLM_PROVIDER` is validated against a fixed set — `src/llm_client.py` defines
`SUPPORTED_PROVIDERS = {"minimax", "claude", "openai", "gemini"}` and
`scripts/optimize.py` maps each to a model. Anything else raises `ValueError`
before any network call. The provider names are `claude` (not `anthropic`), and
the key env var matches the provider (`MINIMAX_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). Earlier revisions of this README said
`ollama` / `OLLAMA_API_KEY`, which no supported provider reads.

Hermetic smoke mode (no network, no key) is the default if `LLM_PROVIDER` is unset.

## How to deploy

The VPS-deploy entry point is `deploy-to-vps.sh` (idempotent: rsync → `.env` → Traefik router → `docker compose up` → healthz). Backup/restore is `deploy/scripts/audit-backup.sh` (age-encrypted `pg_dump` → B2 via `rclone`, weekly cron, monthly restore-verify). See `deploy/README.md` for the full backup install recipe.

## Deploying

The repo ships **two distinct applications** that deploy separately.
They are designed for separate stacks and may share a domain apex.

### Side 1 — FastAPI / API

| | |
| --- | --- |
| **What** | the auditor (v12 AHCIP prompt), denial-risk scorer, missed-revenue detector, SOMB fee lookups, hash-chained audit trail, demo dashboard, `/healthz` smoke endpoint |
| **Source** | `src/`, `prompts/`, `data/synth/`, `Dockerfile`, `docker-compose.yml` |
| **Public target** | `https://ai-billing-audit.ashbi.ca` |
| **Pipeline** | `deploy-to-vps.sh` → rsync to VPS → writes `/etc/traefik/dynamic/routers.yml` → `docker compose up -d` → Traefik → Caddy → FastAPI |
| **Status** | Repository deployment target; verify the public host and reported version independently before release claims. |

To re-ship the API:

```bash
./deploy-to-vps.sh                       # idempotent: rsync → .env → Traefik → compose up → /healthz
```

Backup/restore for the Postgres `audit_trail` table lives at
`deploy/scripts/audit-backup.sh` (age-encrypted `pg_dump` → B2 via
`rclone`, weekly cron, monthly restore-verify).

### Side 2 — Next.js marketing portal

| | |
| --- | --- |
| **What** | the user-facing marketing site — hero ("Find the revenue..."), `/pricing` (CAD $499 / $1,499 / $2,999 tiers), `/what-zorva-finds` (8 finding cards), `/security` controls matrix, `/robots.txt` split rules, plus `/contact`, `/pilot`, `/how-it-works`. Authenticated workspace (`/portal/*`) runs the OnboardingWizard, billing dashboard, encounters/findings/audit workspace. |
| **Source** | `apps/portal/` (Next.js 15 + React 19 + Prisma/SQLite-dev/Postgres-prod + Stripe + Resend) |
| **Public target** | **`https://zorva.ashbi.ca`** — separate Traefik router, PostgreSQL, and Node 22-slim container, with no shared process tree with the API |
| **Pipeline** | `./deploy-portal.sh` → rsync → write `/opt/projects/ai-billing-audit/portal.env` from host secrets → configure Traefik → start PostgreSQL → apply `portal-migrate` → start portal → verify health and trusted HTTPS |
| **Status** | Production-ready repository topology; public deployment and provider configuration remain operator-verified gates. |

To run the marketing portal locally:

```bash
cd apps/portal
pnpm install
cp .env.example .env                     # DATABASE_URL and friends
pnpm exec prisma db push                 # create the dev SQLite schema
pnpm prisma:generate                     # generate the Prisma client
pnpm dev                                 # http://localhost:3000
```

Without the `.env` copy and the two Prisma steps the portal will not start —
there is no `DATABASE_URL` and no generated client. `apps/portal/README.md`
documents the full set of environment variables.

The portal and the API share no code at runtime — separate Postgres
schemas, separate containers, separate Traefik routers. They share the
host and the Traefik dynamic config file. The deploy script for each
side is independent:

- **API deploy:** `./deploy-to-vps.sh` (unchanged)
- **Portal deploy:** `./deploy-portal.sh` (new, 2026-06-26)

To re-ship the portal only (skip the rsync of `apps/portal/`):

```bash
./deploy-portal.sh --portal-only         # only restart the portal container
```

To rotate a portal secret (e.g. `STRIPE_SECRET_KEY`):

```bash
# 1. Write the new value to /root/ai-billing-audit-secrets/stripe_secret_key on the VPS
# 2. Re-run the deploy script (it re-writes portal.env from the secret):
./deploy-portal.sh --portal-only
```

### When you're ready to deploy `apps/portal`

The deploy script
(`deploy-portal.sh`) is the canonical recipe; static-export and
pm2-managed Node are no longer on the roadmap. If a future operator
wants to migrate the portal off the VPS to Cloudflare Pages / Netlify
/ Vercel (zero-VPS-resource path), the per-page output from
`pnpm build` already produces static assets — only the API routes
(`/api/*`, `/api/billing/*`, etc.) need a Node runtime, which those
hosts support natively.

Either choice keeps the FastAPI API on its own subdomain
(`api.ashbi.ca` or `ai-billing-audit.ashbi.ca`) so the two stacks
don't share a process tree.

Full architecture diagram and current deploy status are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The static-export and
pm2-managed alternatives discussed in earlier drafts of this README
are no longer on the roadmap — `apps/portal` ships as a Docker
container alongside the API.

## Project layout

```
ai-billing-audit/
├── src/ai_billing_audit/      # auditor, grader, denial_risk, appeal_letter,
│                              # doctor_email, chain (hash-chain shape),
│                              # audit_actions (hash-chain writer), api (FastAPI)
├── src/ai_billing_audit/chain.py  # SHA-256 audit-chain implementation
├── src/optimize.py            # DSPy optimization entry point
├── prompts/v0..v13/           # versioned auditor prompts (v12 is current;
│                              # v13 is an unmeasured draft, not wired up)
├── data/                      # val.json (synth) + val_ca.json (AHCIP), manifests
├── rules/                     # 26 seed rules (14 CMS E/M + 12 NCCI)
├── apps/portal/               # Next.js 15 billing portal (Tailwind + shadcn)
├── tests/                     # hermetic unit/regression suite plus gated integrations
├── scripts/                   # optimize.py, smartness harnesses, eval scripts
├── deploy/                    # backup/restore scripts + cron
├── deploy-to-vps.sh           # single-shot VPS deploy (Traefik + Coolify)
├── docker-compose.yml         # api + worker + postgres
├── Dockerfile                 # multi-stage (api, worker)
├── Caddyfile / Traefik router # public ingress config
├── docs/                      # 80+ design, audit, AHCIP, and pilot docs
└── artifacts/                 # MIPROv2 checkpoints, smartness runs, summaries
```

## Documentation index

| Doc | Purpose |
| --- | --- |
| [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | Authoritative product status, roadmap, risks, decisions, metrics, and work log |
| [`docs/PROJECT_AUDIT_2026-06-22.md`](docs/PROJECT_AUDIT_2026-06-22.md) | The 2026-06-22 six-agent audit — what works, what doesn't |
| [`docs/PILOT_OFFER.md`](docs/PILOT_OFFER.md) | The 30-day paid pilot contract (Alberta-edition in progress) |
| [`docs/ALBERTA_STRATEGY_BRIEF.md`](docs/ALBERTA_STRATEGY_BRIEF.md) | The 2026-06-22 Alberta-first pivot brief |
| [`docs/ALBERTA_PROSPECT_LIST.md`](docs/ALBERTA_PROSPECT_LIST.md) | 12-clinic outreach list, current as of the pivot |
| [`docs/AHCIP_RULE_REFERENCE.md`](docs/AHCIP_RULE_REFERENCE.md) | AHCIP SOMB rule reference the v12 prompt encodes |
| [`README.design-history.md`](README.design-history.md) | Pre-v12 design history (MIPROv2 loop, Phase 0–7, gpt-4o-mini era) |

Dated files under `research/`, `audits/`, and `docs/daily_report_*` are
historical evidence. Where they conflict with `docs/MASTER_PLAN.md`, the master
plan controls current priority and status.

## Current capabilities

The six Zorva capabilities and where they stand on 2026-06-23:

1. **Auditor** (`src/ai_billing_audit/auditor.py` + `prompts/v12/`) — v12 AHCIP prompt, F1=0.690 on the cleaned AHCIP val set, 0 errors, 10/10 latency p95 ≈ 58s on the evaluated provider. **Implemented and benchmarked; not customer-validated.** Repository evidence is not production performance.
2. **Denial-risk scorer** (`src/ai_billing_audit/denial_risk.py`) — severity × rule-family weighted heuristic, 0.0–1.0 per claim. **Implemented, not yet wired into the portal encounter-detail UI.**
   Dollar figures shown against findings come from `SOMB_FEE_SCHEDULE` in `src/ai_billing_audit/zorva_context.py`. That table is, by its own header comment, reconstructed from training-data knowledge of the 2024–2025 SOMB schedule and **not verified against the Alberta Medical Association Fee Navigator** (accuracy stated there as ±10–15%). Do not quote those figures to a clinic until the table is refreshed.
3. **Appeal-letter generator** (`src/ai_billing_audit/appeal_letter.py`) — markdown/HTML prose, PHI-scrubbed before logging. **Implemented, not yet wired into a portal route.**
4. **Doctor summary outbox** (`src/ai_billing_audit/doctor_email.py`) — builds the summary, then appends one JSONL record per summary to `/app/logs/doctor_emails.jsonl`. No auto-send: the biller reads the file and dispatches each email via their own mail client. Import + export of audit reports is the primary delivery surface; the JSONL is the paper trail. **Implemented; production behaviour unverified.**
5. **Hash-chained audit trail** (`src/ai_billing_audit/chain.py`, written by `audit_actions.py`) — SHA-256 chain over reviewer actions, JSONL on dev, Postgres `audit_trail` on prod, both verifiable. **Live.** The writer and the verifier share one implementation in `ai_billing_audit/chain.py`; `src/audit_log.py` is a thin re-export kept for the runbook and QA scripts. Verify with `audit_actions.verify_chain(audit_actions.read_all())`, which returns `None` on an intact chain. (The `feedback.py` log is a *separate* chain over different fields, not a parallel copy of this one.)
6. **Self-improving loop** (`src/optimize.py` + `src/optimize_compile.py`) — DSPy-style optimization harness; the v12 prompt was a manual AHCIP rewrite, not an optimizer pass. **Harness implemented; not yet run on customer data.**

A **hallucination guardrail** (`tests/test_hallucination_guardrail.py`) wraps the auditor: any finding whose supporting quote is not in the clinical note is rejected, and a finding with no supportable evidence at all is rejected too. **Tested** (`tests/test_hallucination_guardrail.py`). The rule-ID allowlist half of this description is aspirational: `suggested_code` and `rule_ids` are not validated against the SOMB schedule or the encounter payload.

## Known issues (operator-blocked)

The 2026-06-22 audit identified open items that require operator action, not code:

- **Ollama cloud key rotation.** The current Ollama key was shared in chat on 2026-06-17 and is treated as compromised; the live container still uses it. Rotate the key in the Ollama dashboard, update `~/.config/ai-billing/ollama-key`, and update the deploy script. ~15 min of operator work.
- **Alberta HIA data agreement — DRAFT READY, LEGAL REVIEW PENDING.** Template drafted 2026-06-26 at `docs/BAA_TEMPLATE_HIA.md` (framed as an Information Manager Agreement under HIA s. 65 — HIA does not use "agent" terminology). Cross-border disclosure (Hostinger VPS outside Canada, LLM provider outside Alberta) is flagged in section 4 and Appendix A. **Still requires lawyer review before any real Alberta pilot is signed.** Portal copy updated to reference HIA alongside PHIPA in the 8 places that previously implied Ontario-only compliance.

Full risk inventory and fixes: `docs/PROJECT_AUDIT_2026-06-22.md`.

## License

Proprietary — all rights reserved. Contact the maintainers for licensing.

`pyproject.toml` previously declared `license = { text = "MIT" }` while this section said proprietary; the metadata now says `Proprietary` to match. A `LICENSE` file carrying the full terms is still outstanding (issue #16).
