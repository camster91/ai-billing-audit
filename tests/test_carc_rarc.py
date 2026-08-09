"""Tests for the CARC / RARC lookup feature (kanban t_7743e5d5).

What's pinned
-------------
1. **Module unit tests** (no FastAPI):
   - `lookup_carc("16")` returns the description row.
   - `lookup_carc("B12")` returns a Medicare-specific row.
   - `lookup_carc("ZZZ")` returns None for unknown code.
   - `lookup_rarc("M1")` returns the description row.
   - `lookup_rarc("N3")` returns a known remark code.
   - `lookup_rarc("ZZZ")` returns None for unknown code.
   - `table_stats` reports non-zero counts for both.
   - CSV has at least 50 rows for each code set (the task
     spec: "Include the most common 100 codes (~50 CARC +
     ~50 RARC)").

2. **HTTP endpoint tests** (FastAPI TestClient):
   - GET /api/lookup/carc/{code} returns the row.
   - GET /api/lookup/carc/UNKNOWN returns 404.
   - GET /api/lookup/rarc/{code} returns the row.
   - GET /api/lookup/rarc/UNKNOWN returns 404.
   - GET /api/lookup/stats returns counts.

No LLM, no network. The CSVs come from the repo at
``data/tables/{carc,rarc}.csv``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit import api as api_mod  # noqa: E402
from ai_billing_audit import carc_rarc as cr_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Minimal env so api.create_app() doesn't blow up on missing logs."""
    audit_log = tmp_path / "audit_trail.jsonl"
    snooze_log = tmp_path / "snoozes.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(audit_log))
    monkeypatch.setenv("SNOOZE_LOG", str(snooze_log))
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    importlib.reload(api_mod)
    # Reset the CARC/RARC cache so it picks up the real
    # data/tables/*.csv that the test session was started with.
    cr_mod.reset_cache()
    yield {
        "audit_log": audit_log,
        "snooze_log": snooze_log,
    }


@pytest.fixture()
def client(fresh_logs) -> TestClient:
    return TestClient(api_mod.create_app())


# ---------------------------------------------------------------------------
# 1. Module unit tests
# ---------------------------------------------------------------------------


def test_lookup_carc_known_code(fresh_logs) -> None:
    """CARC 16 (missing info) returns the seeded description."""
    entry = cr_mod.lookup_carc("16")
    assert entry is not None
    assert entry.code == "16"
    assert "lacks information" in entry.description.lower()
    assert "resubmit" in " ".join(entry.common_resolutions).lower()


def test_lookup_carc_medicare_specific(fresh_logs) -> None:
    """CARC B12 is a Medicare 'not reasonable/necessary' code."""
    entry = cr_mod.lookup_carc("B12")
    assert entry is not None
    assert "Medicare" in entry.payer_types


def test_lookup_carc_unknown_returns_none(fresh_logs) -> None:
    """An unknown CARC code returns None, not a stub."""
    assert cr_mod.lookup_carc("ZZZ_999") is None
    assert cr_mod.lookup_carc("") is None
    assert cr_mod.lookup_carc("not-a-code") is None


def test_lookup_rarc_known_code(fresh_logs) -> None:
    """RARC M1 is 'x-ray not taken within past 12 months'."""
    entry = cr_mod.lookup_rarc("M1")
    assert entry is not None
    assert entry.code == "M1"
    assert "x-ray" in entry.description.lower()


def test_lookup_rarc_n_code(fresh_logs) -> None:
    """RARC N3 is 'alert: please submit medical records'."""
    entry = cr_mod.lookup_rarc("N3")
    assert entry is not None
    assert "medical records" in entry.description.lower()


def test_lookup_rarc_unknown_returns_none(fresh_logs) -> None:
    """Unknown RARC code returns None."""
    assert cr_mod.lookup_rarc("ZZZ_999") is None
    assert cr_mod.lookup_rarc("") is None


def test_table_stats_nonzero(fresh_logs) -> None:
    """Both code sets should have at least 50 rows each."""
    stats = cr_mod.table_stats()
    assert stats["carc_count"] >= 50, f"only {stats['carc_count']} CARC codes"
    assert stats["rarc_count"] >= 50, f"only {stats['rarc_count']} RARC codes"


def test_csv_files_have_minimum_rows() -> None:
    """The CSV files themselves contain at least 50 data rows each."""
    carc_path = PROJECT_ROOT / "data" / "tables" / "carc.csv"
    rarc_path = PROJECT_ROOT / "data" / "tables" / "rarc.csv"
    assert carc_path.is_file(), f"missing {carc_path}"
    assert rarc_path.is_file(), f"missing {rarc_path}"
    carc_lines = [line for line in carc_path.read_text().splitlines() if line.strip()]
    rarc_lines = [line for line in rarc_path.read_text().splitlines() if line.strip()]
    # Header + N data rows.
    assert len(carc_lines) >= 51, f"carc.csv has only {len(carc_lines) - 1} data rows"
    assert len(rarc_lines) >= 51, f"rarc.csv has only {len(rarc_lines) - 1} data rows"


def test_lookup_returns_dict_shape(fresh_logs) -> None:
    """to_dict() includes all four fields."""
    entry = cr_mod.lookup_carc("16")
    assert entry is not None
    d = entry.to_dict()
    assert set(d.keys()) == {
        "code",
        "description",
        "payer_types",
        "common_resolutions",
    }
    assert isinstance(d["payer_types"], list)
    assert isinstance(d["common_resolutions"], list)


# ---------------------------------------------------------------------------
# 2. HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_http_lookup_carc_known(client: TestClient) -> None:
    """GET /api/lookup/carc/16 returns the row."""
    resp = client.get("/api/lookup/carc/16")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "16"
    assert "lacks information" in body["description"].lower()
    assert isinstance(body["payer_types"], list)


def test_http_lookup_carc_unknown_returns_404(client: TestClient) -> None:
    """GET /api/lookup/carc/ZZZ returns 404, not 200-with-null."""
    resp = client.get("/api/lookup/carc/ZZZ_NOT_REAL")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_http_lookup_rarc_known(client: TestClient) -> None:
    """GET /api/lookup/rarc/M1 returns the row."""
    resp = client.get("/api/lookup/rarc/M1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "M1"
    assert "x-ray" in body["description"].lower()


def test_http_lookup_rarc_unknown_returns_404(client: TestClient) -> None:
    """GET /api/lookup/rarc/ZZZ returns 404."""
    resp = client.get("/api/lookup/rarc/ZZZ_NOT_REAL")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_http_lookup_stats(client: TestClient) -> None:
    """GET /api/lookup/stats returns non-zero counts."""
    resp = client.get("/api/lookup/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["carc_count"] >= 50
    assert body["rarc_count"] >= 50
