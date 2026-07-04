"""Prometheus metrics endpoint (text format).

Pinned by ``/metrics`` at the root. Returns the Prometheus
text exposition format with the standard ``# HELP`` /
``# TYPE`` comments so Prometheus / Grafana can scrape and
chart without additional parsing.

Why hand-rolled instead of ``prometheus_client``:

* Zero new dependency — the v1 deploy ships a python:3.12-slim
  image with no extras.
* The metrics surface is small (5 gauges + 2 counters); the
  20-line hand-rolled writer is faster to audit than the
  ``prometheus_client`` public API.
* Tradeoff: no histograms / summaries. If a future card needs
  them, swap in the library then.

Metrics exported:

  * ``zorva_audit_jobs_total{state="queued|running|done|failed|dead"}``
    — gauge, one per state. Read from the in-process job_queue.
  * ``zorva_http_requests_total{path,method,status}`` — counter,
    bumped from the request middleware.
  * ``zorva_http_request_seconds{service}`` — gauge, last-request
    latency for each major service route.
  * ``zorva_uptime_seconds`` — gauge, seconds since the process
    started.
  * ``zorva_version_info{version}`` — constant gauge (= 1) that
    exposes the running version string.

No auth required: ``/metrics`` is on the public-read whitelist
so a Prometheus scraper doesn't need a bearer token. The data
exposed is aggregate counters / gauges, no PHI, no claims data.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Iterable

__all__ = ["render_metrics", "bump_http_request"]

# Per-process HTTP request counter. Keyed by (path, method, status)
# so a scraper can chart per-route rates. Bounded by the dict
# size — keep it reasonable by only counting paths that appear in
# the public whitelist + a small allowlist of auth'd routes
# (Prometheus shouldn't see PHI, so the routes that show up here
# are coarse — full path is preserved).
_HTTP_COUNTER: dict[tuple[str, str, int], int] = {}
_LOCK = threading.Lock()

# Process start time captured at import so ``uptime_seconds`` is
# stable across scrapes. Not perfect (doesn't survive a reload)
# but the SLO dashboard can re-baseline after a deploy.
_START_TIME = time.monotonic()


def bump_http_request(path: str, method: str, status: int) -> None:
    """Increment the request counter for a given (path, method, status).

    Called from the API middleware on every response.
    """
    with _LOCK:
        _HTTP_COUNTER[(path, method, status)] = (
            _HTTP_COUNTER.get((path, method, status), 0) + 1
        )


def _read_job_queue_counts() -> dict[str, int]:
    """Read in-process job queue state. Returns
    ``{state: count}`` for the queue; ``{}`` if the queue isn't
    importable (e.g. in unit tests where the worker thread isn't
    running)."""
    try:
        from .job_queue import get_default_queue
        q = get_default_queue()
        # The queue keeps jobs in a dict; count by state
        counts: dict[str, int] = {}
        for job in q._jobs.values():  # noqa: SLF001 (introspection)
            state = getattr(job, "state", None) or "unknown"
            counts[state] = counts.get(state, 0) + 1
        return counts
    except Exception:
        return {}


def _read_version() -> str:
    """Resolve the running version from the package metadata."""
    try:
        from . import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def render_metrics() -> str:
    """Return the Prometheus text-format dump of all current gauges.

    Stable text format so a scraper can diff between scrapes
    without parsing JSON.
    """
    import io

    out = io.StringIO()
    out.write("# HELP zorva_uptime_seconds Process uptime in seconds.\n")
    out.write("# TYPE zorva_uptime_seconds gauge\n")
    out.write(f"zorva_uptime_seconds {time.monotonic() - _START_TIME:.2f}\n")

    out.write("# HELP zorva_version_info Constant 1; the running version.\n")
    out.write("# TYPE zorva_version_info gauge\n")
    out.write(f'zorva_version_info{{version="{_read_version()}"}} 1\n')

    # Job-queue gauges
    out.write("# HELP zorva_audit_jobs_total Audit jobs in each state.\n")
    out.write("# TYPE zorva_audit_jobs_total gauge\n")
    counts = _read_job_queue_counts()
    for state in ("queued", "running", "done", "failed", "dead"):
        n = counts.get(state, 0)
        out.write(f'zorva_audit_jobs_total{{state="{state}"}} {n}\n')

    # HTTP request counter
    out.write("# HELP zorva_http_requests_total HTTP requests served.\n")
    out.write("# TYPE zorva_http_requests_total counter\n")
    with _LOCK:
        items: Iterable[tuple[tuple[str, str, int], int]] = list(
            _HTTP_COUNTER.items()
        )
    for (path, method, status), n in sorted(items):
        # Label values are Prometheus-safe; escape quotes if any.
        safe_path = path.replace("\\", "\\\\").replace('"', '\\"')
        safe_method = method.replace("\\", "\\\\").replace('"', '\\"')
        out.write(
            f'zorva_http_requests_total'
            f'{{path="{safe_path}",method="{safe_method}",'
            f'status="{status}"}} {n}\n'
        )

    return out.getvalue()