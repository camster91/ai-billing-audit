#!/usr/bin/env bash
# alinenasseh-dns-probe.sh — verify alinenasseh.com DNS flip to 187.77.26.99
#
# Usage: ./alinenasseh-dns-probe.sh
# Returns: 0 if propagated, non-zero otherwise.

set -uo pipefail

DOMAIN="alinenasseh.com"
EXPECTED="187.77.26.99"
OLD_IPS=("141.193.213.10" "141.193.213.11")
PASS=0
FAIL=0
WARN=0

check() {
  case "$1" in
    ok)   echo "✅ $2 — $3"; PASS=$((PASS+1));;
    warn) echo "⚠️  $2 — $3"; WARN=$((WARN+1));;
    fail) echo "❌ $2 — $3"; FAIL=$((FAIL+1));;
  esac
}

echo "Resolving $DOMAIN from multiple resolvers..."
echo ""

# Local resolver
LOCAL=$(dig +short "$DOMAIN" A 2>/dev/null | head -1)
if [[ "$LOCAL" == "$EXPECTED" ]]; then
  check "local resolver" "ok" "$LOCAL"
else
  check "local resolver" "fail" "got '$LOCAL', expected $EXPECTED"
fi

# Google DNS
GOOGLE=$(dig @8.8.8.8 +short "$DOMAIN" A 2>/dev/null | head -1)
if [[ "$GOOGLE" == "$EXPECTED" ]]; then
  check "Google DNS (8.8.8.8)" "ok" "$GOOGLE"
else
  check "Google DNS (8.8.8.8)" "warn" "got '$GOOGLE' (propagation lag, retry in 60s)"
fi

# Cloudflare DNS
CF=$(dig @1.1.1.1 +short "$DOMAIN" A 2>/dev/null | head -1)
if [[ "$CF" == "$EXPECTED" ]]; then
  check "Cloudflare DNS (1.1.1.1)" "ok" "$CF"
else
  check "Cloudflare DNS (1.1.1.1)" "warn" "got '$CF' (propagation lag, retry in 60s)"
fi

# Quad9
Q9=$(dig @9.9.9.9 +short "$DOMAIN" A 2>/dev/null | head -1)
if [[ "$Q9" == "$EXPECTED" ]]; then
  check "Quad9 DNS (9.9.9.9)" "ok" "$Q9"
else
  check "Quad9 DNS (9.9.9.9)" "warn" "got '$Q9' (propagation lag)"
fi

# Old IPs must be GONE
ALL_IPS=$(dig +short "$DOMAIN" A 2>/dev/null)
for old in "${OLD_IPS[@]}"; do
  if echo "$ALL_IPS" | grep -qF "$old"; then
    check "old IP $old gone" "fail" "still resolving"
  else
    check "old IP $old gone" "ok" "not in records"
  fi
done

# HTTPS works on the new IP
status=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/" --max-time 10 2>/dev/null)
if [[ "$status" == "200" ]]; then
  check "HTTPS alinenasseh.com" "ok" "200 OK"
elif [[ "$status" == "301" || "$status" == "302" ]]; then
  check "HTTPS alinenasseh.com" "warn" "got $status (redirect — verify Location header)"
else
  check "HTTPS alinenasseh.com" "fail" "got $status"
fi

# SSL cert valid
cert_subject=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN":443 2>/dev/null | \
               openssl x509 -noout -subject 2>/dev/null | head -1)
if echo "$cert_subject" | grep -qE "(CN|subject) ?= ?(alinenasseh.com|\*\.alinenasseh.com)"; then
  check "SSL cert subject" "ok" "$cert_subject"
else
  check "SSL cert subject" "warn" "got '$cert_subject' (may still be propagating)"
fi

echo ""
echo "───────────────────────────────────────────"
echo "Results: $PASS pass, $WARN warn, $FAIL fail"
echo ""

# Warn-only is acceptable (propagation takes time). Fail means something is broken.
if [[ $FAIL -gt 0 ]]; then
  exit 1
else
  exit 0
fi