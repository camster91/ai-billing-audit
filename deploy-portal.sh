#!/usr/bin/env bash
# deploy-portal.sh — deploy the Zorva marketing portal (apps/portal)
# to the Hostinger VPS at portal.ashbi.ca.
#
# Idempotent: safe to re-run after a code change. Each step is
# failure-stop: a failure in step N halts before step N+1 so the
# host is never half-configured.
#
# Usage:
#   ./deploy-portal.sh                    # full deploy
#   ./deploy-portal.sh --skip-rsync       # only re-run compose + Traefik
#   ./deploy-portal.sh --portal-only      # only restart the portal container
#
# What this does:
#   1. rsync apps/portal/ to vps:/opt/projects/ai-billing-audit/portal/
#      (excluding node_modules, .next, .env files, tests, etc.)
#   2. Write /opt/projects/ai-billing-audit/portal.env from
#      apps/portal/.env.production.example + host secrets.
#      chmod 600 (so a misconfigured `docker compose config` won't
#      print it to logs).
#   3. Add a Traefik router block for portal.ashbi.ca ->
#      127.0.0.1:3020 (the portal container's loopback binding).
#      Preserves all other routers in /opt/traefik/dynamic/routers.yml.
#   4. docker compose up -d --build portal portal-postgres.
#   5. Wait for healthcheck, then verify the public URL serves a
#      marketing page (HTTP 200 on /).
#
# Prerequisites on the VPS (one-time setup):
#   - /root/ai-billing-audit-secrets/portal_postgres_password  (chmod 600)
#   - /root/ai-billing-audit-secrets/auth_secret              (chmod 600)
#   - /root/ai-billing-audit-secrets/auth_resend_key          (chmod 600)
#   - /root/ai-billing-audit-secrets/stripe_secret_key        (chmod 600)
#   - /root/ai-billing-audit-secrets/stripe_publishable_key   (chmod 600)
#   - /root/ai-billing-audit-secrets/stripe_webhook_secret    (chmod 600)
#   - DNS A record: portal.ashbi.ca -> 187.77.26.99
#     (Cloudflare wildcard *.ashbi.ca already resolves to this)
#
# The script sources the same SSH alias (`coolify`) and host path
# conventions as deploy-to-vps.sh — see that file for the broader
# deploy shape.

set -euo pipefail

# ---- Args ---------------------------------------------------------------
SKIP_RSYNC=0
PORTAL_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --skip-rsync)   SKIP_RSYNC=1 ;;
        --portal-only)  PORTAL_ONLY=1; SKIP_RSYNC=1 ;;
        -h|--help)
            sed -n '2,/^set -euo pipefail/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "unknown arg: $arg" >&2; exit 64 ;;
    esac
done

# ---- Config -------------------------------------------------------------
HOST="coolify"
REMOTE_DIR="/opt/projects/ai-billing-audit"
REMOTE_PORTAL_DIR="${REMOTE_DIR}/portal"
REMOTE_ENV="${REMOTE_DIR}/portal.env"
SECRETS_DIR="/root/ai-billing-audit-secrets"
TRAEFIK_ROUTERS="/opt/traefik/dynamic/routers.yml"
PORTAL_PORT="3020"
PORTAL_HOST="portal.ashbi.ca"
PORTAL_SERVICE="zorva-portal"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Preflight ----------------------------------------------------------
echo "[deploy-portal] preflight: repo root = ${REPO_ROOT}"
[[ -d "${REPO_ROOT}/apps/portal" ]] || {
    echo "FATAL: apps/portal/ missing — run from the repo root" >&2; exit 1; }
[[ -f "${REPO_ROOT}/apps/portal/.env.production.example" ]] || {
    echo "FATAL: apps/portal/.env.production.example missing" >&2; exit 1; }
[[ -f "${REPO_ROOT}/apps/portal/Dockerfile" ]] || {
    echo "FATAL: apps/portal/Dockerfile missing" >&2; exit 1; }
[[ -f "${REPO_ROOT}/docker-compose.yml" ]] || {
    echo "FATAL: docker-compose.yml missing" >&2; exit 1; }

ssh "${HOST}" true || {
    echo "FATAL: cannot ssh to ${HOST}" >&2; exit 1; }

