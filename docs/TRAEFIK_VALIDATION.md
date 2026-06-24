# Traefik Dynamic-Config Validation Cron (proposal)

**Status:** Design proposal only. Implementation is **out of scope** for
`t_11861525`. The doc below is detailed enough that a v2 agent can
pick it up and ship a working `/opt/vps/bin/traefik-validate.py` plus
the corresponding crontab entry without re-deriving the design.

## Why this exists (the risk)

`/etc/traefik/dynamic/routers.yml` on the VPS is the source of truth
for routing inbound traffic to the Docker-compose services that make
up this project (the `ai-billing-audit-api` and `ai-billing-audit-caddy`
services, plus the rest of the `ashbi-services` family). It is
rewritten by `deploy-to-vps.sh` on every ship.

If a deploy errors partway through — power blip during `scp`, OOM
while Traefik is reading, a manual edit that YAML-validates but
references a service that isn't running — the live URL
`https://ai-billing-audit.ashbi.ca/` can 502 / 404 / 521 indefinitely.
Today there is no automated safety net: the broken state survives
until a human notices and fixes it by hand.

The proposed fix is a daily cron that:

1. Reads the current `routers.yml`.
2. Validates that every `services.<name>` reference points at a
   container that is actually running.
3. On any failure, atomically reverts to the most recent
   `routers.yml.bak.<timestamp>` and asks Traefik to reload.

## Operational context

* **File paths (VPS):**
  * live config: `/etc/traefik/dynamic/routers.yml`
  * backups:    `/etc/traefik/dynamic/routers.yml.bak.<unix-ts>`
* **Traefik process:** runs as a host systemd unit (`traefik.service`).
  Reload is `systemctl kill -s HUP traefik` (Traefik supports SIGHUP
  for a graceful reload without dropping in-flight connections).
* **Backup rotation:** `deploy-to-vps.sh` already rotates the prior
  `routers.yml` to `routers.yml.bak.<unix-ts>` before writing the new
  copy. That gives us a free rollback target.
* **Schedule:** daily at 04:17 host-local (random minute to avoid
  the standard cron stampede). Frequency is fine because the
  primary risk surface is a broken deploy, which surfaces
  immediately on the next health-check loop anyway; the cron is the
  safety net, not the primary detector.

## Proposed validator: `/opt/vps/bin/traefik-validate.py`

A small Python 3 script (~150 lines). No external deps beyond
`pyyaml`, `docker` (the CLI), and the stdlib. Pseudocode:

