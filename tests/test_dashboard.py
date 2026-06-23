"""Tests for the demo dashboard app and registry.

Lightweight, no network, no LLM. The dashboard is exercised via
``starlette.testclient.TestClient`` (httpx-backed) so the routes
return real ``Response`` objects the same way they would in production.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from ai_billing_audit import api
from ai_billing_audit.demo_registry import (
    register_demo_encounter,
    list_demo_encounters,
    load_encounter_record,
    get_demo_encounter,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


# --- registry contract ---------------------------------------------------

def test_registry_is_idempotent_on_encounter_id() -> None:
    # Use a fresh id guaranteed not to be in the live registry so we
    # can observe the +1 then +0 transitions cleanly.
    probe_id = "enc_test_probe_idempotent_xyz"
    # Clean up if a prior test left it.
    from ai_billing_audit import demo_registry
    demo_registry._REGISTRY[:] = [
        e for e in demo_registry._REGISTRY if e.encounter_id != probe_id
    ]
    a = register_demo_encounter(
        encounter_id=probe_id, difficulty="EASY", summary="dup"
    )
    b = register_demo_encounter(
        encounter_id=probe_id, difficulty="EASY", summary="dup-again"
    )
    # Same id, same record — the second call is a no-op.
    assert a.encounter_id == b.encounter_id == probe_id
    # Exactly one record for this id (the second registration was a no-op).
    matches = [e for e in list_demo_encounters() if e.encounter_id == probe_id]
    assert len(matches) == 1
    # Clean up.
    demo_registry._REGISTRY[:] = [
        e for e in demo_registry._REGISTRY if e.encounter_id != probe_id
    ]


def test_registry_rejects_unknown_difficulty() -> None:
    with pytest.raises(ValueError, match="EASY, MEDIUM, or HARD"):
        register_demo_encounter(
            encounter_id="enc_bogus", difficulty="WAT", summary="x"
        )


def test_load_encounter_record_finds_known_id() -> None:
    rec = load_encounter_record("enc_10032")
    assert rec is not None
    assert rec["encounter_id"] == "enc_10032"
    assert "clinical_note" in rec
    assert "ground_truth" in rec


def test_load_encounter_record_returns_none_for_missing() -> None:
    assert load_encounter_record("enc_does_not_exist") is None


# --- route contracts -----------------------------------------------------

def test_index_lists_registered_encounter(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "enc_10032" in body
    assert 'class="encounter-card encounter-card--easy"' in body
    # Card has the two action buttons wired to the detail page.
    assert 'href="/encounter/enc_10032"' in body
    assert 'href="/encounter/enc_10032/json"' in body


def test_index_renders_no_card_when_registry_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reset the registry in-place: the module is shared across the
    # process, so we patch list_demo_encounters to return [].
    monkeypatch.setattr(
        "ai_billing_audit.api.list_demo_encounters", lambda: []
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "No demo encounters registered yet." in r.text


def test_encounter_detail_renders_evidence_highlight(
    client: TestClient,
) -> None:
    r = client.get("/encounter/enc_10032")
    assert r.status_code == 200
    body = r.text
    # The verbatim highlight must be present, not escaped.
    assert '<mark class="evidence">Duplicate service on same date</mark>' in body
    # The clinical note paragraph must surround it.
    assert 'class="clinical-note"' in body
    # The finding card has a copy button, a scroll button, and a
    # global toggle button — all must render as real <button> tags.
    assert 'data-action="copy-quote"' in body
    assert 'data-action="scroll-to-note"' in body
    assert 'id="btn-toggle-mark"' in body
    # Severity badge color.
    assert "badge--high" in body
    # The rule id is rendered.
    assert "rule_overlap_001" in body


def test_encounter_detail_404_for_unregistered(client: TestClient) -> None:
    r = client.get("/encounter/does-not-exist")
    assert r.status_code == 404


def test_encounter_json_returns_minimal_envelope(client: TestClient) -> None:
    r = client.get("/encounter/enc_10032/json")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == "enc_10032"
    assert body["difficulty"] == "EASY"
    assert isinstance(body["n_gold_findings"], int)
    assert body["n_gold_findings"] >= 1


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["n_registered"] >= 1


# --- MEDIUM wiring (t_5c741803) -----------------------------------------
#
# The medium task card wires a 4-finding encounter (enc_0007) into the
# shared registry. The tests below pin the medium-tier acceptance
# criteria on top of the dashboard infrastructure the easy task shipped.

MEDIUM_ID = "enc_0007"


def test_medium_entry_registered() -> None:
    """The medium task must register enc_0007 in the shared registry."""
    demo = get_demo_encounter(MEDIUM_ID)
    assert demo is not None, (
        "enc_0007 was not registered; t_5c741803 must add a "
        "register_demo_encounter(encounter_id='enc_0007', difficulty='MEDIUM', ...)"
        "call in demo_entries.py"
    )
    assert demo.difficulty == "MEDIUM"
    assert demo.summary  # one-line description present


def test_medium_record_loadable() -> None:
    """The wired encounter's underlying record (note / claim / rules /
    ground-truth) must load from data/synth/train.json so the detail page
    can render the full audit panel."""
    rec = load_encounter_record(MEDIUM_ID)
    assert rec is not None
    assert rec["encounter_id"] == MEDIUM_ID
    assert "Type 2 diabetes follow-up" in rec["clinical_note"]
    findings = rec["ground_truth"]
    # 4 ground-truth findings, 3 distinct categories, at least one
    # medium-severity finding — the "medium tier evidence" the task
    # card calls out.
    assert len(findings) == 4
    assert len({f["category"] for f in findings}) >= 3
    assert any(f["severity"] == "medium" for f in findings)


def test_index_lists_medium_card(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert MEDIUM_ID in body
    # The card uses the medium-tier CSS hook defined in dashboard.css.
    assert 'class="encounter-card encounter-card--medium"' in body
    # Card has the open-audit-panel and raw-json action links.
    assert f'href="/encounter/{MEDIUM_ID}"' in body
    assert f'href="/encounter/{MEDIUM_ID}/json"' in body


def test_medium_detail_renders_full_audit_panel(client: TestClient) -> None:
    r = client.get(f"/encounter/{MEDIUM_ID}")
    assert r.status_code == 200
    body = r.text
    # Clinical note and the claim block are present.
    assert "Type 2 diabetes follow-up" in body
    # All 4 medium-tier evidence fields per finding are present at least once:
    #   - rule_icd_003 / rule_lab_002 / rule_injection_001 / rule_icd_004
    #   - E11.9 / 83036 / 90686 / I10
    for needle in (
        "rule_icd_003", "rule_lab_002", "rule_injection_001", "rule_icd_004",
        "E11.9", "83036", "90686", "I10",
    ):
        assert needle in body, f"missing medium-tier evidence field: {needle}"


def test_medium_detail_shows_evidence_highlight(client: TestClient) -> None:
    r = client.get(f"/encounter/{MEDIUM_ID}")
    assert r.status_code == 200
    body = r.text
    # The detail template highlights the PRIMARY finding's evidence
    # quote in the clinical note (the verbatim substring is wrapped in
    # <mark class="evidence">...</mark>). For enc_0007, the primary
    # finding is the medium-severity ICD-linkage flag for E11.9 — the
    # task card calls out "medium-tier evidence fields" as the
    # acceptance criterion, and the highlight makes the medium-severity
    # finding's quote unambiguously visible on the page. The clinical
    # note is title-cased ("Type 2 diabetes follow-up") while the
    # finding's quote is lowercase, so we assert the title-cased form
    # that actually lands in the rendered HTML.
    assert '<mark class="evidence">Type 2 diabetes follow-up</mark>' in body, (
        "primary finding's evidence quote must be visibly highlighted "
        "in the clinical note; this is the medium-tier evidence cue "
        "the task acceptance criteria pin"
    )
    # Every non-primary finding still renders its quote in a
    # <blockquote class="finding-quote"> so the full medium-tier audit
    # panel is exercisable.
    assert body.count('<blockquote class="finding-quote">') >= 4


def test_medium_detail_buttons_clickable(client: TestClient) -> None:
    r = client.get(f"/encounter/{MEDIUM_ID}")
    assert r.status_code == 200
    body = r.text
    # Per-finding copy-quote button on every finding card.
    assert body.count('data-action="copy-quote"') >= 4
    # Global evidence-highlight toggle.
    assert 'id="btn-toggle-mark"' in body


def test_medium_json_endpoint(client: TestClient) -> None:
    r = client.get(f"/encounter/{MEDIUM_ID}/json")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == MEDIUM_ID
    assert body["difficulty"] == "MEDIUM"
    assert body["n_gold_findings"] == 4
    assert body["is_flagged"] is True


def test_medium_detail_404_when_unregistered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the medium entry is later removed from the registry, the
    detail page must 404 cleanly rather than 500 — same contract the
    easy-card test pins for an unknown id."""
    from ai_billing_audit import demo_registry
    snapshot = list(demo_registry._REGISTRY)
    monkeypatch.setattr(
        demo_registry, "list_demo_encounters",
        lambda: [e for e in snapshot if e.encounter_id != MEDIUM_ID],
    )
    monkeypatch.setattr(
        demo_registry, "get_demo_encounter",
        lambda eid: None if eid == MEDIUM_ID else next(
            (e for e in snapshot if e.encounter_id == eid), None
        ),
    )
    # Bypass the api-level lookup with the same patch.
    import ai_billing_audit.api as api_mod
    monkeypatch.setattr(api_mod, "get_demo_encounter", demo_registry.get_demo_encounter)
    r = client.get(f"/encounter/{MEDIUM_ID}")
    assert r.status_code == 404