# ---- Step 1: rsync apps/portal/ ----------------------------------------
if [[ "$SKIP_RSYNC" -eq 0 ]]; then
    echo "[deploy-portal] step 1: rsync apps/portal -> ${HOST}:${REMOTE_PORTAL_DIR}"
    ssh "${HOST}" "mkdir -p ${REMOTE_PORTAL_DIR}"
    rsync -az --delete \
        --exclude='node_modules' \
        --exclude='.next' \
        --exclude='out' \
        --exclude='.env' \
        --exclude='.env.local' \
        --exclude='.env.*.local' \
        --exclude='.env.bak' \
        --exclude='*.test.ts' \
        --exclude='*.spec.ts' \
        --exclude='tests/' \
        --exclude='a11y-*.mjs' \
        --exclude='bg-*.mjs' \
        --exclude='artifacts/' \
        --exclude='prisma/dev.db' \
        --exclude='prisma/dev.db-journal' \
        "${REPO_ROOT}/apps/portal/" "${HOST}:${REMOTE_PORTAL_DIR}/"
    echo "  ok"
else
    echo "[deploy-portal] step 1: SKIPPED (--skip-rsync)"
fi

# ---- Step 2: write portal.env ------------------------------------------
echo "[deploy-portal] step 2: write ${REMOTE_ENV}"
# Read each secret from the host via ssh into a local shell var, then
# substitute into the env template. We use ssh cat instead of `ssh
# cat | ssh bash` to avoid heredoc-in-heredoc and shell-escape footguns.
read_secret() {
    local name="$1"
    ssh "${HOST}" "cat ${SECRETS_DIR}/${name} 2>/dev/null" || {
        echo "FATAL: cannot read ${SECRETS_DIR}/${name} on ${HOST}" >&2; exit 1; }
}

POSTGRES_PASSWORD_VAL="$(read_secret portal_postgres_password)"
AUTH_SECRET_VAL="$(read_secret auth_secret)"
AUTH_RESEND_KEY_VAL="$(read_secret auth_resend_key)"
STRIPE_SECRET_VAL="$(read_secret stripe_secret_key)"
STRIPE_PUBLISHABLE_VAL="$(read_secret stripe_publishable_key)"
STRIPE_WEBHOOK_VAL="$(read_secret stripe_webhook_secret)"

# Build the env file locally then scp it. Avoids heredoc-in-ssh
# (chat-layer redaction risk for long values).
TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT
sed \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=\"postgresql://portal:${POSTGRES_PASSWORD_VAL}@portal-postgres:5432/zorva_portal?schema=public\"|" \
    -e "s|^AUTH_SECRET=.*|AUTH_SECRET=\"${AUTH_SECRET_VAL}\"|" \
    -e "s|^AUTH_RESEND_KEY=.*|AUTH_RESEND_KEY=\"${AUTH_RESEND_KEY_VAL}\"|" \
    -e "s|^STRIPE_SECRET_KEY=.*|STRIPE_SECRET_KEY=\"${STRIPE_SECRET_VAL}\"|" \
    -e "s|^STRIPE_PUBLISHABLE_KEY=.*|STRIPE_PUBLISHABLE_KEY=\"${STRIPE_PUBLISHABLE_VAL}\"|" \
    -e "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=\"${STRIPE_WEBHOOK_VAL}\"|" \
    "${REPO_ROOT}/apps/portal/.env.production.example" > "$TMP_ENV"

# Add the docker-compose env vars (not in the portal's .env.example —
# they're consumed by the compose file directly). Append a clearly
# delimited block so an operator can see them at a glance.
cat >> "$TMP_ENV" <<ENVEOF

# ---- docker-compose env (consumed by docker-compose.yml, not by Next.js) -
# These are read by the postgres + portal service blocks in
# docker-compose.yml. Fail-closed: missing PORTAL_POSTGRES_PASSWORD
# halts the stack.
PORTAL_POSTGRES_USER=portal
PORTAL_POSTGRES_PASSWORD=${POSTGRES_PASSWORD_VAL}
PORTAL_POSTGRES_DB=zorva_portal
ENVEOF

# Scp the env file in place with chmod 600. Using scp here (not ssh
# cat) because `cat > file` over ssh requires shell-quoting the entire
# content, which trips up chat-layer redaction on long Stripe keys.
scp "$TMP_ENV" "${HOST}:${REMOTE_ENV}.tmp"
ssh "${HOST}" "chmod 600 ${REMOTE_ENV}.tmp && mv ${REMOTE_ENV}.tmp ${REMOTE_ENV}"
echo "  ok (chmod 600)"

