"""Tests for the industry baseline benchmark feature (kanban t_87fa8483).

What's pinned
-------------
1. **industry_baseline module unit tests** (no FastAPI):
   - ``known_metrics()`` returns the three spec'd metrics.
   - ``get_metric()`` returns the right row / None for unknown.
   - ``classify_value()`` produces the spec'd position strings
     across the boundary cases (below p50, between p50/p75,
     between p75/p90, above p90).
   - ``benchmark_payload()`` returns the spec'd shape with
     percentile_50/75/90 + clinic_value + position.
   - top_category includes ``category_breakdown`` for the UI.

2. **HTTP endpoint tests** (FastAPI TestClient):
   - GET with a known metric returns 200 with the benchmark
     payload (position, percentiles, source, last_updated).
   - GET with an unknown metric returns 400.
   - GET with a missing clinic_id (unknown) returns 404.
   - Window param respected (7d / 30d / 90d).
   - Windowed data: an encounter flagged in-window vs out-of-window
     changes the clinic_value.

No LLM, no network. Test logs redirected to tmp JSONL files.
"""
from __future__ import annotations

import importlib
import json
import sys
import time as time_mod
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit import api as api_mod  # noqa: E402
from ai_billing_audit import audit_actions as aa_mod  # noqa: E402
from ai_billing_audit import feedback as fb_mod  # noqa: E402
from ai_billing_audit import industry_baseline as ib_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect the audit + feedback logs to tmp files."""
    audit_log = tmp_path / "audit_trail.jsonl"
    feedback_log = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("FEEDBACK_LOG", str(feedback_log))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    importlib.reload(aa_mod)
    importlib.reload(fb_mod)
    importlib.reload(api_mod)
    yield {
        "audit_log": audit_log,
        "feedback_log": feedback_log,
    }


@pytest.fixture()
def client(fresh_logs) -> TestClient:
    return TestClient(api_mod.create_app())


def _iso(ts: float) -> str:
    return time_mod.strftime("%Y-%m-%dT%H:%M:%SZ", time_mod.gmtime(ts))


def _iso_dt(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _audit_row(
    *,
    encounter_id: str,
    finding_id: str | None = None,
    ts: float,
    action: str = "flag",
) -> dict:
    """Build one audit_actions row."""
    de: dict = {"encounter_id": encounter_id}
    if finding_id:
        de["finding_id"] = finding_id
        de["finding_ids"] = [finding_id]
    return {
        "event_id": f"ev-{encounter_id}-{finding_id or 'x'}",
        "timestamp": _iso(ts),
        "user_identifier": "test",
        "action": action,
        "tenant_id": "default",
        "data_elements": de,
    }


# ---------------------------------------------------------------------------
# 1. industry_baseline module unit tests
# ---------------------------------------------------------------------------


def test_known_metrics_includes_specd_three() -> None:
    metrics = ib_mod.known_metrics()
    assert "denial_rate" in metrics
    assert "time_to_act" in metrics
    assert "top_category" in metrics


def test_get_metric_returns_row_for_known() -> None:
    row = ib_mod.get_metric("denial_rate")
    assert row is not None
    assert row["percentile_50"] == 6.5
    assert row["percentile_75"] == 11.2
    assert row["percentile_90"] == 18.4
    assert row["source"] == "MGMA 2024"


def test_get_metric_returns_none_for_unknown() -> None:
    assert ib_mod.get_metric("not_a_real_metric") is None


def test_classify_value_below_p50() -> None:
    metric = ib_mod.get_metric("denial_rate")
    assert metric is not None
    assert ib_mod.classify_value(metric, 3.0) == "below p50"


def test_classify_value_between_p50_and_p75() -> None:
    metric = ib_mod.get_metric("denial_rate")
    assert metric is not None
    # 8.3 falls between 6.5 and 11.2
    assert ib_mod.classify_value(metric, 8.3) == "between p50 and p75"


def test_classify_value_between_p75_and_p90() -> None:
    metric = ib_mod.get_metric("denial_rate")
    assert metric is not None
    # 14.0 falls between 11.2 and 18.4
    assert ib_mod.classify_value(metric, 14.0) == "between p75 and p90"


def test_classify_value_above_p90() -> None:
    metric = ib_mod.get_metric("denial_rate")
    assert metric is not None
    assert ib_mod.classify_value(metric, 25.0) == "above p90"


def test_classify_value_boundary_equality_is_below_p50() -> None:
    """A value exactly equal to p50 falls in the "below p50" bucket
    (the spec phrasing is "below p50" inclusive of the median)."""
    metric = ib_mod.get_metric("denial_rate")
    assert metric is not None
    assert ib_mod.classify_value(metric, metric["percentile_50"]) == "below p50"


def test_classify_value_top_category_returns_unknown() -> None:
    """top_category has no percentile keys → returns 'unknown'."""
    metric = ib_mod.get_metric("top_category")
    assert metric is not None
    assert ib_mod.classify_value(metric, 50.0) == "unknown"


def test_benchmark_payload_shape_for_denial_rate() -> None:
    payload = ib_mod.benchmark_payload("denial_rate", 8.3)
    assert payload is not None
    assert payload["metric"] == "denial_rate"
    assert payload["clinic_value"] == 8.3
    assert payload["percentile_50"] == 6.5
    assert payload["percentile_75"] == 11.2
    assert payload["percentile_90"] == 18.4
    assert payload["position"] == "between p50 and p75"
    assert payload["lower_is_better"] is True
    assert payload["source"] == "MGMA 2024"
    assert payload["last_updated"] == ib_mod.SNAPSHOT_LAST_UPDATED
    assert "disclaimer" in payload


def test_benchmark_payload_for_top_category_includes_breakdown() -> None:
    payload = ib_mod.benchmark_payload("top_category", 62.0)
    assert payload is not None
    assert "category_breakdown" in payload
    assert payload["category_breakdown"]["dx_linkage"] == 62.0
    # position is unknown for categorical metric
    assert payload["position"] == "unknown"


def test_benchmark_payload_returns_none_for_unknown_metric() -> None:
    assert ib_mod.benchmark_payload("nope", 10.0) is None


# ---------------------------------------------------------------------------
# 2. HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_benchmark_known_metric_returns_position_and_percentiles(
    client: TestClient,
) -> None:
    """Known metric → 200 with the spec'd payload shape.

    With no audit log data, clinic_value=0.0 → falls "below p50"
    (lower-is-better: a 0% denial rate is best-possible).
    """
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark?metric=denial_rate"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metric"] == "denial_rate"
    assert body["metric_label"] == "Denial rate"
    assert body["unit"] == "pct"
    assert body["percentile_50"] == 6.5
    assert body["percentile_75"] == 11.2
    assert body["percentile_90"] == 18.4
    assert body["position"] == "below p50"  # 0% denial = best
    assert body["lower_is_better"] is True
    assert body["source"] == "MGMA 2024"
    assert "disclaimer" in body
    assert body["clinic_id"] == "default_biller"


def test_benchmark_unknown_metric_returns_400(
    client: TestClient,
) -> None:
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark?metric=not_a_metric"
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "not_a_metric" in detail
    # Error should hint at the known metrics
    assert "denial_rate" in detail


def test_benchmark_missing_metric_returns_400(
    client: TestClient,
) -> None:
    """No metric param → 400 (the endpoint requires it)."""
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark"
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "metric required" in detail


def test_benchmark_unknown_clinic_returns_404(
    client: TestClient,
) -> None:
    r = client.get(
        "/api/dashboard/clinic/does-not-exist-zzz/benchmark?metric=denial_rate"
    )
    assert r.status_code == 404
    assert "does-not-exist-zzz" in r.json()["detail"]


def test_benchmark_window_param_accepted(
    client: TestClient,
) -> None:
    """window=7d / 30d / 90d are all accepted; out-of-set → 30d."""
    for w in ("7d", "30d", "90d"):
        r = client.get(
            f"/api/dashboard/clinic/default_biller/benchmark"
            f"?metric=denial_rate&window={w}"
        )
        assert r.status_code == 200, r.text
        assert r.json()["window_days"] == int(w.rstrip("d"))
    # Out-of-set clamps to 30d
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark"
        "?metric=denial_rate&window=42d"
    )
    assert r.status_code == 200
    assert r.json()["window_days"] == 30


def test_benchmark_windowed_data_changes_clinic_value(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """An encounter flagged inside the 7d window counts toward the
    denial rate; an encounter flagged outside the window doesn't.

    We write 2 audit rows: one in-window, one out-of-window. With
    7d window the in-window row contributes to the rate; with 90d
    both rows do, so the rate changes.
    """
    now = time_mod.time()
    in_window = now - 86400        # 1d ago
    out_window = now - 60 * 86400  # 60d ago

    rows = [
        _audit_row(encounter_id="enc_in", finding_id="f_1", ts=in_window, action="flag"),
        _audit_row(encounter_id="enc_out", finding_id="f_1", ts=out_window, action="flag"),
        _audit_row(encounter_id="enc_clean", finding_id="f_1", ts=in_window, action="append"),
    ]
    _write_jsonl(fresh_logs["audit_log"], rows)

    # 7d window: 1 of 2 in-window encounters is flagged → 50%
    r7 = client.get(
        "/api/dashboard/clinic/default_biller/benchmark"
        "?metric=denial_rate&window=7d"
    )
    assert r7.status_code == 200, r7.text
    assert r7.json()["clinic_value"] == 50.0

    # 90d window: 2 of 3 encounters flagged → 66.67%
    r90 = client.get(
        "/api/dashboard/clinic/default_biller/benchmark"
        "?metric=denial_rate&window=90d"
    )
    assert r90.status_code == 200, r90.text
    assert abs(r90.json()["clinic_value"] - 66.67) < 0.01


def test_benchmark_time_to_act_metric_works(
    client: TestClient, fresh_logs: dict[str, Path]
) -> None:
    """time_to_act returns 200 with the right shape, even with
    no data (clinic_value=0.0 → below p50)."""
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark?metric=time_to_act"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metric"] == "time_to_act"
    assert body["unit"] == "hours"
    assert body["percentile_50"] == 4.2
    assert body["percentile_75"] == 11.7
    assert body["percentile_90"] == 24.3
    assert body["source"] == "HFMA 2024"
    assert body["position"] == "below p50"


def test_benchmark_top_category_returns_breakdown(
    client: TestClient,
) -> None:
    r = client.get(
        "/api/dashboard/clinic/default_biller/benchmark?metric=top_category"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metric"] == "top_category"
    assert "category_breakdown" in body
    assert body["category_breakdown"]["dx_linkage"] == 62.0
    assert body["category_breakdown"]["modifier_25"] == 54.0
    assert body["category_breakdown"]["em_level"] == 48.0