"""Tests for the JSON-API denial-risk + appeal-letter endpoints.

Routes under test (added 2026-06-25 to support the Next.js portal):

* ``GET  /api/encounters/{id}/denial-risk``
* ``POST /api/encounters/{id}/appeal-letter``
* ``GET  /api/encounters/{id}/appeal-letters``
* ``POST /api/encounters/{id}/appeal-letter/{letter_id}/outcome``

These complement the legacy HTML-form routes
(``/encounter/{id}/appeal``, ``/encounter/{id}/appeal/{id}/outcome``)
that the biller-facing dashboard uses, and the module-level tests
in ``test_denial_risk.py`` / ``test_appeal_letter.py`` /
``test_appeal_outcome.py`` / ``test_appeal_fuzzy_match.py``. The new
endpoints are JSON because the Next.js portal needs structured
responses (not HTML form posts) and a stable
``/api/encounters/{id}/...`` URL prefix.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_billing_audit import appeal_letter, demo_registry
from ai_billing_audit.appeal_letter import (
    AppealOutcome,
    log_appeal_letter,
    log_appeal_outcome,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_logs_dir(tmp_path, monkeypatch):
    """Point appeal_letter's log paths at tmp_path so tests never
    touch the real /app/logs."""
    monkeypatch.setattr(appeal_letter, "_LOGS_DIR", tmp_path)
    monkeypatch.setattr(
        appeal_letter, "_APPEAL_LOG",
        tmp_path / "appeal_letters.jsonl",
    )
    monkeypatch.setattr(
        appeal_letter, "_APPEAL_OUTCOMES_LOG",
        tmp_path / "appeal_outcomes.jsonl",
    )
    return tmp_path


@pytest.fixture
def stub_llm_client(monkeypatch):
    """Replace the route's LLMClient with a fake that returns a
    deterministic stub OpenAI-shape response.

    The route does ``from .llm import LLMClient`` inside the
    handler, so the import is re-evaluated on every request. We
    patch the source module's binding (``ai_billing_audit.llm.LLMClient``)
    so each request picks up the stub.

    The stub response is valid JSON with the keys the appeal-letter
    parser requires (``letter_markdown``, ``appeal_basis``,
    ``cited_rule_ids``, ``requested_action``) so the route completes
    the letter-generation flow without falling through to the
    template-only path.
    """
    stub_letter = {
        "letter_markdown": (
            "# Appeal Letter (stub LLM response)\n\n"
            "Dear Payer,\n\nThe claim was denied in error. "
            "See attached clinical documentation."
        ),
        "appeal_basis": (
            "The clinical documentation supports medical necessity."
        ),
        "cited_rule_ids": ["DX_LINKAGE_REQUIRED"],
        "requested_action": "Reconsider and pay claim in full.",
    }
    class _StubLLMClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass
        def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(stub_letter),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
    from ai_billing_audit import llm
    monkeypatch.setattr(llm, "LLMClient", _StubLLMClient)
    return _StubLLMClient


@pytest.fixture
def client(monkeypatch):
    """A FastAPI test client. Auth is bypassed for tests
    (``AUDIT_ALLOW_NO_AUTH=1``) so we don't need a bearer token."""
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    from ai_billing_audit.api import create_app
    app = create_app()
    return TestClient(app)


