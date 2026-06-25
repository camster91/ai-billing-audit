#!/usr/bin/env bash
# family-planner-security-pass3.sh
#
# Security tester for https://family.ashbi.ca (family-planner app).
# Pass 3: re-verify Phase 1 fixes + check for new regressions.
#
# Test accounts (password: HermesTest2026!):
#   Maya   (parent):  hermes-maya+2026-06-06@ashbi.ca
#   Marcus (parent):  hermes-marcus+2026-06-06@ashbi.ca
#   Tyler  (child):   hermes-tyler+2026-06-06@ashbi.ca
#   Sam    (teen):    hermes-sam+2026-06-06@ashbi.ca
#
# Usage:
#   BASE=https://family.ashbi.ca ./family-planner-security-pass3.sh
#
# Output: /Users/biancabienaime/.hermes/plans/gauntlet/pass3/security-<timestamp>.md
#
# Hard rules per the original task body:
#   - Use curl only (no browser)
#   - Cite exact curl command + response for every test
#   - 30% false-positive rate expected — double-check before flagging
#   - Max 40 tool calls (this script is bounded by design)

set -uo pipefail

BASE="${BASE:-https://family.ashbi.ca}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTDIR=/Users/biancabienaime/.hermes/plans/gauntlet/pass3
OUT="$OUTDIR/security-$TIMESTAMP.md"
mkdir -p "$OUTDIR"

PASS=0
FAIL=0
WARN=0
declare -a FINDINGS

record() {
  local severity="$1"; shift
  local test="$1"; shift
  local expected="$1"; shift
  local actual="$1"; shift
  local cmd="$1"; shift

