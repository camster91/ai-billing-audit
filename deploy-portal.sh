#!/usr/bin/env bash
# deploy-portal.sh — deploy the Zorva marketing portal (apps/portal)
# to the Hostinger VPS at zorva.ashbi.ca.
#
# Idempotent: safe to re-run after a code change. Each step is
# failure-stop: a failure in step N halts before step N+1 so the
# host is never half-configured.
#
# Usage:
#   ./deploy-portal.sh                    # full deploy
#   ./deploy-portal.sh --skip-rsync       # only re-run compose + Traefik
#   ./deploy-portal.sh --portal-only      # only restart the portal container
#   ./deploy-portal.sh --skip-router      # preserve an already-verified router
#
# What this does:
#   1. rsync apps/portal/ to vps:/opt/projects/ai-billing-audit/portal/
#      (excluding node_modules, .next, .env files, tests, etc.)
#   2. Write /opt/projects/ai-billing-audit/portal.env from
#      apps/portal/.env.production.example + host secrets.
#      chmod 600 (so a misconfigured `docker compose config` won't
#      print it to logs).
#   3. Add a Traefik router block for zorva.ashbi.ca ->
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
#   - /root/ai-billing-audit-secrets/audit_bearer_token       (chmod 600)
#   - /root/ai-billing-audit-secrets/principal_signing_secret (chmod 600)
#   - /root/ai-billing-audit-secrets/phi_encryption_key       (chmod 600)
#   - DNS A record: zorva.ashbi.ca -> 187.77.26.99
#     (Cloudflare wildcard *.ashbi.ca already resolves to this)
#
# The script sources the same SSH alias (`coolify`) and host path
# conventions as deploy-to-vps.sh — see that file for the broader
# deploy shape.

set -euo pipefail

# ---- Args ---------------------------------------------------------------
SKIP_RSYNC=0
PORTAL_ONLY=0
SKIP_ROUTER=0
for arg in "$@"; do
    case "$arg" in
        --skip-rsync)   SKIP_RSYNC=1 ;;
        --portal-only)  PORTAL_ONLY=1; SKIP_RSYNC=1 ;;
        --skip-router)  SKIP_ROUTER=1 ;;
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
PORTAL_PORT="3060"
PORTAL_HOST="zorva.ashbi.ca"
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
    # `cat file` outputs the trailing newline too, which would embed
    # `\n` inside the env value and break shell + YAML parsing. Strip
    # with `tr -d '\n'` so we get the raw bytes only. If the file is
    # missing or unreadable, fail loud (not silent default).
    ssh "${HOST}" "tr -d '\n' < ${SECRETS_DIR}/${name}" 2>/dev/null || {
        echo "FATAL: cannot read ${SECRETS_DIR}/${name} on ${HOST}" >&2; exit 1; }
}

POSTGRES_PASSWORD_VAL="$(read_secret portal_postgres_password)"
POSTGRES_PASSWORD_URLENCODED="$(printf '%s' "$POSTGRES_PASSWORD_VAL" | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))')"
AUTH_SECRET_VAL="$(read_secret auth_secret)"
AUTH_RESEND_KEY_VAL="$(read_secret auth_resend_key)"
STRIPE_SECRET_VAL="$(read_secret stripe_secret_key)"
STRIPE_PUBLISHABLE_VAL="$(read_secret stripe_publishable_key)"
STRIPE_WEBHOOK_VAL="$(read_secret stripe_webhook_secret)"
FASTAPI_BEARER_TOKEN_VAL="$(read_secret audit_bearer_token)"
FASTAPI_PRINCIPAL_SIGNING_SECRET_VAL="$(read_secret principal_signing_secret)"
PHI_ENCRYPTION_KEY_VAL="$(read_secret phi_encryption_key)"
[[ "${#FASTAPI_BEARER_TOKEN_VAL}" -ge 32 ]] || {
    echo "FATAL: audit_bearer_token must contain at least 32 bytes" >&2; exit 1; }
