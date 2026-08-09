# Deployment architecture

This document describes the checked-in deployment topology. It does not prove
that a public host is running the same revision. A release operator must verify
the deployed revision, trusted HTTPS, health endpoints, database migration,
provider credentials, and user workflows after every authorized deployment.

## Applications

| Side | Location | Repository-backed deployment path | Live-state claim |
| --- | --- | --- | --- |
| FastAPI auditor and worker | `src/ai_billing_audit/`, root `Dockerfile`, `docker-compose.yml` | `deploy-to-vps.sh` and the API/worker services | No current live revision is established by this repository. |
| Next.js billing portal | `apps/portal/` | Portal image, one-shot `portal-migrate` service, PostgreSQL, and portal service in `docker-compose.yml` | No current public portal deployment is established by this repository. |

The applications have separate runtimes and databases. They may share a host
and edge proxy, but a successful local build does not establish that either
application is publicly deployed.

## Portal database contract

- SQLite is supported for local development and tests.
- Production mode requires a PostgreSQL `DATABASE_URL` and fails closed for a
  missing, SQLite, or unsupported URL.
- `pnpm prisma:generate` generates both the development SQLite client and the
  PostgreSQL client used in production.
- `pnpm prisma:migrate:deploy:postgresql` derives the PostgreSQL schema and
  applies the checked-in migration history.
- Docker Compose waits for PostgreSQL health and a successful
  `portal-migrate` completion before starting the portal.

The first authorized rollout must back up any existing production data, test
the migration against a disposable copy, apply the migration, and confirm the
expected schema before traffic is switched.

## Local release gates

Run the repository gates before creating a release candidate:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy src/ai_billing_audit

cd apps/portal
pnpm install --frozen-lockfile
pnpm lint
pnpm exec tsc --noEmit
pnpm test:database-runtime
pnpm build
```

The portal production build requires a syntactically valid PostgreSQL URL for
Prisma generation. It does not need a reachable database until migration or a
database-backed runtime path is exercised.

## Production and operator gates

Local validation cannot clear these gates:

- GitHub Actions must be enabled and the required workflows must pass on the
  exact release revision.
- Production secrets must be supplied and validated without committing them:
  auth secret, PostgreSQL credentials, Stripe credentials/webhook secret,
  Resend credentials, and any selected LLM-provider credentials.
- Payment, email, authentication, webhook, legal/compliance, backup/restore,
  and rollback workflows require authorized staging or production validation.
- The edge router, DNS, trusted certificate, public health/readiness endpoint,
  reported application version, desktop/mobile workflows, and browser console
  must be checked after deployment.

Do not infer production readiness from a container build, a local test pass, or
historical deployment notes.

## Related operations material

- `docs/OPERATIONS_RUNBOOK.md` — command and operational safety summary
- `deploy/README.md` — backup installation and restore guidance
- `deploy-to-vps.sh` — FastAPI deployment entry point
- `deploy-portal.sh` — portal deployment entry point
- `docker-compose.yml` — local/host service topology and migration ordering
