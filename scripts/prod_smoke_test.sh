#!/usr/bin/env bash
# Production smoke test for ai-billing-audit.ashbi.ca.
#
# Usage: bash scripts/prod_smoke_test.sh
#
# What it does:
#   1. Hits /healthz (private; just verifies the api process is up)
#   2. Hits /metrics (public; verifies Prometheus scraping works)
#   3. Hits the public-read marketing pages (/, /roi, /case-studies,
#      /contact, /legal/privacy, /legal/terms) — each must be 200
#      with no bearer token
#   4. Hits /openapi.json — must be 200 with valid JSON schema
#   5. Checks the auth-required behaviour: an encounter detail
#      URL returns 401 (not 200, not 500)
#   6. Optionally checks the rate-limit middleware: 11 rapid
#      POSTs to /contact should include at least one 429
#      (skip this step with --skip-rate-test if the limit was
#      recently hit during a real pilot demo)
#
# Exit code 0 = all smoke tests passed. Non-zero = at least one
# check failed (the failing check is printed to stderr).

set -eo pipefail

HOST="${HOST:-https://ai-billing-audit.ashbi.ca}"
SKIP_RATE_TEST=0
for arg in "$@"; do
    case "$arg" in
        --skip-rate-test) SKIP_RATE_TEST=1 ;;
    esac
done

PASS=0
FAIL=0
TOTAL=0

check_status() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$actual" = "$expected" ]; then
        printf '  ✓ %-45s %s\n' "$label" "$actual"
        PASS=$((PASS + 1))
    else
        printf '  ✗ %-45s got=%s want=%s\n' "$label" "$actual" "$expected" >&2
        FAIL=$((FAIL + 1))
    fi
}

http_status() {
    curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$@"
}

echo "smoke test: $HOST"
echo "============================================"

# 1. /healthz (auth required but anon-readable since /healthz is whitelisted)
check_status "GET /healthz" 200 "$(http_status "$HOST/healthz")"

# 2. /metrics (public)
check_status "GET /metrics (Prometheus)" 200 "$(http_status "$HOST/metrics")"

# 3. Marketing / public-read pages
check_status "GET / (index)" 200 "$(http_status "$HOST/")"
check_status "GET /roi" 200 "$(http_status "$HOST/roi")"
check_status "GET /case-studies" 200 "$(http_status "$HOST/case-studies")"
check_status "GET /contact" 200 "$(http_status "$HOST/contact")"
check_status "GET /legal/privacy" 200 "$(http_status "$HOST/legal/privacy")"
check_status "GET /legal/terms" 200 "$(http_status "$HOST/legal/terms")"

# 4. /openapi.json must be valid JSON with a paths key
SCHEMA_PATHS=$(curl -sS --max-time 10 "$HOST/openapi.json" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('paths', {})))" 2>/dev/null \
    || echo "0")
TOTAL=$((TOTAL + 1))
if [ "$SCHEMA_PATHS" -gt 50 ]; then
    printf '  ✓ %-45s %s paths\n' "GET /openapi.json (valid schema)" "$SCHEMA_PATHS"
    PASS=$((PASS + 1))
else
    printf '  ✗ %-45s only %s paths\n' "GET /openapi.json (valid schema)" "$SCHEMA_PATHS" >&2
    FAIL=$((FAIL + 1))
fi

# 5. Auth-required: a non-whitelisted GET returns 401 (when
# AUDIT_BEARER_TOKEN is set) or 503 (when it's not configured
# yet — operator hasn't provisioned auth). Either is acceptable
# as "the route is not publicly accessible." Use the response
# code as the assertion (>= 400 and not 500/200).
AUTH_CODE=$(http_status "$HOST/encounter/enc-001")
TOTAL=$((TOTAL + 1))
if [ "$AUTH_CODE" = "401" ] || [ "$AUTH_CODE" = "503" ]; then
    printf '  ✓ %-45s %s (auth-gated)\n' "GET /encounter/enc-001" "$AUTH_CODE"
    PASS=$((PASS + 1))
else
    printf '  ✗ %-45s got=%s want=401 or 503\n' "GET /encounter/enc-001" "$AUTH_CODE" >&2
    FAIL=$((FAIL + 1))
fi

# 6. Rate limit (optional)
if [ "$SKIP_RATE_TEST" = "0" ]; then
    echo "  - rate-limit test (POST /contact 11x, expect at least one 429)"
    HIT_429=0
    for _ in $(seq 1 11); do
        CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST \
            -H 'X-Forwarded-For: 10.99.99.99' \
            --data 'name=smoketest' "$HOST/contact")
        if [ "$CODE" = "429" ]; then
            HIT_429=1
            break
        fi
    done
    TOTAL=$((TOTAL + 1))
    if [ "$HIT_429" = "1" ]; then
        printf '  ✓ %-45s got 429 within 11 hits\n' "rate limit kicks in"
        PASS=$((PASS + 1))
    else
        printf '  ✗ %-45s no 429 in 11 hits\n' "rate limit kicks in" >&2
        FAIL=$((FAIL + 1))
    fi
else
    echo "  - rate-limit test skipped (--skip-rate-test)"
fi

echo "============================================"
printf '%d passed, %d failed (of %d total)\n' "$PASS" "$FAIL" "$TOTAL"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0