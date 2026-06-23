#!/usr/bin/env bash
# deploy-to-vps.sh — first-time setup + redeploy for ai-billing-audit
#
# What this does
# --------------
# 1. rsyncs the project source to /opt/projects/ai-billing-audit/ on the
#    host (no node_modules, no .venv, no apps/portal, no .git)
# 2. writes /opt/projects/ai-billing-audit/.env on the host with the
#    LLM provider, LLM API key, base URL, postgres password, and the
#    resolved DATABASE_URL / AUDIT_TRAIL_DB
# 3. adds an ai-billing-audit router+service to /etc/traefik/dynamic/
#    routers.yml on the host (Traefik watches the file and auto-reloads)
# 4. docker compose build + up -d
# 5. installs /etc/logrotate.d/zorva-logs (rotation for /app/logs named volume)
# 6. smoke tests the /healthz endpoint
#    - host-local:  curl http://127.0.0.1:3018/healthz
#    - public:      curl https://ai-billing-audit.ashbi.ca/healthz
#      (waits up to 90s for the Let's Encrypt cert to issue)
#
# Idempotent: re-running does not duplicate containers or Traefik
# routes. Existing routes in routers.yml are preserved; only the
# ai-billing-audit block is rewritten.
#
# Pre-flight
# ----------
# - SSH alias 'coolify' must be configured (~/.ssh/config) and reachable.
# - The host must already have Traefik v3.2 serving :80/:443 and
#   watching /etc/traefik/dynamic (verified at deploy time).
# - DNS for ai-billing-audit.ashbi.ca must point to 187.77.26.99.
#
# Secrets sourcing
# ----------------
# The deploy script reads two files from the HOST (not from this Mac)
# to keep the values off the local terminal:
#   $LLM_API_KEY_FILE   file whose first non-comment, non-blank line is
#                       the bare API key (no key= prefix). The key is
#                       written to the api/worker env as $LLM_API_KEY
#                       (and $OPENAI_API_KEY for the existing
#                       minimax_client code path).
#   $POSTGRES_PASSWORD_FILE
#                       same shape, but the postgres password.
# If those files don't exist, the script falls back to default dev
# values that are obviously NOT production (audit:audit for postgres,
# OPENAI_API_KEY=unset for the LLM). The api process still boots
# because the v1 healthz doesn't touch the LLM; a real LLM call would
# 500 with a clear error. Documented in the handoff.

set -euo pipefail

# --- Config ---
HOST="coolify"
REMOTE_DIR="/opt/projects/ai-billing-audit"
HOST_PORT="3018"
PUBLIC_HOSTNAME="ai-billing-audit.ashbi.ca"
LLM_PROVIDER="minimax"
LLM_BASE_URL="https://api.minimax.io/v1"
LLM_API_KEY_FILE="/root/ai-billing-audit-secrets/llm_api_key"
POSTGRES_PASSWORD_FILE="/root/ai-billing-audit-secrets/postgres_password"

# --- Resolve script dir on the local machine ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# --- Helpers ---
log()  { printf '[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[deploy FAIL] %s\n' "$*" >&2; exit 1; }

require_local_file() {
    [ -f "$1" ] || fail "missing local file: $1"
}

# --- Pre-flight ---
require_local_file "$PROJECT_DIR/Dockerfile"
require_local_file "$PROJECT_DIR/docker-compose.yml"
require_local_file "$PROJECT_DIR/Caddyfile"
require_local_file "$PROJECT_DIR/audit_trail.sql"
require_local_file "$PROJECT_DIR/pyproject.toml"

log "preflight: ssh $HOST"
ssh -o ConnectTimeout=5 "$HOST" true || fail "ssh $HOST unreachable"

log "preflight: docker compose v2 on host"
ssh "$HOST" 'command -v docker && docker compose version' >/dev/null \
    || fail "host missing docker compose v2"

# --- Step 1: rsync source to the host ---
log "rsync source -> $HOST:$REMOTE_DIR"
ssh "$HOST" "mkdir -p $REMOTE_DIR"
rsync -az --delete \
    --chmod=u=rw,g=r,o=r \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.git/' \
    --exclude='node_modules/' \
    --exclude='apps/' \
    --exclude='tests/' \
    --exclude='docs/' \
    --exclude='logs/' \
    --exclude='data/' \
    --exclude='artifacts/' \
    --exclude='prompts/' \
    --exclude='rules/' \
    --exclude='*.md' \
    --exclude='.DS_Store' \
    "$PROJECT_DIR/" "$HOST:$REMOTE_DIR/"

# --- Step 2: write .env on the host ---
log "write .env on host (DATABASE_URL, AUDIT_TRAIL_DB, LLM keys)"
ssh "$HOST" "LLM_API_KEY_FILE=$LLM_API_KEY_FILE POSTGRES_PASSWORD_FILE=$POSTGRES_PASSWORD_FILE LLM_PROVIDER=$LLM_PROVIDER LLM_BASE_URL=$LLM_BASE_URL bash -s" <<'REMOTE_ENV_EOF'
set -euo pipefail
ENV_FILE=/opt/projects/ai-billing-audit/.env
mkdir -p "$(dirname "$ENV_FILE")"

