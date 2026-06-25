#!/usr/bin/env bash
# influencers-link-bulk-set-tracking-secret.sh
#
# Bulk-update wcm_tracking_secret on all 23 WP stores via WP-CLI over SSH.
# Cam (or operator) runs this after:
#   1. Generated the secret (openssl rand -hex 32)
#   2. Set it in /home/u633679196/domains/app.influencerslink.com/public_html/.htaccess
#   3. Verified SSH access works to each store's WP install
#
# Usage:
#   SECRET='your-64-char-hex' ./influencers-link-bulk-set-tracking-secret.sh
#
# What it does:
#   - Lists all stores from the dashboard's API (or a static list if API down)
#   - For each store, runs `wp option update wcm_tracking_secret $SECRET --allow-root`
#   - Verifies with `wp option get wcm_tracking_secret` (masked)
#   - Logs pass/fail per store to /tmp/tracking-secret-rollout.log

set -uo pipefail

: "${SECRET:?Set SECRET env var, e.g. SECRET='\$(openssl rand -hex 32)' ./...}"

# The 23 stores — list their hostinger paths here, one per line.
# Format: "store_id|wp_path"
# If the dashboard has /api/stores, prefer pulling live:
STORES=$(curl -sk https://app.influencerslink.com/api/stores -H "X-API-Key: ${DASHBOARD_API_KEY:-}" 2>/dev/null | \
         python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for s in data.get('stores', data if isinstance(data, list) else []):
        print(f\"{s.get('id')}|{s.get('wp_path','')}\")
except: pass
" 2>/dev/null)

if [[ -z "$STORES" ]]; then
  echo "Could not fetch live store list. Use the static list in the script."
  # Cam will need to populate this with the 23 stores' WP paths
  cat <<'EOF' >&2
Add a static list, e.g.:
  STORES=$(cat <<INNER
  1|/home/u633679196/domains/store1.com/public_html
  2|/home/u633679196/domains/store2.com/public_html
  ...
INNER
)
EOF
  exit 2
fi

LOG=/tmp/tracking-secret-rollout.log
> "$LOG"
PASS=0
FAIL=0

echo "$STORES" | while IFS='|' read -r store_id wp_path; do
  [[ -z "$store_id" ]] && continue
  echo -n "Store $store_id ($wp_path): "

  # WP-CLI over SSH (assumes ashbi-hostinger SSH config)
  result=$(ssh -o ConnectTimeout=10 -o BatchMode=yes \
    "wp@$(hostname -s)" \
    "cd '$wp_path' && wp option update wcm_tracking_secret '$SECRET' --allow-root 2>&1 && \
     wp option get wcm_tracking_secret --allow-root --format=json 2>&1 | head -c 12 && echo '...' && \
     wp option get wcm_tracking_secret --allow-root | grep -qF '$SECRET' && echo MATCH || echo NOMATCH" \
    2>&1) || true

  if echo "$result" | grep -q "MATCH"; then
    echo "OK"
    echo "store_id=$store_id status=ok" >> "$LOG"
    PASS=$((PASS+1))
  else
    echo "FAIL"
    echo "store_id=$store_id status=fail detail=\"$result\"" >> "$LOG"
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "Rollout log: $LOG"
echo "Pass: $PASS / Fail: $FAIL"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1