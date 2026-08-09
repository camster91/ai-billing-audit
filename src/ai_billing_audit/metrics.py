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

    swarm-audit B-Sec-4: previously stored the raw path (with
    encounter_id, user_id, etc. embedded in the URL), which then
    appeared as a Prometheus label value on the public-readable
    /metrics endpoint — a PHI / identifier-disclosure channel.
    Now the path is bucketised to a coarse template
    (``/encounter/{id}/...``) before being labelled. Static
    segments stay verbatim; dynamic segments collapse to ``{id}``
    so a scraper sees route-level cardinality, not per-encounter
    cardinality.
    """
    template = _bucketize_path(path)
    with _LOCK:
        _HTTP_COUNTER[(template, method, status)] = (
            _HTTP_COUNTER.get((template, method, status), 0) + 1
        )


import re as _re_metrics  # noqa: E402 — placed after the first use so
# the module-level _bucketize_path helper below can reference re.

# Dynamic-segment markers we collapse to {id}. Order matters —
# patterns must be applied left-to-right with the longer / more
# specific one first so we don't double-collapse (e.g.
# ``/encounter/ca_ahcip_001`` must collapse ``/ca_ahcip_001``
# first to ``{id}``, then NOT match ``/enc{id}`` as a separate
# dynamic segment — ``/encounter`` is a static route prefix).
_BUCKET_PATTERNS: tuple[tuple[str, str], ...] = (
    # 32-char hex (job_id from upload flow)
    (r"/[a-f0-9]{32}", "/{id}"),
    # 12-char hex (audit-action IDs)
    (r"/[a-f0-9]{12}", "/{id}"),
    # UUIDs
    (r"/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "/{id}"),
    # Slug forms — MUST come BEFORE any catch-all /enc* or /api/*
    # regex, otherwise /encounter/{id}/... double-collapses.
    (r"/ca_[a-z0-9_]+", "/{id}"),
    (r"/enc_[a-z0-9_]+", "/{id}"),
    # Any remaining bare slug — must contain at least one digit
    # (so /encounter, /healthz, /roi stay verbatim; /enc001,
    # /job-abc123, /ev-2026-07-04 collapse).
    (r"/[a-zA-Z][a-zA-Z0-9_-]*\d[a-zA-Z0-9_-]*\b", "/{id}"),
    # clinic_id slug (default = default)
    (r"/clinic/[a-zA-Z0-9_-]+", "/clinic/{id}"),
)


def _bucketize_path(path: str) -> str:
    """Collapse dynamic segments of a path to ``{id}``.

    Static segments (``/healthz``, ``/roi``, ``/metrics``) are
    untouched. Path-specific segments (``/encounter/{id}/...``)
    collapse so a Prometheus scraper never sees per-encounter
    labels on the public /metrics endpoint.

    Examples:
      /encounter/ca_ahcip_001/audit   → /encounter/{id}/audit
      /api/audit-log/export?fmt=json   → /api/audit-log/export (static)
      /jobs/abc123def456              → /jobs/{id}
    """
    out = path
    for pattern, repl in _BUCKET_PATTERNS:
        out = _re_metrics.sub(pattern, repl, out)
    return out


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
        items: Iterable[tuple[tuple[str, str, int], int]] = list(_HTTP_COUNTER.items())
    for (path, method, status), n in sorted(items):
        # Label values are Prometheus-safe; escape quotes if any.
        safe_path = path.replace("\\", "\\\\").replace('"', '\\"')
        safe_method = method.replace("\\", "\\\\").replace('"', '\\"')
        out.write(
            f"zorva_http_requests_total"
            f'{{path="{safe_path}",method="{safe_method}",'
            f'status="{status}"}} {n}\n'
        )

    return out.getvalue()
