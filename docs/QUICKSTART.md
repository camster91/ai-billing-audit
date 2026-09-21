# Zorva Quickstart — 5 steps from `git clone` to first audit on the dashboard

> **For:** A new Zorva pilot clinic's IT contact or technical lead.
> **Time to first audit:** ~25 minutes on a fresh Linux box, ~40 minutes on macOS (Docker Desktop resource setup), ~50 minutes on Windows (WSL2 recommended).
> **What you'll end up with:** A running Zorva stack (api + worker + postgres + caddy) on your local machine, with one successfully audited encounter visible in the demo dashboard.

This guide assumes you have **Docker** and **git** installed, and you have a Zorva pilot **API key** (one is emailed to your billing lead when the pilot kicks off). If you don't have one yet, email `pilot@ashbi.ca` and you'll have it within an hour.

The steps are copy-pasteable. Every command is also in `scripts/pilot_bootstrap.sh` if you'd rather run the whole sequence as a single script.

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/ashbi/ai-billing-audit.git
cd ai-billing-audit
```

If you've been sent a private fork (most pilot clinics are), swap the URL for the one in your welcome email:

```bash
git clone https://github.com/ashbi-private/<your-clinic-slug>.git
cd ai-billing-audit
```

**Sanity check:** `ls` should show `apps/`, `docs/`, `docker-compose.yml`, `Dockerfile`, `README.md`.

---

## Step 2 — Set the environment variables

Copy the example env file and edit it:

```bash
cp .env.example .env
# Then edit .env in your editor of choice.
```

Edit `.env` so it contains these four lines (the others can stay at their defaults for a local pilot run):

```bash
# .env — local pilot values. NEVER commit this file.
ZORVA_API_KEY=zorva_pilot_REPLACE_ME
ZORVA_TENANT_ID=your-clinic-slug
DATABASE_URL=postgresql://zorva:zorva@postgres:5432/zorva
AUDIT_TRAIL_DB=postgresql://zorva:zorva@postgres:5432/zorva_audit
```

The four required values:

| Var | Where it comes from | Example |
|---|---|---|
| `ZORVA_API_KEY` | Welcome email from `pilot@ashbi.ca` | `zorva_pilot_a1b2c3d4...` |
| `ZORVA_TENANT_ID` | The clinic slug you picked at signup (lowercase, dashes) | `strathcona-pcn` |
| `DATABASE_URL` | Local docker-compose default — leave as-is | `postgresql://zorva:zorva@postgres:5432/zorva` |
| `AUDIT_TRAIL_DB` | Local docker-compose default — leave as-is | `postgresql://zorva:zorva@postgres:5432/zorva_audit` |

**Sanity check:** `grep -v '^#' .env | grep -v '^$'` should print exactly those four lines.

---

## Step 3 — Start the stack

```bash
docker compose up -d --build
```

The first build takes ~6 minutes (it pulls the v12 prompt bundle, installs Python deps, builds the Next.js portal). Subsequent boots take ~20 seconds.

Watch the logs as it comes up:

```bash
docker compose logs -f api
```

You're looking for this line, which means the API is healthy:

```
[api] Uvicorn running on http://0.0.0.0:8000
[api] Application startup complete.
```

**Hit Ctrl-C** to detach from the log stream (the containers keep running).

**Sanity check the four containers are up:**

```bash
docker compose ps
```

You should see `api`, `worker`, `postgres`, and `caddy` all in state `running`/`healthy`.

---

## Step 4 — POST your first audit

The API expects an authenticated encounter-audit request. For the very first audit we ship a sample encounter so you don't have to wire up your EHR yet:

```bash
# Verify healthz (no auth required)
curl -s http://localhost:8000/healthz | jq

# POST a sample-encounter audit using your pilot key.
# (Read ZORVA_API_KEY from .env so it doesn't sit in shell history.)
export ZORVA_API_KEY=$(grep '^ZORVA_API_KEY=' .env | cut -d= -f2-)
export ZORVA_TENANT_ID=$(grep '^ZORVA_TENANT_ID=' .env | cut -d= -f2-)

curl -s -X POST http://localhost:8000/api/audit/run \
  -H "Authorization: Bearer ${ZORVA_API_KEY}" \
  -H "X-Tenant-Id: ${ZORVA_TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "encounterId": "sample-001"
  }' | jq
```

