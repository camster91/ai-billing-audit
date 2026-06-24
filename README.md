# Zorva

Pre-submit medical-billing auditor for Alberta clinics — flags AHCIP (Schedule of Medical Benefits) claims that will be denied before they're sent to Alberta Health.

## Current state

Zorva is on **v12 AHCIP** (a 7-section AHCIP-only prompt that drops the US `-24` modifier and adds 5 AHCIP rules). On the cleaned AHCIP val set (10 encounters, 13 gold findings) v12 scores **F1 = 0.690, R = 0.769, P = 0.625** with 0 errors (micro over the cleaned gold, 2026-06-23 post-leakage-fix). The auditor, denial-risk scorer, appeal-letter generator, doctor-summary emailer, hash-chained audit trail, and self-improving loop are all implemented in `src/ai_billing_audit/`; the test suite is **791 pytest tests**, all passing locally. The **billing portal is live** at [https://ai-billing-audit.ashbi.ca](https://ai-billing-audit.ashbi.ca) (Next.js + FastAPI, served by Traefik on a single Hostinger VPS).

**Alberta pivot (2026-06-22).** The product was US/Mexico/Colombia multi-market on v0–v11; v12 is Alberta-first. Compliance is now PIPEDA + the Alberta *Health Information Act* (HIA, not Ontario's PHIPA). The go-to-market is a 30-day paid pilot with Alberta clinics (CAD $499 / $1,499 / $2,999 tiers, real Stripe checkout). 12-clinic prospect list is in `docs/ALBERTA_PROSPECT_LIST.md`.

## Quick start

```bash
git clone <repo> ai-billing-audit && cd ai-billing-audit
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                # 791 tests, ~10s, no API key
```

To exercise the live AHCIP auditor against a real LLM, set the provider env var and run the dev loop:

```bash
export LLM_PROVIDER=ollama            # or: openai, anthropic, minimax
export OLLAMA_API_KEY=...             # or the relevant key for your provider
python run.py                         # thin shim → scripts/optimize.py
```

Hermetic smoke mode (no network, no key) is the default if `LLM_PROVIDER` is unset.

## How to deploy

The VPS-deploy entry point is `deploy-to-vps.sh` (idempotent: rsync → `.env` → Traefik router → `docker compose up` → healthz). Backup/restore is `deploy/scripts/audit-backup.sh` (age-encrypted `pg_dump` → B2 via `rclone`, weekly cron, monthly restore-verify). See `deploy/README.md` for the full backup install recipe.

## Deployment

The repo ships **two distinct applications** that deploy separately:

- **FastAPI / API** (`src/ai_billing_audit/`, `Dockerfile`, `docker-compose.yml`) — the auditor, denial-risk scorer, missed-revenue detector, hash-chained audit trail, demo dashboard. **Live** at `https://ai-billing-audit.ashbi.ca` via `deploy-to-vps.sh`.
- **Next.js marketing portal** (`apps/portal/`) — the user-facing marketing site (hero, `/pricing`, `/what-zorva-finds`, `/security`, `/robots.txt`, etc.). **Built locally, not yet deployed.** The `deploy-to-vps.sh` rsync step excludes `apps/`.

Three approaches to close the gap (second docker-compose service, static export of marketing routes, separate repo) and the trade-offs are documented in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Project layout

```
ai-billing-audit/
├── src/ai_billing_audit/      # auditor, grader, denial_risk, appeal_letter,
│                              # doctor_email, audit_actions (hash chain),
│                              # optimize (self-improving loop), api (FastAPI)
├── src/optimize.py            # DSPy optimization entry point
├── prompts/v0..v12/           # versioned auditor prompts (v12 is current)
├── data/                      # val.json (synth) + val_ca.json (AHCIP), manifests
├── rules/                     # 26 seed rules (14 CMS E/M + 12 NCCI)
├── apps/portal/               # Next.js 15 billing portal (Tailwind + shadcn)
├── tests/                     # 791 pytest tests
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
| [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) | Master plan and current OKRs (post-pivot revision) |
| [`docs/PROJECT_AUDIT_2026-06-22.md`](docs/PROJECT_AUDIT_2026-06-22.md) | The 2026-06-22 six-agent audit — what works, what doesn't |
| [`docs/PILOT_OFFER.md`](docs/PILOT_OFFER.md) | The 30-day paid pilot contract (Alberta-edition in progress) |
| [`docs/ALBERTA_STRATEGY_BRIEF.md`](docs/ALBERTA_STRATEGY_BRIEF.md) | The 2026-06-22 Alberta-first pivot brief |
| [`docs/ALBERTA_PROSPECT_LIST.md`](docs/ALBERTA_PROSPECT_LIST.md) | 12-clinic outreach list, current as of the pivot |
| [`docs/AHCIP_RULE_REFERENCE.md`](docs/AHCIP_RULE_REFERENCE.md) | AHCIP SOMB rule reference the v12 prompt encodes |
| [`README.design-history.md`](README.design-history.md) | Pre-v12 design history (MIPROv2 loop, Phase 0–7, gpt-4o-mini era) |

## Current capabilities

The six Zorva capabilities and where they stand on 2026-06-23:

1. **Auditor** (`src/ai_billing_audit/auditor.py` + `prompts/v12/`) — v12 AHCIP prompt, F1=0.690 on the cleaned AHCIP val set, 0 errors, 10/10 latency p95 ≈ 58s on `ollama/minimax-m3:cloud`. **Live.**
2. **Denial-risk scorer** (`src/ai_billing_audit/denial_risk.py`) — severity × rule-family weighted heuristic, 0.0–1.0 per claim. **Implemented, not yet wired into the portal encounter-detail UI.**
3. **Appeal-letter generator** (`src/ai_billing_audit/appeal_letter.py`) — markdown/HTML prose, PHI-scrubbed before logging. **Implemented, not yet wired into a portal route.**
4. **Doctor summary email** (`src/ai_billing_audit/doctor_email.py`) — Mailgun REST send with a JSONL dev-fallback when `MAILGUN_API_KEY` is unset. **Implemented. Live sends currently dropping to `/app/logs/doctor_emails.jsonl` because the key is not yet set on the prod container.**
5. **Hash-chained audit trail** (`src/ai_billing_audit/audit_actions.py`) — SHA-256 chain over reviewer actions, JSONL on dev, Postgres `audit_trail` on prod, both verifiable. **Live. A second parallel chain in `src/audit_log.py` should be consolidated.**
6. **Self-improving loop** (`src/optimize.py` + `src/optimize_compile.py`) — DSPy-style optimization harness; the v12 prompt was a manual AHCIP rewrite, not an optimizer pass. **Harness live; not yet run on customer data.**

A **hallucination guardrail** (`tests/test_hallucination_guardrail.py`) wraps the auditor: any finding that cites a rule not in the encounter's `rules[]` payload is dropped. **Live, tested.**

## Known issues (operator-blocked)

The 2026-06-22 audit identified three open items that require operator action, not code:

- **Ollama cloud key rotation.** The current Ollama key was shared in chat on 2026-06-17 and is treated as compromised; the live container still uses it. Rotate the key in the Ollama dashboard, update `~/.config/ai-billing/ollama-key`, and update the deploy script. ~15 min of operator work.
- **MAILGUN_API_KEY on the prod container.** `docker-compose.yml` and `deploy-to-vps.sh` don't set the key, so all live doctor-summary emails silently fall back to the dev JSONL. Add the key to the host secret file + `.env` template + compose env block. ~30 min. Restores a primary product feature.
- **Alberta HIA data agreement.** The HIA-specific data-sharing agreement that Alberta clinics will require before signing a pilot is not yet drafted. The Ontario PHIPA template on the portal still appears in 12 places (`apps/portal/src/`), 6 of them wrong for Alberta. Draft the HIA agreement and replace the PHIPA references in the OnboardingWizard and security page.

Full risk inventory and fixes: `docs/PROJECT_AUDIT_2026-06-22.md`.

## License

Proprietary — all rights reserved. Contact the maintainers for licensing.
