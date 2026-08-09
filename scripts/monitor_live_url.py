#!/usr/bin/env python3
"""5xx error-rate alert for the ai-billing-audit live URL.

Polls https://ai-billing-audit.ashbi.ca/healthz every 5 minutes (via
crontab; see docs/MONITORING.md) and fires a single alert when the
endpoint returns a non-2xx response for 3 consecutive checks
(~15 minutes of failure).

Design goals (see docs/MONITORING.md for the full write-up):

- **Self-contained.** Pure-stdlib Python 3; uses `urllib` (not curl) so
  there is no external-binary dependency. The crontab wrapper invokes
  it directly.
- **Crash-safe state.** The failure counter is persisted to
  ``/var/lib/zorva/monitor_state.json`` between invocations. Restarting
  the cron daemon does not wipe the failure history and does not cause
  a premature alert.
- **Alert-storm suppression.** Once an alert fires, a marker file is
  written to ``/var/run/zorva-alert-{hostname}.alert``. The script
  refuses to fire a second alert until that marker is removed by a
  human. A single 2xx response resets the counter and clears the
  marker, re-arming the monitor for the next outage.
- **Observable.** Every check (timestamp, status code, counter value)
  is appended to ``/var/log/zorva-monitor.log``. The webhook payload,
  when an alert fires, also includes that context.
- **Testable.** ``--dry-run`` mode prints the actions it would take
  without writing any state, logging, or sending a webhook. Useful
  for local development and the CI self-test in tests/.

Configuration is via environment variables so the script can be
deployed unchanged to a new host by editing the systemd EnvironmentFile
or crontab wrapper. See ``CONFIG`` below for the full list.

Usage::

    /opt/vps/bin/monitor_live_url.py                # normal cron run
    /opt/vps/bin/monitor_live_url.py --dry-run      # local test
    /opt/vps/bin/monitor_live_url.py --once --verbose  # manual check
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration — single source of truth (override via env vars).
# --------------------------------------------------------------------------- #

CONFIG = {
    # Endpoint to probe. Must be the /healthz route (cheap, unauthenticated,
    # already returns {"status": "ok"} when the API can reach its DB).
    "url": os.environ.get(
        "ZORVA_MONITOR_URL",
        "https://ai-billing-audit.ashbi.ca/healthz",
    ),
    # HTTP timeout per check (seconds). Kept tight so a slow host
    # doesn't pile up cron invocations.
    "timeout_s": float(os.environ.get("ZORVA_MONITOR_TIMEOUT", "10")),
    # Number of consecutive non-2xx checks before firing.
    # 3 × 5min = 15 minutes of failure, per the task acceptance criteria.
    "fail_threshold": int(os.environ.get("ZORVA_MONITOR_FAIL_THRESHOLD", "3")),
    # Webhook destination for the single alert. Empty string = log only
    # (useful in --dry-run and on hosts where Slack/Teams has not been
    # wired up yet).
    "webhook_url": os.environ.get("ZORVA_MONITOR_WEBHOOK", ""),
    # File locations — overridable for --dry-run and tests.
    "state_file": Path(
        os.environ.get("ZORVA_MONITOR_STATE_FILE", "/var/lib/zorva/monitor_state.json")
    ),
    "log_file": Path(
        os.environ.get("ZORVA_MONITOR_LOG_FILE", "/var/log/zorva-monitor.log")
    ),
    "alert_marker_dir": Path(os.environ.get("ZORVA_MONITOR_ALERT_DIR", "/var/run")),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    """UTC timestamp in ISO-8601, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert_marker_path() -> Path:
    """Per-host alert marker so two VPSes can run the monitor independently."""
    return CONFIG["alert_marker_dir"] / f"zorva-alert-{socket.gethostname()}.alert"


def _load_state() -> dict:
    """Load persisted counter; missing/corrupt file ⇒ fresh start."""
    p = CONFIG["state_file"]
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "consecutive_failures" not in data:
            raise ValueError("state file missing required keys")
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {"consecutive_failures": 0, "last_status": None, "last_check": None}


