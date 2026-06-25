"""Tests for audit_depth module (kanban t_e2c5afab)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_billing_audit import audit_depth as ad


def test_default_depth_is_standard():
    assert ad.DEFAULT_DEPTH == 2


def test_model_for_depth_each_level():
    assert ad.model_for_depth(1) == "claude-haiku-4-5"
    assert ad.model_for_depth(2) == "claude-sonnet-4-5"
    assert ad.model_for_depth(3) == "claude-opus-4-1"


def test_invalid_depth_raises():
    with pytest.raises(ValueError):
        ad.model_for_depth(0)
    with pytest.raises(ValueError):
        ad.model_for_depth(4)
    with pytest.raises(ValueError):
        ad.model_for_depth("deep")  # type: ignore[arg-type]


def test_depth_metadata_shape():
    for d in (1, 2, 3):
        meta = ad.depth_metadata(d)
        assert "model" in meta
        assert "uses_rag" in meta
        assert "uses_chain_of_thought" in meta
        assert "approx_latency_s" in meta
        assert "cost_per_million_tokens_usd" in meta
        assert "description" in meta
    # Deep MUST use chain-of-thought + rag
    deep = ad.depth_metadata(3)
    assert deep["uses_chain_of_thought"] is True
    assert deep["uses_rag"] is True
    # Quick MUST NOT use either
    quick = ad.depth_metadata(1)
    assert quick["uses_chain_of_thought"] is False
    assert quick["uses_rag"] is False


def test_cost_estimate_zero_tokens():
    assert ad.cost_estimate_usd(1, 0) == 0.0
    assert ad.cost_estimate_usd(3, 0) == 0.0


def test_cost_estimate_scales_linearly():
    a = ad.cost_estimate_usd(2, 1000)
    b = ad.cost_estimate_usd(2, 2000)
    c = ad.cost_estimate_usd(2, 4000)
    # Same depth, so rates match
    assert b == pytest.approx(a * 2, rel=1e-6)
    assert c == pytest.approx(a * 4, rel=1e-6)


def test_cost_estimate_deep_is_most_expensive():
    # Same tokens, deep should cost the most.
    cheap = ad.cost_estimate_usd(1, 100_000)
    mid = ad.cost_estimate_usd(2, 100_000)
    deep = ad.cost_estimate_usd(3, 100_000)
    assert cheap < mid < deep


def test_audit_depth_for_claim_override_wins():
    cfg = ad.audit_depth_for(
        tenant_id="t1",
        claim_id="c1",
        claim_override=3,
        tenant_default=2,
    )
    assert cfg.depth == 3
    assert cfg.source == "claim_override"
    assert cfg.model == "claude-opus-4-1"


def test_audit_depth_for_tenant_default_used_when_no_override():
    cfg = ad.audit_depth_for(
        tenant_id="t1",
        claim_id="c1",
        claim_override=None,
        tenant_default=1,
    )
    assert cfg.depth == 1
    assert cfg.source == "tenant_default"
    assert cfg.model == "claude-haiku-4-5"


def test_audit_depth_for_global_default_fallback():
    cfg = ad.audit_depth_for(tenant_id="t1", claim_id="c1")
    assert cfg.depth == ad.DEFAULT_DEPTH
    assert cfg.source == "global_default"
    assert cfg.model == ad.model_for_depth(ad.DEFAULT_DEPTH)


def test_audit_depth_for_invalid_override_raises():
    with pytest.raises(ValueError):
        ad.audit_depth_for(tenant_id="t", claim_id="c", claim_override=99)


def test_audit_depth_config_includes_cost():
    cfg = ad.audit_depth_for(tenant_id="t1", claim_id="c1", n_tokens_estimate=50_000)
    assert cfg.cost_estimate_usd > 0
    # 50k tokens at depth 2 should cost 0.45 USD (9.00 / 1M * 50k)
    assert cfg.cost_estimate_usd == pytest.approx(0.45, rel=1e-6)


def test_save_and_load_tenant_default(tmp_path: Path, monkeypatch):
    log = tmp_path / "depth.jsonl"
    monkeypatch.setenv("TENANT_AUDIT_DEPTH_LOG", str(log))

    assert ad.load_tenant_default("clinic_a", log_path=log) == ad.DEFAULT_DEPTH
    ad.save_tenant_default("clinic_a", 3)
    assert ad.load_tenant_default("clinic_a", log_path=log) == 3

    # Latest write wins
    ad.save_tenant_default("clinic_a", 1)
    assert ad.load_tenant_default("clinic_a", log_path=log) == 1

    # Tenant isolation
    assert ad.load_tenant_default("clinic_b", log_path=log) == ad.DEFAULT_DEPTH


def test_save_tenant_default_validates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENANT_AUDIT_DEPTH_LOG", str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        ad.save_tenant_default("clinic_a", 99)


def test_load_default_config_returns_all_tenants(tmp_path: Path, monkeypatch):
    log = tmp_path / "depth.jsonl"
    monkeypatch.setenv("TENANT_AUDIT_DEPTH_LOG", str(log))
    ad.save_tenant_default("clinic_a", 3)
    ad.save_tenant_default("clinic_b", 1)
    cfg = ad.load_default_config(log_path=log)
    assert cfg == {"clinic_a": 3, "clinic_b": 1}


def test_save_tenant_default_signature_chain(tmp_path: Path, monkeypatch):
    log = tmp_path / "depth.jsonl"
    monkeypatch.setenv("TENANT_AUDIT_DEPTH_LOG", str(log))
    ad.save_tenant_default("clinic_a", 2)
    ad.save_tenant_default("clinic_b", 3)
    rows = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(rows) == 2
    assert rows[0]["previous_signature"] == "0" * 64
    assert rows[1]["previous_signature"] == rows[0]["cryptographic_signature"]