# ---- Step 3: Traefik router block --------------------------------------
echo "[deploy-portal] step 3: Traefik router for ${PORTAL_HOST}"
# Read the live routers.yml, merge in the new portal block, write back.
# Mirrors the same python-merge pattern that deploy-to-vps.sh uses for
# the api's ratelimit middleware — preserves every existing field
# exactly (no string-templating surprises).
ssh "${HOST}" "python3 - <<'PY'
import sys, pathlib
p = pathlib.Path('${TRAEFIK_ROUTERS}')
import yaml
data = yaml.safe_load(p.read_text()) or {}
data.setdefault('http', {})
data['http'].setdefault('routers', {})
data['http'].setdefault('services', {})

# Router: Host(portal.ashbi.ca) -> zorva-portal service, no
# middleware (the portal sets its own CSP + security headers in
# next.config.ts; we don't double up at the edge). certResolver
# letsencrypt re-uses the same Let's Encrypt account the rest of
# the fleet uses, so adding portal.ashbi.ca requires no new DNS or
# ACME registration beyond the existing *.ashbi.ca wildcard.
data['http']['routers']['zorva-portal'] = {
    'rule': 'Host(`${PORTAL_HOST}`)',
    'entryPoints': ['websecure'],
    'service': '${PORTAL_SERVICE}',
    'tls': {'certResolver': 'letsencrypt'},
}

# Service: loadBalancer to the portal container's loopback port.
# 127.0.0.1 because Traefik runs on the host network and reaches
# the docker-published port directly.
data['http']['services']['${PORTAL_SERVICE}'] = {
    'loadBalancer': {
        'servers': [{'url': 'http://127.0.0.1:${PORTAL_PORT}'}],
    },
}

yaml.safe_dump(data, p.open('w'), default_flow_style=False, sort_keys=False)
print('routers.yml updated: zorva-portal router + service added')
PY"
echo "  ok"

# ---- Step 4: docker compose up ----------------------------------------
echo "[deploy-portal] step 4: docker compose up -d --build portal portal-postgres"
cd "${REPO_ROOT}"
# rsync the compose file (in case it changed since the last full deploy)
rsync -az "${REPO_ROOT}/docker-compose.yml" "${HOST}:${REMOTE_DIR}/docker-compose.yml"
if [[ "$PORTAL_ONLY" -eq 1 ]]; then
    ssh "${HOST}" "cd ${REMOTE_DIR} && docker compose up -d --no-deps --build portal"
else
    ssh "${HOST}" "cd ${REMOTE_DIR} && docker compose up -d --build portal portal-postgres"
fi
echo "  ok"

# ---- Step 5: healthcheck + verify -------------------------------------
echo "[deploy-portal] step 5: wait for portal healthcheck"
ssh "${HOST}" "cd ${REMOTE_DIR} && for i in \$(seq 1 30); do
    status=\$(docker inspect --format='{{.State.Health.Status}}' zorva-portal 2>/dev/null || echo 'starting')
    if [ \"\$status\" = 'healthy' ]; then echo '  portal healthy'; exit 0; fi
    sleep 5
done
echo '  FATAL: portal did not become healthy in 150s' >&2
docker inspect --format='{{json .State.Health}}' zorva-portal
exit 1"

echo "[deploy-portal] step 6: verify public HTTPS endpoint"
HTTP_STATUS=$(ssh "${HOST}" "curl -sS -o /dev/null -w '%{http_code}' https://${PORTAL_HOST}/" || echo "000")
if [[ "$HTTP_STATUS" != "200" ]]; then
    echo "  FATAL: ${PORTAL_HOST}/ returned ${HTTP_STATUS} (expected 200)" >&2
    exit 1
fi
echo "  ok: https://${PORTAL_HOST}/ -> 200"

echo
echo "[deploy-portal] DONE. portal live at https://${PORTAL_HOST}/"
echo "  healthcheck: ssh ${HOST} docker inspect --format='{{.State.Health.Status}}' zorva-portal"
echo "  logs:        ssh ${HOST} docker logs --tail=100 -f zorva-portal"
echo "  rollback:    ssh ${HOST} 'cd ${REMOTE_DIR} && docker compose stop portal && docker compose rm -f portal'"
