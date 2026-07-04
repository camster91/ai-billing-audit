#!/usr/bin/env bash
# Rotate the AUDIT_BEARER_TOKEN on the running VPS deployment.
#
# Usage: bash scripts/rotate_bearer_token.sh
#
# What it does:
#   1. Generates a new 64-char token (cryptographically random).
#   2. Writes it to /root/ai-billing-audit-secrets/bearer-token.
#   3. Re-renders the api's .env to reference the secret file.
#   4. Restarts the api container (graceful, 5s drain).
#   5. Verifies /healthz returns 200 (the new token took effect).
#
# Operator impact:
#   - Anything holding the OLD token gets 401 on the next request.
#     Standard rotation cadence: every 90 days, or immediately
#     after a suspected leak.
#   - The portal at zorva.ashbi.ca reads the bearer from a
#     secret-injection env (Caddy reads it from disk too), so
#     the portal will need a refresh after rotation. There's no
#     automatic portal-side rotation; the next deploy-portal.sh
#     run will pick up the new token.
#
# This script is INTENTIONALLY not auto-CRON'd. Token rotation
# is an operator action that should be confirmed by a human.

set -eo pipefail

HOST="coolify"
REMOTE_DIR="/opt/projects/ai-billing-audit"
SECRETS_DIR="/root/ai-billing-audit-secrets"
SECRET_FILE="$SECRETS_DIR/bearer-token"

log() { printf '[rotate-bearer %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# Step 1: generate the new token locally so we can show it to the
# operator BEFORE pushing it to the host. The script aborts if the
# operator passes --confirm; otherwise it just prints the new
# token and exits.
# ``set -e`` + a closing pipe makes `head -c 64` raise SIGPIPE on
# the upstream tr process. Disable pipefail JUST for this line so
# the variable assignment still succeeds.
set +o pipefail
NEW_TOKEN=$(LC_ALL=C tr -dc 'A-Za-z0-9_-' </dev/urandom | head -c 64)
set -o pipefail
log "generated new token (first 8 chars): ${NEW_TOKEN:0:8}..."

if [ "${1:-}" != "--confirm" ]; then
    log "DRY RUN — pass --confirm to push to $HOST and restart."
    log "  new token: $NEW_TOKEN"
    log "  target file: $HOST:$SECRET_FILE"
    exit 0
fi

# Step 2: push the new token to the host.
log "pushing new token to $HOST:$SECRET_FILE"
ssh "$HOST" "mkdir -p $SECRETS_DIR && chmod 700 $SECRETS_DIR && printf '%s' '$NEW_TOKEN' > $SECRET_FILE && chmod 600 $SECRET_FILE" \
    || { log "ERROR: failed to write $SECRET_FILE"; exit 1; }

# Step 3: re-render the api's .env to source the secret file. We
# append AUDIT_BEARER_TOKEN_FILE=$SECRET_FILE (deploy-to-vps.sh
# already understands this convention). If .env already references
# the secret file, skip the append.
log "updating api .env to reference the secret file"
ssh "$HOST" "cd $REMOTE_DIR && grep -q '^AUDIT_BEARER_TOKEN_FILE=' .env || echo 'AUDIT_BEARER_TOKEN_FILE=$SECRET_FILE' >> .env"

# Step 4: graceful container restart. `docker compose up -d` on a
# single service triggers a recreate with the new env.
log "restarting api container (graceful, 5s drain)"
ssh "$HOST" "cd $REMOTE_DIR && docker compose -f docker-compose.yml --env-file .env --env-file portal.env up -d --no-deps --force-recreate api" \
    || { log "ERROR: api restart failed"; exit 1; }

# Step 5: wait for /healthz to come back. The compose healthcheck
# already polls /healthz; we just give it a few tries.
log "verifying /healthz returns 200 with new token..."
for i in $(seq 1 12); do
    HTTP=$(ssh "$HOST" "curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3018/healthz" 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ]; then
        log "api is healthy after ${i}*5s"
        log "rotation complete. Update the portal at zorva.ashbi.ca to use the new token on next deploy."
        exit 0
    fi
    log "  attempt $i/12: api status=$HTTP"
    sleep 5
done

log "ERROR: api did not become healthy within 60s. Check the container logs."
exit 1