[[ "${#FASTAPI_PRINCIPAL_SIGNING_SECRET_VAL}" -ge 32 ]] || {
    echo "FATAL: principal_signing_secret must contain at least 32 bytes" >&2; exit 1; }
[[ "${PHI_ENCRYPTION_KEY_VAL}" =~ ^[A-Za-z0-9_-]{43}=?$ ]] || {
    echo "FATAL: phi_encryption_key must be URL-safe base64 for exactly 32 bytes" >&2; exit 1; }

# Build the env file locally then scp it. Avoids heredoc-in-ssh
# (chat-layer redaction risk for long values).
TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT
sed \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=\"postgresql://portal:${POSTGRES_PASSWORD_URLENCODED}@portal-postgres:5432/zorva_portal?schema=public\"|" \
    -e "s|^AUTH_SECRET=.*|AUTH_SECRET=\"${AUTH_SECRET_VAL}\"|" \
    -e "s|^AUTH_RESEND_KEY=.*|AUTH_RESEND_KEY=\"${AUTH_RESEND_KEY_VAL}\"|" \
    -e "s|^STRIPE_SECRET_KEY=.*|STRIPE_SECRET_KEY=\"${STRIPE_SECRET_VAL}\"|" \
    -e "s|^STRIPE_PUBLISHABLE_KEY=.*|STRIPE_PUBLISHABLE_KEY=\"${STRIPE_PUBLISHABLE_VAL}\"|" \
    -e "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=\"${STRIPE_WEBHOOK_VAL}\"|" \
    -e "s|^FASTAPI_BEARER_TOKEN=.*|FASTAPI_BEARER_TOKEN=\"${FASTAPI_BEARER_TOKEN_VAL}\"|" \
    -e "s|^FASTAPI_PRINCIPAL_SIGNING_SECRET=.*|FASTAPI_PRINCIPAL_SIGNING_SECRET=\"${FASTAPI_PRINCIPAL_SIGNING_SECRET_VAL}\"|" \
    -e "s|^ZORVA_PHI_ENCRYPTION_KEY=.*|ZORVA_PHI_ENCRYPTION_KEY=\"${PHI_ENCRYPTION_KEY_VAL}\"|" \
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

# Transfer the env file in place with chmod 600. Using `ssh base64 -d`
# instead of `scp` because the Hostinger VPS image ships without
# `sftp-server` (scp returns "Connection closed" with exit status 127
# even though ssh itself works — confirmed 2026-06-26). The base64
# round-trip is binary-safe, and we strip the trailing newline before
# the `echo` so the file ends with exactly one `\n`.
#
# Why not `ssh "cat > file"`? A long Stripe key contains shell-special
# chars (`/`, `+`, `=`) that need escaping; base64 sidesteps the quoting
# problem entirely.
ENV_B64="$(base64 < "$TMP_ENV" | tr -d '\n')"
ssh "${HOST}" "echo '${ENV_B64}' | base64 -d > ${REMOTE_ENV}.tmp && chmod 600 ${REMOTE_ENV}.tmp && mv ${REMOTE_ENV}.tmp ${REMOTE_ENV}"
echo "  ok (chmod 600)"

# ---- Step 3: Traefik router block --------------------------------------
echo "[deploy-portal] step 3: Traefik router for ${PORTAL_HOST}"
if [[ "$SKIP_ROUTER" -eq 1 ]]; then
    echo "  skipped (--skip-router; use only after verifying the live router)"
