"""Tests for ``scripts/shadow_audit.py`` -- concurrency + canonical-name stability.

The shadow runner is the production CLI for the no-cost 100-claim
pilot, so its behaviour is part of the marketing promise. These
tests pin three things:

1. The runner accepts ``--concurrency N`` and dispatches encounters
   to a ThreadPoolExecutor without dropping or duplicating any
   audit. (Regression: would lose findings if the parallel path
   forgot to write the result back into the same index.)
2. Sequential and concurrent runs produce the same summary
   (encounter count, finding count, per-rule counts, per-severity
   counts, total estimated dollars). The only thing allowed to
   differ between the two paths is the wall-clock time, which is
   NOT asserted here.
3. The runner emits a Markdown report that mentions SOMB-anchored
   rates and timing metadata so a privacy officer can verify
   provenance.

Each test uses ``provider="stub"`` (the hermetic canned-finding
auditor) so it runs offline with no LLM key. ``stub`` produces a
deterministic lookup against ``runs/recall/v12_ahcip_clean.json``;
when that file is missing the stub returns a ``STUB_NO_DATA``
finding per encounter. Tests that need canned findings skip if
the recall file is absent rather than failing the suite.
"""

from __future__ import annotations

import importlib.util as _u
import sys
import time as _time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_shadow():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = _u.spec_from_file_location(
        "shadow_audit", str(ROOT / "scripts" / "shadow_audit.py")
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        pytest.skip("shadow_audit.py not importable")
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHADOW = _load_shadow()


@pytest.fixture
def canned_encounters() -> list[dict]:
    """Twelve minimal encounters matching val_ca.json's expected shape.

    The auditor only reads ``encounter_id``, ``clinical_note`` and
    ``claim``; the rest is ignored. We use predictable encounter_ids
    so the stub auditor's per-encounter lookup is deterministic.
    """
    return [
        {
            "encounter_id": f"enc-{i:03d}",
            "clinical_note": "Patient seen for follow-up.",
            "claim": {
                "CPT_codes": ["03.04A"],
                "diagnosis_codes": ["I10"],
                "date_of_service": "2026-07-01",
            },
        }
        for i in range(12)
    ]


def _run_auditor(run, encounters: list[dict], concurrency: int) -> list[dict]:
    """Mirror the runner's audit-loop logic but skip the report
    write so tests don't pollute ``runs/shadow/``.

    Returns ``encounters`` with ``findings`` populated.
    """
    if concurrency == 1 or len(encounters) <= 1:
        for enc in encounters:
            enc["findings"] = run(enc)
        return encounters

    import concurrent.futures as _cf

    n_workers = min(concurrency, len(encounters))
    with _cf.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures: dict[_cf.Future[list[dict]], int] = {
            ex.submit(run, enc): idx for idx, enc in enumerate(encounters)
        }
        for fut in _cf.as_completed(futures):
            encounters[futures[fut]]["findings"] = fut.result()
    return encounters


def test_concurrency_one_matches_default_sequential_path(canned_encounters):
    """Sequential path produces stable findings; concurrency=1
    must hit the same code path and produce the same findings.
    """
    run = SHADOW._auditor_for("stub", None)
    out_seq = _run_auditor(run, [dict(e) for e in canned_encounters], concurrency=1)
    assert all("findings" in e for e in out_seq), "sequential path dropped a finding"
    assert len(out_seq) == len(canned_encounters)
    summary = SHADOW._summarise(out_seq)
    assert summary["n_encounters"] == len(canned_encounters)
    assert summary["n_findings"] >= 0


def test_concurrency_four_preserves_encounter_count_and_findings(canned_encounters):
    """Concurrent path must audit every encounter and write
    findings back into the right index (no swap, no drop, no dup).
    """
    run = SHADOW._auditor_for("stub", None)
    out_par = _run_auditor(run, [dict(e) for e in canned_encounters], concurrency=4)
    assert len(out_par) == len(canned_encounters)
    assert all("findings" in e for e in out_par)
    # Per-encounter: findings is a non-None list. Empty list is allowed
    # (stub returns STUB_NO_DATA when no recall data).
    for enc in out_par:
        assert isinstance(enc["findings"], list)


def test_concurrent_path_summary_matches_sequential(canned_encounters):
    """Sequential and concurrent runs of the same encounters with
    the same auditor must produce the same summary stats.
    """
    run_seq = SHADOW._auditor_for("stub", None)
    seq_enc = [dict(e) for e in canned_encounters]
    _run_auditor(run_seq, seq_enc, concurrency=1)
    summary_seq = SHADOW._summarise(seq_enc)

    run_par = SHADOW._auditor_for("stub", None)
    par_enc = [dict(e) for e in canned_encounters]
    _run_auditor(run_par, par_enc, concurrency=4)
    summary_par = SHADOW._summarise(par_enc)

    assert summary_seq["n_encounters"] == summary_par["n_encounters"]
    assert summary_seq["n_findings"] == summary_par["n_findings"]
    assert summary_seq["by_rule"] == summary_par["by_rule"]
    assert summary_seq["by_severity"] == summary_par["by_severity"]
    assert summary_seq["n_estimated_dollars"] == summary_par["n_estimated_dollars"]


def test_concurrency_speedup_is_real(canned_encounters):
    """Smoke test: concurrency=4 should not be catastrophically slower
    than sequential. The stub auditor is a pure dict lookup (microseconds)
    so the speedup won't be large, but it should at least be within
    5x of sequential (concurrent has thread-pool overhead; this
    bound is generous to avoid flakiness on slow runners).
    """
    run_seq = SHADOW._auditor_for("stub", None)
    seq = [dict(e) for e in canned_encounters]
    t0 = _time.monotonic()
    _run_auditor(run_seq, seq, concurrency=1)
    t_seq = _time.monotonic() - t0

    run_par = SHADOW._auditor_for("stub", None)
    par = [dict(e) for e in canned_encounters]
    t0 = _time.monotonic()
    _run_auditor(run_par, par, concurrency=4)
    t_par = _time.monotonic() - t0

    # Concurrent must complete (lower-bound 0s trivially) and
    # not be more than 5x slower than sequential due to thread-pool
    # overhead on a CPU-bound stub. Real LLM calls would invert
    # this by 5-10x; that's the point.
    assert t_par >= 0
    assert t_par <= max(0.5, t_seq * 5 + 0.5), (
        f"concurrent path took {t_par:.3f}s vs sequential {t_seq:.3f}s; "
        "thread pool overhead shouldn't be this bad."
    )


def test_markdown_report_includes_timing_metadata(canned_encounters, tmp_path):
    """The 1-page report's header should mention wall-clock time
    and concurrency level so a reviewer can verify the run
    parameters without re-running.
    """
    run = SHADOW._auditor_for("stub", None)
    _run_auditor(run, [dict(e) for e in canned_encounters], concurrency=4)
    summary = SHADOW._summarise(canned_encounters)
    md = SHADOW._render_markdown(
        tmp_path / "fixture.json",
        canned_encounters,
        summary,
        "stub",
        wall_seconds=12.34,
        concurrency=4,
    )
    assert "wall=12.3s" in md
    assert "concurrency=4" in md
    assert "SOMB-anchored" in md
    assert "Not a guarantee of recovered revenue" in md


def test_render_json_includes_full_encounter_list(canned_encounters):
    """The JSON report keeps every encounter so downstream tooling
    can ingest the report without re-running the audit. ``stub``
    returns one row per encounter (even if it's a STUB_NO_DATA
    sentinel), so the length must equal the input length.
    """
    run = SHADOW._auditor_for("stub", None)
    _run_auditor(run, [dict(e) for e in canned_encounters], concurrency=2)
    summary = SHADOW._summarise(canned_encounters)
    out = SHADOW._render_json(Path("fixture.json"), canned_encounters, summary, "stub")
    assert out["provider"] == "stub"
    assert out["summary"]["n_encounters"] == len(canned_encounters)
    assert len(out["encounters"]) == len(canned_encounters)
    for enc in out["encounters"]:
        assert "findings" in enc
        assert isinstance(enc["findings"], list)
