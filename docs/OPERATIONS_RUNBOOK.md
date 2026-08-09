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
passwords, `ZORVA_PHI_ENCRYPTION_KEY`, `AUDIT_BEARER_TOKEN`, and
`ZORVA_PRINCIPAL_SIGNING_SECRET`; deployment must fail rather than use a
default password, accept unsigned identity, or write PHI without encryption.

The API and portal deployments share the host files `audit_bearer_token` and
`principal_signing_secret`. The portal exposes them only as server-side
`FASTAPI_BEARER_TOKEN` and `FASTAPI_PRINCIPAL_SIGNING_SECRET` values. Portal
requests carry a signed subject, tenant, role, and expiration no more than five
minutes in the future. Never prefix these variables with `NEXT_PUBLIC_`.

Before deploying this storage revision over a host with any legacy plaintext
state, stop application writers, back up the volume, and run every applicable
explicit migration once with the new image and the final
`ZORVA_PHI_ENCRYPTION_KEY`:

```bash
python -m ai_billing_audit.admin_cli migrate-job-log
python -m ai_billing_audit.admin_cli migrate-doctor-emails
python -m ai_billing_audit.admin_cli migrate-appeal-logs
python -m ai_billing_audit.admin_cli migrate-feedback-logs
python -m ai_billing_audit.admin_cli migrate-clinical-metric-logs
python -m ai_billing_audit.admin_cli migrate-audit-trail
python -m ai_billing_audit.admin_cli migrate-integration-logs
python -m ai_billing_audit.admin_cli migrate-portal-state-logs
python -m ai_billing_audit.admin_cli migrate-contact-uploads
cd /opt/projects/ai-billing-audit/portal
pnpm migrate:portal-phi
```

The JSON migrations authenticate every record, write an encrypted backup of
the original bytes, and atomically replace the active files. The contact-upload
migration preserves each manifest path while encrypting the staged claim and
retaining an encrypted backup beside it. Successful migrations are idempotent.
A portal migration encrypts legacy staged claims in place (with encrypted
backups), replaces legacy plaintext SFTP passwords, clinical narratives,
finding evidence, and reviewer free text in portal Postgres with AES-256-GCM
ciphertext, and re-signs each affected tenant audit chain after verifying its
pre-migration integrity. Run it with the portal database reachable and portal
writers stopped; the database backup is the rollback artifact.
A missing or wrong key, malformed record, or pre-existing migration backup must
stop the rollout. Inspect and restore from the volume backup; do not delete a
backup or plaintext volume as a workaround. Start API and worker writers only
after all commands succeed, then verify `/readyz` and a tenant-scoped workflow.

## API and portal deployment

`deploy-to-vps.sh` synchronizes and probes the API stack. `deploy-portal.sh` is
the separate Next.js deployment path. The checked-in Compose topology runs the
one-shot `portal-migrate` service after portal PostgreSQL is healthy and starts
the portal only after migration succeeds. Confirm the portal build, migration
output, portal Postgres backup, and target router before changing the live
portal. The two databases require separate backup/restore evidence.

The current `/healthz` endpoint is a liveness smoke check. It returns the
application version and registered-demo count; it does not prove LLM
credentials, database migrations, backup freshness, or durable worker health.
Do not use a green `/healthz` response as release qualification.

`/readyz` is the dependency-configuration baseline for a load balancer or
deployment smoke test. It returns 200 only when `DATABASE_URL`,
`AUDIT_TRAIL_DB`, `ZORVA_PHI_ENCRYPTION_KEY`, and
`ZORVA_PRINCIPAL_SIGNING_SECRET` are configured and the parent directory of
`UPLOAD_AUDIT_LOG_PATH` (default `/app/logs/upload_jobs.jsonl`) is writable;
otherwise it returns 503 with per-check results. It does not make a database or
LLM request, and it does not replace monitoring for connectivity, stalled
workers, disk capacity, TLS, or backup freshness. Keep `/healthz` for liveness
and use `/readyz` as the additional pre-traffic gate until those deeper checks
are deployed.

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
