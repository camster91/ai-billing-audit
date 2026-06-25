"""Tests for clinical-impact doctor-facing surfaces.

Covers the four priority-1 kanban tasks implemented in
``ai_billing_audit.clinical_metrics``:

* t_267a1ad6 — Doctor effectiveness metric
* t_a26d25be — Rejected-fix teaching signal queue + verdict
* t_f5ea3bf2 — Doctor 'fix-it' re-audit queue
* t_17ec5fec — Per-tenant prompt version pinning

Each test enables the matching feature flag first so the route
guards don't 404.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_logs(monkeypatch, tmp_path: Path) -> Iterator[None]:
    """Redirect the four JSONL log files into a tmp dir for the test."""
    monkeypatch.setenv("FEATURE_FLAG_LOG", str(tmp_path / "feature_flags.jsonl"))
    monkeypatch.setenv("FEATURE_FLAG_REGISTRY", str(tmp_path / "feature_flags_registry.json"))
    monkeypatch.setenv("FEEDBACK_LOG", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setenv("CLINIC_PROMPT_PIN_LOG", str(tmp_path / "clinic_pins.jsonl"))
    monkeypatch.setenv("TEACHING_VERDICT_LOG", str(tmp_path / "teaching_verdicts.jsonl"))
    monkeypatch.setenv("REAUDIT_QUEUE_LOG", str(tmp_path / "reaudit_queue.jsonl"))
    yield


def _enable(clinic_id: str, flag: str) -> None:
    from ai_billing_audit import feature_flags

    feature_flags.enable(clinic_id, flag, actor="test")


def test_doctor_effectiveness_insufficient_data(tmp_logs) -> None:
    from ai_billing_audit.clinical_metrics import compute_doctor_effectiveness

    payload = compute_doctor_effectiveness("doctor_1", "clinic_a", feedback_log=[])
    assert payload["status"] == "insufficient_data"
    assert payload["doctor_id"] == "doctor_1"
    assert payload["clinic_id"] == "clinic_a"


def test_doctor_effectiveness_with_feedback(tmp_logs) -> None:
    from ai_billing_audit.clinical_metrics import compute_doctor_effectiveness

    log = [
        {"encounter_id": "e1", "doctor_id": "doctor_1", "action": "accept"},
        {"encounter_id": "e1", "doctor_id": "doctor_1", "action": "dismiss"},
        {"encounter_id": "e2", "doctor_id": "doctor_1", "action": "accept"},
    ]
    payload = compute_doctor_effectiveness("doctor_1", "clinic_a", feedback_log=log)
    assert payload["status"] == "ok"
    # 2 encounters, 3 total = 1.5 flags/encounter
    assert payload["current_quarter_flags_per_encounter"] == 1.5
    assert payload["encounters_with_feedback"] == 2


def test_teaching_queue_and_verdict_round_trip(tmp_logs) -> None:
    from ai_billing_audit import feedback
    from ai_billing_audit.clinical_metrics import (
        TeachingVerdict,
        list_do_not_flag_rules,
        list_teaching_signal_queue,
        record_teaching_verdict,
    )

    # Seed one 'incorrect' feedback entry directly via JSONL.
    # The FeedbackStore dataclass validator rejects 'incorrect' as
    # not in its closed Literal set, but the teaching-signal queue
    # reads the log file directly so it can surface doctor-only rows.
    log_path = Path(os.environ["FEEDBACK_LOG"])
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "encounter_id": "e1",
                    "finding_id": "f1",
                    "action": "incorrect",
                    "doctor_id": "doctor_1",
                    "clinic_id": "clinic_a",
                    "rule_id": "r1",
                    "severity": "low",
                    "category": "documentation",
                    "biller_id": "doctor_1",
                    "timestamp": "2026-06-25T00:00:00Z",
                    "event_id": "fb_1",
                }
            )
            + "\n"
        )

    rows = list_teaching_signal_queue(clinic_id="clinic_a")
    assert len(rows) == 1
    assert rows[0]["action"] == "incorrect"

    # Admin verdict: doctor was right → add to do_not_flag list
    verdict = TeachingVerdict(
        feedback_id="fb_1",
        clinic_id="clinic_a",
        finding_id="f1",
        verdict="doctor_right",
        notes="Modifier-25 is correct here per specialty guidance",
    )
    record_teaching_verdict(verdict)

    rules = list_do_not_flag_rules("clinic_a")
    assert len(rules) == 1
    assert rules[0]["verdict"] == "doctor_right"


def test_reaudit_queue(tmp_logs) -> None:
    from ai_billing_audit.clinical_metrics import list_reaudit_queue, queue_reaudit

    payload = queue_reaudit("enc_a", actor="doctor_1", note="note updated")
    assert payload["status"] == "queued"
    assert payload["encounter_id"] == "enc_a"

    queue = list_reaudit_queue()
    assert len(queue) == 1
    assert queue[0]["actor"] == "doctor_1"


def test_prompt_pin_round_trip(tmp_logs) -> None:
    from ai_billing_audit.clinical_metrics import (
        get_pinned_prompt_version,
        list_pinned_clinics,
        pin_prompt_version,
    )

    # Initially no pin
    assert get_pinned_prompt_version("clinic_a") is None

    pin_prompt_version("clinic_a", "v12", actor="admin")
    assert get_pinned_prompt_version("clinic_a") == "v12"

    # Re-pin to v13 overwrites
    pin_prompt_version("clinic_a", "v13", actor="admin")
    assert get_pinned_prompt_version("clinic_a") == "v13"

    pinned = list_pinned_clinics()
    assert pinned["clinic_a"] == "v13"


@pytest.mark.parametrize(
    "route,flag_name",
    [
        ("/api/doctor/doctor_1/effectiveness?clinic_id=clinic_a", "doctor_effectiveness_metric"),
        ("/api/admin/teaching-signal-queue?clinic_id=clinic_a", "rejected_fix_teaching_signal"),
    ],
)
def test_routes_wired_and_flag_gated(tmp_logs, route: str, flag_name: str) -> None:
    from fastapi.testclient import TestClient

    from ai_billing_audit import feature_flags
    from ai_billing_audit.api import create_app

    # Force the feature_flags module to honour the test's tmp path
    # (it captured _LOG_PATH at import time).
    feature_flags._LOG_PATH = Path(os.environ["FEATURE_FLAG_LOG"])  # noqa: SLF001

    app = create_app()
    client = TestClient(app)

    # Feature flag off → 404
    resp = client.get(route)
    assert resp.status_code == 404

    # Enable flag and re-check
    _enable("clinic_a", flag_name)
    resp = client.get(route)
    assert resp.status_code == 200, resp.text


def test_reaudit_route_not_flag_gated(tmp_logs) -> None:
    """Re-audit queue is for the doctor's own dashboard — not gated."""
    from fastapi.testclient import TestClient

    from ai_billing_audit.api import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/encounter/enc_a/re-audit?note=updated&actor=doctor_1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"


def test_prompt_version_put_flag_gated(tmp_logs) -> None:
    """PUT prompt-version requires the per_tenant_prompt_version flag."""
    from fastapi.testclient import TestClient

    from ai_billing_audit import feature_flags
    from ai_billing_audit.api import create_app

    feature_flags._LOG_PATH = Path(os.environ["FEATURE_FLAG_LOG"])  # noqa: SLF001

    app = create_app()
    client = TestClient(app)

    # GET is always 200 (read-only inspection).
    resp = client.get("/api/clinic/clinic_a/prompt-version")
    assert resp.status_code == 200

    # PUT is gated
    resp = client.put("/api/clinic/clinic_a/prompt-version?prompt_version_id=v12")
    assert resp.status_code == 404

    _enable("clinic_a", "per_tenant_prompt_version")
    resp = client.put("/api/clinic/clinic_a/prompt-version?prompt_version_id=v12")
    assert resp.status_code == 200, resp.text
    assert resp.json()["prompt_version_id"] == "v12"