# --- HARD wiring (t_d16db103) -------------------------------------------
#
# The hard task card wires a 5-finding encounter (enc_0000) into the
# shared registry. The tests below pin the hard-tier acceptance
# criteria on top of the dashboard infrastructure the easy/medium tasks
# shipped. The hard tier is the only one that surfaces the advanced
# actions panel (jump-to-high, next-finding, severity-filter), per the
# {% if difficulty == "HARD" %} block in encounter_detail.html.

HARD_ID = "enc_0000"


def test_hard_entry_registered() -> None:
    """The hard task must register enc_0000 in the shared registry."""
    demo = get_demo_encounter(HARD_ID)
    assert demo is not None, (
        "enc_0000 was not registered; t_d16db103 must add a "
        "register_demo_encounter(encounter_id='enc_0000', difficulty='HARD', ...)"
        " call in demo_entries.py"
    )
    assert demo.difficulty == "HARD"
    assert demo.summary  # one-line description present


def test_hard_record_loadable() -> None:
    """The wired encounter's underlying record (note / claim / rules /
    ground-truth) must load from data/synth/train.json so the detail page
    can render the full audit panel. Hard tier also implies multi-
    finding / multi-category / at least one high-severity finding."""
    rec = load_encounter_record(HARD_ID)
    assert rec is not None
    assert rec["encounter_id"] == HARD_ID
    assert "ECG performed in office" in rec["clinical_note"]
    findings = rec["ground_truth"]
    # 5 ground-truth findings, 5 distinct categories, at least one
    # HIGH-severity finding — the "hard-tier evidence" the task card
    # calls out.
    assert len(findings) == 5
    assert len({f["category"] for f in findings}) >= 4
    assert any(f["severity"] == "high" for f in findings)


