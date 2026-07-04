#!/usr/bin/env bash
# Rotate the PATIENT_HASH_PEPPER on the running VPS deployment.
#
# Usage: bash scripts/rotate_patient_hash_pepper.sh
#
# What it does:
#   1. Generates a new 64-char pepper (cryptographically random).
#   2. Writes it to /root/ai-billing-audit-secrets/patient_hash_pepper.
#   3. Re-renders the api's .env to reference the secret file.
#   4. Restarts the api container.
#   5. Verifies /healthz returns 200.
#
# CRITICAL: rotating the pepper invalidates all existing patient
# hash lookups. Any patient_hash lookup that goes through the
# portal will return NULL after the restart. There is no graceful
# migration path — the v1 design treats the pepper as a
# pre-shared secret and rotates by hand.
#
# Operator impact:
#   - All patient hash lookups will FAIL after rotation until the
#     caller re-hashes the patient_id with the new pepper.
#   - For a production pilot, this means the biller has to
#     re-upload the encounter list after a rotation. Plan for
#     that downtime.
#   - The recommended cadence is "never" once the pilot starts;
#     rotate only if the pepper is suspected to be leaked.
#
# Multi-pepper support (rotate-by-write): the v1 design does NOT
# support multiple peppers at verify-time, so this is a hard
# rotation. A follow-up kanban card adds a "previous peppers"
# allowlist so the next rotation can be seamless.

set -eo pipefail

HOST="coolify"
REMOTE_DIR="/opt/projects/ai-billing-audit"
SECRETS_DIR="/root/ai-billing-audit-secrets"
SECRET_FILE="$SECRETS_DIR/patient_hash_pepper"

log() { printf '[rotate-pepper %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# Generate the new pepper. Same SIGPIPE dance as the bearer
# rotation script (head -c 64 closes the pipe early).
set +o pipefail
NEW_PEPPER=$(LC_ALL=C tr -dc 'A-Za-z0-9_=' </dev/urandom | head -c 64)
set -o pipefail
log "generated new pepper (first 8 chars): ${NEW_PEPPER:0:8}..."

if [ "${1:-}" != "--confirm" ]; then
    log "DRY RUN — pass --confirm to push to $HOST and restart."
    log "WARNING: pepper rotation invalidates ALL existing patient hash lookups."
    log "The biller will need to re-upload the encounter list after the restart."
    log "  new pepper: $NEW_PEPPER"
    log "  target file: $HOST:$SECRET_FILE"
    exit 0
fi

# Push the new pepper to the host.
log "pushing new pepper to $HOST:$SECRET_FILE"
ssh "$HOST" "mkdir -p $SECRETS_DIR && chmod 700 $SECRETS_DIR && printf '%s' '$NEW_PEPPER' > $SECRET_FILE && chmod 600 $SECRET_FILE" \
    || { log "ERROR: failed to write $SECRET_FILE"; exit 1; }

# Update the api's .env to source the secret file (deploy-to-vps.sh
# already understands PATIENT_HASH_PEPPER_FILE convention).
log "updating api .env to reference the secret file"
ssh "$HOST" "cd $REMOTE_DIR && grep -q '^PATIENT_HASH_PEPPER_FILE=' .env || echo 'PATIENT_HASH_PEPPER_FILE=$SECRET_FILE' >> .env"

# Restart the api container.
log "restarting api container"
ssh "$HOST" "cd $REMOTE_DIR && docker compose -f docker-compose.yml --env-file .env --env-file portal.env up -d --no-deps --force-recreate api" \
    || { log "ERROR: api restart failed"; exit 1; }

# Verify /healthz.
log "verifying /healthz returns 200..."
for i in $(seq 1 12); do
    HTTP=$(ssh "$HOST" "curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3018/healthz" 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ]; then
        log "api is healthy after ${i}*5s"
        log "rotation complete. Re-upload the encounter list to rehash patient_ids."
        exit 0
    fi
    log "  attempt $i/12: api status=$HTTP"
    sleep 5
done

log "ERROR: api did not become healthy within 60s."
exit 1