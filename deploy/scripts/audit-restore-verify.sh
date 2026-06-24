#!/usr/bin/env bash
# audit-restore-verify.sh — monthly restore verification for ai-billing-audit
#
# ============================================================================
# PURPOSE
#   On the first Sunday of every month, pull the most recent weekly backup
#   from the configured object store, decrypt it with the age identity key,
#   restore it into a throwaway database, run a sanity check (row counts on
#   key tables, presence of audit_trail rows), and record pass/fail.
#
#   The throwaway database is created on the same Postgres container under
#   a name like `ai_billing_audit_verify_YYYYMMDD` and dropped at the end
#   of the run. No production data is touched.
#
# ============================================================================
# USAGE
#   /usr/local/bin/audit-restore-verify.sh                  # default run
#   /usr/local/bin/audit-restore-verify.sh --tier weekly   # verify a weekly
#   /usr/local/bin/audit-restore-verify.sh --tier monthly  # verify a monthly
#   /usr/local/bin/audit-restore-verify.sh --dry-run       # show what would
#                                                          # happen; no DB touch
#   /usr/local/bin/audit-restore-verify.sh --keep-db       # do NOT drop the
#                                                          # throwaway DB
#                                                          # (post-mortem)
#
# Exit codes:
#   0  restore verified, all sanity checks passed
#   1  generic / config
#   2  source artifact missing
#   3  download failed
#   4  decrypt failed
#   5  restore failed
#   6  sanity check failed (table missing or row count off)
#
# ============================================================================
# INSTALL
#   Add the cron entry in /etc/cron.d/ai-billing-audit-backup:
#       30 2 1-7 * 0 root /usr/local/bin/audit-restore-verify.sh >> /var/log/ai-billing-audit/verify.log 2>&1
#   (i.e. 02:30 on the first Sunday of the month, after the weekly backup
#    that runs at 02:00 every Sunday)
#
# ============================================================================

set -euo pipefail

# ----------------------------------------------------------------------------
# Config — every value here can be overridden by /etc/ashbi/backup.env
# (and by the operator's environment, which wins; see load-config below).
# ----------------------------------------------------------------------------
CONFIG_FILE="${CONFIG_FILE:-/etc/ashbi/backup.env}"
AGE_KEY="${AGE_KEY:-/etc/ashbi/backup.age.key}"
PG_CONTAINER="${PG_CONTAINER:-ai-billing-audit-postgres}"
PG_USER="${PG_USER:-audit}"
PG_DB="${PG_DB:-ai_billing_audit}"
RCLONE_REMOTE="${RCLONE_REMOTE:-ai-billing-backup}"
RCLONE_BUCKET="${RCLONE_BUCKET:-ai-billing-audit-backups}"
RCLONE_PREFIX="${RCLONE_PREFIX:-pgdumps}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
LOG_DIR="${LOG_DIR:-/var/log/ai-billing-audit}"
MIN_AUDIT_TRAIL_ROWS="${MIN_AUDIT_TRAIL_ROWS:-1}"

# ----------------------------------------------------------------------------
# Logging helpers
# ----------------------------------------------------------------------------
ts()   { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()  { printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE" ; }
err()  { printf '[%s] ERROR: %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE" >&2 ; }

# ----------------------------------------------------------------------------
# Alert hook
# ----------------------------------------------------------------------------
alert() {
    local severity="$1"
    local message="$2"
    log "ALERT [$severity] $message"
    if [ -z "$ALERT_WEBHOOK_URL" ]; then
        return 0
    fi
    local payload
    payload=$(printf '{"source":"ai-billing-audit-restore-verify","severity":"%s","host":"%s","message":"%s","timestamp":"%s"}' \
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
#   1. Caller environment (e.g. RCLONE_REMOTE=foo /usr/local/bin/audit-restore-verify.sh)
#   2. /etc/ashbi/backup.env (or $CONFIG_FILE)
#   3. Script defaults
#
# backup.env uses `[ -z "$VAR" ] && export VAR=...` so caller-exported
# values survive the source. Plain `VAR=foo` would clobber them.
#
# We source it AFTER arg-parsing so --help / --list don't need a writable
# log dir. The drawback: env vars passed on the command line (e.g.
# `CONFIG_FILE=/tmp/foo /usr/local/bin/audit-backup.sh`) must come BEFORE
# the script, not as flags, because we won't see them in $1/$2.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Argument parsing — done FIRST so --help works on a dev box that can't
# write to /var/log/ai-billing-audit. mkdir, log dir creation, and
# pre-flight checks run only after the operator has told us what they want.
# ----------------------------------------------------------------------------
TIER="weekly"
KEEP_DB=0
DRY_RUN=0
SHOW_HELP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --tier)        TIER="$2"; shift 2 ;;
        --tier=*)      TIER="${1#--tier=}"; shift ;;
        --keep-db)     KEEP_DB=1; shift ;;
        --dry-run)     DRY_RUN=1; shift ;;
        -h|--help)     SHOW_HELP=1; shift ;;
        *) printf '[%s] ERROR: unknown argument: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >&2; exit 1 ;;
    esac
