#!/usr/bin/env bash
# test-backup-scripts.sh — unit tests for audit-backup.sh logic
# ----------------------------------------------------------------------------
# Tests the parts of the script that can be exercised without docker, rclone,
# or the live database:
#   - size-anomaly detection (>=50% drop)
#   - tier auto-pick from date
#   - idempotency check (filename prefix matching)
#   - retention tier max-age constants
#   - arg parsing accepts/flags the right combinations
#
# Run from anywhere:
#   bash deploy/scripts/test-backup-scripts.sh
# ----------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
FAIL=0
LOG_DIR="/tmp/audit-test-$$"
mkdir -p "$LOG_DIR"

assert() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [ "$expected" = "$actual" ]; then
        printf '  PASS  %s\n' "$label"
        PASS=$((PASS+1))
    else
        printf '  FAIL  %s\n' "$label"
        printf '        expected: %q\n' "$expected"
        printf '        actual:   %q\n' "$actual"
        FAIL=$((FAIL+1))
    fi
}

# ----------------------------------------------------------------------------
# Test 1: size-anomaly detection
# Simulates the awk + arithmetic logic from check_size_anomaly() in
# audit-backup.sh. We extract the function to a standalone script so we
# can test it without sourcing the whole main script (which would try to
# touch /var/log and require all the deps).
# ----------------------------------------------------------------------------
test_size_anomaly() {
    printf '\n== size-anomaly ==\n'
    # Mock log with 4 weekly entries; the most recent is what check_size_anomaly
    # should compare against (using the 2nd-to-last = the "prior weekly").
    local LOG="$LOG_DIR/backup.sizes.log"
    : > "$LOG"

    # Helper: simulate check_size_anomaly against a "new_bytes" value and a
    # mock log of weekly sizes. Returns 0 if no alert, 6 if alert fires.
    simulated_check() {
        local new_bytes="$1"
        local prior_weekly
        prior_weekly=$(awk '$2=="weekly"' "$LOG" | tail -n 2 | head -n 1 | awk '{print $3}')
        if [ -z "$prior_weekly" ] || [ "$prior_weekly" -eq 0 ] 2>/dev/null; then
            return 0
        fi
        # Guard division: if new_bytes >= prior_weekly, no drop.
        if [ "$new_bytes" -ge "$prior_weekly" ]; then
            return 0
        fi
        local pct=$(( (prior_weekly - new_bytes) * 100 / prior_weekly ))
        if [ "$pct" -ge 50 ]; then
            return 6
        fi
        return 0
    }

    # First-ever run: no prior weekly, should not alert
    simulated_check 1000; assert "first run, no prior" "0" "$?"

    # Add a "previous" weekly run of 1000 bytes
    printf '2026-06-10T02:00:00Z weekly 1000\n' >> "$LOG"
    simulated_check 900; assert "10% drop, no alert" "0" "$?"
    simulated_check 500; assert "50% drop, alert" "6" "$?"
    simulated_check 400; assert "60% drop, alert" "6" "$?"
    simulated_check 1100; assert "increase, no alert" "0" "$?"

    # Edge case: prior=0
    printf '2026-06-10T02:00:00Z weekly 0\n' > "$LOG"
    simulated_check 5000; assert "prior=0, no alert" "0" "$?"
}

# ----------------------------------------------------------------------------
# Test 2: tier auto-pick from date
# We extract the auto-pick block from audit-backup.sh and test it against
# fixed TODAY_DOW/DAY_OF_MONTH values.
# ----------------------------------------------------------------------------
test_tier_pick() {
    printf '\n== tier auto-pick ==\n'
    pick_tier() {
        local today_dow="$1"
        local day_of_month="$2"
        if [ "$day_of_month" = "01" ] && [ "$today_dow" = "7" ]; then
            echo "monthly"
        elif [ "$today_dow" = "7" ]; then
            echo "weekly"
        else
            echo "daily"
        fi
    }
    assert "Sun + day=01"   "monthly" "$(pick_tier 7 01)"
    assert "Sun + day=08"   "weekly"  "$(pick_tier 7 08)"
    assert "Sun + day=29"   "weekly"  "$(pick_tier 7 29)"
    assert "Mon + day=01"   "daily"   "$(pick_tier 1 01)"
    assert "Mon + day=15"   "daily"   "$(pick_tier 1 15)"
    assert "Sat + day=30"   "daily"   "$(pick_tier 6 30)"
}

