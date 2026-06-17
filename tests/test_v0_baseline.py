"""Tests for the v0 Auditor baseline harness (task t_1400da1f).

These tests guard the three acceptance criteria:

  1. The 50 val encounters + manifest exist on disk.
  2. The v0 prompt pin (prompts/v0/) is byte-identical to the bundled
     src/ai_billing_audit/auditor_prompt.txt copy, and the manifest
     hash matches the on-disk content.
  3. A single end-to-end run_audit() call on the first val encounter
     produces a parseable AuditResult that matches the expected
     finding schema (one Finding per canned response, all five
     required fields populated, encounter_id round-trips).

The tests use a FakeLLM (deterministic, no network) so they run
in <100ms and don't require API credentials.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ai_billing_audit.auditor import (  # noqa: E402
    RESPONSE_JSON_SCHEMA,
    AuditResult,
    Finding,
    run_audit,
    validate_findings,
)
from ai_billing_audit.llm import LLMClient  # noqa: E402


VAL_PATH = PROJECT_ROOT / "data" / "val.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "val_manifest.json"
V0_PIN_PATH = PROJECT_ROOT / "prompts" / "v0" / "auditor_prompt.txt"
V0_MANIFEST_PATH = PROJECT_ROOT / "prompts" / "v0" / "MANIFEST.json"
BUNDLED_PROMPT_PATH = PROJECT_ROOT / "src" / "ai_billing_audit" / "auditor_prompt.txt"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeLLM:
    """Deterministic LLMClient double that returns a canned one-finding response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[tuple] = []

    def complete(self, messages, **kwargs):  # noqa: ANN001, ANN201
        self.calls.append((messages, kwargs))
        return {
            "choices": [{"message": {"content": json.dumps(self._payload)}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def complete_json(self, messages, json_schema, **kwargs):  # noqa: ANN001, ANN201
        response = self.complete(messages, response_format=json_schema, **kwargs)
        return json.loads(response["choices"][0]["message"]["content"])


@pytest.fixture(scope="module")
def val_split() -> list[dict]:
    assert VAL_PATH.is_file(), (
        f"v0 test split not found at {VAL_PATH}. "
        f"Generate it with: python scripts/generate_test_split.py"
    )
    with open(VAL_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.is_file(), f"manifest not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Acceptance #1: 50 val encounters + manifest with gold labels
# ---------------------------------------------------------------------------


def test_val_split_has_50_encounters(val_split: list[dict]) -> None:
    assert len(val_split) == 50, (
        f"expected 50 val encounters (the v0 holdout), got {len(val_split)}. "
        f"Regenerate with python scripts/generate_test_split.py if the spec changed."
    )


def test_val_split_ids_are_unique(val_split: list[dict]) -> None:
    ids = [e["encounter_id"] for e in val_split]
    assert len(set(ids)) == 50, "encounter_id values are not unique"


def test_val_split_ids_use_encounter_id_field(val_split: list[dict]) -> None:
    for e in val_split:
        assert "encounter_id" in e, f"encounter missing encounter_id: {e}"
        assert isinstance(e["encounter_id"], str)
        assert e["encounter_id"].startswith("enc_"), (
            f"encounter_id {e['encounter_id']!r} does not start with 'enc_'"
        )


def test_every_encounter_has_ground_truth(val_split: list[dict]) -> None:
    for e in val_split:
        gt = e.get("ground_truth")
        assert isinstance(gt, list), (
            f"encounter {e['encounter_id']!r} missing ground_truth list"
        )
        for f in gt:
            assert "category" in f, f"ground truth finding missing category: {f}"
            assert "suggested_code" in f
            assert "clinical_evidence_quote" in f


def test_manifest_matches_val_split(val_split: list[dict], manifest: dict) -> None:
    assert manifest["size"] == 50
    assert manifest["split"] == "val"
    val_ids = {e["encounter_id"] for e in val_split}
    manifest_ids = {e["encounter_id"] for e in manifest["entries"]}
    assert val_ids == manifest_ids, (
        "manifest entries do not line up with val.json encounter_ids"
    )


def test_manifest_gold_categories_match_ground_truth(val_split: list[dict], manifest: dict) -> None:
    for entry in manifest["entries"]:
        enc = next(e for e in val_split if e["encounter_id"] == entry["encounter_id"])
        actual_categories = sorted({f["category"] for f in enc["ground_truth"]})
        assert entry["gold_categories"] == actual_categories, (
            f"manifest gold_categories mismatch for {entry['encounter_id']!r}: "
            f"manifest={entry['gold_categories']} actual={actual_categories}"
        )


def test_manifest_n_gold_findings_matches(val_split: list[dict], manifest: dict) -> None:
    for entry in manifest["entries"]:
        enc = next(e for e in val_split if e["encounter_id"] == entry["encounter_id"])
        assert entry["n_gold_findings"] == len(enc["ground_truth"]), (
            f"n_gold_findings mismatch for {entry['encounter_id']!r}"
        )


# ---------------------------------------------------------------------------
# Acceptance #2: v0 prompt is pinned
# ---------------------------------------------------------------------------


def test_v0_pin_file_exists() -> None:
    assert V0_PIN_PATH.is_file(), f"v0 pin missing at {V0_PIN_PATH}"


def test_v0_pin_matches_bundled_prompt() -> None:
    assert BUNDLED_PROMPT_PATH.is_file(), (
        f"bundled prompt missing at {BUNDLED_PROMPT_PATH}"
    )
    bundled = BUNDLED_PROMPT_PATH.read_bytes()
    pinned = V0_PIN_PATH.read_bytes()
    assert bundled == pinned, (
        f"v0 pin at {V0_PIN_PATH} does not match bundled src/ copy. "
        f"Re-pin with: cp {BUNDLED_PROMPT_PATH} {V0_PIN_PATH}"
    )


def test_v0_manifest_records_correct_hash() -> None:
    assert V0_MANIFEST_PATH.is_file()
    with open(V0_MANIFEST_PATH, "r", encoding="utf-8") as f:
        m = json.load(f)
    actual_hash = "sha256:" + __import__("hashlib").sha256(
        V0_PIN_PATH.read_bytes()
    ).hexdigest()
    assert m["content_sha256"] == actual_hash, (
        f"v0 manifest content_sha256 {m['content_sha256']} "
        f"does not match actual file hash {actual_hash}. "
        f"Re-pin the prompt and update the manifest."
    )
    assert m["version_label"] == "v0"
    assert m["byte_size"] == V0_PIN_PATH.stat().st_size


def test_v0_manifest_paired_test_split_hash_matches() -> None:
    with open(V0_MANIFEST_PATH, "r", encoding="utf-8") as f:
        m = json.load(f)
    paired = m["test_split_paired_with"]
    actual_val_hash = "sha256:" + __import__("hashlib").sha256(
        VAL_PATH.read_bytes()
    ).hexdigest()
    assert paired["val_json_sha256"] == actual_val_hash, (
        f"v0 manifest pairs with val.json hash {paired['val_json_sha256']} "
        f"but actual is {actual_val_hash}. "
        f"Regenerate the test split and update the manifest."
    )


# ---------------------------------------------------------------------------
# Acceptance #3: smoke test on 1 encounter produces parseable output
# ---------------------------------------------------------------------------


def test_smoke_run_audit_on_first_val_encounter(val_split: list[dict]) -> None:
    """End-to-end: run_audit on encounter 0 returns a parseable AuditResult.

    The canned LLM response contains a single finding whose quote is a
    real substring of the encounter's clinical_note (this is the same
    contract scripts/smoke_test_auditor.py verifies, inlined here as
    a pytest test so a regression fails CI).
    """
    enc = val_split[0]
    quote = "ECG performed in office"
    assert quote in enc["clinical_note"], (
        f"smoke test quote {quote!r} not present in clinical_note; "
        f"the test split may have been regenerated against different templates"
    )

    canned_payload = {
        "summary": "Smoke test encounter.",
        "findings": [
            {
                "category": "cardiology",
                "suggested_code": "93000",
                "quote": quote,
                "severity": "medium",
                "rule_ids": ["rule_ecg_001"],
            }
        ],
    }

    fake = FakeLLM(canned_payload)
    client = LLMClient(complete=fake.complete)
    result = run_audit(enc, llm=client, prompt_path=V0_PIN_PATH)

    # --- The returned value is the typed shape.
    assert isinstance(result, AuditResult)
    assert result.encounter_id == enc["encounter_id"]
    assert result.summary == canned_payload["summary"]
    assert len(result.findings) == 1
    f = result.findings[0]
    assert isinstance(f, Finding)
    for key in ("category", "suggested_code", "quote", "severity"):
        assert getattr(f, key), f"finding.{key} is empty after smoke run"
    assert f.category == "cardiology"
    assert f.suggested_code == "93000"
    assert f.severity == "medium"
    assert f.rule_ids == ("rule_ecg_001",)
    assert f.quote == quote

    # --- The LLM was called with the v0 prompt as the system message
    #     and the encounter's clinical_note in the user message.
    assert len(fake.calls) == 1
    sent_messages, sent_kwargs = fake.calls[0]
    assert sent_messages[0]["role"] == "system"
    bundled = BUNDLED_PROMPT_PATH.read_bytes().rstrip(b"\n").decode("utf-8")
    assert sent_messages[0]["content"] == bundled, (
        "run_audit did not send the pinned v0 prompt to the LLM"
    )
    assert enc["clinical_note"] in sent_messages[1]["content"]
    # --- The response_format was forwarded to the LLM as a constrained-
    #     decoding envelope wrapping RESPONSE_JSON_SCHEMA (the fix for
    #     review t_3ebd3694 finding #2: the legacy `{"type": "json_object"}`
    #     envelope is unconstrained; the new envelope asks the provider
    #     for JSON-schema-mode output and validates locally as a backstop).
    assert "response_format" in sent_kwargs
    rf = sent_kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "response"
    assert rf["json_schema"]["schema"] is RESPONSE_JSON_SCHEMA


def test_validate_findings_accepts_schema_shape() -> None:
    """validate_findings must accept a finding matching RESPONSE_JSON_SCHEMA.

    Catches drift between the JSON schema (used by constrained
    decoding) and the typed Finding dataclass.
    """
    payload = {
        "summary": "x",
        "findings": [
            {
                "category": "cardiology",
                "suggested_code": "93000",
                "quote": "ECG performed in office",
                "severity": "medium",
                "rule_ids": ["rule_ecg_001"],
            }
        ],
    }
    findings = validate_findings(payload)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.category == "cardiology"
    assert f.suggested_code == "93000"
    assert f.severity == "medium"
    assert f.quote == "ECG performed in office"
    assert f.rule_ids == ("rule_ecg_001",)
