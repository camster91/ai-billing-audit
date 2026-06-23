# Log rotation for the `/app/logs` named volume

`/app/logs` is a Docker named volume mounted into the `api` container at
`/app/logs`. It is the storage target for five application-managed JSON
log/caches. Without rotation the volume grows unbounded; this config caps
each file at the appropriate retention window for its data class.

The config in `zorva-logs` is the actual logrotate file that gets installed
to `/etc/logrotate.d/zorva-logs` on the VPS by `deploy-to-vps.sh`.

## Files rotated

| File | Rotation | Retention | Why |
| --- | --- | --- | --- |
| `audit_trail.jsonl` | daily | 2555 days (~7 years) | Hash-chained audit log. PHIPA requires 7-year retention for health-information records; this file is the binding artifact. |
| `upload_jobs.jsonl` | daily | 365 days (1 year) | Job history. Useful for one fiscal year of triage; no retention requirement beyond that. |
| `doctor_emails.jsonl` | daily | 60 days | Fallback mailbox of physician emails. Holds transient contact data; 60 days is enough for retry/repair windows and keeps PII surface small. |
| `doctor_optouts.json` | daily | 365 days (1 year) | Opt-out state. Needs to outlive one calendar year so re-imports and disputes can resolve, but no long-term PHIPA hook. |
| `npi_email_cache.json` | weekly | 12 weeks (~90 days) | Soft lookup cache (NPI → email). Pure performance optimisation — losing entries just means we re-resolve upstream. |

## Why `copytruncate`

Every file in `/app/logs/` is appended-to by the api process. `copytruncate`
asks logrotate to copy the file in place and then truncate the original,
rather than moving + creating a new inode and signalling the process to
reopen. We chose `copytruncate` because:

- It avoids any need for the api to install signal handlers (SIGHUP /
  SIGUSR1 reopen logic).
- The named volume already lives inside the container's filesystem; a
  short truncate window is fine for append-only structured logs.
- The api opens these files with `O_APPEND`, so concurrent writes that
  land during the copy window are kept (they end up in the new truncated
  file) rather than being dropped.

The trade-off is a brief moment where the file is being copied; for a
~7-year archive of small JSONL lines that's acceptable.

## Why `delaycompress` (and why not for `doctor_optouts.json`)

`delaycompress` keeps the most-recently-rotated file uncompressed, so a
process or operator that opens `audit_trail.jsonl-20260622` can still
`grep` / `tail` it without `gunzip` in the middle of the pipeline. Only
the older rotations are gzipped. The exception is `doctor_optouts.json`,
which is a single rolling JSON object, not a stream — `delaycompress`
adds no value there, so the option is omitted.

## Why `dateformat -%Y%m%d`

Default logrotate date suffix is `-YYYYMMDD`; we set it explicitly with
the leading `-` so rotated files sort lexicographically and so the
suffix is unambiguous (no `audit_trail.jsonl.1` mixed with
`audit_trail.jsonl-20260622.gz`).

## Verification

After install, run a non-destructive dry run:

```bash
logrotate -d /etc/logrotate.d/zorva-logs
```

That prints what logrotate *would* do (rotate, compress, prune) without
actually touching any files. The operator should run this once after
install and again any time the file is edited.

## Out of scope

- Migrating logs to an external system (syslog / Loki / etc.).
- Encrypting rotated archives at rest. If the named volume itself isn't
  encrypted, an attacker who reads `/app/logs` reads both current and
  rotated files. Disk-level encryption on the VPS is the current
  mitigation.
- Alerting on rotation failure. The default logrotate cron job logs to
  `/var/lib/logrotate/status`; if a rotation fails, it will be retried on
  the next daily run.

## Install

This is wired into `deploy-to-vps.sh` (step 4b — after the
`docker compose up -d` step, before the smoke tests). On a manual
install:

```bash
sudo install -m 644 deploy/logrotate/zorva-logs /etc/logrotate.d/zorva-logs
sudo logrotate -d /etc/logrotate.d/zorva-logs   # sanity check
```

The paths inside `zorva-logs` are the **in-container** paths
(`/app/logs/*.jsonl`) — they are the paths the api process opens. The
operator is responsible for making sure logrotate can see those paths
on whatever host runs it (e.g. by installing logrotate inside the api
container with `/etc/logrotate.d/` bind-mounted from the host, or by
running logrotate in a sidecar container that shares the named volume).
The deploy script just copies the file into place; the wiring of
"which process invokes logrotate on which paths" is documented in the
container's own Dockerfile and compose file, not here.