# Resolve LLM API key. File format: a single line with the bare key.
# If missing, fall back to a clearly-dev placeholder so the api
# process can boot (the v1 healthz does not invoke the LLM).
if [ -f "$LLM_API_KEY_FILE" ]; then
    LLM_API_KEY="$(grep -v '^[[:space:]]*#' "$LLM_API_KEY_FILE" | grep -v '^[[:space:]]*$' | head -n 1)"
    [ -n "$LLM_API_KEY" ] || { echo "LLM_API_KEY_FILE is empty" >&2; exit 1; }
else
    LLM_API_KEY="dev-placeholder-set-LLM_API_KEY_FILE-on-host"
    echo "warning: $LLM_API_KEY_FILE missing, using placeholder (v1 healthz still works)" >&2
fi

if [ -f "$POSTGRES_PASSWORD_FILE" ]; then
    POSTGRES_PASSWORD="$(grep -v '^[[:space:]]*#' "$POSTGRES_PASSWORD_FILE" | grep -v '^[[:space:]]*$' | head -n 1)"
    [ -n "$POSTGRES_PASSWORD" ] || { echo "POSTGRES_PASSWORD_FILE is empty" >&2; exit 1; }
else
    POSTGRES_PASSWORD="audit"
    echo "warning: $POSTGRES_PASSWORD_FILE missing, using default 'audit' (dev only)" >&2
fi

cat > "$ENV_FILE" <<ENV
# generated by deploy-to-vps.sh — do not edit by hand
LLM_PROVIDER=${LLM_PROVIDER}
LLM_BASE_URL=${LLM_BASE_URL}
LLM_API_KEY=${LLM_API_KEY}
LLM_MODEL=MiniMax-M3
MINIMAX_BASE_URL=${LLM_BASE_URL}
MINIMAX_API_KEY=${LLM_API_KEY}
# The existing minimax_client code reads OPENAI_API_KEY; mirror the
# value so the same secret unlocks both the spec-named and the
# code-named env var.
OPENAI_API_KEY=${LLM_API_KEY}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
# Hard-fail if POSTGRES_PASSWORD ended up empty rather than emitting a
# literal '***' (or worse, an empty string) into DATABASE_URL and
# breaking Postgres auth silently on the host.
if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "ERROR: POSTGRES_PASSWORD is empty; refusing to write DATABASE_URL with a blank password." >&2
    exit 1
fi
DATABASE_URL=postgresql://audit:${POSTGRES_PASSWORD}@postgres:5432/ai_billing_audit
AUDIT_TRAIL_DB=postgresql://audit:${POSTGRES_PASSWORD}@postgres:5432/ai_billing_audit
LOG_LEVEL=INFO
ENV

chmod 600 "$ENV_FILE"
echo "wrote $ENV_FILE"
REMOTE_ENV_EOF

# --- Step 3: write Traefik dynamic router+service on the host ---
log "write Traefik router+service for $PUBLIC_HOSTNAME -> 127.0.0.1:$HOST_PORT"
# The live Traefik container on this host is bound to
# /opt/traefik/dynamic/routers.yml on the host filesystem (NOT
# /etc/traefik/dynamic — that path is a misnomer from an earlier
# Caddy era; the live container's static config is
# /opt/traefik/traefik.yml and the file provider watches
# /opt/traefik/dynamic). Update the live file.
ssh "$HOST" "PUBLIC_HOSTNAME=$PUBLIC_HOSTNAME HOST_PORT=$HOST_PORT bash -s" <<'REMOTE_TRAEFIK_EOF'
set -euo pipefail
ROUTERS=/opt/traefik/dynamic/routers.yml
BACKUP="${ROUTERS}.bak.$(date +%Y%m%d_%H%M%S)"

# Backup the current live routers file before we touch it.
cp -a "$ROUTERS" "$BACKUP"

# Idempotent: strip any prior ai-billing-audit router (4-space-indent)
# and ai-billing-audit service (4-space-indent) block, then insert
# the new ones at the end of the existing routers: / services:
# sections in the established pattern.
python3 - <<'PYEOF'
import re, pathlib, datetime

p = pathlib.Path("/opt/traefik/dynamic/routers.yml")
src = p.read_text()

def strip_block(text, key, indent=4):
    pat = re.compile(rf"^ {{{indent}}}{re.escape(key)}:\n(?: {{{indent+2}}}.*\n|\n)+", re.MULTILINE)
    return pat.sub("", text)

src = strip_block(src, "ai-billing-audit", indent=4)

ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
router_block = (
    f"    ai-billing-audit:\n"
    f"      rule: \"Host(`ai-billing-audit.ashbi.ca`)\"\n"
    f"      entryPoints: [websecure]\n"
    f"      service: ai-billing-audit\n"
    f"      tls:\n"
    f"        certResolver: letsencrypt\n"
)
service_block = (
    f"    ai-billing-audit:\n"
    f"      loadBalancer:\n"
    f"        servers:\n"
    f"          - url: \"http://127.0.0.1:3018\"\n"
)