A successful response looks like:

```json
{
  "allowed": true,
  "state": "ok",
  "used": 1,
  "quota": 1000,
  "percent": 0.1,
  "upgradeUrl": "/billing/upgrade"
}
```

If you get `allowed: false` with `state: "blocked"`, your pilot quota is exhausted — check `quota` vs `used` in the response. Email `pilot@ashbi.ca` and we'll bump it.

**For real EHR data:** wire your billing system up to `POST /api/audit/run` per the payload shape in `apps/portal/src/app/api/audit/run/route.ts`. Most clinics start with a CSV upload through the dashboard instead — see Step 5. The full webhook event catalog is in `docs/api/WEBHOOK-EVENTS.md`.

---

## Step 5 — Verify the dashboard

The portal is on `http://localhost:3018` (Caddy forwards to the api service):

```bash
# Open the dashboard
open http://localhost:3018   # macOS
xdg-open http://localhost:3018   # Linux
start http://localhost:3018   # Windows
```

Log in with the **pilot credentials** from your welcome email. The first thing you'll see is the **Encounters** page — your sample-001 audit from Step 4 should be at the top with one finding (`rule_ahcip_modifier_25`, severity `high`).

The four pages worth opening on day one:

| Page | URL | What you're checking |
|---|---|---|
| Dashboard | `/dashboard` | Today's audit count, finding distribution, top 3 rules firing |
| Encounters | `/encounters` | The full encounter list — click any row for findings + biller actions |
| Findings | `/findings` | Every finding across every encounter, filterable by rule / severity / status |
| Settings → Audit trail | `/settings` → "Audit trail" tab | The hash-chained audit log (HIA-required, PIPEDA-required) |

**Sanity check:** in the Encounters page, click on `sample-001` and confirm you see (a) the original claim, (b) at least one finding, (c) the suggested fix, (d) the biller accept/edit/dismiss buttons.

If all four checks pass, you're done. The pilot clinic onboarding script (`scripts/onboard_pilot.sh`) walks the rest of the team through the rest from here.

---

## Troubleshooting

**`docker compose up` fails with "port 5432 already in use"** — you have a local Postgres running. Either stop it (`brew services stop postgresql` on macOS, `sudo systemctl stop postgresql` on Linux) or change the host port in `docker-compose.yml` from `5432` to `5433` and update `DATABASE_URL` to match.

**`curl http://localhost:8000/healthz` returns "connection refused"** — the api container didn't finish booting. Run `docker compose logs api | tail -50` and look for a Python traceback. The most common cause is a typo in `ZORVA_API_KEY`; the api refuses to start if it's malformed.

**The dashboard shows "0 encounters"** — the audit from Step 4 didn't land. Run it again and watch the api logs: `docker compose logs -f api | grep audit`. If you see `tenant not found`, your `ZORVA_TENANT_ID` doesn't match what we have on file — email `pilot@ashbi.ca` with the slug you used and we'll reconcile.

**`docker compose ps` shows `postgres` as `unhealthy`** — first boot is initializing the schema (the `audit_trail.sql` mount runs automatically). Give it 60 seconds and re-check.

**`docker compose up` complains about buildx or BuildKit on macOS** — install BuildKit: `brew install docker-buildx`. Then re-run with `DOCKER_BUILDKIT=1 docker compose up -d --build`.

---

## What to read next

- **Privacy / compliance:** `docs/legal/PIA-TEMPLATE.md` — Alberta OIPC + Ontario IPC Privacy Impact Assessment template, 80% pre-filled for a 60-day pilot.
- **Data processing agreement:** `docs/legal/HIA-DPA-TEMPLATE.md` — HIA-compliant DPA, signable by a privacy officer.
- **Webhook events:** `docs/api/WEBHOOK-EVENTS.md` — every event the API emits, payload shapes, sample curl to subscribe.
- **Specialty landing pages:** `/for/family-medicine` — what the auditor finds on Alberta FP claims, with the missed-revenue math per 1,000 claims.
- **Pilot program overview:** `/pilot` — what the 60-day pilot actually covers, week by week, and what it costs.

When you're ready to roll into the paid engagement, the ops handoff is in `docs/DEPLOYMENT.md`.
