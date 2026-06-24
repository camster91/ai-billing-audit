# Live-URL 5xx monitoring — `monitor_live_url.py`

> Captured 2026-06-24 in service of kanban task
> `zorva-post-deploy-2026-06-24 / t_b27973a5`. The monitor polls the
> already-deployed FastAPI endpoint at
> `https://ai-billing-audit.ashbi.ca/healthz` every 5 minutes and
> fires a single webhook alert when the endpoint returns a non-2xx
> response for 3 consecutive checks (~15 minutes of failure).

This is a **docs-and-script** change only. The script is written and
committed to the repo but **not deployed** — the VPS deploy is a
separate concern handled by `deploy-to-vps.sh` and tracked elsewhere.

---

## 1. Why a custom script and not Datadog / Better Uptime / etc.

We already pay for `ashbi-services` monitoring on the host. It does
**uptime pings from one external region** — useful for "is the VM
alive" but blind to application-level outages (LLM provider down,
Postgres connection pool exhausted, FastAPI process crashed but
container kept restarting). Those are the exact failure modes the
task calls out:

- LLM provider outage → `/healthz` starts returning 503 or 500
- Postgres connection-pool exhaustion → FastAPI hangs → `/healthz`
  times out
- Caddy reverse-proxy TLS cert expired → 502s upstream

`/healthz` (in `src/ai_billing_audit/api.py`) returns
`{"status": "ok", ...}` only when the API process can reach its
dependencies. It is the right probe. It just needs a polling agent
that knows when to alert.

A 50-line pure-stdlib Python script run from cron beats wiring up a
SaaS integration for one URL.

---

## 2. Design

### 2.1 Probe

```python
urllib.request.urlopen("https://ai-billing-audit.ashbi.ca/healthz", timeout=10)
```

- **10-second timeout** — long enough to absorb a slow Caddy, short
  enough that a single hung probe doesn't block the next cron tick
  (cron runs every 5 minutes, so the headroom is large).
- **No curl subprocess.** Pure-stdlib `urllib` removes the
  external-binary dependency and makes the script trivially portable
  to any Linux host with Python ≥ 3.8.

### 2.2 Failure window

3 consecutive non-2xx checks at 5-minute intervals = **~15 minutes of
confirmed failure** before an alert fires. This is long enough to
ride out:

- A Caddy reload that briefly returns 502
- A postgres failover that takes 1–2 minutes
- An LLM provider blip that recovers within a few minutes

…and short enough that a real outage (api process OOM-killed, LLM
provider down for >15 min, postgres replica lag spike) pages someone
while the issue is still actionable.

### 2.3 State persistence

The counter and last-check metadata are written to
`/var/lib/zorva/monitor_state.json` after every run, atomically
(`write-temp-then-os.replace`). A corrupt or missing file falls back
to a fresh start (`consecutive_failures = 0`).

This satisfies the task requirement that *deleting the state file
manually re-arms the monitor cleanly*.

### 2.4 Alert-storm suppression

Two mechanisms cooperate:

1. **Marker file** at `/var/run/zorva-alert-{hostname}.alert` —
   written *immediately after* an alert fires. The script checks for
   the marker at the start of every run and refuses to fire a second
   alert while it exists.
2. **Counter reset on success** — a single 2xx response zeroes the
   counter *and* deletes the marker, re-arming the monitor.

Net effect: one outage → exactly one alert. Two outages separated by
any successful check → two alerts. Two outages back-to-back with no
recovery between them → one alert.

### 2.5 Webhook payload

```json
{
  "service": "ai-billing-audit",
  "url": "https://ai-billing-audit.ashbi.ca/healthz",
  "status_code": 503,
  "error": "HTTP Error 503: Service Unavailable",
  "consecutive_failures": 3,
  "first_failed_at": "2026-06-24T15:42:00Z",
  "alert_at":      "2026-06-24T15:57:00Z",
  "host": "vps-ashbi-01",
  "ack_command": "rm /var/run/zorva-alert-vps-ashbi-01.alert"
}
```

POSTed as `application/json` to whatever URL is in
`$ZORVA_MONITOR_WEBHOOK` (Slack incoming-webhook, Teams connector,
PagerDuty Events API v2 — all accept the same JSON shape with minor
massaging).

If the webhook env var is empty, the alert is logged to
`/var/log/zorva-monitor.log` only. Useful on hosts where Slack has
not been wired up yet — the operator still gets the alert from the
cron mailer.

---

## 3. Deployment

### 3.1 Files to install on the VPS

| Source path                                       | Target on host                          | Mode    |
| ------------------------------------------------- | --------------------------------------- | ------- |
| `scripts/monitor_live_url.py` (this repo)         | `/opt/vps/bin/monitor_live_url.py`      | `0755`  |
| n/a                                               | `/var/lib/zorva/` (state-file dir)      | `0755`  |
| n/a                                               | `/var/log/zorva-monitor.log` (log file) | `0644`  |
| n/a                                               | `/var/run/zorva-alert-*.alert` (marker) | `0644`  |

### 3.2 Crontab entry

```
# /etc/cron.d/zorva-monitor — installed by deploy-to-vps.sh after
# the FastAPI containers are confirmed healthy.
#
# Polls https://ai-billing-audit.ashbi.ca/healthz every 5 minutes.
# 3 consecutive non-2xx responses (~15 min of failure) fires one
# webhook alert. Marker file suppresses alert storms until acked.
*/5 * * * * root /opt/vps/bin/monitor_live_url.py 2>&1 | logger -t zorva-monitor
```

The `| logger -t zorva-monitor` tail mirrors script output into
syslog (journald on the VPS) for backup visibility — the script
itself appends to `/var/log/zorva-monitor.log` as the primary
record.