else
# Read the live routers.yml, merge in the new portal block, write back.
# Mirrors the same python-merge pattern that deploy-to-vps.sh uses for
# the api's ratelimit middleware — preserves every existing field
# exactly (no string-templating surprises).
#
# We do the merge LOCALLY (not via ssh heredoc) and ship the merged
# file via base64 echo. Why: a heredoc inside `ssh '...'` is interpreted
# by the LOCAL bash before the single quotes are processed, so any
# `${VAR}` in the heredoc body triggers a local shell expansion that
# the remote python3 then chokes on (we hit this on the first deploy
# attempt 2026-06-26: `bash: line 1: + host + : command not found`).
TMP_ROUTERS="$(mktemp)"
trap 'rm -f "$TMP_ENV" "$TMP_ROUTERS"' EXIT
ssh "${HOST}" "cat ${TRAEFIK_ROUTERS}" > "$TMP_ROUTERS"
# IMPORTANT: no backticks in this heredoc. Bash sees backticks as
# command substitution even inside `<<PY` (the unquoted heredoc
# delimiter triggers parameter expansion AND command substitution).
# We use double quotes around the Host() rule instead — Traefik
# accepts both forms (single-quoted is the original style; double
# works too).
python3 - <<PY
import pathlib, yaml
host = "${PORTAL_HOST}"
svc = "${PORTAL_SERVICE}"
port = "${PORTAL_PORT}"

p = pathlib.Path("${TMP_ROUTERS}")
data = yaml.safe_load(p.read_text()) or {}
data.setdefault("http", {})
data["http"].setdefault("routers", {})
data["http"].setdefault("services", {})

# Router: Host(zorva.ashbi.ca) -> zorva-portal service, no
# middleware (the portal sets its own CSP + security headers in
# next.config.ts; we do not double up at the edge). certResolver
# letsencrypt re-uses the same Let's Encrypt account the rest of
# the fleet uses, so adding zorva.ashbi.ca requires no new DNS or
# ACME registration beyond the existing *.ashbi.ca wildcard.
data["http"]["routers"]["zorva-portal"] = {
    "rule": 'Host("' + host + '")',
    "entryPoints": ["websecure"],
    "service": svc,
    "tls": {"certResolver": "letsencrypt"},
}

# Service: loadBalancer to the portal container's loopback port.
# 127.0.0.1 because Traefik runs on the host network and reaches
# the docker-published port directly.
data["http"]["services"][svc] = {
    "loadBalancer": {
        "servers": [{"url": "http://127.0.0.1:" + port}],
    },
}

yaml.safe_dump(data, p.open("w"), default_flow_style=False, sort_keys=False)
print("routers.yml merged locally")
PY
ROUTERS_B64="$(base64 < "$TMP_ROUTERS" | tr -d '\n')"
ssh "${HOST}" "echo '${ROUTERS_B64}' | base64 -d > ${TRAEFIK_ROUTERS}.tmp && mv ${TRAEFIK_ROUTERS}.tmp ${TRAEFIK_ROUTERS} && echo 'routers.yml updated: zorva-portal router + service added'"
echo "  ok"
fi

# ---- Step 4: docker compose up ----------------------------------------
echo "[deploy-portal] step 4: docker compose up -d --build portal portal-postgres"
cd "${REPO_ROOT}"
# rsync the compose file (in case it changed since the last full deploy)
rsync -az "${REPO_ROOT}/docker-compose.yml" "${HOST}:${REMOTE_DIR}/docker-compose.yml"
# `docker compose up` defaults to looking for `.env` (not `portal.env`)
# in the same dir as the compose file, but we keep the portal secrets
# in their own file. The `--env-file` flag tells compose to interpolate
# `${VAR:?...}` references from portal.env at compose-parse time.
# Without this, the fail-closed `PORTAL_POSTGRES_PASSWORD:?` check in
# docker-compose.yml trips immediately (interpolation happens BEFORE
# env_file is loaded into the container).
if [[ "$PORTAL_ONLY" -eq 1 ]]; then
    ssh "${HOST}" "cd ${REMOTE_DIR} && docker compose --env-file .env --env-file portal.env up -d --no-deps --build portal"
else
    ssh "${HOST}" "cd ${REMOTE_DIR} && docker compose --env-file .env --env-file portal.env up -d --build portal portal-postgres"
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