# Insert the router at the end of "  routers:".
m = re.search(r"^(  routers:.*\n(?:    .*\n|\n)+)(?=  services:)", src, re.MULTILINE)
if not m:
    raise SystemExit("could not locate routers: block in live file")
new_routers = m.group(1).rstrip("\n") + "\n" + router_block
src = src[:m.start()] + new_routers + "\n" + src[m.end():]

# Insert the service at the end of "  services:".
m = re.search(r"^(  services:.*\n(?:    .*\n|\n)+)", src, re.MULTILINE)
if not m:
    raise SystemExit("could not locate services: block in live file")
new_services = m.group(1).rstrip("\n") + "\n" + service_block
src = src[:m.start()] + new_services + src[m.end():]

p.write_text(src)
print("wrote", p)
PYEOF

echo "Traefik dynamic config updated at $ROUTERS"
REMOTE_TRAEFIK_EOF

# --- Step 4: docker compose build + up ---
log "docker compose build (api image)"
ssh "$HOST" "cd $REMOTE_DIR && docker compose build --pull" || fail "docker compose build failed"

log "docker compose up -d"
ssh "$HOST" "cd $REMOTE_DIR && docker compose up -d" || fail "docker compose up failed"

# --- Step 4b: install logrotate config for the /app/logs named volume ---
# /app/logs is a Docker named volume that grows unbounded unless rotated.
# The config file lives in the repo at deploy/logrotate/zorva-logs and is
# copy-installed to /etc/logrotate.d/ on the host. Per-file retention is
# documented in deploy/logrotate/README.md (PHIPA 7yr on audit_trail.jsonl,
# 60d on doctor_emails.jsonl, 90d on the NPI cache, etc.).
#
# Only installs the file if logrotate is present on the host. logrotate is
# standard on Debian/Ubuntu but not guaranteed on minimal VPS images; in
# that case we log a warning rather than failing the deploy, because the
# api container will still boot and serve /healthz without logrotate.
log "install logrotate config to /etc/logrotate.d/zorva-logs"
ssh "$HOST" "REMOTE_DIR=$REMOTE_DIR bash -s" <<'REMOTE_LOGROTATE_EOF' || log "warning: logrotate install skipped (see previous lines)"
set -euo pipefail
if ! command -v logrotate >/dev/null 2>&1; then
    echo "warning: logrotate not installed on host; skipping /etc/logrotate.d/zorva-logs" >&2
    echo "         install with: apt-get install -y logrotate" >&2
    exit 0
fi
install -d -m 755 /etc/logrotate.d
install -m 644 "$REMOTE_DIR/deploy/logrotate/zorva-logs" /etc/logrotate.d/zorva-logs
echo "installed /etc/logrotate.d/zorva-logs"
# Non-destructive dry-run so the operator can see what logrotate would do.
if logrotate -d /etc/logrotate.d/zorva-logs >/dev/null; then
    echo "logrotate -d /etc/logrotate.d/zorva-logs: OK (parse + would-rotate)"
else
    echo "warning: logrotate -d /etc/logrotate.d/zorva-logs reported an issue; investigate" >&2
fi
REMOTE_LOGROTATE_EOF

# Give the stack up to 60s to converge (postgres init + api boot).
log "wait up to 60s for the api container to become healthy"
for i in $(seq 1 12); do
    STATUS=$(ssh "$HOST" "docker inspect -f '{{.State.Health.Status}}' ai-billing-audit-api 2>/dev/null || echo missing")
    if [ "$STATUS" = "healthy" ]; then
        log "api is healthy after ${i}*5s"
        break
    fi
    log "  attempt ${i}/12: api status = $STATUS"
    sleep 5
done

# --- Step 5: smoke tests ---
log "smoke 1/3: docker ps (all 4 services should be Up)"
ssh "$HOST" "cd $REMOTE_DIR && docker compose ps" || true

log "smoke 2/3: host-local curl http://127.0.0.1:$HOST_PORT/healthz"
LOCAL_BODY=$(ssh "$HOST" "curl -fsS --max-time 10 http://127.0.0.1:$HOST_PORT/healthz" 2>&1) || fail "local healthz failed: $LOCAL_BODY"
echo "$LOCAL_BODY"
echo "$LOCAL_BODY" | grep -q '"version"' || fail "local healthz response missing version field"

log "smoke 3/3: public https://$PUBLIC_HOSTNAME/healthz (waits up to 90s for cert issuance)"
SUCCESS=0
for i in 1 2 3 4 5 6 7 8 9; do
    if curl -fsS --max-time 10 "https://$PUBLIC_HOSTNAME/healthz" 2>/dev/null; then
        echo
        SUCCESS=1
        break
    fi
    printf "  attempt %d failed, retrying in 10s...\n" "$i"
    sleep 10
done
if [ "$SUCCESS" -ne 1 ]; then
    fail "public https://$PUBLIC_HOSTNAME/healthz never returned 200 within 90s"
fi

log "deploy complete"
log "  local URL : http://127.0.0.1:$HOST_PORT/healthz"
log "  public URL: https://$PUBLIC_HOSTNAME/healthz"
log "  host dir  : $HOST:$REMOTE_DIR"
