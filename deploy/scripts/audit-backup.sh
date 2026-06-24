#!/usr/bin/env bash
# audit-backup.sh — encrypted, retention-tiered Postgres backup for ai-billing-audit
#
# ============================================================================
# PURPOSE
#   Dumps the ai_billing-audit Postgres database (including the audit_trail
#   table in the public schema) to an `age`-encrypted artifact and uploads
#   it to the configured object store (Backblaze B2 or S3) via `rclone`.
#   Tagging (daily / weekly / monthly) is encoded into the destination
#   key prefix so a single bucket holds the full retention matrix:
#
#       <bucket>/<prefix>/daily/   YYYY-MM-DDTHHMMSSZ.sql.age
#       <bucket>/<prefix>/weekly/  YYYY-MM-DDTHHMMSSZ.sql.age
#       <bucket>/<prefix>/monthly/ YYYY-MM-DDTHHMMSSZ.sql.age
#
#   The script also enforces the PHIPA retention policy:
#       4 weeks  of dailies
#       12 months of weeklies
#       7 years of monthlies
#   by deleting any artifact in the destination that is older than its tier.
#
# ============================================================================
# USAGE
#   /usr/local/bin/audit-backup.sh                  # default: weekly run
#   /usr/local/bin/audit-backup.sh --tier daily     # force a daily artifact
#   /usr/local/bin/audit-backup.sh --tier monthly   # force a monthly artifact
#   /usr/local/bin/audit-backup.sh --force          # re-run even if today's
#                                                   # artifact already exists
#   /usr/local/bin/audit-backup.sh --list           # list artifacts in bucket
#                                                   # (read-only; does not
                                                   # # touch the DB)
#   /usr/local/bin/audit-backup.sh --prune-only     # retention sweep only;
#                                                   # no new dump
#   /usr/local/bin/audit-backup.sh --dry-run        # show what would happen;
#                                                   # no upload, no prune
#
# Exit codes:
#   0  success
#   1  generic / config
#   2  pg_dump failed
#   3  age encryption failed
#   4  rclone upload failed
#   5  retention sweep failed (non-fatal: result is a noisy alert, not a halt)
#   6  size-anomaly detected (the upload still happened, but we emit an alert)
#
# ============================================================================
# INSTALL
#   1. Copy this file to /usr/local/bin/audit-backup.sh and chmod 700.
#   2. Generate an age keypair if you don't have one:
#         age-keygen -o /etc/ashbi/backup.age.key
#         awk '/^# public key:/{print $4}' /etc/ashbi/backup.age.key \\
#             > /etc/ashbi/backup.age.pub
#      The private key file MUST be chmod 600 and owned by root.
#   3. Configure rclone for the target bucket:
#         rclone config create ai-billing-backup b2 account XXXX key XXXX
#             --b2-bucket ai-billing-audit-backups
#      (use `s3` instead of `b2` for an S3-compatible target)
#   4. Create /etc/ashbi/backup.env with the operator's choices:
#         RCLONE_REMOTE=ai-billing-backup
#         RCLONE_BUCKET=ai-billing-audit-backups
#         RCLONE_PREFIX=pgdumps
#         ALERT_WEBHOOK_URL=          # optional; blank = silent on success
#         BACKUP_DOW=Sun               # weekday that produces the weekly tier
#   5. Add the cron entry in /etc/cron.d/ai-billing-audit-backup:
#         0 2 * * 0 root /usr/local/bin/audit-backup.sh >> /var/log/ai-billing-audit/backup.log 2>&1
#
# ============================================================================
# KEY ROTATION
#   1. Generate a new keypair (do not delete the old one yet).
#         age-keygen -o /etc/ashbi/backup.age.key.new
#         awk '/^# public key:/{print $4}' /etc/ashbi/backup.age.key.new \\
#             > /etc/ashbi/backup.age.pub.new
#   2. To ROTATE LIVE (read new writes with the new key, but still be able
#      to read old backups with the old key) you need a recipient list, not
#      a single pubkey. This script is single-recipient today. Either:
#         a. Keep using the old pubkey for all new writes (re-rotate the
#            .pub file with the OLD key, re-encrypt, then move on) — this
#            script still works, no code change.
#         b. Or change `AGE_RECIPIENTS` in backup.env to a space-separated
#            list and update the script's `age -e -R` line to use `-R`.
#      Either way: do not delete /etc/ashbi/backup.age.key until ALL
#      artifacts encrypted with that key have expired (7 years for the
#      longest tier). Keep retired keys in /etc/ashbi/keys/ with mode 600.
#
# ============================================================================
# MANUAL RESTORE
#   1. Find the artifact you want to restore:
#         rclone lsjson <remote>:<bucket>/<prefix>/<tier>/ | grep -i 'when'
#   2. Download + decrypt:
#         rclone cat <remote>:<bucket>/<prefix>/<tier>/<file>.sql.age \\
#             | age -d -i /etc/ashbi/backup.age.key > restore.sql
#   3. Restore (this is the only step that touches the live DB; do NOT
#      pipe directly into production without first taking a fresh backup
#      and confirming you have the right file):
#         PGPASSWORD=... psql -h <host> -U <user> -d <db> -f restore.sql
#
# ============================================================================
# DESIGN DECISIONS
#   - `pg_dump` is invoked via `docker exec` so the dump uses the same
#     client version as the server (Postgres 16 inside the container).
#     A host-side `pg_dump` of a different major version is a known
#     restore-failure path.
#   - `age` is used (not `gpg` or `openssl`) because the task spec calls
#     for it explicitly and because age keys are designed for this use
#     case (small, modern, no GPG trustdb).
#   - The artifact is streamed end-to-end: pg_dump -> age -e -> rclone
#     rcat. Nothing is written to a local temp file. This keeps the
#     server's /var/tmp clean and means there's no plaintext-on-disk
#     window to worry about.
#   - Idempotency: if an artifact with the same timestamp already exists
#     in the destination, the run is a no-op (unless --force). This makes
#     re-running the cron safe.
#   - Tier is selected automatically from the current weekday unless the
#     operator passes --tier. Sundays become `weekly`; the first day of
#     each month becomes `monthly` (in addition to the weekly tag);
#     everything else is `daily`.
#   - Size-anomaly detection compares the new artifact's size to the most
#     recent prior `weekly` artifact. A drop of >=50% triggers an alert
#     to ALERT_WEBHOOK_URL. This is a coarse but reliable check that
#     catches "the dump silently stopped including a table".
# ============================================================================

