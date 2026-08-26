# ai-billing-audit — Backup & Restore Verification

> **Historical context.** This runbook documents the checked-in
> backup and restore scripts (`audit-backup.sh`,
> `audit-restore-verify.sh`, `test-backup-scripts.sh`,
> `backup.env.template`, `ai-billing-audit-backup.cron`). The
> canonical repository-wide preflight, deploy, rollback, and
> retention guidance lives in
> [`docs/OPERATIONS_RUNBOOK.md`](../docs/OPERATIONS_RUNBOOK.md);
> use this file for the script-specific install and verification
> steps. Tracked in issue #15.

Encrypted, retention-tiered Postgres backup for `ai_billing_audit`, with a
monthly restore-verification job. Designed to be installed once and run
forever on the production VPS.

## Files

| Path | Role |
| --- | --- |
| `audit-backup.sh` | Dumps the DB, encrypts with `age`, uploads to B2/S3 via `rclone`. Runs weekly (Sunday 02:00 UTC). Daily and monthly tier runs are side-effects of the date. |
| `audit-restore-verify.sh` | First Sunday of each month, pulls the most recent weekly, decrypts, restores into a throwaway DB, sanity-checks. |
| `backup.env.template` | Operator config — copy to `/etc/ashbi/backup.env` and edit. |
| `ai-billing-audit-backup.cron` | 6-field cron entries (user column included — 5-field entries are silently ignored). |
| `test-backup-scripts.sh` | Local unit tests for the size-anomaly, tier-pick, and idempotency logic. Runs without docker or rclone. |

## Install

```bash
# 1. Generate age keypair
mkdir -p /etc/ashbi
age-keygen -o /etc/ashbi/backup.age.key
awk '/^# public key:/{print $4}' /etc/ashbi/backup.age.key > /etc/ashbi/backup.age.pub
chmod 600 /etc/ashbi/backup.age.key /etc/ashbi/backup.age.pub

# 2. Configure rclone (B2 example — substitute for S3/MinIO as needed)
rclone config create ai-billing-backup b2 account XXXX key XXXX \
    --b2-bucket ai-billing-audit-backups
# Verify:
rclone lsd ai-billing-backup:

# 3. Install scripts
install -m 700 deploy/scripts/audit-backup.sh /usr/local/bin/
install -m 700 deploy/scripts/audit-restore-verify.sh /usr/local/bin/

# 4. Operator config
cp deploy/scripts/backup.env.template /etc/ashbi/backup.env
chmod 600 /etc/ashbi/backup.env
$EDITOR /etc/ashbi/backup.env  # set RCLONE_REMOTE/BUCKET/PREFIX and ALERT_WEBHOOK_URL

# 5. Cron
install -m 644 deploy/scripts/ai-billing-audit-backup.cron /etc/cron.d/

# 6. Log dir
mkdir -p /var/log/ai-billing-audit
chmod 755 /var/log/ai-billing-audit
```

> This runbook describes the checked-in backup scripts only. Retention periods,
> legal basis, production topology, and restore ownership require current
> operator/privacy approval; do not treat the values below as legal advice or
> proof of live configuration. See `docs/OPERATIONS_RUNBOOK.md` for the
> repository-wide deployment boundary.

## Repository default retention tiers (approval required)

| Tier | Keep | Notes |
| --- | --- | --- |
| daily | 4 weeks (28d) | Nightly snapshots |
| weekly | 12 months + 1 day (366d) | Sunday 02:00 UTC |
| monthly | 7 years + 2 days (2557d) | First Sunday of each month |

`audit_trail` rows live in the `public` schema and are included in every dump.
The configured tiers are operational defaults, not a substitute for the
approved HIA/PIPEDA/PHIPA retention and deletion policy.

## Manual restore

```bash
# Find a recent artifact
RCLONE_REMOTE=ai-billing-backup \
RCLONE_BUCKET=ai-billing-audit-backups \
RCLONE_PREFIX=pgdumps \
    /usr/local/bin/audit-backup.sh --list

# Download + decrypt
rclone cat ai-billing-backup:ai-billing-audit-backups/pgdumps/weekly/<filename>.sql.age \
    | age -d -i /etc/ashbi/backup.age.key > restore.sql

# Restore (do NOT pipe into production without a fresh backup first)
PGPASSWORD=... psql -h <host> -U <user> -d <db> -v ON_ERROR_STOP=1 -f restore.sql
```

## Test the install

```bash
# 1. Verify --help on both scripts works without root
LOG_DIR=/tmp audit-backup.sh --help
LOG_DIR=/tmp audit-restore-verify.sh --help

# 2. Run the unit tests (no docker / rclone needed)
bash deploy/scripts/test-backup-scripts.sh

# 3. Smoke-test the backup pipeline end-to-end (requires docker + rclone + age)
DRY_RUN=1 LOG_DIR=/tmp audit-backup.sh --tier daily

# 4. Force a real run as a one-off (idempotent — re-run does nothing unless --force)
LOG_DIR=/tmp audit-backup.sh --tier weekly
```

## Alerts

- **Size-anomaly**: weekly backup size drops >=50% week-over-week. First
  run after a fresh install has no baseline, so the check is a no-op.
- **Failed upload / decrypt / restore**: all paths emit a JSON POST to
  `ALERT_WEBHOOK_URL`. If the URL is empty, only the log line fires.
- **Monthly verify failure**: critical alert + a `FAIL` line in
  `/var/log/ai-billing-audit/verify.history`.

## Key rotation

The current script uses a single recipient. To rotate without losing the
ability to read 7-year-old monthly backups:

1. Generate a new keypair. **Do not delete the old one.**
2. Move the old private key to `/etc/ashbi/keys/backup.age.key.YYYY-MM-DD` (mode 600).
3. Replace `/etc/ashbi/backup.age.pub` with the new public key.
4. Future artifacts will encrypt with the new key.
5. To decrypt a future restore of an old artifact, you need the old
   private key. Either keep both keys in `age` form (use `-i A.key -i B.key`
   to `age -d` — multi-key decrypt works natively) or migrate to a
   recipient list (see SKILL: "age key rotation patterns" if you need it).

When ALL artifacts encrypted with a given key have expired from
retention, the corresponding private key can be deleted.

## Acceptance checklist (per task spec)

- [x] `audit-backup.sh` exists, shellcheck-clean, idempotent on re-runs.
- [x] Produces `.sql.age` artifacts with timestamps; uploads to configured B2/S3.
- [x] Cron entry has 6 fields (user column) — 5-field entries are silently ignored.
- [x] Retention sweep: 4w dailies, 12mo weeklies, 7yr monthlies.
- [x] `audit_trail` schema/rows are in the dump (verified by `pg_restore --list`
      or a test decrypt — see "Test the install" above).
- [x] Monthly restore-verify job runs at 02:30 on the first Sunday.
- [x] Size-anomaly alert fires on a 50%+ WoW drop.
- [x] Secrets (age key, bucket creds) are not in the repo — read from
      `/etc/ashbi/` or env.
- [x] README/runbook is this file plus the script header comments.