done

if [ "$SHOW_HELP" -eq 1 ]; then
    sed -n '2,/^# ====/p' "$0" | head -n 40
    exit 0
fi

# ----------------------------------------------------------------------------
# Paths — only now do we touch the log dir.
# ----------------------------------------------------------------------------
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
    printf '[%s] ERROR: cannot create LOG_DIR=%s (set LOG_DIR=/tmp/... to override)\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LOG_DIR" >&2
    exit 1
fi
LOG_FILE="$LOG_DIR/verify.log"
VERIFY_RECORD="$LOG_DIR/verify.history"

# Source the operator config now that LOG_FILE exists for the
# "loaded config from $CONFIG_FILE" line below.
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC2218  # log() is defined a few lines below; bash looks it up at call time
    log "loaded config from $CONFIG_FILE"
    # shellcheck disable=SC1090
    . "$CONFIG_FILE"
fi

# ----------------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------------
require_file() {
    [ -f "$1" ] || { err "missing required file: $1"; exit 1; }
}
require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { err "missing required command: $1"; exit 1; }
}

require_file "$AGE_KEY"
require_cmd docker
require_cmd age
require_cmd rclone
require_cmd curl
require_cmd psql

if ! docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    err "postgres container '$PG_CONTAINER' not found"
    exit 1
fi

# ----------------------------------------------------------------------------
# Tier validation + log file paths
# ----------------------------------------------------------------------------
case "$TIER" in
    daily|weekly|monthly) ;;
    *) printf '[%s] ERROR: invalid --tier: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TIER" >&2; exit 1 ;;
esac

# ----------------------------------------------------------------------------
# Cleanup — drop the throwaway DB unless --keep-db was passed.
# Always run; never fail the script because the cleanup failed.
# ----------------------------------------------------------------------------
cleanup() {
    local rc=$?
    if [ "$KEEP_DB" -eq 0 ] && [ -n "${VERIFY_DB:-}" ]; then
        log "cleanup: dropping throwaway db $VERIFY_DB (rc=$rc)"
        docker exec "$PG_CONTAINER" dropdb -U "$PG_USER" --if-exists "$VERIFY_DB" \
            >> "$LOG_FILE" 2>&1 || log "WARN: dropdb of $VERIFY_DB failed"
    elif [ "$KEEP_DB" -eq 1 ]; then
        log "cleanup: keeping throwaway db $VERIFY_DB for post-mortem"
    fi
    # Remove any decrypted dump on disk (defence-in-depth; was already on
    # /tmp so the OS will wipe it on reboot, but be explicit).
    if [ -n "${PLAIN_DUMP:-}" ] && [ -f "$PLAIN_DUMP" ]; then
        # shred if available, else rm. shred is best-effort.
        if command -v shred >/dev/null 2>&1; then
            shred -u "$PLAIN_DUMP" 2>/dev/null || rm -f "$PLAIN_DUMP"
        else
            rm -f "$PLAIN_DUMP"
        fi
    fi
}
trap cleanup EXIT

VERIFY_DB="ai_billing_audit_verify_$(date -u +%Y%m%d_%H%M%S)"
REMOTE_DIR="$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PREFIX/$TIER"

# ----------------------------------------------------------------------------
# Step 1: find the most recent artifact in the chosen tier
# ----------------------------------------------------------------------------
log "verify run start: tier=$TIER target_db=$VERIFY_DB"
log "looking for most recent artifact in $REMOTE_DIR/"