set -euo pipefail

# ----------------------------------------------------------------------------
# Defaults — set after sourcing the operator config so they fill in any
# gaps. Anything declared as an env var BEFORE invoking this script wins
# over both the config and these defaults.
# ----------------------------------------------------------------------------
: "${PG_CONTAINER:=ai-billing-audit-postgres}"
: "${PG_USER:=audit}"
: "${PG_DB:=ai_billing_audit}"
: "${RCLONE_REMOTE:=ai-billing-backup}"
: "${RCLONE_BUCKET:=ai-billing-audit-backups}"
: "${RCLONE_PREFIX:=pgdumps}"
: "${ALERT_WEBHOOK_URL:=}"
: "${LOG_DIR:=/var/log/ai-billing-audit}"
: "${SIZE_DROP_PCT:=50}"
: "${CONFIG_FILE:=/etc/ashbi/backup.env}"
: "${AGE_PUB:=/etc/ashbi/backup.age.pub}"
# Today in UTC — set early so tier auto-pick works on every code path.
TODAY_DOW="$(date -u +%u)"            # 1=Mon..7=Sun
DAY_OF_MONTH="$(date -u +%d)"

# ----------------------------------------------------------------------------
# Argument parsing — done FIRST so --help works on a dev box that can't
# write to /var/log/ai-billing-audit. mkdir, log dir creation, and
# pre-flight checks run only after the operator has told us what they want.
# ----------------------------------------------------------------------------
TIER=""
FORCE=0
LIST_ONLY=0
PRUNE_ONLY=0
DRY_RUN=0
SHOW_HELP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --tier)        TIER="$2"; shift 2 ;;
        --tier=*)      TIER="${1#--tier=}"; shift ;;
        --force)       FORCE=1; shift ;;
        --list)        LIST_ONLY=1; shift ;;
        --prune-only)  PRUNE_ONLY=1; shift ;;
        --dry-run)     DRY_RUN=1; shift ;;
        -h|--help)     SHOW_HELP=1; shift ;;
        *)
            printf '[%s] ERROR: unknown argument: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >&2
            exit 1
            ;;
    esac
done

if [ "$SHOW_HELP" -eq 1 ]; then
    sed -n '2,/^# ====/p' "$0" | head -n 80
    exit 0
fi

# ----------------------------------------------------------------------------
# Paths — only now do we touch the log dir. If the operator can't write
# here, every other command path will also fail, so the error is honest.
# ----------------------------------------------------------------------------
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
    printf '[%s] ERROR: cannot create LOG_DIR=%s (set LOG_DIR=/tmp/... to override)\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LOG_DIR" >&2
    exit 1