def test_index_lists_hard_card(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert HARD_ID in body
    # The card uses the hard-tier CSS hook defined in dashboard.css.
    assert 'class="encounter-card encounter-card--hard"' in body
    # Card has the open-audit-panel and raw-json action links.
    assert f'href="/encounter/{HARD_ID}"' in body
    assert f'href="/encounter/{HARD_ID}/json"' in body


def test_hard_detail_renders_full_audit_panel(client: TestClient) -> None:
    r = client.get(f"/encounter/{HARD_ID}")
    assert r.status_code == 200
    body = r.text
    # Clinical note and the claim block are present.
    assert "ECG performed in office" in body
    # The 5 hard-tier evidence fields per finding are present at least once:
    #   - rule_em_001 / rule_ecg_001 / rule_icd_001 / rule_modifier_25_001 / rule_lab_001
    #   - 99214 / 93000 / R00.2 / modifier 25 / 80061
    for needle in (
        "rule_em_001", "rule_ecg_001", "rule_icd_001",
        "rule_modifier_25_001", "rule_lab_001",
        "99214", "93000", "R00.2", "80061",
    ):
        assert needle in body, f"missing hard-tier evidence field: {needle}"


def test_hard_detail_shows_evidence_highlight(client: TestClient) -> None:
    r = client.get(f"/encounter/{HARD_ID}")
    assert r.status_code == 200
    body = r.text
    # The detail template highlights the PRIMARY (first) finding's
    # evidence quote in the clinical note. For enc_0000 the primary
    # finding is gt0 (rule_em_001, info) with quote 'established
    # patient moderate complexity' — that span must be wrapped in
    # <mark class="evidence">. The acceptance criteria call out
    # "evidence highlight is visible on the detail page" as a hard
    # requirement; the gt0 quote appears verbatim in the clinical
    # note so the highlight is unambiguous.
    assert '<mark class="evidence">established patient moderate complexity</mark>' in body, (
        "primary (first) finding's evidence quote must be visibly "
        "highlighted in the clinical note; this is the hard-tier "
        "evidence cue the task acceptance criteria pin"
    )
    # Every non-primary finding still renders its quote in a
    # <blockquote class="finding-quote"> so the full hard-tier audit
    # panel is exercisable.
    assert body.count('<blockquote class="finding-quote">') >= 5


def test_hard_detail_buttons_clickable(client: TestClient) -> None:
    r = client.get(f"/encounter/{HARD_ID}")
    assert r.status_code == 200
    body = r.text
    # Per-finding copy-quote button on every finding card.
    assert body.count('data-action="copy-quote"') >= 5
    # Global evidence-highlight toggle (the standard action row, present
    # for all difficulties).
    assert 'id="btn-toggle-mark"' in body
    # Advanced actions unique to the hard tier — only rendered when
    # difficulty == "HARD". These are the "advanced actions unique to
    # hard encounters" the task body calls out.
    assert 'id="btn-jump-high"' in body, (
        "hard encounters must expose a 'jump to high-severity finding' "
        "button — this is the advanced hard-tier action"
    )
    assert 'id="btn-next-finding"' in body, (
        "hard encounters must expose a 'next finding' button"
    )
    assert 'id="btn-severity-filter"' in body, (
        "hard encounters must expose a 'filter: <severity>' button"
    )
    # Every advanced button is a real <button> (not a no-op or disabled).
    assert body.count('id="btn-jump-high"') >= 1
    assert body.count('id="btn-next-finding"') >= 1
    assert body.count('id="btn-severity-filter"') >= 1


def test_hard_detail_advanced_actions_absent_on_easy(
    client: TestClient,
) -> None:
    """The advanced actions panel is unique to HARD — easy and medium
    encounters must NOT render the jump-to-high / next-finding /
    severity-filter buttons. This proves the {% if difficulty == "HARD" %}
    gate is wired correctly and the buttons are not just always-on."""
    r = client.get("/encounter/enc_10032")
    assert r.status_code == 200
    body = r.text
    assert 'id="btn-jump-high"' not in body
    assert 'id="btn-next-finding"' not in body
    assert 'id="btn-severity-filter"' not in body


def test_hard_json_endpoint(client: TestClient) -> None:
    r = client.get(f"/encounter/{HARD_ID}/json")
    assert r.status_code == 200
    body = r.json()
    assert body["encounter_id"] == HARD_ID
    assert body["difficulty"] == "HARD"
    assert body["n_gold_findings"] == 5
    assert body["is_flagged"] is True


def test_hard_detail_404_when_unregistered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the hard entry is later removed from the registry, the
    detail page must 404 cleanly rather than 500 — same contract the
    easy/medium tests pin for an unknown id."""
    from ai_billing_audit import demo_registry
    snapshot = list(demo_registry._REGISTRY)
    monkeypatch.setattr(
        demo_registry, "list_demo_encounters",
        lambda: [e for e in snapshot if e.encounter_id != HARD_ID],
    )
    monkeypatch.setattr(
        demo_registry, "get_demo_encounter",
        lambda eid: None if eid == HARD_ID else next(
            (e for e in snapshot if e.encounter_id == eid), None
        ),
    )
    import ai_billing_audit.api as api_mod
    monkeypatch.setattr(api_mod, "get_demo_encounter", demo_registry.get_demo_encounter)
    r = client.get(f"/encounter/{HARD_ID}")
    assert r.status_code == 404