@pytest.fixture
def registered_encounter(monkeypatch):
    """Register a demo encounter + a corresponding encounter record.

    The denial-risk + appeal-letter endpoints look up
    ``load_encounter_record(encounter_id)`` for the gold findings
    (or fall back to the record if no real-audit exists), so we
    patch the function to return our synthetic record directly.
    """
    demo_registry.register_demo_encounter(
        "ENC-API-001", "MEDIUM", "synthetic encounter for API tests",
    )

    fake_record: dict[str, Any] = {
        "encounter_id": "ENC-API-001",
        "clinical_note": (
            "Patient is a 52-year-old male presenting for follow-up "
            "of type 2 diabetes with HbA1c 7.8%. Assessment includes "
            "99213 evaluation. No acute findings."
        ),
        "claim": {
            "encounter_id": "ENC-API-001",
            "date_of_service": "2024-05-15",
            "line_items": [
                {"cpt": "99213", "modifiers": [], "dx_pointers": ["Z0000"]},
            ],
        },
        "patient_id": "MBR-TEST-001",
        "rules": [],
        "ground_truth": [
            {
                "finding_id": "F-CLEAN-1",
                "category": "evaluation",
                "severity": "info",
                "suggested_code": "99213",
                "rule_id": "EVAL_NEW_VS_ESTABLISHED",
                "clinical_evidence_quote": (
                    "Established patient follow-up, uncomplicated."
                ),
            },
            {
                "finding_id": "F-MISSING-DX-1",
                "category": "diagnosis",
                "severity": "high",
                "suggested_code": "",
                "rule_id": "DX_LINKAGE_REQUIRED",
                "clinical_evidence_quote": (
                    "CPT 99213 billed without an ICD-10 pointer."
                ),
            },
            {
                "finding_id": "F-MOD-1",
                "category": "modifier",
                "severity": "critical",
                "suggested_code": "25",
                "rule_id": "MOD_25_SEPARATELY_IDENTIFIABLE",
                "clinical_evidence_quote": (
                    "Modifier 25 used without separately identifiable E/M."
                ),
            },
        ],
    }

    def _fake_load(encounter_id: str):
        if encounter_id == "ENC-API-001":
            return fake_record
        return None

    monkeypatch.setattr(
        "ai_billing_audit.api.load_encounter_record", _fake_load,
    )
    return "ENC-API-001"


def _post_json(client: TestClient, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, json=body)


# ---------------------------------------------------------------------------
# GET /api/encounters/{id}/denial-risk
# ---------------------------------------------------------------------------


def test_denial_risk_for_unknown_encounter_returns_404(client, temp_logs_dir):
    """404 when the encounter isn't registered. The route checks
    ``load_encounter_record`` first; if it returns None, the route
    surfaces 404 with a clear ``detail`` message."""
    r = client.get("/api/encounters/UNKNOWN-9999/denial-risk")
    assert r.status_code == 404
    assert "UNKNOWN-9999" in r.json()["detail"]


def test_denial_risk_for_registered_encounter_returns_score(
    client, temp_logs_dir, registered_encounter
):
    """A registered encounter returns a denial-risk dict.

    The shape mirrors ``denial_risk.compute_denial_risk`` (the
    module function the route wraps): ``denial_probability``,
    ``tier``, ``n_findings``, ``per_finding``, ``top_risk``,
    plus the encounter_id + the min_severity we scored against."""
    r = client.get(f"/api/encounters/{registered_encounter}/denial-risk")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == registered_encounter
    assert "denial_probability" in body
    assert "tier" in body
    assert body["tier"] in {"low", "medium", "high", "critical"}
    assert body["n_findings"] == 3
    # critical-severity finding pushes the score into the
    # "critical" tier (>0.60) — pin so future scoring changes don't
    # silently flip the dashboard tier colour.
    assert body["tier"] == "critical"
    assert body["denial_probability"] > 0.60


def test_denial_risk_attaches_min_severity_used(client, temp_logs_dir, registered_encounter):
    """The response includes the min_severity threshold used to
    score, so the portal can decide whether to apply a stricter
    threshold client-side."""
    r = client.get(f"/api/encounters/{registered_encounter}/denial-risk")
    assert r.status_code == 200
    body = r.json()
    assert "min_severity" in body
    assert isinstance(body["min_severity"], int)


# ---------------------------------------------------------------------------
# POST /api/encounters/{id}/appeal-letter
# ---------------------------------------------------------------------------


