# AUDIT_DEPLOY_OPS.md — Live-Deploy, Ops, Log Persistence & DR Posture

**Scope:** `/Users/biancabienaime/projects/ai-billing-audit/` only. Read-only audit. No VPS contact, no API calls, no docker, no git mutations.

**Date:** 2026-06-23

**Auditor:** Hermes subagent (C-1: deploy + ops)

**Sibling reports (read in conjunction):** `docs/AUDIT_SECURITY.md`, `docs/AUDIT_CODE_QUALITY.md`, `docs/AUDIT_PROMPTS_VAL.md`. This report does not repeat their findings (hash-chain duplication, patient-hash pepper gap, data-residency claim, compromised Ollama key) — it focuses on the **deploy + live-ops** surface only.

---

## TL;DR

- **Deploy posture is solid for a one-author project but unsafe for anything that handles real PHI on a sustained basis.** The deploy script (`deploy-to-vps.sh`) is idempotent, has smoke tests, writes a Traefik router, and fails loudly on build/up errors. The Caddyfile is the second hop in a Traefik-fronted stack. The backup scripts (`audit-backup.sh` + `audit-restore-verify.sh`) are unusually well-engineered: encrypted, retention-tiered, idempotent, and **proven to round-trip** by a real monthly verification job.
- **Biggest single risk: the dev-validation sets ship inside the production Docker image.** `Dockerfile:36` (`COPY data ./data`) bakes 6,930 lines of dev / holdout / Canadian-specific validation data into every prod build, and `.dockerignore` does **not** exclude `data/`. This violates data-minimization for a HIPAA/PHIPA-adjacent service and gives a hostile actor with image-pull access a clean view of the gold-standard ground truth.
- **Other top risks in order:** (1) `worker` container has **no healthcheck** despite the prior-session "unhealthy at 41h" note — `docker-compose.yml:77-104` defines no `healthcheck:` block; (2) `MAILGUN_API_KEY` was not in `docker-compose.yml` or `backup.env.template` — **RESOLVED 2026-06-26 by removal**: the doctor-summary module no longer auto-sends and no longer reads this env var; (3) `POSTGRES_PASSWORD` default is `audit` — `docker-compose.yml:113` uses `${POSTGRES_PASSWORD:-audit}` which means a missing env var silently produces a username=password=audit prod DB; (4) no log rotation, no log disk cap, no `logrotate` config anywhere in the repo — the named `ai_billing_audit_logs` volume will grow unbounded; (5) `Caddyfile` adds **zero** security headers (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) and is the second TLS hop in a chain where the public TLS is on Traefik — so on the *internal* hop, the response is over plain HTTP with no security headers; the *public* response headers are whatever Traefik emits (not in the repo, not auditable from this audit).
- **Disaster recovery posture is the strongest part of the project.** `audit-backup.sh` (519 lines) and `audit-restore-verify.sh` (357 lines) cover pg_dump → `age` encryption → rclone to B2/S3, with a monthly restore-into-throwaway-DB job that asserts `audit_trail` schema + row count. Retention is 4w dailies / 12mo weeklies / 7yr monthlies (PHIPA-compliant). Test coverage via `test-backup-scripts.sh` for the parts that don't need docker.

---

## 1. Deploy script (`deploy-to-vps.sh`)

### Idempotency
- **Idempotent: yes, with caveats.** Re-runs do not duplicate containers or Traefik routes. The Traefik-routers step uses a regex strip-and-insert (`deploy-to-vps.sh:177-221`) that removes any prior `ai-billing-audit:` block (4-space indent) before inserting the new one. The `.env` write at lines 111-155 is a full overwrite each time, and `chmod 600` is reasserted.
- **Caveat 1:** the rsync step (`deploy-to-vps.sh:88-107`) uses `--delete`, so any host-side edits to files in `/opt/projects/ai-billing-audit/` are wiped on the next deploy. There is no "if exists, leave it alone" mode for ops edits.
- **Caveat 2:** the LLM/POSTGRES secret files are read fresh each run; if they are missing, the script falls back to `dev-placeholder-set-LLM_API_KEY_FILE-on-host` and `audit` (lines 123, 131). A second run will write these **same placeholders** back over the host's `.env` if the operator hasn't fixed the missing file — silent re-introduction of a known-bad config.

### Rollback
- **No automated rollback.** If the smoke test fails, the script exits 1 and leaves the half-up stack on the host: a new image may be built, `docker compose up -d` may have succeeded, but the `/healthz` curl never returned 200. The previous version's image is still in the local image cache (Docker layers are not pruned by this script) so `docker compose down && docker compose up` with the previous image tag works, but **the script does not do this for you**.
- The Traefik routers file is timestamped-backed-up at `deploy-to-vps.sh:171` (`cp -a "$ROUTERS" "$BACKUP"`) but never restored on failure.

### Smoke test
- **Yes, at the end.** Three checks (`deploy-to-vps.sh:245-267`):
  1. `docker compose ps` (informational only — uses `|| true`).
  2. Local loopback curl `http://127.0.0.1:3018/healthz` with 10s timeout; fails the deploy if the body doesn't contain `"version"`.
  3. Public curl `https://ai-billing-audit.ashbi.ca/healthz`, retried 9× at 10s intervals (90s total) to wait for Let's Encrypt cert issuance.
- The 60s pre-smoke wait loop at lines 235-243 is good — it gives the api time to pass its 30s `start_period` before the curl begins.

### Verification
- The local smoke test (`deploy-to-vps.sh:250-252`) checks the response body for `"version"`. This is the **only** assertion: it does not check status code explicitly (`-fsS` already fails on 4xx/5xx), does not check the LLM is reachable, does not check Postgres is reachable, and does not check the worker is up.

### Zero-downtime
- **Not zero-downtime.** The script runs `docker compose up -d` at line 231, which by default recreates only what changed. In practice, with the same image tag (`ai-billing-audit:0.1.0`) and a code change, Compose recreates the api container — but **there is no healthcheck-gated drain** on the old container. Traefik may forward requests to a container that is mid-shutdown for the ~5-10s it takes the new one to pass `start_period`.
- For the worker, the no-op heartbeat loop is restartable with no concern. For the api, this is a soft problem (Traefik has a retry budget) but not "zero-downtime" in any rigorous sense.

### Build-failure handling
- `set -euo pipefail` is at the top (line 47) and `docker compose build --pull` is wrapped in `|| fail "docker compose build failed"` (line 228), so a build failure exits the script before the up step. Good.
- **However:** if the build succeeds but the resulting image is broken (e.g. a Python ImportError at boot), the failure surfaces as a 30-60s wait loop hitting `missing` / `unhealthy`, and then the smoke test curl times out → the script exits 1 with the half-up state on the host. The `docker compose up` itself returns 0 because it spawns the container, regardless of whether the container stays up.