```python
#!/usr/bin/env python3
"""Daily Traefik dynamic-config validator + auto-revert.

Exit codes:
  0  OK (or successfully recovered)
  1  Validation failed AND no usable backup
  2  Validation failed, revert attempted but Traefik reload failed
  3  Validation failed, backup not writable / SIGHUP not permitted

Logs to /var/log/traefik-validate.log and posts a one-line summary to
/var/run/traefik-validate.last (for an external monitor to scrape).
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

LIVE = Path("/etc/traefik/dynamic/routers.yml")
BACKUP_GLOB = "/etc/traefik/dynamic/routers.yml.bak.*"
TRAEFIK_UNIT = "traefik.service"


def parse(path: Path) -> dict:
    """Parse routers.yml. Raises yaml.YAMLError on bad YAML."""
    with path.open() as f:
        return yaml.safe_load(f)


def running_containers() -> set[str]:
    """Return the set of <name>@<id> for every running container."""
    r = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}@{{.ID}}"],
        capture_output=True, text=True, check=True,
    )
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def services_referenced(doc: dict) -> set[str]:
    """Pull every `loadbalancer.server.URL` and bare service reference
    out of the dynamic-config doc. We are deliberately conservative:
    if Traefik might route to it, we want to know the container is up.
    """
    refs: set[str] = set()
    # routers.<name>.service -> services.<name>.loadBalancer.server.URL
    for r in (doc.get("http", {}).get("routers", {}) or {}).values():
        sname = r.get("service")
        if isinstance(sname, str):
            refs.add(sname)
    # Walk services, too — direct docker-network loadBalancer URLs
    for s in (doc.get("http", {}).get("services", {}) or {}).values():
        lb = s.get("loadBalancer", {})
        for srv in lb.get("servers", []) or []:
            url = srv.get("url", "")
            # http://container-name:port  -> container-name
            if "://" in url:
                host = url.split("://", 1)[1].split(":", 1)[0]
                refs.add(host)
    # tcp routers too
    for r in (doc.get("tcp", {}).get("routers", {}) or {}).values():
        sname = r.get("service")
        if isinstance(sname, str):
            refs.add(sname)
    return refs


def resolve(refs: set[str], running: set[str]) -> tuple[set[str], set[str]]:
    """Given service-name references and running container names,
    return (missing, present). A reference is 'present' if any running
    container name (left of '@') matches the reference.
    """
    names = {n.split("@", 1)[0] for n in running}
    missing = {r for r in refs if r not in names}
    return missing, refs - missing


def latest_backup() -> Path | None:
    cands = sorted(glob.glob(BACKUP_GLOB), key=os.path.getmtime, reverse=True)
    return Path(cands[0]) if cands else None


def revert_to(bak: Path) -> None:
    shutil.copy2(bak, LIVE)


def reload_traefik() -> None:
    subprocess.run(
        ["systemctl", "kill", "-s", "HUP", TRAEFIK_UNIT],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually revert + reload on failure. "
                         "Default is dry-run.")
    ap.add_argument("--log", default="/var/log/traefik-validate.log")
    args = ap.parse_args()

    log_line = lambda msg: print(msg, file=open(args.log, "a"))

    try:
        doc = parse(LIVE)
    except yaml.YAMLError as e:
        log_line(f"[{time.strftime('%F %T')}] YAML PARSE FAIL: {e}")
        return _maybe_revert(args, log_line, reason=f"yaml parse: {e}")

    refs = services_referenced(doc)
    if not refs:
        log_line(f"[{time.strftime('%F %T')}] WARN: zero services referenced")
        return 0  # nothing to validate

    running = running_containers()
    missing, present = resolve(refs, running)
    if not missing:
        log_line(f"[{time.strftime('%F %T')}] OK ({len(present)} services up)")
        return 0

    log_line(f"[{time.strftime('%F %T')}] FAIL: missing={sorted(missing)} "
             f"present={sorted(present)}")
    return _maybe_revert(args, log_line,
                         reason=f"missing services: {sorted(missing)}")


def _maybe_revert(args, log_line, *, reason: str) -> int:
    bak = latest_backup()
    if bak is None:
        log_line(f"[{time.strftime('%F %T')}] no backup to revert to")
        return 1
    if not args.apply:
        log_line(f"[{time.strftime('%F %T')}] DRY-RUN: would revert to {bak}")
        return 0
    try:
        revert_to(bak)
    except OSError as e:
        log_line(f"[{time.strftime('%F %T')}] REVERT COPY FAIL: {e}")
        return 3
    try:
        reload_traefik()
    except subprocess.CalledProcessError as e:
        log_line(f"[{time.strftime('%F %T')}] RELOAD FAIL: {e}")
        return 2
    log_line(f"[{time.strftime('%F %T')}] RECOVERED via {bak} ({reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Key implementation notes

* **Atomic revert:** `shutil.copy2(bak, LIVE)` is atomic on the same
  filesystem (POSIX rename under the hood via `copy` mode). The
  crontab uses `--apply`; the deploy script may also call the
  validator manually after a ship as a one-shot smoke check.
* **Why `docker ps`:** the services referenced in `routers.yml` are
  almost always Docker containers on the same host. Reading from
  `docker ps` is one query and is authoritative.
* **Conservative reference set:** the script errs on the side of
  flagging a reference as missing if it can't find an exact name
  match. This is intentional — a false positive (alerting on a
  phantom service) costs one cron run; a false negative (missing a
  real broken ref) costs the user-facing URL.
* **No LLM calls.** Validation is deterministic.
* **Lockfile:** if a future version wants to coordinate with the
  deploy script, add a `/var/lock/traefik-validate.lock` via
  `flock(1)`. Not needed for the v1 single-runner cron.

### Crontab entry

```
# /etc/cron.d/traefik-validate
17 4 * * * root /opt/vps/bin/traefik-validate.py --apply \
    >> /var/log/traefik-validate.log 2>&1
```

(Stub `0 4 * * *` for an hourly smoke ping on a fresh deploy until
the daily cron is the only watcher.)

## Edge cases the validator handles (and ones it does not)

### Handled

* `routers.yml` is not valid YAML → parse error → revert.
* `routers.yml` references a service for which no container exists
  with that name → missing set non-empty → revert.
* No backups present → exit 1, do not modify live file.
* Traefik unit is down → reload fails → exit 2; live file still
  reverted (so the next manual start picks up a good config).
* Backup itself is corrupt → revert succeeds, but the next validator
  run will detect the same failure class and step further back.
  Recommend retaining at least 10 generations of `.bak.*` (the
  deploy script already does this).

### Not handled (deliberately out of scope for v1)

* Service exists but its health check is failing (e.g. Postgres up
  but app can't connect). Detected by the `/healthz` smoke cron
  (`t_b27973a5`).
* TLS cert near expiry. Let Traefik + Let's Encrypt handle.
* Stale `routers.yml` that YAML-parses and references real services
  but routes to the wrong backend (typo in container name vs port).
  The validator catches the missing-service case; the typo case
  requires a traffic-aware monitor.

## What this task did NOT do

* Did **not** write the validator script to `/opt/vps/bin/` on the
  VPS. That requires host access and is a separate deploy task.
* Did **not** install the cron entry. Same reason.
* Did **not** add `pyyaml` to a host-level `requirements.txt`
  (VPS uses system Python; `pyyaml` ships in `python3-yaml` on
  Debian-family images).
* Did **not** wire a Slack/email alert on `exit != 0`. That's the
  `t_b27973a5` "5xx error rate alert" task.

## Acceptance for `t_11861525`

* [x] Risk is documented (deploys can leave `routers.yml` in a
  broken state).
* [x] Proposed fix is documented (daily cron at
  `/opt/vps/bin/traefik-validate.py`).
* [x] Pseudocode is detailed enough for a v2 agent to implement
  without re-deriving the design (parse → resolve → revert → reload).
* [x] Edge cases and out-of-scope items are enumerated.