def test_appeal_letter_generates_with_finding_id(
    client, temp_logs_dir, registered_encounter, stub_llm_client
):
    """POST with finding_id → 200, returns a letter dict, and
    logs the letter to appeal_letters.jsonl so the outcome endpoint
    can find it later."""
    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {
            "finding_id": "F-MISSING-DX-1",
            "denial_reason": "Missing ICD-10 linkage for the E/M code.",
            "clinical_note": (
                "Patient is a 52-year-old male with established "
                "type 2 diabetes. HbA1c 7.8%."
            ),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["encounter_id"] == registered_encounter
    assert body["finding_id"] == "F-MISSING-DX-1"
    assert "letter" in body
    assert "letter_markdown" in body["letter"]
    # The letter landed in the log so the outcome endpoint can join on it.
    letters = appeal_letter.read_appeal_letters(encounter_id=registered_encounter)
    assert len(letters) == 1
    assert letters[0]["encounter_id"] == registered_encounter


def test_appeal_letter_generates_with_rule_id_fuzzy_match(
    client, temp_logs_dir, registered_encounter, stub_llm_client
):
    """POST with rule_id (not finding_id) → still 200.

    Mirrors the legacy endpoint's fuzzy rule_id match so the two
    routes behave identically. The gold finding's rule_id is
    ``DX_LINKAGE_REQUIRED``; we POST with the trailing-M variant
    ``DX_LINKAGE_REQUIREMENT`` to confirm the matcher fires.

    The response echoes the RESOLVED finding_id (from the matched
    gold finding), not the biller's raw rule_id input — the
    portal needs the canonical finding_id so it can correlate
    the letter with the matching finding on the encounter detail.
    """
    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {
            "rule_id": "DX_LINKAGE_REQUIREMENT",
            "denial_reason": "Payer says no DX linkage.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # The matcher resolved to the gold finding that has
    # rule_id "DX_LINKAGE_REQUIRED". The response surfaces that
    # finding's canonical id so the portal can correlate the
    # letter with the encounter-detail finding card.
    assert body["finding_id"] == "F-MISSING-DX-1"


def test_appeal_letter_missing_finding_and_rule_returns_400(
    client, temp_logs_dir, registered_encounter
):
    """POST without finding_id AND without rule_id → 400."""
    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {"denial_reason": "x"},
    )
    assert r.status_code == 400
    assert "finding_id" in r.json()["detail"].lower()


def test_appeal_letter_missing_denial_reason_returns_400(
    client, temp_logs_dir, registered_encounter
):
    """POST without denial_reason → 400."""
    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {"finding_id": "F-MISSING-DX-1"},
    )
    assert r.status_code == 400
    assert "denial_reason" in r.json()["detail"].lower()


def test_appeal_letter_unknown_finding_returns_404(
    client, temp_logs_dir, registered_encounter
):
    """POST with finding_id that isn't on the encounter → 404."""
    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {
            "finding_id": "F-DOES-NOT-EXIST",
            "denial_reason": "x",
        },
    )
    assert r.status_code == 404


def test_appeal_letter_unknown_encounter_returns_404(
    client, temp_logs_dir
):
    """POST against an unregistered encounter → 404."""
    r = _post_json(
        client,
        "/api/encounters/UNKNOWN-9999/appeal-letter",
        {"finding_id": "F-1", "denial_reason": "x"},
    )
    assert r.status_code == 404


