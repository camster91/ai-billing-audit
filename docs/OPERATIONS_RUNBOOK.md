# Operations runbook

This is the repository-backed runbook for the current stack. It is not
evidence that a live host matches the repository. Before a production change,
record the deployed commit, inspect the host environment files, and obtain the
required operator, security, and privacy approvals.

## Repository topology

The checked-in `docker-compose.yml` defines the FastAPI API, heartbeat-only
worker sidecar, FastAPI Postgres database, Caddy, Next.js portal, and separate
portal Postgres database. The worker is not a durable queue consumer yet;
durable job execution remains tracked in issue #18.

The API deploy script is `deploy-to-vps.sh`. The portal deploy script is
`deploy-portal.sh`. They are separate workflows and are not one atomic release.

## Preflight

Run these checks from a clean checkout and record the commit SHA:

```bash
git status --short --branch
git rev-parse HEAD
docker compose config --quiet
docker compose --env-file .env --env-file portal.env config --quiet
```

Do not print `.env`, `portal.env`, or secret files. Compose requires database
passwords; deployment must fail rather than use a default password.

## API and portal deployment

`deploy-to-vps.sh` synchronizes and probes the API stack. `deploy-portal.sh` is
the separate Next.js deployment path. Confirm the portal build, Prisma
migration plan, portal Postgres backup, and target router before changing the
live portal. The two databases require separate backup/restore evidence.

The current `/healthz` endpoint is a liveness smoke check. It returns the
application version and registered-demo count; it does not prove LLM
credentials, database migrations, backup freshness, or durable worker health.
Do not use a green `/healthz` response as release qualification.

## Backup and restore

The supported checked-in scripts are `deploy/scripts/audit-backup.sh`,
`deploy/scripts/audit-restore-verify.sh`, and
`deploy/scripts/test-backup-scripts.sh`. Their configuration is documented in
`deploy/scripts/backup.env.template` and `deploy/README.md`.

Never paste backup keys, bucket credentials, database passwords, or decrypted
dumps into issues, logs, or chat. A successful backup command is not restore
evidence; retain the monthly restore-verification result.

## Rollback

Before deployment, record image tags, commit, database backup artifact, and
migration state. If health or smoke checks fail, stop the rollout, retain logs,
and restore the prior application image/configuration. Database rollback
requires the approved restore procedure; do not run destructive SQL as an
improvised application rollback.

## Documentation boundaries

`docs/DEPLOYMENT.md` and older audit documents contain historical snapshots and
decision context. This file is the canonical repository-backed operational
summary; live topology, credentials, retention periods, legal claims, and
monitoring ownership still require current confirmation.