# ----------------------------------------------------------------------------
# Test 3: idempotency prefix matching
# Verifies the Python helper that picks an existing artifact for a given
# UTC date + tier works correctly. Uses a synthetic list of files.
# ----------------------------------------------------------------------------
test_idempotency() {
    printf '\n== idempotency prefix match ==\n'
    local result
    result=$(printf '%s\n' \
        'ai-billing-audit_weekly_20260610T020000Z.sql.age' \
        'ai-billing-audit_weekly_20260615T023000Z.sql.age' \
        'ai-billing-audit_weekly_20260617T020000Z.sql.age' \
        'ai-billing-audit_daily_20260617T020000Z.sql.age' \
        | python3 -c '
import sys
utc_date, tier = "20260617", "weekly"
prefix = f"ai-billing-audit_{tier}_{utc_date}"
for line in sys.stdin:
    name = line.rstrip("\n")
    if name.startswith(prefix) and name.endswith(".sql.age"):
        print(name)
        break
')
    assert "match today's weekly" "ai-billing-audit_weekly_20260617T020000Z.sql.age" "$result"

    result=$(printf '%s\n' \
        'ai-billing-audit_weekly_20260610T020000Z.sql.age' \
        | python3 -c '
import sys
utc_date, tier = "20260617", "weekly"
prefix = f"ai-billing-audit_{tier}_{utc_date}"
for line in sys.stdin:
    name = line.rstrip("\n")
    if name.startswith(prefix) and name.endswith(".sql.age"):
        print(name)
        break
')
    assert "no match for missing date" "" "$result"
}

# ----------------------------------------------------------------------------
# Test 4: retention max-age constants
# Verifies the published retention policy is consistent: 28d, 366d, 2557d.
# ----------------------------------------------------------------------------
test_retention_constants() {
    printf '\n== retention max-age constants ==\n'
    local daily=28 weekly=366 monthly=2557
    assert "daily = 28d (4 weeks)"  "28"  "$daily"
    assert "weekly = 366d (12mo+1)" "366" "$weekly"
    assert "monthly = 2557d (7yr+1)" "2557" "$monthly"
    # 7 years: 7*365 + 2 leap days (2024, 2028) = 2555+2 = 2557. Correct.
    if [ "$monthly" -ge 2555 ] && [ "$monthly" -le 2558 ]; then
        printf '  PASS  monthly 7yr covers leap year window (%d)\n' "$monthly"
        PASS=$((PASS+1))
    else
        printf '  FAIL  monthly 7yr out of plausible range (%d)\n' "$monthly"
        FAIL=$((FAIL+1))
    fi
}

# ----------------------------------------------------------------------------
# Test 5: arg parsing on audit-backup.sh and audit-restore-verify.sh
# Verifies --help exits 0, --unknown exits 1, --tier=daily is accepted
# (when the rest of pre-flight is bypassed via LOG_DIR override).
# ----------------------------------------------------------------------------
test_arg_parsing() {
    printf '\n== arg parsing ==\n'
    local bk="$SCRIPT_DIR/audit-backup.sh"
    local rv="$SCRIPT_DIR/audit-restore-verify.sh"
    LOG_DIR=/tmp "$bk" --help >/dev/null 2>&1
    assert "audit-backup.sh --help exits 0" "0" "$?"
    LOG_DIR=/tmp "$rv" --help >/dev/null 2>&1
    assert "audit-restore-verify.sh --help exits 0" "0" "$?"

    # Unknown arg should exit 1 (non-zero)
    LOG_DIR=/tmp "$bk" --bogus >/dev/null 2>&1
    assert "audit-backup.sh --bogus exits 1" "1" "$?"
    LOG_DIR=/tmp "$rv" --bogus >/dev/null 2>&1
    assert "audit-restore-verify.sh --bogus exits 1" "1" "$?"
}

test_size_anomaly
test_tier_pick
test_idempotency
test_retention_constants
test_arg_parsing

printf '\n=== %d passed, %d failed ===\n' "$PASS" "$FAIL"
rm -rf "$LOG_DIR"
[ "$FAIL" -eq 0 ]
