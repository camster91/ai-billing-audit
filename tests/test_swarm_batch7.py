"""Tests pinning the v12 prompt trigger-word additions (swarm-batch7).

H-Engine-3 (high-severity rules relying on inference):
  Pre-batch-7 the high-severity bucket of the v12 prompt
  (rules A, B, D, G, I, J) relied on body-text inference rather
  than explicit trigger-phrase lists. Reasoning models with a
  constrained JSON schema tend to skip body-text triggers and
  fall back to "summarize mode" → 0 findings on encounters
  where SOMB rules clearly apply.

  Fix: added explicit trigger-phrase lists for each high-severity
  rule. This file pins the contract: each rule's section in
  the prompt must contain a "Trigger phrases" block.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


PROMPT = (ROOT / "prompts" / "v12" / "auditor_prompt.txt").read_text()


@pytest.mark.parametrize(
    "rule_marker",
    [
        "A. DIAGNOSIS LINKAGE",
        "B. NON-INSURED SERVICE",
        "D. CONSULTATION / REFERRING PRACTITIONER ID",
        "G. TELEHEALTH PREMIUM",
        "I. SAME-DAY VISIT CONFLICT",
        "J. CHRONIC DISEASE (CMGP)",
    ],
)
def test_high_severity_rule_has_trigger_phrases(rule_marker: str):
    """Each high-severity rule's section must include a
    'Trigger phrases' block listing explicit signal words /
    phrases that fire the rule. Without this list the model
    falls back to inference on body-text and misses the rule
    (recall drops on the v12 cleaned run, especially for D
    and J)."""
    # Extract the section: from the rule marker line to the next
    # rule marker (uppercase letter followed by period).
    pat = re.compile(
        rf"^{re.escape(rule_marker)}.*?(?=^[A-Z]\. [A-Z]|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(PROMPT)
    assert m, f"could not isolate section for {rule_marker!r}"
    section = m.group(0)
    # The section must contain a "Trigger phrases" block (or
    # equivalent — "trigger" + "phrase" within 80 chars).
    assert re.search(r"[Tt]rigger\s+phrases?", section), (
        f"section for {rule_marker!r} lacks a 'Trigger phrases' "
        "block. swarm-batch7 added explicit trigger-word lists to "
        "each high-severity rule; if you're removing one, also "
        "update this test (or restore the trigger block)."
    )


def test_prompt_size_grew_with_trigger_words():
    """The v12 prompt grew by ~30 lines with the trigger-word
    additions. Pin a lower bound so a future refactor that
    silently truncates the trigger blocks fails loud."""
    lines = PROMPT.count("\n")
    assert lines > 800, (
        f"v12 prompt has {lines} lines; expected >800 after "
        "swarm-batch7's trigger-word additions. Did someone "
        "truncate the trigger blocks?"
    )


def test_in_tree_prompt_matches_v12_canonical_after_batch7():
    """src/ai_billing_audit/auditor_prompt.txt (the editable
    fallback) must match the v12 canonical text byte-for-byte
    even after swarm-batch7 grew the canonical text."""
    in_tree = (
        ROOT / "src" / "ai_billing_audit" / "auditor_prompt.txt"
    ).read_bytes()
    canonical = (
        ROOT / "prompts" / "v12" / "auditor_prompt.txt"
    ).read_bytes()
    assert in_tree == canonical, (
        f"in-tree prompt is {len(in_tree):,} bytes; canonical is "
        f"{len(canonical):,} bytes. The editable-install fallback "
        "drifted from the v12 canonical text. Re-copy."
    )


def test_manifest_hash_matches_canonical():
    """MANIFEST.json's content_sha256 must match the actual
    prompt hash. Pre-batch-7 this was stale because the
    editable fallback had a different prompt; the MANIFEST
    pin no longer matched reality."""
    import hashlib
    import json
    manifest = json.loads(
        (ROOT / "prompts" / "v12" / "MANIFEST.json").read_text()
    )
    actual = hashlib.sha256(PROMPT.encode()).hexdigest()
    expected = manifest["content_sha256"].removeprefix("sha256:")
    assert actual == expected, (
        f"MANIFEST pin {expected[:12]}... doesn't match "
        f"actual {actual[:12]}... Regenerate MANIFEST.json."
    )