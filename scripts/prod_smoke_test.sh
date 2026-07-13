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
check_status "GET / (marketing landing)" 200 "$(http_status "$HOST/")"
check_status "GET /audits (dashboard)" 200 "$(http_status "$HOST/audits")"
check_status "GET /about" 200 "$(http_status "$HOST/about")"
check_status "GET /blog" 200 "$(http_status "$HOST/blog")"
check_status "GET /careers" 200 "$(http_status "$HOST/careers")"
check_status "GET /changelog" 200 "$(http_status "$HOST/changelog")"
check_status "GET /compare" 200 "$(http_status "$HOST/compare")"
check_status "GET /contact" 200 "$(http_status "$HOST/contact")"
check_status "GET /demo-request" 200 "$(http_status "$HOST/demo-request")"
check_status "GET /faq" 200 "$(http_status "$HOST/faq")"
check_status "GET /for/family-medicine" 200 "$(http_status "$HOST/for/family-medicine")"
check_status "GET /glossary" 200 "$(http_status "$HOST/glossary")"
check_status "GET /how-it-works" 200 "$(http_status "$HOST/how-it-works")"
check_status "GET /legal/privacy" 200 "$(http_status "$HOST/legal/privacy")"
check_status "GET /legal/terms" 200 "$(http_status "$HOST/legal/terms")"
check_status "GET /pilot" 200 "$(http_status "$HOST/pilot")"
check_status "GET /press" 200 "$(http_status "$HOST/press")"
check_status "GET /pricing" 200 "$(http_status "$HOST/pricing")"
check_status "GET /roi" 200 "$(http_status "$HOST/roi")"
check_status "GET /case-studies" 200 "$(http_status "$HOST/case-studies")"
check_status "GET /security" 200 "$(http_status "$HOST/security")"
check_status "GET /status" 200 "$(http_status "$HOST/status")"
check_status "GET /trust" 200 "$(http_status "$HOST/trust")"
check_status "GET /try" 200 "$(http_status "$HOST/try")"
check_status "GET /what-zorva-finds" 200 "$(http_status "$HOST/what-zorva-finds")"
check_status "GET /newsletter" 200 "$(http_status "$HOST/newsletter")"
check_status "GET /blog/why-we-built-zorva" 200 "$(http_status "$HOST/blog/why-we-built-zorva")"
check_status "GET /blog/18-ahcip-rules" 200 "$(http_status "$HOST/blog/18-ahcip-rules")"
check_status "GET /blog/why-flat-fee" 200 "$(http_status "$HOST/blog/why-flat-fee")"
check_status "GET /blog/why-alberta-first" 200 "$(http_status "$HOST/blog/why-alberta-first")"
check_status "GET /glossary/ahcip" 200 "$(http_status "$HOST/glossary/ahcip")"
check_status "GET /glossary/modifier-25" 200 "$(http_status "$HOST/glossary/modifier-25")"
check_status "GET /changelog/v0.5.0" 200 "$(http_status "$HOST/changelog/v0.5.0")"
check_status "GET /rss.xml" 200 "$(http_status "$HOST/rss.xml")"
check_status "GET /sitemap.xml" 200 "$(http_status "$HOST/sitemap.xml")"
check_status "GET /robots.txt" 200 "$(http_status "$HOST/robots.txt")"
check_status "GET /static/dashboard.css" 200 "$(http_status "$HOST/static/dashboard.css")"
check_status "GET /static/og-image.jpg" 200 "$(http_status "$HOST/static/og-image.jpg")"
check_status "GET /static/favicon.ico" 200 "$(http_status "$HOST/static/favicon.ico")"
check_status "GET /this-does-not-exist (branded 404)" 404 "$(http_status "$HOST/this-does-not-exist")"

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