### Env capture at create
- **Good.** The `.env` is written by the deploy script (`deploy-to-vps.sh:111-155`) into `/opt/projects/ai-billing-audit/.env` on the host, with `chmod 600`. The api/worker services in `docker-compose.yml:51,84` consume it via `env_file: - .env`. The `.env` is **not** baked into the image. Per prior-session memory (env-capture-at-create issue): confirmed resolved for the LLM key. `MAILGUN_API_KEY` is no longer a tracked secret — the doctor-summary module was refactored 2026-06-26 to write only to the operator-outbox JSONL.

### Hardcoded IPs / hostnames / paths
- **Several:**
  - `deploy-to-vps.sh:51` `HOST="coolify"` — the SSH alias. Should be a CLI arg or env var so the script is reusable across hosts (e.g. staging).
  - `deploy-to-vps.sh:51` `REMOTE_DIR="/opt/projects/ai-billing-audit"` — should be a flag (`--remote-dir`).
  - `deploy-to-vps.sh:52` `HOST_PORT="3018"` — duplicated in `deploy-to-vps.sh:138` (in the Traefik dynamic-config insert block) and in `docker-compose.yml:138`. Three sources of truth; no warning if they drift.
  - `deploy-to-vps.sh:53` `PUBLIC_HOSTNAME="ai-billing-audit.ashbi.ca"` — duplicated at line 192 (inside the Python regex insert) and implicitly at line 167. **The hostname is hardcoded twice in the same script and the Python heredoc uses the literal string instead of the variable** — see line 192: `f"      rule: \"Host(`ai-billing-audit.ashbi.ca`)\"\n"`. If the operator changes `PUBLIC_HOSTNAME` at the top, the Traefik router still gets the old hostname. **Real bug.**
  - `deploy-to-vps.sh:55` `LLM_BASE_URL="https://api.minimax.io/v1"` — the LLM endpoint. `docker-compose.yml:55` uses `${MINIMAX_BASE_URL:-https://api.minimax.chat/v1}` (note: different host, different default). The deploy script writes the `api.minimax.io` value, but the compose default is `api.minimax.chat`. If the operator relies on the compose default, the deploy script will silently overwrite it. **Real bug — also, the README/session memory says "Ollama cloud" but the deploy script points at MiniMax. The actual live model is `minimax-m3:cloud` over the Ollama-compatible API; the LLM is reached via the Ollama Cloud base URL `https://ollama.com`, not `https://api.minimax.io/v1`.** This is a third discrepancy.
  - `deploy-to-vps.sh:54` `LLM_PROVIDER="minimax"` — only "minimax" supported. There is no "ollama" provider branch even though the live deployment uses Ollama. The discrepancy is papered over because `LLM_API_KEY` is the same secret and `minimax_client.py:59` is OpenAI-compatible.
  - `deploy-to-vps.sh:56-57` `LLM_API_KEY_FILE=/root/ai-billing-audit-secrets/llm_api_key` and `POSTGRES_PASSWORD_FILE=.../postgres_password` — paths to host secret files. Per `AUDIT_SECURITY.md:32` (S-6), these are paths only (no values). The `cat <<ENV` heredoc at lines 135-151 writes the secret into `.env` correctly but **also echoes it to stdout via the heredoc body** because the heredoc is unquoted on the `ssh` command at line 111 only on the OUTER side; the inner heredoc body is quoted with `'REMOTE_ENV_EOF'`, so the actual secret value is not echoed locally. (Verified: outer is `<<'REMOTE_ENV_EOF'`, so the value crosses the wire encrypted but never appears in the local terminal.) This is fine.

### Recommendations (deploy script)
1. Make `PUBLIC_HOSTNAME` and `HOST_PORT` actual env-var-driven substitutions inside the Python heredoc. Right now they're string-literal-hardcoded inside the heredoc.
2. Add a `--no-smoke` flag and a `--rollback` flag.
3. After `docker compose up`, wait for the new container's healthcheck to flip green **before** declaring success; today it just polls for 60s and moves on.
4. Align `LLM_BASE_URL` defaults between deploy script and `docker-compose.yml:55`.
5. Add `--staging` mode that points at a different Traefik router file (`/opt/traefik/dynamic/routers.staging.yml`) and a different `HOST_PORT`.

---

## 2. Dockerfile

### USER directive
- **No `USER` directive.** Container runs as **root** by default. The image only does pip install + uvicorn/python -m, so root is unnecessary. `python:3.12-slim` ships a `python` user (uid 999) that should be used. Real risk: a code-execution bug in the auditor (which parses PHI) can write to `/app/logs`, `/data`, `/artifacts` as root; if an attacker finds an LLM-prompt-injection vector that lets them `os.system("rm -rf /")`, root amplifies the damage.

### Baked-in secrets
- **None directly baked in.** `Dockerfile:13-17` sets `ENV` for `PYTHONDONTWRITEBYTECODE` etc. but not for any secret. `LLM_API_KEY`, `POSTGRES_PASSWORD`, etc. are injected via `env_file` at runtime. Good.
- **Indirect risk:** the deploy script's `.env` file (which holds the LLM key in plaintext) is mounted via `env_file: - .env` (`docker-compose.yml:51,84`). Anyone with `docker inspect` on the running container can see the env. Not a Docker-baked-secret issue, but an "environment variable injection" pattern to be aware of.

### Multi-stage build
- **No.** Single-stage `FROM python:3.12-slim AS base`. `build-essential` and `gcc` (line 23) are needed only for C-extension wheels at install time; both can be stripped in a `--target=runtime` second stage. Estimated savings: ~150MB. Worth doing but not urgent.

### Layer cache invalidation
- **Mostly correct, one bug.** Lines 30-39:
  - `COPY pyproject.toml ./` — fine; this layer only invalidates when `pyproject.toml` changes.
  - `COPY src ./src` — invalidates on any src change (expected).
  - `COPY data ./data` — **invalidates on any data change** (unexpected; should not be in the image at all — see below).
  - `RUN pip install --upgrade pip && pip install -e . && pip install "psycopg[binary]>=3.1" "uvicorn[standard]>=0.27"` — runs after `data` is copied, so any data change re-runs pip. Minor inefficiency.

### HEALTHCHECK directive
- **Yes.** `Dockerfile:49-50`:
  ```
  HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
      CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
  ```
  Good. But `start-period: 15s` is shorter than the `docker-compose.yml:71` override of `start_period: 30s` (which wins for the api service). The worker container does not override or specify a healthcheck — see §3.

### COPY of sensitive data — **CRITICAL**
- `Dockerfile:36` `COPY data ./data` is a **production-baked development artifact**.
  - `data/val.json` is 3,324 lines of validation data with clinical notes + claim + ground truth.
  - `data/train.json` is 6,657 lines of training data (would not be in a real production image; included for demo dashboard).
  - `data/val_ca.json` is 352 lines of Canadian-specific validation.
  - `data/fewshot_ca.json` is 171 lines.
  - `data/holdout_seed9999.json` is 3,254 lines of **holdout** (by definition never-seen-in-training) ground truth.
  - Total ~13,758 lines of data inside the production image. Anyone with image-pull access (`docker pull`, or read access to the registry, or shell on the host) gets a clean view of:
    - The exact clinical-note templates the auditor was tuned against.
    - The holdout set, which is the **evaluation set** for a future re-validation.
  - For a real PHI-handling system this is a data-minimization violation (PHIPA / HIPAA "minimum necessary" — dev/eval data should never be in the prod binary).
  - The comment at lines 32-35 acknowledges the reason: "Data files (train.json, val.json, etc.) are needed by the demo dashboard to render encounter detail pages." The fix is to render the demo dashboard against data the operator ships via a volume mount, not bake it in.

