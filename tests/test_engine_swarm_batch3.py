"""Tests pinning the engine BLOCKING fixes from swarm-batch3.

Two contracts:

1. The in-tree auditor_prompt.txt must be the canonical v12
   prompt (40 KB AHCIP-tuned). Pre-fix the file was 1,200 bytes
   of v0 generic text — anyone running ``python -m pytest``
   without Docker was loading the wrong prompt and would get
   silent drift on every audit.

2. shadow_audit.py must pass temperature=0.2 to LLMClient (the
   same deterministic-leaning default auditor.py uses). Without
   this fix the live ``--provider ollama`` shadow run drifted
   from the in-process ``run_audit`` distribution — different
   runs gave different recall numbers, defeating the
   'shadow reproduces the live auditor' marketing promise.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_in_tree_prompt_matches_v12_canonical():
    """The in-tree auditor_prompt.txt (the editable-install
    fallback) must match the canonical v12 prompt byte-for-byte.
    This pins the contract that a developer who runs
    ``pytest tests/`` without rebuilding the Docker image
    still loads the right prompt."""
    in_tree = (SRC / "ai_billing_audit" / "auditor_prompt.txt").read_bytes()
    canonical = (ROOT / "prompts" / "v12" / "auditor_prompt.txt").read_bytes()
    assert in_tree == canonical, (
        f"in-tree prompt is {len(in_tree):,} bytes; canonical is "
        f"{len(canonical):,} bytes. The editable-install fallback "
        "shipped the wrong prompt. Re-sync by copying "
        "prompts/v12/auditor_prompt.txt → "
        "src/ai_billing_audit/auditor_prompt.txt."
    )
    # And the canonical hash should match the MANIFEST pin.
    # The manifest pins the canonical LF/UTF-8 content. Text-mode
    # reading normalizes a Windows CRLF checkout before hashing.
    actual_hash = hashlib.sha256(
        (SRC / "ai_billing_audit" / "auditor_prompt.txt")
        .read_text(encoding="utf-8")
        .encode("utf-8")
    ).hexdigest()
    manifest_path = ROOT / "prompts" / "v12" / "MANIFEST.json"
    if manifest_path.is_file():
        import json

        manifest = json.loads(manifest_path.read_text())
        expected_hash = manifest.get("content_sha256", "").removeprefix("sha256:")
        assert actual_hash == expected_hash, (
            f"MANIFEST pin {expected_hash[:12]}... doesn't match "
            f"on-disk prompt hash {actual_hash[:12]}... Update "
            "MANIFEST.json or re-pin the canonical prompt."
        )


def test_shadow_audit_passes_temperature_0_2():
    """shadow_audit.py must call complete_json with
    temperature=0.2 to match auditor.py's calibration."""
    shadow_path = ROOT / "scripts" / "shadow_audit.py"
    src = shadow_path.read_text()
    # The single complete_json call inside _auditor_for's run()
    # closure must include temperature=0.2.
    assert "temperature=0.2" in src, (
        "shadow_audit.py does not pass temperature=0.2 — "
        "drifts from auditor.py's calibrated default."
    )
    # And the temperature literal must be 0.2 (not 0.7 or 1.0).
    import re

    matches = re.findall(r"temperature\s*=\s*([\d.]+)", src)
    assert matches, "no temperature= literal in shadow_audit.py"
    for m in matches:
        f = float(m)
        assert f == 0.2, f"shadow_audit.py uses temperature={f}, expected 0.2"


def test_auditor_and_shadow_audit_use_same_temperature_default():
    """Both auditor.run_audit() and shadow_audit.py must use
    temperature=0.2. This is the calibration contract: the
    audit pipeline and the shadow runner should sample from
    the same distribution so a shadow run is meaningful."""
    auditor_src = (SRC / "ai_billing_audit" / "auditor.py").read_text()
    shadow_src = (ROOT / "scripts" / "shadow_audit.py").read_text()
    import re

    auditor_temps = [
        float(m) for m in re.findall(r"temperature\s*=\s*([\d.]+)", auditor_src)
    ]
    shadow_temps = [
        float(m) for m in re.findall(r"temperature\s*=\s*([\d.]+)", shadow_src)
    ]
    assert 0.2 in auditor_temps, (
        f"auditor.py does not use temperature=0.2; found {auditor_temps}"
    )
    assert 0.2 in shadow_temps, (
        f"shadow_audit.py does not use temperature=0.2; found {shadow_temps}"
    )
