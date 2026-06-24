# ai-billing-audit — Changelog

Project-level changes that the deploy script, the runbook, and the audit
trail all reference. Entries are grouped by date (most recent first).
For the in-deploy / in-PR commit log, see `git log`.

---

## 2026-06-24

### Restore caddy `rate_limit` directive via a custom caddy build
(kanban `t_0910e627`, post-deploy board `zorva-post-deploy-2026-06-24`)

**Why.** The security audit (task `t_106739f0`, commit `877ad92`) added a
`rate_limit` directive to `Caddyfile`, but the stock `caddy:2-alpine`
image does not ship the `http.handlers.rate_limit` module — config
validation fails on the host, so the directive was commented out at
deploy time (commit `7cff811`, 2026-06-24).

**What changed.**
- New `Dockerfile.caddy` at the repo root. Multi-stage build:
  - `FROM caddy:2.7.6-builder-alpine AS builder`
  - `RUN xcaddy build --with github.com/mholt/caddy-ratelimit --with github.com/lucaslorentz/caddy-docker-proxy/v2`
  - `FROM caddy:2.7.6-alpine`
  - `COPY --from=builder /usr/bin/caddy /usr/bin/caddy`
  - `RUN caddy list-modules | grep -E '^(http.handlers.rate_limit|http.handlers.docker_proxy)$'` (sanity check)
- `docker-compose.yml` `caddy` service now uses `build: { context: ., dockerfile: Dockerfile.caddy }` and `image: ai-billing-audit-caddy:0.1.0` instead of `image: caddy:2-alpine`.
- `Caddyfile` `rate_limit ai_billing {remote_host} 10r/s 60r/m` is uncommented. The 8-line comment block explaining the disabled state is replaced with a 4-line note pointing at `Dockerfile.caddy`.
- No `deploy-to-vps.sh` change required: the existing `docker compose build --pull` step (line 296) builds every service with a `build:` block, so the caddy image is rebuilt on every deploy. The custom image also benefits from `--pull`, which fetches the pinned `caddy:2.7.6-builder-alpine` and `caddy:2.7.6-alpine` bases.

**Pin rationale.** Both base images are pinned to `2.7.6` (not the floating
`2` or `2-alpine` tag) so a future Caddy release can't silently change the
modules the rate-limit build expects. Bump both `FROM` lines in lockstep.

**Why `lucaslorentz/caddy-docker-proxy/v2` is included.** We don't use
it today (the caddy config is file-based), but the rebuild is already
paying the xcaddy cost, and shipping the module means a future
"service discovery from docker labels" refactor doesn't need a second
rebuild. Cheap insurance; one line.

**Build verification (this commit).**
- Image-tag sanity: queried Docker Hub registry for `library/caddy:2.7.6-builder-alpine` and `library/caddy:2.7.6-alpine` — both resolve to active linux/amd64 manifests (last_pulled 2026-06-24).
- Module-path sanity: `github.com/mholt/caddy-ratelimit` and `github.com/lucaslorentz/caddy-docker-proxy/v2` are the canonical import paths per each project's README.
- Local `docker build -f Dockerfile.caddy -t zorva-caddy:test .` was **not** run on the dev workstation (no Docker daemon installed — see "Caveats"). The first build verification will happen on the VPS during the next `deploy-to-vps.sh` run, which is the canonical verification path for this project.

**Caveats / follow-ups.**
- The local build verification step in the kanban card assumes a
  Docker daemon on the dev host. This machine has no `docker` /
  `podman` / `colima` / `nerdctl` binary, so the verification was
  deferred to the VPS-side `docker compose build --pull` (Step 4 of
  `deploy-to-vps.sh`). If a future card needs a local pre-build, the
  workstation needs Docker installed.
- The `caddy list-modules` sanity-check `RUN` will fail the build if
  either module fails to compile, so the custom image is
  self-validating. No follow-up needed unless xcaddy or the Go base
  moves forward faster than the caddy:2.7.6-builder-alpine image.

**Files changed.**
- `Dockerfile.caddy` (new)
- `docker-compose.yml` (caddy service: image → build)
- `Caddyfile` (uncomment `rate_limit`, trim comment block)
- `CHANGELOG.md` (this entry)