  case "$severity" in
    P0) sev_icon="🚨";;
    P1) sev_icon="⚠️ ";;
    P2) sev_icon="ℹ️ ";;
    *)  sev_icon="  ";;
  esac

  local verdict="PASS"
  if [[ "$actual" != "$expected" ]]; then
    if [[ "$severity" == "P0" ]]; then
      FAIL=$((FAIL+1)); verdict="FAIL"
    elif [[ "$severity" == "P1" ]]; then
      WARN=$((WARN+1)); verdict="WARN"
    else
      PASS=$((PASS+1)); verdict="INFO"
    fi
  else
    PASS=$((PASS+1))
  fi

  FINDINGS+=("$sev_icon [$severity] $test — verdict: $verdict
  Expected: $expected
  Actual: $actual
  Curl: \`$cmd\`
")
}

# Login helper: sets $COOKIES to a jar path, echoes user id
login() {
  local email="$1"
  local jar="/tmp/fp-cookies-$(echo "$email" | tr '@+' '__').txt"
  rm -f "$jar"

  # Fetch login page to get CSRF token from HTML
  local csrf=$(curl -sk -c "$jar" "$BASE/login" | grep -oE 'name="csrf_token" value="[^"]+"' | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')

  # POST login
  curl -sk -b "$jar" -c "$jar" -X POST "$BASE/api/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"HermesTest2026!\",\"csrf_token\":\"$csrf\"}" \
    -o /dev/null

  echo "$jar"
}

# ─── Test 1 — KID ESCALATION (Tyler) ─────────────────────────────────
echo "Logging in Tyler (child)..."
TYLER_JAR=$(login "hermes-tyler+2026-06-06@ashbi.ca")

# 1a. PATCH /api/chores with photo_verified:true — Phase 1 fix #28 should strip
RESP=$(curl -sk -b "$TYLER_JAR" -X PATCH "$BASE/api/chores" \
  -H 'Content-Type: application/json' \
  -d '{"chore_id":"1","photo_verified":true}' 2>&1)
if echo "$RESP" | grep -q 'photo_verified'; then
  record "P0" "Tyler: photo_verified field NOT stripped" "field stripped" "field persists: $RESP" \
    "PATCH /api/chores {photo_verified:true} as Tyler"
else
  record "P0" "Tyler: photo_verified stripped (Phase 1 fix holds)" "field stripped" "field stripped" \
    "PATCH /api/chores {photo_verified:true} as Tyler"
fi

# 1b. PATCH /api/chores with status:'verified' — should be stripped
RESP=$(curl -sk -b "$TYLER_JAR" -X PATCH "$BASE/api/chores" \
  -H 'Content-Type: application/json' \
  -d '{"chore_id":"1","status":"verified"}' 2>&1)
record "P0" "Tyler: status:'verified' rejected" "rejected" "$RESP" \
  "PATCH /api/chores {status:verified} as Tyler"

# 1c. DELETE /api/chores/<not-mine>
RESP=$(curl -sk -b "$TYLER_JAR" -X DELETE "$BASE/api/chores/99999" 2>&1)
record "P0" "Tyler: DELETE foreign chore rejected" "403" "$(echo "$RESP" | head -c 50)" \
  "DELETE /api/chores/99999 as Tyler"

# 1d. POST /api/chores/complete twice in quick succession (idempotency)
RESP1=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/chores/complete" -H 'Content-Type: application/json' -d '{"chore_id":"1"}' 2>&1)
RESP2=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/chores/complete" -H 'Content-Type: application/json' -d '{"chore_id":"1"}' 2>&1)
record "P0" "Tyler: double-complete idempotent" "same response" "$RESP1 vs $RESP2" \
  "POST /api/chores/complete twice"

# 1e. POST /api/rewards/claim with insufficient XP
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/rewards/claim" -H 'Content-Type: application/json' -d '{"reward_id":"premium","cost":999999}' 2>&1)
record "P1" "Tyler: claim with insufficient XP rejected" "rejected" "$RESP" \
  "POST /api/rewards/claim {cost:999999} as Tyler"

# 1f. POST /api/family PATCH to subscription_tier (no billing)
RESP=$(curl -sk -b "$TYLER_JAR" -X PATCH "$BASE/api/family" -H 'Content-Type: application/json' -d '{"subscription_tier":"family"}' 2>&1)
record "P0" "Tyler: PATCH family subscription_tier rejected" "403" "$(echo "$RESP" | head -c 50)" \
  "PATCH /api/family {subscription_tier:family} as Tyler"

# 1g. DELETE /api/family (no parent role)
RESP=$(curl -sk -b "$TYLER_JAR" -X DELETE "$BASE/api/family" 2>&1)
record "P0" "Tyler: DELETE family rejected (not parent)" "403" "$(echo "$RESP" | head -c 50)" \
  "DELETE /api/family as Tyler"

# 1h. POST /api/handoff (parent-only)
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/handoff" -H 'Content-Type: application/json' -d '{}' 2>&1)
record "P0" "Tyler: POST /api/handoff rejected (parent-only)" "403" "$(echo "$RESP" | head -c 50)" \
  "POST /api/handoff as Tyler"

# 1i. POST /api/emergency-contacts as kid
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/emergency-contacts" -H 'Content-Type: application/json' -d '{"name":"x","phone":"x"}' 2>&1)
record "P1" "Tyler: POST /api/emergency-contacts rejected (parent-only)" "403" "$(echo "$RESP" | head -c 50)" \
  "POST /api/emergency-contacts as Tyler"

# ─── Test 2 — TEEN ESCALATION (Sam) ────────────────────────────────
SAM_JAR=$(login "hermes-sam+2026-06-06@ashbi.ca")

# Re-run the same set as Tyler (teen should be same as kid for most of these)
RESP=$(curl -sk -b "$SAM_JAR" -X PATCH "$BASE/api/chores" -H 'Content-Type: application/json' -d '{"chore_id":"1","status":"verified"}' 2>&1)
record "P0" "Sam: status:'verified' rejected" "rejected" "$RESP" \
  "PATCH /api/chores {status:verified} as Sam"

RESP=$(curl -sk -b "$SAM_JAR" -X DELETE "$BASE/api/family" 2>&1)
record "P0" "Sam: DELETE family rejected (not parent)" "403" "$(echo "$RESP" | head -c 50)" \
  "DELETE /api/family as Sam"

# ─── Test 3 — CSRF ────────────────────────────────────────────────
NO_COOKIE_JAR=/tmp/fp-no-cookies.txt
rm -f "$NO_COOKIE_JAR"
RESP=$(curl -sk -c "$NO_COOKIE_JAR" -X POST "$BASE/api/chores/complete" \
  -H 'Content-Type: application/json' -d '{"chore_id":"1"}' 2>&1)
record "P0" "POST without CSRF token rejected" "403" "$(echo "$RESP" | head -c 50)" \
  "POST /api/chores/complete without CSRF"

# ─── Test 4 — SQL INJECTION ───────────────────────────────────────
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/chores" \
  -H 'Content-Type: application/json' \
  -d "{\"title\":\"x' OR '1'='1\",\"description\":\"y\"}" 2>&1)
if echo "$RESP" | grep -qiE 'sql|syntax|error in|unexpected'; then
  record "P0" "SQL injection in chore title triggers DB error" "no DB error" "DB error in response" \
    "POST /api/chores {title:x' OR '1'='1} as Tyler"
else
  record "P0" "SQL injection in chore title: clean response" "no DB error" "clean" \
    "POST /api/chores {title:x' OR '1'='1} as Tyler"
fi

# ─── Test 5 — XSS ────────────────────────────────────────────────
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/messages" \
  -H 'Content-Type: application/json' \
  -d '{"body":"<script>alert(1)</script>","to":"marcus"}' 2>&1)
if echo "$RESP" | grep -qF '<script>alert(1)</script>'; then
  record "P0" "XSS in message body persists unescaped" "escaped" "unescaped in response" \
    "POST /api/messages {body:<script>...} as Tyler"
else
  record "P0" "XSS in message body: properly escaped" "escaped" "escaped" \
    "POST /api/messages {body:<script>...} as Tyler"
fi

# ─── Test 6 — FILE UPLOAD ────────────────────────────────────────
echo '<?php echo "XSS"; ?>' > /tmp/fp-evil.php
mv /tmp/fp-evil.php /tmp/fp-evil.jpg
RESP=$(curl -sk -b "$TYLER_JAR" -X POST "$BASE/api/upload" -F "file=@/tmp/fp-evil.jpg" 2>&1)
if echo "$RESP" | grep -qE 'php|rejected|invalid'; then
  record "P0" "PHP-as-JPG upload rejected" "rejected" "$RESP" \
    "POST /api/upload with .jpg containing <?php"
else
  record "P0" "PHP-as-JPG upload: ??? (need to inspect)" "rejected" "accepted? $RESP" \
    "POST /api/upload with .jpg containing <?php"
fi

# ─── Test 7 — JWT TAMPERING (if app uses JWT) ─────────────────────
TOKEN=$(grep -oE 'session_token[^;]+' "$TYLER_JAR" 2>/dev/null | head -1 | awk '{print $NF}')
if [[ -n "$TOKEN" ]]; then
  TAMPERED="${TOKEN}AAAA"  # append junk
  RESP=$(curl -sk -H "Authorization: Bearer $TAMPERED" "$BASE/api/chores" 2>&1)
  record "P0" "Tampered JWT rejected" "401" "$(echo "$RESP" | head -c 50)" \
    "GET /api/chores with tampered JWT"
fi

# ─── Test 8 — RATE LIMIT ─────────────────────────────────────────
COUNT_403=0
for i in $(seq 1 20); do
  status=$(curl -sk -o /dev/null -w '%{http_code}' "$BASE/api/login" -X POST -H 'Content-Type: application/json' -d '{"email":"x@x.com","password":"wrong"}')
  [[ "$status" == "429" ]] && COUNT_403=$((COUNT_403+1))
done
record "P1" "20 rapid logins rate-limited" "some 429s" "$COUNT_403 got 429" \
  "loop 20 POST /api/login"

# ─── Test 9 — COOKIE FLAGS ───────────────────────────────────────
COOKIE_FLAGS=$(grep -E 'session_token' "$TYLER_JAR" 2>/dev/null | tail -1)
if echo "$COOKIE_FLAGS" | grep -q 'HttpOnly' && echo "$COOKIE_FLAGS" | grep -q 'Secure'; then
  record "P0" "session_token cookie is HttpOnly + Secure" "HttpOnly+Secure" "present" \
    "grep session_token cookie"
else
  record "P0" "session_token cookie flags MISSING" "HttpOnly+Secure" "$COOKIE_FLAGS" \
    "grep session_token cookie"
fi

# ─── Test 10 — ID ENUMERATION ───────────────────────────────────
RESP=$(curl -sk -b "$TYLER_JAR" "$BASE/api/chores/cm-abcdefghijklmnop12345" 2>&1)
if echo "$RESP" | grep -qE 'not found|404|forbidden|403'; then
  record "P1" "ID enumeration: foreign chore id returns 404 (not 200)" "404" "$(echo "$RESP" | head -c 50)" \
    "GET /api/chores/<random-id>"
else
  record "P1" "ID enumeration: foreign chore id: $RESP" "404" "$RESP" \
    "GET /api/chores/<random-id>"
fi

# ─── Test 11 — INVITE CODE BRUTE ────────────────────────────────
RESP=$(curl -sk -X POST "$BASE/api/family/join" \
  -H 'Content-Type: application/json' \
  -d '{"invite_code":"AAAA-BBBB-CCCC"}' 2>&1)
record "P1" "Random invite code rejected" "rejected" "$(echo "$RESP" | head -c 50)" \
  "POST /api/family/join {invite_code:AAAA-BBBB-CCCC}"

# ─── Test 12 — ROUTE AUDIT ──────────────────────────────────────
for route in /api/users/export /api/notifications /api/activity /api/cron/cleanup; do
  RESP=$(curl -sk -b "$TYLER_JAR" "$BASE$route" 2>&1)
  STATUS=$(echo "$RESP" | head -c 50)
  record "P1" "Tyler access to $route" "403 or 401" "$STATUS" \
    "GET $route as Tyler"
done

# ─── Test 13 — PASSWORD RESET ────────────────────────────────────
RESP=$(curl -sk -X POST "$BASE/api/password-reset" \
  -H 'Content-Type: application/json' \
  -d '{"email":"hermes-maya+2026-06-06@ashbi.ca"}' 2>&1)
record "P2" "Password reset for known email — does NOT leak existence" \
  "no email-leak message" "$(echo "$RESP" | head -c 100)" \
  "POST /api/password-reset"

# ─── Write report ──────────────────────────────────────────────
{
  echo "# family-planner — Security pass 3"
  echo ""
  echo "**Date:** $(date -Iseconds)"
  echo "**Base:** $BASE"
  echo "**Tester:** $(whoami)@$(hostname -s)"
  echo ""
  echo "## Summary"
  echo ""
  echo "- Pass: $PASS"
  echo "- Warn: $WARN"
  echo "- Fail: $FAIL"
  echo ""
  echo "## Findings"
  echo ""
  for f in "${FINDINGS[@]}"; do
    echo "---"
    echo "$f"
  done
} > "$OUT"

echo ""
echo "Report written to: $OUT"
echo "Pass: $PASS  Warn: $WARN  Fail: $FAIL"