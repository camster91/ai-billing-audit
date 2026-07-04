"""Tests for ``/metrics`` (Prometheus text exposition) + the
metrics module counters.

The ``/metrics`` endpoint is on the public-read whitelist so
Prometheus can scrape without a bearer token. Exposed metrics:

  * ``zorva_uptime_seconds`` — gauge, process uptime
  * ``zorva_version_info{version=...}`` — constant 1
  * ``zorva_audit_jobs_total{state=...}`` — gauge per job state
  * ``zorva_http_requests_total{path,method,status}`` — counter

These tests pin:

1. The endpoint returns 200 with the Prometheus media type.
2. The body contains the standard ``# HELP`` / ``# TYPE`` lines.
3. The HTTP counter is bumped by the middleware on each request.
4. The /metrics endpoint itself does NOT bump its own counter
   (a scrape shouldn't inflate the rate).
5. Per-route counters stay separate (counter for /healthz doesn't
   bleed into /roi).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient with fresh metrics state."""
    import ai_billing_audit.api as api_mod
    from fastapi.testclient import TestClient
    # Reset the http counter + rate-limit state for clean isolation
    if hasattr(api_mod, "_rate_limit_state"):
        api_mod._rate_limit_state.clear()
    from ai_billing_audit import metrics
    metrics._HTTP_COUNTER.clear()
    return TestClient(api_mod.create_app())


def test_metrics_endpoint_returns_200_with_prometheus_media_type(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")


def test_metrics_body_contains_help_and_type_lines(client):
    r = client.get("/metrics")
    body = r.text
    # Standard Prometheus exposition comments
    assert re.search(r"^# HELP zorva_uptime_seconds ", body, re.MULTILINE)
    assert re.search(r"^# TYPE zorva_uptime_seconds gauge", body, re.MULTILINE)
    assert re.search(r"^# HELP zorva_version_info ", body, re.MULTILINE)
    assert re.search(r"^# TYPE zorva_version_info gauge", body, re.MULTILINE)


def test_metrics_body_includes_current_version(client):
    r = client.get("/metrics")
    # The version gauge should be 1 with the current version string
    from ai_billing_audit import __version__
    expected_line = f'zorva_version_info{{version="{__version__}"}} 1'
    assert expected_line in r.text


def test_metrics_uptime_increases_between_requests(client):
    """The uptime gauge is monotonically increasing across scrapes."""
    r1 = client.get("/metrics")
    import time as _time
    _time.sleep(0.05)
    r2 = client.get("/metrics")
    m1 = re.search(r"zorva_uptime_seconds ([\d.]+)", r1.text)
    m2 = re.search(r"zorva_uptime_seconds ([\d.]+)", r2.text)
    assert m1 is not None and m2 is not None
    assert float(m2.group(1)) > float(m1.group(1))


def test_http_request_counter_bumped_on_healthz(client):
    """Hitting /healthz twice bumps the counter for /healthz+GET+200."""
    from ai_billing_audit import metrics

    client.get("/healthz")
    client.get("/healthz")
    r = client.get("/metrics")
    # Find the counter line for /healthz GET 200
    pattern = r'zorva_http_requests_total\{path="/healthz",method="GET",status="200"\} (\d+)'
    m = re.search(pattern, r.text)
    assert m is not None, f"missing counter for /healthz GET 200; body:\n{r.text}"
    assert int(m.group(1)) >= 2


def test_metrics_endpoint_does_not_bump_its_own_counter(client):
    """Scraping /metrics must not increment the /metrics counter."""
    from ai_billing_audit import metrics

    initial = metrics._HTTP_COUNTER.copy()
    client.get("/metrics")
    # No entry for /metrics should have been added
    for key in metrics._HTTP_COUNTER:
        assert key[0] != "/metrics", (
            f"/metrics scrape bumped its own counter: {key}"
        )
    # And the snapshot we took before should match exactly
    assert set(metrics._HTTP_COUNTER.keys()) == set(initial.keys())


def test_per_route_counters_are_independent(client):
    """Hitting /healthz doesn't bump the /roi counter."""
    from ai_billing_audit import metrics

    client.get("/healthz")
    r = client.get("/metrics")
    assert 'path="/healthz"' in r.text
    # /roi counter may or may not exist depending on prior tests,
    # but if it does, it must be 0 (we never called /roi).
    m = re.search(
        r'zorva_http_requests_total\{path="/roi",method="GET",status="200"\} (\d+)',
        r.text,
    )
    if m:
        assert int(m.group(1)) == 0


def test_status_label_distinguishes_200_from_404(client):
    """404 hits should be tracked separately from 200."""
    client.get("/healthz")  # 200
    client.get("/nonexistent-route-xyz")  # 404
    r = client.get("/metrics")
    assert 'path="/healthz",method="GET",status="200"' in r.text
    assert 'path="/nonexistent-route-xyz",method="GET",status="404"' in r.text


def test_bump_http_request_increments_counter():
    from ai_billing_audit import metrics

    metrics._HTTP_COUNTER.clear()
    metrics.bump_http_request("/foo", "GET", 200)
    metrics.bump_http_request("/foo", "GET", 200)
    metrics.bump_http_request("/foo", "POST", 201)
    assert metrics._HTTP_COUNTER[("/foo", "GET", 200)] == 2
    assert metrics._HTTP_COUNTER[("/foo", "POST", 201)] == 1


def test_render_metrics_returns_string(client):
    """render_metrics is the export function; it should always
    return a non-empty string regardless of process state."""
    from ai_billing_audit.metrics import render_metrics
    out = render_metrics()
    assert isinstance(out, str)
    assert "zorva_uptime_seconds" in out