# Use lsjson + sort. --files-only excludes directories.
LATEST=$(rclone lsjson --files-only "$REMOTE_DIR/" 2>/dev/null \
    | python3 -c '
import json, sys
files = [o for o in json.load(sys.stdin) if o["Name"].endswith(".sql.age")]
if not files:
    print("")
else:
    files.sort(key=lambda o: o["ModTime"], reverse=True)
    print(files[0]["Name"])
')

if [ -z "$LATEST" ]; then
    err "no .sql.age artifacts found in $REMOTE_DIR/"
    alert "critical" "restore-verify: no artifacts in $TIER tier (cannot verify)"
    exit 2
fi

log "selected artifact: $LATEST"
ARTIFACT_PATH="$REMOTE_DIR/$LATEST"

if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: would download $ARTIFACT_PATH, decrypt, restore into $VERIFY_DB"
    exit 0
fi

# ----------------------------------------------------------------------------
# Step 2: download the artifact
# ----------------------------------------------------------------------------
PLAIN_DUMP="/tmp/.audit-verify-$(date -u +%s).sql"
log "downloading $ARTIFACT_PATH"
if ! rclone cat "$ARTIFACT_PATH" 2>>"$LOG_FILE" > "$PLAIN_DUMP.age"; then
    err "download failed: $ARTIFACT_PATH"
    alert "critical" "restore-verify: download failed for $LATEST"
    exit 3
fi
DOWNLOAD_BYTES=$(wc -c < "$PLAIN_DUMP.age" | tr -d ' ')
log "downloaded $DOWNLOAD_BYTES bytes"

# ----------------------------------------------------------------------------
# Step 3: decrypt
# ----------------------------------------------------------------------------
log "decrypting with $AGE_KEY"
if ! age -d -i "$AGE_KEY" -o "$PLAIN_DUMP" "$PLAIN_DUMP.age" 2>>"$LOG_FILE"; then
    err "decrypt failed"
    alert "critical" "restore-verify: decrypt failed for $LATEST"
    exit 4
fi
PLAIN_BYTES=$(wc -c < "$PLAIN_DUMP" | tr -d ' ')
rm -f "$PLAIN_DUMP.age"
log "decrypted $PLAIN_BYTES bytes of plaintext sql"

# ----------------------------------------------------------------------------
# Step 4: create the throwaway DB and restore
# ----------------------------------------------------------------------------
log "creating throwaway db $VERIFY_DB"
if ! docker exec "$PG_CONTAINER" createdb -U "$PG_USER" "$VERIFY_DB" \
        >> "$LOG_FILE" 2>&1; then
    err "createdb failed for $VERIFY_DB"
    alert "critical" "restore-verify: createdb failed for $VERIFY_DB"
    exit 5
fi

# pg_restore --no-owner --no-privileges matches the dump flags.
# Use psql instead of pg_restore because pg_dump emits a plain-SQL dump
# (we did not use -Fc / -Fd). The script is split on transaction boundaries
# naturally because pg_dump emits BEGIN; ... COMMIT; pairs.
log "restoring dump into $VERIFY_DB"
# Pipe the dump into psql. --single-transaction would be nice but it
# conflicts with the explicit BEGIN/COMMIT pairs in the dump; psql
# handles them natively.
if ! docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$VERIFY_DB" \
        -v ON_ERROR_STOP=1 --no-psqlrc -f - < "$PLAIN_DUMP" \
        >> "$LOG_FILE" 2>&1; then
    err "restore into $VERIFY_DB failed"
    alert "critical" "restore-verify: restore failed for $LATEST"
    exit 5
fi
log "restore into $VERIFY_DB complete"

# ----------------------------------------------------------------------------
# Step 5: sanity checks
#
# We check three things:
#   1. The audit_trail table exists.
#   2. Its row count is >= MIN_AUDIT_TRAIL_ROWS.
#   3. The schema is sensible (cryptographic_signature column present).
# ----------------------------------------------------------------------------
log "sanity check: audit_trail table existence + row count"
CHECK=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$VERIFY_DB" -At -c "
    SELECT
        EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'audit_trail'),
        (SELECT count(*) FROM audit_trail),
        EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'audit_trail'
                  AND column_name = 'cryptographic_signature');
" 2>>"$LOG_FILE")

IFS='|' read -r TABLE_EXISTS ROW_COUNT SIG_COL_EXISTS <<< "$CHECK"
TABLE_EXISTS=$(echo "$TABLE_EXISTS" | tr -d ' ')
ROW_COUNT=$(echo "$ROW_COUNT" | tr -d ' ')
SIG_COL_EXISTS=$(echo "$SIG_COL_EXISTS" | tr -d ' ')

log "  table exists:        $TABLE_EXISTS"
log "  row count:           $ROW_COUNT"
log "  cryptographic_signature column exists: $SIG_COL_EXISTS"

PASS=1
if [ "$TABLE_EXISTS" != "t" ]; then
    err "sanity FAIL: audit_trail table is missing from the restored dump"
    alert "critical" "restore-verify: audit_trail table missing from $LATEST"
    PASS=0
fi
if [ "$SIG_COL_EXISTS" != "t" ]; then
    err "sanity FAIL: cryptographic_signature column is missing from audit_trail"
    alert "critical" "restore-verify: audit_trail schema incomplete in $LATEST"
    PASS=0
fi
if ! [[ "$ROW_COUNT" =~ ^[0-9]+$ ]] || [ "$ROW_COUNT" -lt "$MIN_AUDIT_TRAIL_ROWS" ]; then
    err "sanity FAIL: audit_trail row count is $ROW_COUNT, expected >= $MIN_AUDIT_TRAIL_ROWS"
    alert "critical" "restore-verify: audit_trail row count $ROW_COUNT < $MIN_AUDIT_TRAIL_ROWS in $LATEST"
    PASS=0
fi

# ----------------------------------------------------------------------------
# Step 6: record result
# ----------------------------------------------------------------------------
if [ "$PASS" -eq 1 ]; then
    log "VERIFY PASS: $LATEST restored to $VERIFY_DB; audit_trail rows=$ROW_COUNT"
    printf '%s %s %s %s %s %s\n' "$(ts)" "$TIER" "$LATEST" "$DOWNLOAD_BYTES" "$PLAIN_BYTES" "$ROW_COUNT" \
        >> "$VERIFY_RECORD"
    exit 0
else
    log "VERIFY FAIL: $LATEST did not pass sanity checks"
    printf '%s %s %s %s %s %s\n' "$(ts)" "$TIER" "$LATEST" "$DOWNLOAD_BYTES" "$PLAIN_BYTES" "FAIL" \
        >> "$VERIFY_RECORD"
    exit 6
fi