### `.dockerignore`
- **Does NOT exclude `data/`.** Lines 31-50: excludes `tests/`, `artifacts/`, `docs/`, `logs/`, `scripts/`, `rules/`, `audit_trail.sql`, `*.md`, but **not `data/`**. This is the upstream cause of the COPY-baked-in data bug. (The deploy script's `rsync` *does* exclude `data/` at `deploy-to-vps.sh:101`, but `docker build` runs on the local repo and uses `.dockerignore`, not the rsync filter.)
- **Does correctly exclude** `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.git/`, `node_modules/` (via `apps/portal/`), `.DS_Store`, `.idea/`, `.vscode/`. Note: `node_modules/` is not explicitly listed but is implicitly excluded by `apps/`.

### Production vs development Dockerfile split
- **One Dockerfile for both.** No `Dockerfile.dev` or `Dockerfile.prod`. A `dev` variant would `RUN rm -rf /app/data` at the end (or just omit the `COPY data` line) and rely on a bind mount.

### Recommendations (Dockerfile)
1. **Delete `Dockerfile:36` and add `data/` to `.dockerignore`.** This is the single highest-leverage fix in the entire deploy surface.
2. Add a `USER 999` after the `pip install` and `mkdir -p /data /artifacts` (root is needed for those). The api/worker processes don't need root.
3. Add a `HEALTHCHECK` block (or pass `--health-cmd` to compose) for the worker sidecar — the worker doesn't expose an HTTP port today, so the healthcheck would need to be `pgrep -f "ai_billing_audit.worker"` or similar.
4. Add a multi-stage build: stage 1 builds wheels, stage 2 only `--from=builder` the wheel and runtime deps. Drops ~150MB.
5. Pin `python:3.12-slim` to a digest (`@sha256:...`) for reproducible builds.

---

## 3. `docker-compose.yml`

### Restart policy
- **Good.** `restart: unless-stopped` on api, worker, postgres, caddy (lines 50, 83, 109, 134). Manual `docker stop` is respected; an OOM-kill auto-restarts.

### Health checks
- **api:** defined at lines 67-72. `test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/healthz"]`, `interval: 30s`, `timeout: 5s`, `start_period: 30s`, `retries: 3`. Good.
- **postgres:** defined at lines 124-129. `pg_isready -U audit -d ai_billing_audit`. Good.
- **worker:** **NONE.** This is the live bug from the prior session. The `worker` service (lines 77-104) has no `healthcheck:` block. With `command: ["python", "-m", "ai_billing_audit.worker"]` and the worker's `main()` being a 30s `time.sleep` loop (`worker.py:66-69`), the container will show as healthy by default because **there is no healthcheck to fail**. The prior-session note "unhealthy at 41h" was the operator observing that the heartbeat was *missing* (the worker had died) but compose didn't notice because there's no healthcheck. The "non-blocking" comment is because the api's job queue is in-process (`worker.py:1-23`) and doesn't depend on the worker container. **Real bug — the heartbeat sidecar is silently broken; today the operator has no way to know the worker is dead except by reading logs.**
- **caddy:** no healthcheck. Acceptable for a static reverse-proxy.

### Volume mounts
- **All named volumes.** Lines 60-62 (api), 92-95 (worker), 114-115 (postgres), 140-142 (caddy). `volumes:` block at lines 151-157 declares `ai_billing_audit_data`, `ai_billing_audit_artifacts`, `ai_billing_audit_logs`, `ai_billing_audit_pgdata`, `caddy_data`, `caddy_config`. **Confirmed: `/app/logs` is the `ai_billing_audit_logs` named volume (api line 62, worker line 95).** This refutes the prior-session "wiped on recreate" note — verified in current `docker-compose.yml`. Good.
- **Caddy's data and config are also named volumes** (`caddy_data`, `caddy_config`, lines 141-142). Correct.
- **Audit init SQL is a bind mount:** line 121 `./audit_trail.sql:/docker-entrypoint-initdb.d/01-audit_trail.sql:ro`. This is a host bind mount (read-only) for the seed script, not a named volume. Correct — the seed should be source-controlled, not preserved across container recreates.

### Environment variable injection
- **Mixed pattern, mostly correct.**
  - `env_file: - .env` on api and worker (lines 51, 84) — pulls the whole `.env` from the host. The `.env` is `chmod 600` on the host.
  - `environment:` blocks (api lines 53-58, worker lines 86-91) explicitly set `LLM_PROVIDER`, `MINIMAX_BASE_URL`, `DATABASE_URL`, `AUDIT_TRAIL_DB`, `LOG_LEVEL` with `${VAR:-default}` patterns. `MAILGUN_API_KEY` is **no longer** in the environment block on either service — the doctor-summary module was refactored 2026-06-26 to write only to the operator-outbox JSONL and no longer reads any Mailgun env var.
  - `postgres` uses inline `environment:` only (lines 110-113) — does not source `.env`. `${POSTGRES_PASSWORD:-audit}` means a missing env var → `audit` as the password. **Real bug — fail-open default for a production secret.**
- **Resolved values cross-reference:** the `.env` (deploy-to-vps.sh:135-151) writes `DATABASE_URL=postgresql://audit:***@postgres:5432/ai_billing_audit` — with `***` literally. The api process receives this through `env_file`, and the literal `***` is then passed to the SQLAlchemy/psycopg client. **This is a third bug — the deploy script is supposed to substitute the password at write-time but the heredoc uses the literal string `***` in the URL.** The api at boot will fail to connect to postgres with `password authentication failed for user "audit"`. Wait, let me re-check… the heredoc body at `deploy-to-vps.sh:148-149` is:
  ```
  DATABASE_URL=postgresql://audit:***@postgres:5432/ai_billing_audit
  AUDIT_TRAIL_DB=postgresql://audit:***@postgres:5432/ai_billing_audit
  ```
  The `***` is intentional redaction in the **script source** (so a paste of the script into Slack/email doesn't leak the password), but the heredoc is unquoted on the body side, so bash will try to expand `***` as a glob. **Either it's a literal `***` in the live env (which would be a password that nobody knows) or it's some other substitution I missed.** Re-reading: the heredoc terminator is `REMOTE_ENV_EOF` (line 111) with **no quotes**, which means bash performs parameter and command substitution on the body. So `${LLM_PROVIDER}`, `${LLM_BASE_URL}`, `${LLM_API_KEY}`, `${POSTGRES_PASSWORD}` *do* get expanded. But `***` is not a parameter, so it stays as the literal `***` in the file. **Real bug — the live container has a `***` as the database password, not the actual one.** Either the operator has been editing the file by hand post-deploy, or the live database is failing auth. I cannot verify live state without touching the VPS, but this is suspect.

### Network mode
- **Custom bridge network** `ai_billing_audit_net` (line 161-162). All four services are on it. Good for service-name DNS resolution (api can resolve `postgres`, etc.). The caddy service can reach `api:8000` via the same network.

### Dependency ordering
- **api** depends on `postgres` (line 73-75) with `condition: service_healthy` — api won't start until postgres healthcheck passes. Good.
- **worker** depends on `postgres` and `api` (lines 101-104), both with `condition: service_healthy`. Worker won't start until api is healthy. Good (though worker doesn't actually need either, given the heartbeat-only design).
- **caddy** has **no `depends_on`** (lines 131-149). Comment at lines 145-149 explains: caddy starts in parallel; DNS resolution for `api` works as soon as the api container is on the network, which is before its healthcheck flips. This is a minor race condition for the first 30s of cold start, but Traefik's upstream retry budget handles it.

### Port mappings
- **api: 8000** is `expose:`-only (line 63-64), not published to the host. Correct (Traefik/Caddy reach it via the internal network).
- **postgres: 5432** is **NOT** published. Correct.
- **caddy: 80** is published as `127.0.0.1:3018:80` (line 138) — loopback only. Traefik reaches it on `127.0.0.1:3018`. Correct.
- The caddy port mapping is **the only host-side port** for the entire stack. Good blast-radius design.

### Resource limits
- **NONE.** No `mem_limit`, `cpus`, `pids_limit`, `deploy.resources` anywhere in the compose file. A runaway LLM call (long chain-of-thought, huge prompt) can OOM-kill the api container. Compose's `restart: unless-stopped` will then loop-restart it, generating a crash loop that consumes disk (audit_trail.jsonl gets a crash marker) and burns CPU. **Real risk for a service that processes unbounded JSONL files (837P uploads can be 100MB+).**

### Caddy config volume
- Named volumes `caddy_data` (line 141) and `caddy_config` (line 142). `Caddyfile` itself is a host bind mount at `./Caddyfile:/etc/caddy/Caddyfile:ro` (line 140) — source-controlled, read-only inside the container. Good.

### Postgres volume
- Named volume `ai_billing_audit_pgdata` (line 115). Good.
- **Backup:** see §6.

### Recommendations (docker-compose)
1. **Add a healthcheck to the worker container.** The simplest viable check is `test: ["CMD-SHELL", "pgrep -f 'ai_billing_audit.worker' || exit 1"]`. This makes the sidecar's liveness observable.
2. **Fail-closed on `POSTGRES_PASSWORD`.** Change `${POSTGRES_PASSWORD:-audit}` to `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}` so a missing env var halts the stack instead of starting with a known-weak credential.
3. **Add resource limits.** Suggestion: api `mem_limit: 1g`, worker `mem_limit: 256m`, postgres `mem_limit: 512m`, caddy `mem_limit: 128m`. No CPU caps (let the host scheduler decide).
4. **Resolve the `***` literal in `DATABASE_URL`.** Either move the password substitution to the docker-compose YAML using `${POSTGRES_PASSWORD}` interpolation, or have the api process build the URL from `POSTGRES_USER` + `POSTGRES_PASSWORD` + `POSTGRES_HOST` env vars. Today the literal is either broken or being hand-fixed post-deploy.
5. ~~**Inject `MAILGUN_API_KEY` into the api/worker environment**~~ **RESOLVED 2026-06-26 by removal.** The doctor-summary module no longer auto-sends and no longer reads any Mailgun env var. `/app/logs/doctor_emails.jsonl` is now the ONLY delivery surface — manual outbox dispatch is the chosen model (Cameron: "we can import and export reports and send emails ourselves").

---

## 4. Caddy config (`Caddyfile`)

### TLS config
- **No TLS.** Caddy is the **second hop** in a Traefik-fronted stack. The public TLS is terminated by Traefik (Let's Encrypt via `certResolver: letsencrypt`, per `deploy-to-vps.sh:196`). Caddy listens on plain HTTP (`:80`, line 15) inside the docker network. This is intentional and correct: layering a second TLS hop on the internal network would add latency and a second cert with no benefit.

### Reverse proxy rules
- **Minimal but correct.** Lines 19-24:
  ```
  reverse_proxy api:8000 {
      header_up Host {host}
      header_up X-Real-IP {remote_host}
      header_up X-Forwarded-For {remote_host}
      header_up X-Forwarded-Proto {scheme}
  }
  ```
  All four standard proxy headers present. `X-Forwarded-Proto {scheme}` is important: Traefik terminates TLS, so the request reaches Caddy as `http` and `{scheme}` is `http`. This means `X-Forwarded-Proto: http` is what the api process sees, **even though the original request was HTTPS**. **Real bug for any downstream code that uses `request.url.scheme` to decide "is this a secure connection?" — it'll always see `http`.** The api should be looking at `X-Forwarded-Proto` instead, or Caddy should be configured to set `X-Forwarded-Proto https` since Traefik is upstream.
- No `health_path`, no `lb_policy`, no `health_interval` — using defaults (round-robin, no active health probing). For a single api instance, this is fine.

### Security headers
- **None.** Caddy adds **no** response headers: no `Strict-Transport-Security`, no `X-Frame-Options`, no `X-Content-Type-Options`, no `Referrer-Policy`, no `Content-Security-Policy`, no `Permissions-Policy`. The `header` directive in Caddy is not used anywhere in the file.
- **Refutes the "Traefik adds them" assumption.** Traefik is configured at the host level (`/opt/traefik/dynamic/routers.yml`, edited by the deploy script) and the deploy script does **not** add any `responseHeaders` middleware. The live public response almost certainly lacks HSTS and friends.
- **Per `AUDIT_SECURITY.md` (prior agent #2): security headers are missing — confirmed.**
- For a service that handles PHI and serves a multi-tenant dashboard, the absence of HSTS is a real risk: a downgrade attack to HTTP would not be prevented.

### Rate limiting
- **None.** No `rate_limit` directive. The api is behind Traefik on the public side, and Traefik's rate-limit middleware is not configured in `routers.yml` (the deploy script's `router_block` at lines 190-197 contains only `rule`, `entryPoints`, `service`, `tls`).
- For a public-internet FastAPI service, no rate limit means the audit endpoint and the LLM calls can be hammered. The LLM cost is the primary concern; a 10× request amplification would burn real money at the Ollama Cloud provider.

### Logging
- **Configured.** Lines 26-29:
  ```
  log {
      output stdout
      format console
  }
  ```
  Caddy logs to stdout, which is captured by Docker's logging driver (default: json-file, rotated by Docker's daemon-level rotation, **not by the project**). For a service that needs log persistence beyond Docker's defaults, this is fine because Docker's default json-file driver rotates at 10MB×3 per container. The `ai_billing_audit_logs` named volume is for **application** logs (`/app/logs/*.jsonl`), not Caddy access logs.

### Recommendations (Caddyfile)
1. **Add security headers** as a Caddy `header` block. Suggested minimum:
   ```
   header {
       Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
       X-Content-Type-Options "nosniff"
       X-Frame-Options "DENY"
       Referrer-Policy "strict-origin-when-cross-origin"
       Permissions-Policy "geolocation=(), microphone=(), camera=()"
       -Server
   }
   ```
   Note: these will be on the *internal hop* (Traefik → Caddy → api → Caddy → Traefik → client), so the *client* sees them only if Traefik doesn't strip them. Configure Traefik to forward them, or set them on the Traefik `ResponseHeaders` middleware instead. Doing both is safest.
2. **Fix `X-Forwarded-Proto`.** Set it to `https` unconditionally in Caddy, since Traefik is upstream:
   ```
   header_up X-Forwarded-Proto "https"
   ```
3. **Add rate limiting** at the Traefik layer (not Caddy — Traefik is the public edge). `10 req/s` per IP for `/healthz` and `/encounter/*` paths; `2 req/s` for the upload endpoints. The deploy script should write the rate-limit middleware into `routers.yml`.

---

## 5. Log persistence and rotation

### Named volume verification — **CONFIRMED**
- `/app/logs` is the **`ai_billing_audit_logs` named volume** in `docker-compose.yml:62` (api) and `docker-compose.yml:95` (worker). The named volume is declared at line 154. **Refutes the prior-session "wiped on recreate" claim.** Logs survive `docker compose up -d --force-recreate`.

### Log files in `/app/logs/`
- `audit_trail.jsonl` — SHA-256 hash chain, written by `src/ai_billing_audit/audit_actions.py:27` (`_LOG_PATH = Path(os.environ.get("AUDIT_TRAIL_LOG", "/app/logs/audit_trail.jsonl"))`) and `src/audit_log.py`. Read back in `api.py:1138`.
- `upload_jobs.jsonl` — job history, written by `src/ai_billing_audit/job_queue.py:747` (`pkg_root.parent.parent / "logs" / "upload_jobs.jsonl"`). Read in `api.py:311, 539, 1893-1897`.
- `doctor_emails.jsonl` — operator outbox (was: Mailgun fallback when `MAILGUN_API_KEY` unset). **Refactored 2026-06-26**: this is now the ONLY delivery surface for doctor summaries. Written by `src/ai_billing_audit/doctor_email.py:_LOGS_DIR / "doctor_emails.jsonl"`. PHI-bearing; the biller reads the file and dispatches via their own mail client.
- `doctor_optouts.json` — opt-out storage, `doctor_email.py:78, 95-96`. Persistent JSON (not JSONL).
- `npi_email_cache.json` — NPI-to-email cache, `doctor_email.py:589, 627-628`. Persistent JSON.
- `appeal_letters.jsonl` — appeal letters log, `api.py:1876-1878`. Not in the brief but relevant for a future audit.
- `audit_trail.jsonl` is **also** in the Postgres `audit_trail` table (`audit_trail.sql` mounts at `docker-compose.yml:121`). **The two are parallel implementations** (per `AUDIT_CODE_QUALITY.md`); a bug fix in one doesn't propagate to the other. The JSONL is the on-disk dev surface; the SQL is the prod surface.

### Log rotation
- **None.** No `logrotate` config in the repo (`search_files logrotate` returns 0 results). No Python-side rotation in any of the log-writing modules (each `_LOG_PATH.open("a")` is an unbounded append). No `size` cap on the named volume.
- The named volume `ai_billing_audit_logs` will grow unbounded over time. A high-volume tenant (say 10,000 encounters/month × ~5KB per audit log row) = 50MB/month just for `audit_trail.jsonl`. After 2 years that's 1.2GB. After 7 years (PHIPA retention) that's 4.2GB. The Hostinger VPS disk (per the project notes, `coolify` VPS at 187.77.26.99) likely has a finite quota; a fill will cascade to other services.

### Disk usage caps
- **None.** No `tmpfs` cap, no volume size limit, no log compression, no archival job. **Real risk for long-term uptime.**

### Recommendations (logs)
1. **Add log rotation.** A `logrotate.d` config in `deploy/scripts/` that the install procedure copies to `/etc/logrotate.d/ai-billing-audit` would do it. Suggest: daily rotation, 7 daily + 4 weekly + 12 monthly = max ~6 months on disk in compressed form.
2. **Add a per-volume size cap** (e.g. `volumes: ai_billing_audit_logs: { driver: local, driver_opts: { size: "5g" } }`) so an unbounded growth bug fails fast instead of filling the host disk.
3. **Add an in-process log archiver** (cron-driven Python script) that moves old rows out of the JSONL files into a daily tar.gz in `/artifacts/logs/`. Then `audit_trail.jsonl` is bounded to the current week.
4. **Document the named volume mapping in a runbook** so a future `docker volume prune` doesn't silently nuke the audit trail. (Per `AUDIT_SECURITY.md:224`, the prior session flagged this same concern.)

---

## 6. Backup and disaster recovery

### `audit-backup.sh` (519 lines)

**What it backs up:**
- The Postgres database inside the `ai-billing-audit-postgres` container, via `docker exec -i "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner --no-privileges --quote-all-identifiers --serializable-deferrable` (line 461).
- Dumps the **public schema** including the `audit_trail` table. Verified post-upload by re-downloading the artifact, decrypting, and grepping for `CREATE TABLE.*audit_trail|COPY.*audit_trail` (lines 480-487). If the grep fails, the script exits 2 with a critical alert. **This is excellent engineering** — a silent partial-dump bug would be caught on the same run.
- **Does NOT back up:** `/app/logs/*.jsonl` (the on-disk audit trail, doctor emails cache, etc.), the source code, the `.env`, the Caddy config. These are on the host, not in a container volume that this script touches.

**Where backups go:**
- `rclone` to a configured B2 or S3 bucket (template at `backup.env.template:11-15`). Default `RCLONE_REMOTE=ai-billing-backup`, `RCLONE_BUCKET=ai-billing-audit-backups`, `RCLONE_PREFIX=pgdumps`. Path layout: `<bucket>/<prefix>/daily/`, `<prefix>/weekly/`, `<prefix>/monthly/`.
- Encryption: `age` with the public key at `/etc/ashbi/backup.age.pub` (line 464). Single-recipient today; rotation requires manual steps (lines 68-83 of the comment block).

**Stream end-to-end:** `pg_dump | age -e | tee /tmp/.audit-backup-bytes | rclone rcat` (lines 460-466). **No plaintext on disk during the run** — pg_dump output never touches a file except via the `tee` for size capture, which is `/tmp/.audit-backup-bytes` and is `rm -f`'d immediately after (line 468). Defence-in-depth.

**Idempotency:** if an artifact for today's UTC date and tier already exists at the destination, the run is a no-op (lines 332-354). `--force` overrides.

**Retention:** 4 weeks dailies, 12 months weeklies, 7 years monthlies (lines 367-371). PHIPA-compliant.

**Tier auto-pick:** Sundays → `weekly`, first Sunday of month → `monthly`, else `daily` (lines 273-282). `--tier` overrides.

**Size-anomaly detection:** compares new artifact to the prior weekly; a ≥50% drop fires a `critical` alert (lines 410-438). First run after install has no baseline and is a no-op.

**Alerting:** JSON POST to `ALERT_WEBHOOK_URL` (lines 209-227). Empty URL = log-only.

**Pre-flight:** requires `docker`, `age`, `rclone`, `curl`, and a reachable postgres container (lines 252-271). All failures exit 1.

**Caveats:**
- `set -o pipefail` is enabled inside the `if` block (line 459) but only there. If a non-pipeline command fails between arg-parsing and the pipeline, the script exits (good). The `pipefail` toggle is reset at line 476 after the pipeline, so subsequent commands don't have the strict pipe behavior. Fine.
- The script sources `backup.env` AFTER arg-parsing (line 192) — this means env vars passed on the command line (`RCLONE_REMOTE=foo /usr/local/bin/audit-backup.sh`) work, but `audit-backup.sh --tier daily RCLONE_REMOTE=foo` would not (flag is at the wrong position). Minor footgun.
- The `LOCAL_DUMP` temp file at `/tmp/.audit-backup-bytes` (line 465) is plaintext bytes of the encrypted stream (still ciphertext, not plaintext SQL). The `rm -f` at line 468 is the only cleanup. If the script is killed (SIGKILL) between `tee` and `rm`, the file persists in `/tmp` indefinitely. Minor, since it's ciphertext.

### `audit-restore-verify.sh` (357 lines)

**What it does:** monthly job, defaults to the first Sunday of the month (`deploy/scripts/ai-billing-audit-backup.cron:28`). Pulls the most recent `weekly` artifact, decrypts with `/etc/ashbi/backup.age.key`, creates a throwaway DB `ai_billing_audit_verify_YYYYMMDD_HHMMSS` on the same Postgres container, restores the dump into it, runs a sanity check (audit_trail table exists, `cryptographic_signature` column exists, row count ≥ `MIN_AUDIT_TRAIL_ROWS`), records PASS/FAIL to `/var/log/ai-billing-audit/verify.history`, and drops the throwaway DB (unless `--keep-db`).

**The verification is the strongest part of the DR story.** Most projects' "we have backups" claim is unsupported by any actual restore. This project has a monthly job that round-trips a real artifact and writes a pass/fail line to disk. A reviewer can `tail -F /var/log/ai-billing-audit/verify.log` and see history.

**Caveats:**
- The throwaway DB lives on the same Postgres container. If the container is down or the data dir is corrupted, the verify fails — and **the failure looks the same as a "the backup itself is corrupt" failure**. The script doesn't distinguish.
- Restoring into the same container means a corrupt dump (e.g. one with `CREATE DATABASE ai_billing_audit;` in it) could overwrite the live DB. The dump flags (`--no-owner --no-privileges`) reduce the surface but a malicious or buggy dump that includes `DROP TABLE audit_trail CASCADE;` would be executed. `psql -v ON_ERROR_STOP=1` (line 291) catches errors but not the destructive statements that succeed.

### RPO / RTO

- **RPO:** 24 hours (daily tier, runs at 02:00 UTC). For the weekly tier the worst case is 7 days. **Realistic worst-case RPO is 7 days** if the daily cron has been failing for a week.
- **RTO:** Untested end-to-end. The verify job proves a *backup artifact* can be restored; it does not prove that **a hot VPS can be replaced from scratch** (new VM, new Coolify, restore the DB from the artifact, redeploy via `deploy-to-vps.sh`). That full path has never been exercised (no evidence in the repo of a DR drill).

### Runbook for "live VPS is down"

- **Not present in the repo.** `docs/RUNBOOK.md` exists (per `AUDIT_SECURITY.md:190` and `search_files RUNBOOK.md`) but per the security audit, it covers hash-chain verification and PHI breach notification — **not VPS-down restoration**. The `deploy/scripts/README.md` has a "Manual restore" section (lines 60-75) but it covers "restore a single artifact into a known-good DB", not "stand up a new VPS from scratch".

### Recommendations (backup / DR)
1. **Author a `docs/RUNBOOK_DR.md`** (or extend `docs/RUNBOOK.md`) with the full "VPS is gone, what do I do" sequence: provision new VPS, install docker + rclone + age, restore `/etc/ashbi/`, restore `audit_trail.jsonl` etc. from the latest named-volume snapshot if available, restore Postgres from the most recent weekly artifact, redeploy via `deploy-to-vps.sh`, run the smoke test, verify `/healthz`, run a verify-restoration smoke against the prod DB.
2. **Add `/app/logs/*.jsonl` to the backup scope.** The on-disk JSONL files contain the chain that the SQL `audit_trail` table is *meant* to mirror, but per `AUDIT_CODE_QUALITY.md` they are parallel implementations; the JSONL has rows the SQL doesn't. A complete restore needs both. Suggest: a separate `audit-logs-backup.sh` that rsyncs the named volume to the same bucket under `<prefix>/logs/`.
3. **Run a real DR drill.** Schedule a quarterly exercise: spin up a fresh VPS, restore, verify. Record the actual RTO (the difference between "disaster declared" and "API back up"). Right now this is an unmeasured number.
4. **Tighten the `ALERT_WEBHOOK_URL` story.** The template is set up for it; there's no evidence the operator has configured a real webhook. Empty URL = log-only. A 7-day-old unnoticed backup failure means the weekly restore-verify will run against the last-known-good artifact, which is fine for chain integrity but the verify is checking the *backup of 7 days ago*, not *today's* data.

---

## 7. CI/CD

### `.github/workflows/e2e.yml`

**What it does:** runs Playwright e2e tests against the Next.js **portal** (`apps/portal/`), not the API. This is the portal's e2e suite, not the API's. Triggers on `pull_request` to `main` or `feat/**` and on `push` to `feat/billing-page`.

**Does it deploy on push to main?** No. There is no deploy job, no `appleboy/ssh-action`, no webhook to Coolify, no `docker push` to a registry. The `push` branch trigger is just for the e2e suite.

**Is there a test gate?** Yes for the e2e suite (it's the job itself), but **not for the API**. The API has 791 pytest tests per the session memory, but `.github/workflows/` has no Python test job. The pytest suite runs locally only; it is not a CI gate.

**Is there a separate staging environment?** No. The e2e workflow uses `DATABASE_URL: "file:./prisma/dev.db"` (SQLite, ephemeral). There is no staging deployment of the API.

**Are secrets in CI encrypted?** Yes (`GitHub Secrets` is the default for `secrets.*` references in workflows), but **no secrets are referenced in this workflow**. The workflow uses an empty `AUTH_RESEND_KEY` (line 28) and a dev `AUTH_SECRET` (line 29). No production secrets are exposed.

**Concurrency control:** `cancel-in-progress: true` per ref (line 13). Good — a force-push cancels the prior run.

**Timeout:** 15 minutes (line 22). Reasonable for a Playwright smoke suite.

### `audit_trail.sql` is mounted but not tested in CI

The SQL schema file is bind-mounted into postgres (`docker-compose.yml:121`) but no workflow tests that the schema applies cleanly. A syntax error in `audit_trail.sql` would surface only at first-boot of a fresh Postgres container, which (per the daily 02:00 cron and the weekly verify) is "almost never". Recommend a workflow that runs `docker compose up postgres` against a fresh volume and checks `psql -c '\dt audit_trail'`.

### No deploy pipeline

**The deploy to the live VPS is entirely manual.** A human runs `bash deploy-to-vps.sh` from their Mac, which ssh's to `coolify` and runs the steps. There is no record of who deployed what when (no git tag, no deploy log, no audit). The "deploy" is a `bash` command someone remembers to run.

### Recommendations (CI/CD)
1. **Add a Python pytest workflow** (`.github/workflows/api-tests.yml`) that runs on every PR. The API has 791 tests; they should be a CI gate.
2. **Add a docker-build workflow** that builds the API image and pushes to a registry (Docker Hub or ghcr.io) on merge to main. Tag with the git short SHA. This gives `deploy-to-vps.sh` a registry to pull from instead of building on the host.
3. **Add a deploy workflow** triggered manually (`workflow_dispatch`) that runs `deploy-to-vps.sh` against a configured VPS. Requires the SSH key as a GitHub Secret.
4. **Add a workflow that boots `docker compose up postgres` and verifies `audit_trail.sql` applies** on a fresh volume.
5. **Tag releases.** Today there is no `git tag` discipline; the image is hardcoded as `ai-billing-audit:0.1.0` (`docker-compose.yml:48`).

---

## 8. `/healthz` endpoint

### Definition
- `src/ai_billing_audit/api.py:842-849`:
  ```
  @app.get("/healthz")
  def healthz() -> dict[str, Any]:
      return {
          "status": "ok",
          "version": app.version,
          "title": app.title,
          "n_registered": len(list_demo_encounters()),
      }
  ```

### What it checks
- **Almost nothing.** The function returns a static dict. It does not check the database, does not check the LLM provider, does not check the worker queue, does not check that the audit_trail.jsonl is writable. The `n_registered` field is `len(list_demo_encounters())` — this reads from the **in-memory demo registry** (per `demo_entries.py`), not from Postgres. So even if Postgres is down, `/healthz` returns 200 with `n_registered: <whatever was in the demo set>`.

### Version + commit SHA
- **Version: yes** (`app.version`). But no commit SHA. The version is set in `pyproject.toml` and does not reflect which git commit the image was built from. Recommend: build-time `GIT_SHA` env var, baked into the image, returned by `/healthz`.

### LLM model name leak
- **No leak in /healthz itself.** The LLM model name `minimax-m3:cloud` (or whatever is in `MINIMAX_DEFAULT_MODEL`) is not returned. However, the model name is exposed in the HTML at `templates/encounters_upload.html:8` ("the LLM (minimax-m3) checks each claim...") and `templates/index.html:122` — these are public-facing strings. Not a /healthz issue, but a "model name is not a secret" issue.

### Auth requirement
- **No auth.** The `_bearer_auth` middleware whitelists `/healthz` (line 411) and `AUDIT_ALLOW_NO_AUTH=1` would also allow it (line 417-418). Even with a `AUDIT_BEARER_TOKEN` set, `/healthz` is reachable by anyone who can hit the public URL. This is correct for a load-balancer health check.

### External uptime monitor
- **No evidence in the repo.** No UptimeRobot / Better Stack / Pingdom config. The deploy script's `deploy-to-vps.sh:254-267` does its own "wait up to 90s" check during deploy, but there's no evidence of a 24/7 external monitor. The smoke test is one-shot at deploy time, not continuous.

### Recommendations (healthz)
1. **Extend `/healthz` to actually check things.** Suggested:
   ```
   {
     "status": "ok" | "degraded",
     "version": "0.1.0",
     "git_sha": "abc1234",
     "checks": {
       "postgres": {"ok": true, "latency_ms": 3},
       "llm": {"ok": true, "model": "minimax-m3:cloud", "latency_ms": 412},
       "audit_log_writable": {"ok": true, "path": "/app/logs/audit_trail.jsonl"},
       "operator_outbox_writable": {"ok": true, "path": "/app/logs/doctor_emails.jsonl"}
     }
    }
    ```
2. **Add a separate `/readyz`** that returns 200 only if all checks pass, leaving `/healthz` as a shallow liveness check (current behavior). K8s-style split.
3. **Add the git SHA.** A `GIT_SHA` env injected at `docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD)` and exposed via `app.version` or as a separate field.
4. **Configure an external uptime monitor.** UptimeRobot has a free tier; one HTTP check on `/healthz` with a 5-minute interval would catch a deploy-induced downtime.

---

## 9. Known-issues confirmation/refutation table

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `/app/logs` is a named volume (agent #2) | **CONFIRMED** | `docker-compose.yml:62, 95, 154` — `ai_billing_audit_logs:/app/logs` on both api and worker, declared as a named volume. Refutes the prior-session "wiped on recreate" note. |
| 2 | worker container is "unhealthy at 41h" (prior session) | **CONFIRMED as ongoing** | `docker-compose.yml:77-104` defines no `healthcheck:` block for `worker`. The container's main (`worker.py:66-69`) is a `time.sleep(30)` loop. With no healthcheck, the container is "healthy" by default and a hang would be invisible. The prior-session observation was likely the heartbeat *missing from logs*, not the container flagged unhealthy. The root cause (no healthcheck) is still unfixed. |
| 3 | ~~`MAILGUN_API_KEY` not set on live container~~ | **RESOLVED 2026-06-26 by removal.** The doctor-summary module no longer reads this env var and no longer auto-sends. `pyproject.toml` no longer pins `requests`. The operator-outbox JSONL (`/app/logs/doctor_emails.jsonl`) is the ONLY delivery surface. |
| 4 | Ollama cloud key rotation (compromised-on-send) has NOT been rotated | **CONFIRMED** | `search_files ~/.config/ai-billing/ollama-key` returns 5 hits, all reading the same file. `scripts/check_live.py:31-32`, `scripts/ab_prompt.py:30-31`, `scripts/run_7x.py:17-18`, `scripts/run_v7b_full.sh:6-8`, `scripts/run_ollama_audit.py:33-34` all read the same path. There is no evidence in the repo that a rotation has occurred. The deploy script writes the *current* key on every deploy (`deploy-to-vps.sh:135-151`), so a rotation on the local Mac needs to be followed by a `deploy-to-vps.sh` re-run. If the operator hasn't done that, the live container is still using the compromised key. (I cannot confirm live state without touching the VPS, but the absence of any code path or config indicating a rotated key is consistent with the claim.) |
| 5 | Caddy config has security headers (per agent #2: missing) | **CONFIRMED missing in Caddyfile** | `Caddyfile:15-30` is 30 lines. There is no `header` block anywhere. The `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` headers are not set on the Caddy hop. Whether Traefik (the public edge) adds them is not auditable from this repo — the deploy script writes only `rule`, `entryPoints`, `service`, `tls` to `routers.yml` (`deploy-to-vps.sh:190-197`), no `middlewares` field. Conclusion: security headers are likely missing from the public response too. |
| 6 | ~~`doctor_email.py` has dev fallback at `/app/logs/doctor_emails.jsonl` when `MAILGUN_API_KEY` unset~~ | **RESOLVED 2026-06-26 by removal.** The JSONL is no longer a fallback — it is the ONLY delivery surface. `_mailgun_configured` and `_send_via_mailgun` were deleted from `src/ai_billing_audit/doctor_email.py`. The function `send_doctor_summary()` always writes to the outbox (when not opted-out). |

---

## 10. Risk-ranked recommendations (top 10)

| Rank | Action | File(s) | Effort | Impact |
|---|---|---|---|---|
| 1 | **Delete `Dockerfile:36` `COPY data ./data`** and add `data/` to `.dockerignore`. The 13,758 lines of dev/holdout/CA val data have no business in a production image. | `Dockerfile`, `.dockerignore` | 5 min | High — removes 6 dev/holdout val sets + training data from the prod binary |
| 2 | ~~**Inject `MAILGUN_API_KEY` into the deploy path**~~ **RESOLVED 2026-06-26 by removal.** The doctor-summary module no longer auto-sends; manual outbox dispatch is the chosen model. | n/a | n/a | n/a |
| 3 | **Fix the `***` literal in `DATABASE_URL`.** Either interpolate `${POSTGRES_PASSWORD}` directly in `docker-compose.yml:56-57` or build the URL in code from `POSTGRES_USER` + `POSTGRES_PASSWORD` + `POSTGRES_HOST`. Today the deploy script writes a `***` to the host `.env` that no client can authenticate with. | `deploy-to-vps.sh:148-149`, `docker-compose.yml:56-57` | 15 min | Critical — possible live outage / auth failure on every fresh deploy |
| 4 | **Fail-closed on `POSTGRES_PASSWORD` default.** Change `${POSTGRES_PASSWORD:-audit}` to `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}`. Today a missing env var gives a prod DB with username=password=audit. | `docker-compose.yml:113` | 1 min | High — prevents silent weak-credential prod database |
| 5 | **Add a healthcheck to the worker container.** `test: ["CMD-SHELL", "pgrep -f 'ai_billing_audit.worker' || exit 1"]`. Makes the sidecar's liveness observable. | `docker-compose.yml:77-104` | 5 min | Medium — restores observability for the broken sidecar |
| 6 | **Add log rotation and a per-volume size cap.** A `logrotate.d` config for the named volume, and a `size: "5g"` driver option. Today logs grow unbounded on a 7-year retention PHIPA service. | `deploy/scripts/`, `docker-compose.yml:154` | 1 hour | High — prevents disk-fill outage in 1-2 years |
| 7 | **Add a Python pytest CI workflow** and a docker-build/push workflow. The 791 tests should be a merge gate, not a local-only check. | `.github/workflows/` | 2 hours | High — prevents regressions in the test suite from reaching prod |
| 8 | **Add Caddy security headers + Traefik rate limiting.** `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` at Caddy, plus a rate-limit middleware in Traefik's `routers.yml` for the upload endpoints. | `Caddyfile`, `deploy-to-vps.sh:165-224` | 1 hour | Medium-High — addresses public-internet attack surface |
| 9 | **Author a `docs/RUNBOOK_DR.md`** with the full "VPS is gone, stand up a new one" sequence. Run a real DR drill quarterly. | `docs/` | 4 hours (runbook) + 2 hours/drill | High — first measured RTO |
| 10 | **Fix the hardcoded `PUBLIC_HOSTNAME` inside the Python heredoc in `deploy-to-vps.sh:192`.** Today the deploy script's top-of-file `PUBLIC_HOSTNAME` is not actually used; the literal string is. The same for `LLM_BASE_URL` (which conflicts with `docker-compose.yml:55`). | `deploy-to-vps.sh:50-55, 192` | 15 min | Medium — prevents deploy-time hostname/URL drift |

---

## Appendix: file-by-file audit map

| File | Lines | Audit verdict |
|---|---|---|
| `deploy-to-vps.sh` | 272 | Solid for a 1-author project. Idempotent, smoke-tested, fails loudly. Hardcoded `PUBLIC_HOSTNAME` and `LLM_BASE_URL` inside the Python heredoc (real bug); no rollback step; no fail-closed on missing secrets. |
| `deploy/scripts/audit-backup.sh` | 519 | Best-in-class. End-to-end streaming, age-encrypted, retention-tiered, size-anomaly-detected, idempotent, alert-hooked, post-upload-validated. |
| `deploy/scripts/audit-restore-verify.sh` | 357 | Best-in-class. Monthly round-trip into throwaway DB with schema/row-count assertions. |
| `deploy/scripts/backup.env.template` | 65 | Clean. Documents every override. |
| `deploy/scripts/ai-billing-audit-backup.cron` | 28 | 6-field entries (user column present). Good. |
| `deploy/scripts/test-backup-scripts.sh` | 202 | 5 unit tests for the non-docker parts. Good but doesn't cover the pipeline. |
| `Dockerfile` | 56 | Ships 13K lines of dev/holdout/CA val data. No USER directive. Single-stage. Good HEALTHCHECK. |
| `.dockerignore` | 50 | Does not exclude `data/`. Excludes `node_modules/` implicitly via `apps/`. |
| `docker-compose.yml` | 162 | All named volumes (good). Worker has no healthcheck. `POSTGRES_PASSWORD:-audit` fail-open. No resource limits. `MAILGUN_API_KEY` no longer a tracked secret (removed 2026-06-26). |
| `Caddyfile` | 30 | Zero security headers. `X-Forwarded-Proto {scheme}` is wrong (should be `https` unconditionally for the public-edge scenario). No rate limiting. |
| `.github/workflows/e2e.yml` | 110 | Portal e2e only. No API tests. No deploy. |
| `src/ai_billing_audit/api.py:842-849` | 8 | `/healthz` returns a static dict, doesn't check DB/LLM/writable. No git SHA. |
| `src/ai_billing_audit/doctor_email.py` | 537 | Operator-outbox JSONL writer only. `MAILGUN_API_KEY` no longer read; `_send_via_mailgun` + `_mailgun_configured` deleted 2026-06-26. |
| `src/ai_billing_audit/worker.py` | 75 | 30s heartbeat loop. No healthcheck in compose to detect hang. |
| `src/audit_log.py` + `src/ai_billing_audit/audit_actions.py` | 2 files | Two parallel hash-chain implementations. Not a deploy/ops concern; covered in `AUDIT_CODE_QUALITY.md`. |
| `audit_trail.sql` | 95 | Bind-mounted into postgres. Schema covers the hash chain + audit log + audit hash table. (Not directly audited here; referenced by `audit-restore-verify.sh` for column-existence checks.) |

---

*End of report. 4,180 words.*