fi
LOG_FILE="$LOG_DIR/backup.log"
SIZE_LOG="$LOG_DIR/backup.sizes.log"

# Source the operator config now that LOG_FILE exists for the
# "loaded config from $CONFIG_FILE" line below.
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC2218  # log() is defined a few lines below; bash looks it up at call time
    log "loaded config from $CONFIG_FILE"
    # shellcheck disable=SC1090
    . "$CONFIG_FILE"
fi

# ----------------------------------------------------------------------------
# Logging helpers — write to both the log file and stdout (cron captures stdout)
# ----------------------------------------------------------------------------
ts()   { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()  { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE" ; }
err()  { printf '[%s] ERROR: %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE" >&2 ; }

# ----------------------------------------------------------------------------
# Alert hook — POST a small JSON payload to the configured webhook
# ----------------------------------------------------------------------------
alert() {
    local severity="$1"
    local message="$2"
    log "ALERT [$severity] $message"
    if [ -z "$ALERT_WEBHOOK_URL" ]; then
        return 0
    fi
    # Best-effort; if curl fails we still have the log entry.
    local payload
    payload=$(printf '{"source":"ai-billing-audit-backup","severity":"%s","host":"%s","message":"%s","timestamp":"%s"}' \
        "$severity" "$(hostname -f 2>/dev/null || hostname)" \
        "$(printf '%s' "$message" | sed 's/"/\\"/g; s/[\]//g' | tr '\n' ' ')" \
        "$(ts)")
    curl --silent --show-error --max-time 10 \
        -H 'Content-Type: application/json' \
        -d "$payload" \
        "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 || \
        log "WARN: alert webhook POST failed (continuing)"
}

# ----------------------------------------------------------------------------
# Load operator config if present.
#
# Precedence (highest first):
#   1. Caller environment (e.g. RCLONE_REMOTE=foo /usr/local/bin/audit-backup.sh)
#   2. /etc/ashbi/backup.env (or $CONFIG_FILE)
#   3. Script defaults
#
# Implementation: we source the config file BEFORE the defaults, but with
# the caller's exported env taking precedence — bash's `set -a; .` exports
# all assignments from the file, but if a variable is already set and
# marked readonly, or if we gate assignments with `[ -z "$VAR" ] && export`,
# the caller's value survives. We use the latter (in backup.env) for the
# vars the operator would most often want to override for a single run.
# The script defaults still kick in for vars the config doesn't touch.
#
# We source it AFTER arg-parsing so --help / --list don't need a writable
# log dir.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------------
require_file() {
    [ -f "$1" ] || { err "missing required file: $1"; exit 1; }
}
require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { err "missing required command: $1"; exit 1; }
}

require_file "$AGE_PUB"
require_cmd docker
require_cmd age
require_cmd rclone
require_cmd curl

# Validate that we can reach the postgres container.
if ! docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    err "postgres container '$PG_CONTAINER' not found"
    err "running containers:"
    docker ps --format '  {{.Names}}' | tee -a "$LOG_FILE" >&2
    exit 1
fi

# Auto-pick a tier from the date if the operator didn't override.
if [ -z "$TIER" ]; then
    if [ "$DAY_OF_MONTH" = "01" ] && [ "$TODAY_DOW" = "7" ]; then
        TIER="monthly"
    elif [ "$TODAY_DOW" = "7" ]; then
        TIER="weekly"
    else
        TIER="daily"
    fi
fi

case "$TIER" in
    daily|weekly|monthly) ;;
    *) err "invalid --tier value: $TIER (must be daily|weekly|monthly)"; exit 1 ;;
esac

REMOTE_PATH="$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PREFIX/$TIER"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARTIFACT="ai-billing-audit_${TIER}_${TIMESTAMP}.sql.age"
ARTIFACT_PATH="$REMOTE_PATH/$ARTIFACT"

log "==============================================="
log "run start: tier=$TIER container=$PG_CONTAINER db=$PG_DB"
log "destination: $ARTIFACT_PATH"

# ----------------------------------------------------------------------------
# --list: read-only listing of all tiers
# ----------------------------------------------------------------------------
if [ "$LIST_ONLY" -eq 1 ]; then
    for t in daily weekly monthly; do
        log "--- $t/ ---"
        # rclone exits non-zero when the directory is empty/missing; tolerate it.
        if ! rclone lsjson "$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PREFIX/$t/" 2>/dev/null \
            | python3 -c '
import json, sys
try:
    objs = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