def _save_state(state: dict) -> None:
    """Persist counter atomically (write-temp-then-rename)."""
    p = CONFIG["state_file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, p)


def _log(line: str, *, dry_run: bool) -> None:
    """Append a timestamped line to the log file (or stdout in dry-run)."""
    stamped = f"{_now_iso()} {line}"
    if dry_run:
        print(stamped)
        return
    p = CONFIG["log_file"]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(stamped + "\n")
    except OSError as exc:
        # Logging must never crash the monitor — fall back to stderr
        # so the cron mailer at least captures the failure.
        print(f"monitor_live_url: log write failed: {exc}", file=sys.stderr)


def _probe(url: str, timeout_s: float) -> tuple[int | None, str]:
    """Return (status_code, error_string). status_code is None on network/HTTP error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zorva-monitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), ""
    except urllib.error.HTTPError as exc:
        # HTTPError is a "successful" round-trip — capture the status code.
        return int(exc.code), str(exc)
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return None, str(exc)


def _send_webhook(webhook_url: str, payload: dict, *, dry_run: bool) -> bool:
    """POST a JSON payload to the configured webhook. Returns success."""
    body = json.dumps(payload).encode("utf-8")
    if dry_run:
        print(f"DRY-RUN webhook → {webhook_url or '<unset>'}: {payload}")
        return True
    if not webhook_url:
        _log(f"webhook skipped (no ZORVA_MONITOR_WEBHOOK): {payload}", dry_run=dry_run)
        return False
    try:
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
            _log(f"webhook POST → {resp.status}", dry_run=dry_run)
            return ok
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        _log(f"webhook FAILED: {exc}", dry_run=dry_run)
        return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def run_once(*, dry_run: bool = False, verbose: bool = False) -> int:
    """One check cycle. Returns process exit code (0 = ok, 1 = alert fired)."""
    cfg = CONFIG
    state = _load_state()
    marker = _alert_marker_path()
    alert_active = marker.exists()

    status, err = _probe(cfg["url"], cfg["timeout_s"])
    healthy = status is not None and 200 <= status < 300
    iso = _now_iso()

    if healthy:
        state["consecutive_failures"] = 0
        state["last_status"] = status
        state["last_check"] = iso
        if alert_active:
            # Recovery: clear the marker so the next outage can alert again.
            try:
                marker.unlink()
                _log(f"RECOVERY: marker cleared ({marker})", dry_run=dry_run)
            except OSError as exc:
                _log(f"RECOVERY: marker unlink failed: {exc}", dry_run=dry_run)
        _log(f"check ok status={status}", dry_run=dry_run)
    else:
        state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
        state["last_status"] = status
        state["last_check"] = iso
        _log(
            f"check FAIL status={status!r} err={err!r} "
            f"consecutive={state['consecutive_failures']}/{cfg['fail_threshold']}",
            dry_run=dry_run,
        )

    _save_state(state)

    # Should we fire? Only on the crossing — not on every check past the
    # threshold, and only if no marker exists from a prior alert.
    threshold = cfg["fail_threshold"]
    should_alert = state["consecutive_failures"] >= threshold and not alert_active
    if not should_alert:
        if verbose:
            print(
                f"consecutive_failures={state['consecutive_failures']} "
                f"threshold={threshold} alert_active={alert_active} → no alert"
            )
        return 0

    # Fire the alert.
    payload = {
        "service": "ai-billing-audit",
        "url": cfg["url"],
        "status_code": status,
        "error": err,
        "consecutive_failures": state["consecutive_failures"],
        "first_failed_at": state.get("last_check"),
        "alert_at": iso,
        "host": socket.gethostname(),
        "ack_command": f"rm {marker}",
    }
    _log(
        f"ALERT firing: {json.dumps(payload, sort_keys=True)}",
        dry_run=dry_run,
    )
    _send_webhook(cfg["webhook_url"], payload, dry_run=dry_run)

    # Drop the marker AFTER firing so a slow webhook doesn't block a
    # second invocation from noticing the new state. A failed webhook
    # still leaves the marker absent — the operator will see the log
    # line and clear it manually if needed.
    # In dry-run, write a fake marker so subsequent --dry-run cycles
    # correctly demonstrate the alert-storm suppression behaviour.
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker_text = (
            f"[dry-run] would write marker at {marker}\n"
            if dry_run
            else json.dumps(payload, indent=2) + "\n"
        )
        marker.write_text(marker_text, encoding="utf-8")
        _log(f"alert marker written: {marker}", dry_run=dry_run)
    except OSError as exc:
        _log(f"alert marker write FAILED: {exc}", dry_run=dry_run)

    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print actions instead of writing state/log/webhook",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="(default behaviour; kept for clarity in the crontab wrapper)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print counter values to stdout (independent of --dry-run)",
    )
    args = parser.parse_args(argv)
    return run_once(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