def test_appeal_letter_template_only_when_no_llm(
    client, temp_logs_dir, registered_encounter, monkeypatch
):
    """When LLMClient construction raises, the route falls through
    to the template-only path and still returns a valid letter.

    The template-only letter has ``template_only: True`` so the
    biller knows it's not LLM-generated.
    """
    class _BrokenLLMClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("simulated offline")
    from ai_billing_audit import llm
    monkeypatch.setattr(llm, "LLMClient", _BrokenLLMClient)

    r = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {
            "finding_id": "F-MISSING-DX-1",
            "denial_reason": "Missing DX linkage.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["letter"]["template_only"] is True
    assert body["letter"]["scrubbed_phi"] is True


# ---------------------------------------------------------------------------
# GET /api/encounters/{id}/appeal-letters
# ---------------------------------------------------------------------------


def test_appeal_letters_empty_when_none_generated(
    client, temp_logs_dir, registered_encounter
):
    """GET when no letter has been logged → empty list."""
    r = client.get(f"/api/encounters/{registered_encounter}/appeal-letters")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["letters"] == []
    assert body["encounter_id"] == registered_encounter


def test_appeal_letters_returns_logged_letters(
    client, temp_logs_dir, registered_encounter, stub_llm_client
):
    """After a letter is generated, GET returns it."""
    # Generate first via the endpoint.
    r1 = _post_json(
        client,
        f"/api/encounters/{registered_encounter}/appeal-letter",
        {"finding_id": "F-CLEAN-1", "denial_reason": "Test reason."},
    )
    assert r1.status_code == 200
    r2 = client.get(f"/api/encounters/{registered_encounter}/appeal-letters")
    assert r2.status_code == 200
    body = r2.json()
    assert body["count"] >= 1
    assert any(
        l.get("encounter_id") == registered_encounter
        for l in body["letters"]
    )


# ---------------------------------------------------------------------------
# POST /api/encounters/{id}/appeal-letter/{letter_id}/outcome
# ---------------------------------------------------------------------------


def _seed_one_letter(
    encounter_id: str = "ENC-API-001",
    letter_id: str = "L-1",
    finding_id: str = "F-MISSING-DX-1",
) -> None:
    """Drop a fake letter row so the outcome endpoint can find it."""
    log_appeal_letter(
        {
            "letter_id": letter_id,
            "encounter_id": encounter_id,
            "finding_id": finding_id,
            "appeal_basis": "x",
            "cited_rule_ids": ["DX_LINKAGE_REQUIRED"],
            "requested_action": "Reconsider",
            "market": "CA-AB",
            "compliance_law": "HIA",
            "generated_at": "2026-06-25T00:00:00+00:00",
            "template_only": True,
        },
        encounter_id,
        tenant_id="default",
        finding_id=finding_id,
    )


def test_appeal_letter_outcome_accepts_valid_status(
    client, temp_logs_dir
):
    """POST with valid status → 200, outcome appended to log."""
    _seed_one_letter()
    r = _post_json(
        client,
        "/api/encounters/ENC-API-001/appeal-letter/L-1/outcome",
        {
            "status": "won",
            "notes": "Payer reversed on first review.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "won"
    assert body["encounter_id"] == "ENC-API-001"
    assert body["appeal_id"] == "L-1"
    assert "timestamp" in body
    outcomes = appeal_letter.read_appeal_outcomes(encounter_id="ENC-API-001")
    assert len(outcomes) == 1
    assert outcomes[0].status == "won"


def test_appeal_letter_outcome_rejects_unknown_status(
    client, temp_logs_dir
):
    """POST with status outside the closed enum → 400."""
    _seed_one_letter()
    r = _post_json(
        client,
        "/api/encounters/ENC-API-001/appeal-letter/L-1/outcome",
        {"status": "victorious"},  # not in {won, lost, withdrawn, pending, did_not_file}
    )
    assert r.status_code == 400
    assert "status" in r.json()["detail"].lower()


def test_appeal_letter_outcome_accepts_all_five_statuses(
    client, temp_logs_dir
):
    """Pin the full closed enum: won / lost / withdrawn /
    pending / did_not_file all return 200."""
    for i, status in enumerate(
        ["won", "lost", "withdrawn", "pending", "did_not_file"]
    ):
        letter_id = f"L-{status}"
        _seed_one_letter(letter_id=letter_id)
        r = _post_json(
            client,
            f"/api/encounters/ENC-API-001/appeal-letter/{letter_id}/outcome",
            {"status": status},
        )
        assert r.status_code == 200, f"{status}: {r.text}"
        assert r.json()["status"] == status


def test_appeal_letter_outcome_missing_status_returns_400(
    client, temp_logs_dir
):
    """POST without status → 400 (status is empty, not in enum)."""
    _seed_one_letter()
    r = _post_json(
        client,
        "/api/encounters/ENC-API-001/appeal-letter/L-1/outcome",
        {"notes": "forgot the status"},
    )
    assert r.status_code == 400


def test_appeal_letter_outcome_letter_id_in_path_required(
    client, temp_logs_dir
):
    """POST with empty letter_id → 400 (path segment is empty)."""
    # FastAPI would 404 the route match for a literal empty segment;
    # we test the URL-encoded-space variant which still hits the route.
    r = _post_json(
        client,
        "/api/encounters/ENC-API-001/appeal-letter/%20/outcome",
        {"status": "won"},
    )
    # Either 404 (route mismatch) or 400 (handler) — both acceptable.
    assert r.status_code in (400, 404)