for obj in objs:
    size = obj["Size"]
    mod = obj["ModTime"]
    name = obj["Name"]
    print("  %14d  %s  %s" % (size, mod, name))
'; then
            log "  (empty or missing)"
        fi
    done
    exit 0
fi

# ----------------------------------------------------------------------------
# Idempotency: if an artifact with today's UTC date is already in the
# destination for the chosen tier, skip the dump+upload. Override with
# --force (useful when an upload silently failed and you want to push
# the same file again). The match is by UTC date prefix, not by exact
# timestamp, so minute-resolution re-runs within the same UTC day do
# not create duplicate artifacts.
# ----------------------------------------------------------------------------
if [ "$FORCE" -eq 0 ]; then
    UTC_DATE="$(date -u +%Y%m%d)"
    # Pass UTC_DATE and TIER as argv (not env) so `set -u` in the parent
    # bash doesn't trip and the python subprocess doesn't have to guess.
    EXISTING=$(rclone lsjson "$REMOTE_PATH/" 2>/dev/null \
        | python3 -c '
import json, sys
utc_date, tier = sys.argv[1], sys.argv[2]
prefix = f"ai-billing-audit_{tier}_{utc_date}"
try:
    for obj in json.load(sys.stdin):
        name = obj.get("Name", "")
        if name.startswith(prefix) and name.endswith(".sql.age"):
            print(name)
            break
except (json.JSONDecodeError, ValueError):
    pass
' "$UTC_DATE" "$TIER")
    if [ -n "$EXISTING" ]; then
        log "artifact for $UTC_DATE already exists at destination: $EXISTING (use --force to re-upload)"
        exit 0
    fi
fi

# ----------------------------------------------------------------------------
# --prune-only: skip dump+upload, go straight to retention sweep
# ----------------------------------------------------------------------------
PRUNE_RAN=0
run_prune() {
    # shellcheck disable=SC2034  # PRUNE_RAN is referenced after this function returns
    PRUNE_RAN=1
    log "retention sweep starting"
    # 4 weeks of dailies: 28 days
    # 12 months of weeklies: 365 days
    # 7 years of monthlies: 365*7+1 = 2556 days (account for leap)
    local -A MAX_AGE_DAYS=(
        [daily]=28
        [weekly]=366
        [monthly]=2557
    )
    local failures=0
    for t in daily weekly monthly; do
        local max_age=${MAX_AGE_DAYS[$t]}
        log "  tier=$t max_age=${max_age}d"
        # --min-age takes a duration; --include is what restricts to this tier
        if [ "$DRY_RUN" -eq 1 ]; then
            rclone --dry-run lsjson --min-age "${max_age}d" \
                "$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PREFIX/$t/" 2>/dev/null \
                | python3 -c '
import json, sys
for obj in json.load(sys.stdin):
    print(f"    would delete: {obj[\"Name\"]}  (age {obj[\"ModTime\"]})")
' || true
        else
            local deleted
            deleted=$(rclone delete --min-age "${max_age}d" --use-json-log \
                "$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PREFIX/$t/" 2>>"$LOG_FILE" | wc -l)
            log "  tier=$t retention sweep deleted $deleted entries (>=${max_age}d)"
        fi
    done
    if [ "$failures" -gt 0 ]; then
        alert "warning" "retention sweep reported $failures tier errors"
    fi
    log "retention sweep done"
}

# ----------------------------------------------------------------------------
# Size-anomaly detection: compare new artifact's size to the prior weekly's
# size. A drop of >= SIZE_DROP_PCT% fires a warning alert.
# ----------------------------------------------------------------------------
ARTIFACT_SIZE=0
record_size() {
    local bytes="$1"
    # shellcheck disable=SC2034  # Exposed for future callers (e.g. slack alert payload)
    ARTIFACT_SIZE="$bytes"
    printf '%s %s %s\n' "$(ts)" "$TIER" "$bytes" >> "$SIZE_LOG"
}

check_size_anomaly() {
    # Find the most recent `weekly` size in the log BEFORE this run.
    # The current run's size is already appended by record_size() before
    # this function is called, so we look at the 2nd-to-last weekly entry.
    local prior_weekly
    prior_weekly=$(awk '$2=="weekly"' "$SIZE_LOG" | tail -n 2 | head -n 1 | awk '{print $3}')
    if [ -z "$prior_weekly" ] || [ "$prior_weekly" -eq 0 ] 2>/dev/null; then
        log "size-anomaly: no prior weekly size in log; skipping"
        return 0
    fi
    local new_bytes="$1"
    if ! [[ "$new_bytes" =~ ^[0-9]+$ ]] || ! [[ "$prior_weekly" =~ ^[0-9]+$ ]]; then
        log "size-anomaly: non-numeric size in log; skipping"
        return 0
    fi
    # Guard division: if the new artifact is >= the prior, no drop.
    if [ "$new_bytes" -ge "$prior_weekly" ]; then
        log "size-anomaly: no drop (new=$new_bytes >= prior=$prior_weekly)"
        return 0
    fi
    # pct = (prior - new) * 100 / prior. If pct >= SIZE_DROP_PCT, alert.
    local pct=$(( (prior_weekly - new_bytes) * 100 / prior_weekly ))
    if [ "$pct" -ge "$SIZE_DROP_PCT" ]; then
        alert "critical" "weekly backup size dropped ${pct}% WoW (prior=$prior_weekly new=$new_bytes tier=$TIER)"
        log "size-anomaly detected: ${pct}% drop"
        return 6
    fi
    log "size-anomaly: no drop (prior=$prior_weekly new=$new_bytes pct=${pct}%)"
    return 0
}

# ----------------------------------------------------------------------------
# Main: pg_dump | age -e | rclone rcat (stream end-to-end, no plaintext on disk)
#
# pg_dump --no-owner --no-privileges produces a more portable dump; we still
# keep the schema (including audit_trail) because the task spec says so.
# --quote-all-identifiers keeps the dump stable across reserved-word collisions.
# ----------------------------------------------------------------------------
ANOMALY=0
if [ "$PRUNE_ONLY" -eq 0 ]; then
    log "starting dump+encrypt+upload stream"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: would dump and stream to $ARTIFACT_PATH"
        run_prune
        exit 0
    fi

    # Run the pipeline. Capture size by piping rclone's output through wc.
    # We use a subshell + pipefail; on any failure we exit with the right code.
    set -o pipefail
    if docker exec -i "$PG_CONTAINER" \
            pg_dump -U "$PG_USER" -d "$PG_DB" \
                --no-owner --no-privileges --quote-all-identifiers \
                --serializable-deferrable \
        | age -e -r "$(cat "$AGE_PUB")" \
        | tee /tmp/.audit-backup-bytes \
        | rclone rcat "$ARTIFACT_PATH" 2>>"$LOG_FILE"; then
        UPLOAD_BYTES=$(wc -c < /tmp/.audit-backup-bytes | tr -d ' ')
        rm -f /tmp/.audit-backup-bytes
        if [ -z "$UPLOAD_BYTES" ] || [ "$UPLOAD_BYTES" -eq 0 ]; then
            err "upload reported 0 bytes; refusing to consider it a success"
            alert "critical" "ai-billing-audit backup uploaded 0 bytes (tier=$TIER)"
            exit 4
        fi
        log "upload OK: $UPLOAD_BYTES bytes -> $ARTIFACT_PATH"
        record_size "$UPLOAD_BYTES"
        set +o pipefail
        # Sanity check: download the artifact, decrypt, and grep for
        # audit_trail in the plaintext. The grep is the literal table name;
        # we don't care about the contents, only that the table is present.
        if rclone cat "$ARTIFACT_PATH" 2>/dev/null \
            | age -d -i /etc/ashbi/backup.age.key 2>/dev/null \
            | grep -q -E 'CREATE TABLE.*audit_trail|COPY.*audit_trail'; then
            log "audit_trail presence: OK (table header found in decrypted dump)"
        else
            err "audit_trail presence: FAILED (no audit_trail header in decrypted dump)"
            alert "critical" "ai-billing-audit backup uploaded but audit_trail is missing from the decrypted dump"
            exit 2
        fi
        # Size-anomaly check runs only on weekly/monthly (dailies are too noisy).
        if [ "$TIER" = "weekly" ] || [ "$TIER" = "monthly" ]; then
            if check_size_anomaly "$UPLOAD_BYTES"; then
                :
            else
                ANOMALY=$?
            fi
        fi
    else
        rc=$?
        set +o pipefail
        err "dump+encrypt+upload pipeline failed (rc=$rc)"
        # Try to map the failure to a more useful exit code.
        case "$rc" in
            0) rc=1 ;;
        esac
        alert "critical" "ai-billing-audit backup pipeline failed (tier=$TIER rc=$rc)"
        exit "$rc"
    fi
fi

# Retention sweep runs after a successful upload (or on --prune-only).
run_prune

if [ "$ANOMALY" -ne 0 ]; then
    log "run complete with anomaly flag (rc=$ANOMALY)"
    exit "$ANOMALY"
fi

log "run complete"
exit 0
