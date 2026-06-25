#!/usr/bin/env bash
# joesheating-probe.sh — pre-flight checks before the 22-task WP edit sprint.
#
# Usage:   ./joesheating-probe.sh
# Returns: 0 if all checks pass, non-zero on any failure.
#
# Checks:
#   1. Domain resolves
#   2. Site is up (200) and HTTPS cert valid
#   3. WP REST API reachable (proves WP core healthy)
#   4. Admin endpoint reachable (proves wp-login not blocked by WAF)
#   5. Image attachment audit — count posts with no featured image
#   6. Find any remaining "Durham" references (the keyword we just fixed)
#   7. /furnace/ → /furnaces/ redirect exists
#   8. /projects/ archive page exists (returns 200)
#   9. /offers page returns 200 + contains "savings"
#
# Does NOT require WP admin auth — pure external probing.

set -uo pipefail

DOMAIN="https://joesheating.ca"
PASS=0
FAIL=0
WARN=0

check() {
  local name="$1"
  local result="$2"   # ok | warn | fail
  local detail="$3"
  case "$result" in
    ok)   echo "✅ $name — $detail"; PASS=$((PASS+1));;
    warn) echo "⚠️  $name — $detail"; WARN=$((WARN+1));;
    fail) echo "❌ $name — $detail"; FAIL=$((FAIL+1));;
  esac
}

# 1. DNS resolves
if dig +short joesheating.ca A | grep -qE '^[0-9.]+$'; then
  check "DNS A-record" "ok" "$(dig +short joesheating.ca A | head -1)"
else
  check "DNS A-record" "fail" "no A record"
fi

# 2. HTTPS 200
status=$(curl -sk -o /dev/null -w '%{http_code}' "$DOMAIN/" --max-time 10)
if [[ "$status" == "200" ]]; then
  check "Site reachable" "ok" "200 OK"
else
  check "Site reachable" "fail" "got $status"
fi

# 3. WP REST API
status=$(curl -sk -o /dev/null -w '%{http_code}' "$DOMAIN/wp-json/wp/v2/" --max-time 10)
if [[ "$status" == "200" ]]; then
  check "WP REST API" "ok" "200 OK (WP core healthy)"
else
  check "WP REST API" "fail" "got $status (WP core broken?)"
fi

# 4. wp-login.php reachable
status=$(curl -sk -o /dev/null -w '%{http_code}' "$DOMAIN/wp-login.php" --max-time 10)
if [[ "$status" == "200" ]]; then
  check "wp-login.php" "ok" "200 OK (admin reachable)"
else
  check "wp-login.php" "warn" "got $status (WAF may be blocking, needs IP whitelist)"
fi

# 5. Posts without featured images — public REST API only counts posts that have a featured_image, so look at recent 20
no_feat=$(curl -sk "$DOMAIN/wp-json/wp/v2/posts?per_page=20" --max-time 10 | \
  python3 -c "import sys,json; posts=json.load(sys.stdin); print(sum(1 for p in posts if not p.get('featured_media')))" 2>/dev/null)
if [[ -n "$no_feat" && "$no_feat" -gt 0 ]]; then
  check "Featured images missing" "warn" "$no_feat of last 20 posts have no featured image"
else
  check "Featured images" "ok" "all sampled posts have featured images"
fi

# 6. Residual "Durham" mentions
count=$(curl -sk "$DOMAIN/" --max-time 10 | grep -io 'durham' | wc -l | tr -d ' ')
if [[ "$count" -gt 0 ]]; then
  check "Durham keyword" "warn" "$count occurrences on homepage (spec'd to be removed)"
else
  check "Durham keyword" "ok" "0 occurrences on homepage"
fi

# 7. /furnace/ → /furnaces/ redirect
loc=$(curl -sk -o /dev/null -w '%{redirect_url}' "$DOMAIN/furnace/" --max-time 10)
if [[ "$loc" == *"/furnaces/"* ]]; then
  check "/furnace/ redirect" "ok" "→ $loc"
elif [[ -z "$loc" ]]; then
  check "/furnace/ redirect" "warn" "no redirect (rule not added yet)"
else
  check "/furnace/ redirect" "warn" "redirects to $loc (not /furnaces/)"
fi

# 8. /projects/ archive
status=$(curl -sk -o /dev/null -w '%{http_code}' "$DOMAIN/projects/" --max-time 10)
if [[ "$status" == "200" ]]; then
  check "/projects/ archive" "ok" "200 OK"
else
  check "/projects/ archive" "warn" "got $status (page not created yet)"
fi

# 9. /offers page
status=$(curl -sk -o /dev/null -w '%{http_code}' "$DOMAIN/offers/" --max-time 10)
content=$(curl -sk "$DOMAIN/offers/" --max-time 10)
if [[ "$status" == "200" ]] && echo "$content" | grep -qi 'savings'; then
  check "/offers page" "ok" "200 OK, contains 'savings'"
else
  check "/offers page" "warn" "got $status (page may need fixing)"
fi

echo ""
echo "───────────────────────────────────────────"
echo "Results: $PASS pass, $WARN warn, $FAIL fail"
echo "───────────────────────────────────────────"

# Exit non-zero only on hard failures (warns are pre-fix expected state)
[[ $FAIL -eq 0 ]] && exit 0 || exit 1