### 3.3 Environment / secrets

The webhook URL must NOT live in the crontab file. Put it in
`/etc/zorva-monitor.env` (mode `0600`, owned by `root`) and source it
from a wrapper, or wrap the script in a systemd timer unit (preferred
long-term — out of scope for this task).

For now the cron entry above is sufficient; the deploy script will
add a `ZORVA_MONITOR_WEBHOOK=` line to a wrapper script that
sources `/etc/zorva-monitor.env` before exec'ing the monitor.

### 3.4 Self-test on first install

After `deploy-to-vps.sh` installs the script, it runs:

```
/opt/vps/bin/monitor_live_url.py --dry-run --verbose
```

Expected output:

```
2026-06-24T15:30:00Z check ok status=200
consecutive_failures=0 threshold=3 alert_active=False → no alert
```

If the live URL is not yet healthy at deploy time, this will surface
the failure immediately rather than waiting 15 minutes for the real
cron to detect it.

---

## 4. Operator runbook

### 4.1 Ack / clear an alert

The alert payload contains the exact `ack_command`:

```
rm /var/run/zorva-alert-vps-ashbi-01.alert
```

(Substitute `{hostname}`.) Run as root. The next cron tick will see
`alert_active=False` and resume normal monitoring. The state file
still shows the failure counter — a 2xx response resets it.

### 4.2 Re-arm without waiting for a successful check

```
rm /var/run/zorva-alert-*.alert /var/lib/zorva/monitor_state.json
```

The monitor will start counting from zero on the next run.

### 4.3 Tail the log

```
tail -f /var/log/zorva-monitor.log
# or, via journald:
journalctl -t zorva-monitor -f
```

### 4.4 Triage a page

1. `curl -v https://ai-billing-audit.ashbi.ca/healthz` — confirm the
   failure from the operator's shell (rules out local-network issues
   on the monitor host).
2. `docker compose ps` in `/opt/projects/ai-billing-audit/` — check
   the four service statuses (api, worker, postgres, caddy).
3. `docker compose logs --tail=200 api` — last 200 lines of API logs.
4. `docker compose logs --tail=200 worker` — last 200 lines of worker.
5. If a service is down: `docker compose up -d <service>`.
6. If everything looks healthy from the operator's shell but the
   monitor still alerts: check Caddy (`docker compose logs caddy`) —
   the TLS cert may have expired and Caddy is returning 502 upstream.

---

## 5. Out of scope (explicitly)

These were considered and rejected for this task:

- **Latency / response-time alerts.** The task is 5xx-only. Could be
  added later by sampling `time.monotonic()` around the probe and
  adding a `slow_threshold_s` to the config.
- **Per-endpoint monitoring.** `/healthz` is the right probe because
  it exercises the full API → DB stack. Other routes don't add
  signal.
- **Prometheus / Grafana integration.** Out of scope; would require
  a metrics endpoint and a scrape config.
- **Authenticated probes.** `/healthz` is unauthenticated by design
  (it's the load-balancer probe). No change needed.
- **4xx alerting.** Task explicitly says "focus is 5xx / outage
  detection". A 401 from `/healthz` would be a config error, not an
  outage.

---

## 6. Acceptance-criteria checklist

Mapping back to the task body:

- [x] Cron job runs every 5 minutes against `/healthz`. *(§3.2 crontab)*
- [x] State file persisted between invocations; deleting it re-arms.
      *(§2.3)*
- [x] Three consecutive non-200 responses trigger exactly one
      webhook. *(§2.2 + §2.4)*
- [x] Any single 200 between failures resets the counter and
      prevents an alert. *(§2.4 — tested live via the dry-run
      sequence in §7 below)*
- [x] After an alert, no further alerts fire until the counter is
      reset. *(§2.4 — marker file)*
- [x] Logs each check (timestamp, status code). *(§2.5 — every run
      appends to `/var/log/zorva-monitor.log`)*
- [x] Webhook destination configurable via env var
      (`ZORVA_MONITOR_WEBHOOK`). *(§3.3)*

---

## 7. Local verification (already done in this PR)

```bash
# 1. Happy path: real live URL, should be 200
./scripts/monitor_live_url.py --dry-run --verbose
# → 2026-06-24T15:29:10Z check ok status=200
# → consecutive_failures=0 threshold=3 alert_active=False → no alert

# 2. Failure path: point at a closed port, watch the counter climb
for i in 1 2 3 4 5; do
  ZORVA_MONITOR_URL=http://127.0.0.1:1/healthz \
  ZORVA_MONITOR_STATE_FILE=/tmp/m.json \
  ZORVA_MONITOR_LOG_FILE=/tmp/m.log \
  ZORVA_MONITOR_ALERT_DIR=/tmp \
    ./scripts/monitor_live_url.py --dry-run
done
# → call 1, 2: "consecutive=1/3", "consecutive=2/3" — no alert
# → call 3: ALERT firing, webhook payload printed, marker written
# → call 4, 5: counter still climbing, NO new alert (marker blocks)

# 3. Recovery path: switch back to the real URL, marker is cleared
ZORVA_MONITOR_URL=https://ai-billing-audit.ashbi.ca/healthz \
  ZORVA_MONITOR_STATE_FILE=/tmp/m.json \
  ZORVA_MONITOR_LOG_FILE=/tmp/m.log \
  ZORVA_MONITOR_ALERT_DIR=/tmp \
    ./scripts/monitor_live_url.py --dry-run
# → "RECOVERY: marker cleared" + "check ok status=200"
# → next failure starts at consecutive=1/3 (counter reset)
```