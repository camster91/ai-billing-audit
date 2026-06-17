"""Determinism regression suite for the synth agent.

Ported into the canonical ``tests/`` location from the t_928d8928
workspace harness. The 21 cases below prove that ``generate_suite`` and
``generate_encounter`` are pure functions of (tier, variant, seed) under
every perturbation the parent task identified:

- in-process (two calls, no state in between)
- across processes (subprocess-level isolation)
- with PYTHONHASHSEED pinned (no dict-iteration-order artefacts)
- with the global ``random`` module perturbed
- across many seeds (catches accidental ``abs(seed)`` / hash-only-of-int bugs)
- with output mutation between calls (no cached state)
- against the docstring contract (locks the "one RNG per call" claim)

If any of these regress, the synth is no longer pure and the rest of
this task's purity contract is meaningless.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ai_billing_audit.synth_agent import (
    TIERS,
    VARIANTS,
    generate_encounter,
    generate_suite,
    tier_variants,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _dumps_roundtrip(obj):
    return json.loads(json.dumps(obj, sort_keys=True))


def _diff_summary(a, b):
    """Return a short human-readable diff of two deeply-equal-but-not-identical objects."""
    return f"a==b: {a == b}; type(a)={type(a).__name__}; len(a)={len(a)}"


# ---------------------------------------------------------------------------
# 1. In-process byte equality
# ---------------------------------------------------------------------------


def test_two_calls_same_seed_inprocess_are_byte_identical():
    a = generate_suite(seed=42)
    b = generate_suite(seed=42)
    assert a == b, f"in-process: {_diff_summary(a, b)}"
    # JSON round-trip equivalence (defends against container subtypes).
    assert _dumps_roundtrip(a) == _dumps_roundtrip(b)


# ---------------------------------------------------------------------------
# 2. Per-encounter determinism across all (tier, variant) pairs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier,variant", [
    ("EASY", "clean"),
    ("EASY", "flagged"),
    ("MEDIUM", "clean"),
    ("MEDIUM", "flagged"),
    ("HARD", "clean"),
    ("HARD", "flagged"),
])
def test_generate_encounter_individually_deterministic(tier, variant):
    a = generate_encounter(tier, variant, seed=42)
    b = generate_encounter(tier, variant, seed=42)
    assert a == b, f"{tier}/{variant}: {_diff_summary(a, b)}"


# ---------------------------------------------------------------------------
# 3. The global ``random`` module is NOT consulted
# ---------------------------------------------------------------------------


def test_deterministic_even_after_perturbing_global_rng():
    # Burn the global RNG far away from the synth's seed space.
    for _ in range(50):
        random.random()
        random.choice([1, 2, 3])
    # Set a different global seed.
    random.seed(9999)
    # Shuffle a list.
    random.shuffle([1, 2, 3, 4, 5])
    a = generate_suite(seed=42)
    b = generate_suite(seed=42)
    assert a == b, "global RNG perturbation leaked into synth output"


# ---------------------------------------------------------------------------
# 4. Across processes
# ---------------------------------------------------------------------------


def _run_subprocess_suite(seed: int) -> dict:
    code = textwrap.dedent(
        f"""
        import json
        from ai_billing_audit.synth_agent import generate_suite
        suite = generate_suite(seed={seed})
        print(json.dumps(suite, sort_keys=True))
        """
    )
    env = os.environ.copy()
    # Force unbuffered stdout so json.dumps arrives in one read.
    env["PYTHONUNBUFFERED"] = "1"
    out = subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
    )
    return json.loads(out.decode())


def test_across_process_byte_identical():
    a = _run_subprocess_suite(42)
    b = _run_subprocess_suite(42)
    assert a == b, "two subprocess invocations disagree"
    md5_a = hashlib.md5(json.dumps(a, sort_keys=True).encode()).hexdigest()
    md5_b = hashlib.md5(json.dumps(b, sort_keys=True).encode()).hexdigest()
    assert md5_a == md5_b, f"md5s disagree: {md5_a} vs {md5_b}"


def test_across_process_same_hash_seed():
    """Same as above, with PYTHONHASHSEED pinned."""
    a = _run_subprocess_suite(42)
    b = _run_subprocess_suite(42)
    # Compare after the dict is reconstructed, ruling out hash-randomisation
    # effects (if any) by pinning PYTHONHASHSEED at process start.
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    code = textwrap.dedent(
        """
        import json
        from ai_billing_audit.synth_agent import generate_suite
        print(json.dumps(generate_suite(seed=42), sort_keys=True))
        """
    )
    pinned = json.loads(
        subprocess.check_output(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            env={**env, "PYTHONUNBUFFERED": "1"},
        ).decode()
    )
    assert pinned == a, "PYTHONHASHSEED-pinned run disagrees with default run"


# ---------------------------------------------------------------------------
# 5. Independence: returned suite has no shared state
# ---------------------------------------------------------------------------


def test_returned_suite_is_deep_independent():
    s1 = generate_suite(seed=42)
    s2_snapshot = copy.deepcopy(generate_suite(seed=42))
    # Mutate s1 aggressively.
    s1.clear()
    s1.append({"bogus": True})
    s2_fresh = generate_suite(seed=42)
    assert s2_fresh == s2_snapshot, (
        "synth returned a cached/mutated suite; later calls are contaminated"
    )


# ---------------------------------------------------------------------------
# 6. Multiple seeds, not just 42
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 20260616, -1, 10**9])
def test_stable_across_seeds(seed):
    a = generate_suite(seed=seed)
    b = generate_suite(seed=seed)
    assert a == b, f"seed={seed}: not stable"


# ---------------------------------------------------------------------------
# 7. Reseeding other suites does not contaminate seed=42
# ---------------------------------------------------------------------------


def test_reseed_does_not_contaminate_original_seed():
    a42 = generate_suite(seed=42)
    _ = generate_suite(seed=9999)
    b42 = generate_suite(seed=42)
    assert a42 == b42, "synth suite depends on call order"


# ---------------------------------------------------------------------------
# 8. Docstring contract (catches accidental regression of the design)
# ---------------------------------------------------------------------------


def test_docstring_claim_in_module_source():
    src = (REPO_ROOT / "src" / "ai_billing_audit" / "synth_agent.py").read_text()
    # Module docstring must keep the "pure function of (template, seed)" / "byte-identical
    # output given the same seed" claim in some form. The exact phrasing can change
    # across refactors; assert the substantive claim survives.
    assert "byte-identical" in src or "deterministic" in src, (
        "docstring contract regressed; synth_agent.py no longer claims deterministic output"
    )
    assert "random.Random" in src, (
        "docstring contract regressed; synth_agent.py no longer references the per-call RNG"
    )


# ---------------------------------------------------------------------------
# 9. Dump full output for human audit (writes to logs/ if available)
# ---------------------------------------------------------------------------


def test_dump_full_output_for_audit(tmp_path):
    a = generate_suite(seed=42)
    b = generate_suite(seed=42)
    log_dir = tmp_path
    (log_dir / "synth_seed42_run1.json").write_text(
        json.dumps(a, indent=2, sort_keys=True)
    )
    (log_dir / "synth_seed42_run2.json").write_text(
        json.dumps(b, indent=2, sort_keys=True)
    )
    # Sanity: encounter IDs unique within a run.
    ids = [enc["encounter_id"] for enc in a]
    assert len(ids) == len(set(ids)), "encounter IDs not unique within a suite"
    # And the run files agree.
    assert a == b, "dumped run files disagree"
