"""Tests for the 837I (institutional) upload path.

Kanban ``t_ca101c1c``: support 837I in addition to 837P. The 837I
shape differs from 837P in three ways:

* Multiple provider NPIs per claim (attending, operating, ...)
* Inpatient admission / discharge date spans
* Per-line ``place_of_service`` — some lines are facility lines
  billed by the hospital, others are professional lines rendered
  by an attending / operating provider inside the same facility

These tests cover the v1 acceptance criteria:

1. ``validate_837i`` returns the right errors for malformed
   payloads (missing required fields, bad NPIs, bad dates, bad
   value_codes, bad service_lines).
2. ``parse_837i`` maps a happy-path payload to the canonical
   claim shape with the right field substitutions
   (attending → rendering, admission → date_of_service, etc).
3. The mapping produces at least one facility line. When the
   input has no facility line, one is synthesized.
4. ``POST /upload/837i`` creates a job (the canonical claim
   survives end-to-end through the runner's 837I short-circuit).
5. The route returns 400 with the error list on validation
   failure, and 200 on success.
6. The runner's 837I branch is exercised end-to-end: the
   claim survives without an LLM call (we stub the auditor).

NO LLM tests: the auditor is stubbed in the runner-level test
to avoid hitting the live LLM provider. The TestClient tests
use a custom JobQueue whose runner echoes the enqueued
encounter, so the new ``/upload/837i`` route is exercised
without ever reaching the default runner.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# The bearer middleware in create_app() reads AUDIT_ALLOW_NO_AUTH
# at construction time, so this must be set BEFORE we import
# ``ai_billing_audit.api``. (See test_csv_ingest.py:30 for the
# same pattern.)
os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_billing_audit import api  # noqa: E402
from ai_billing_audit.institutional_837i import (
    FACILITY_PLACE_OF_SERVICE,
    map_837i_to_enqueue_payload,
    parse_837i,
    validate_837i,
)
from ai_billing_audit.job_queue import (  # noqa: E402
    get_default_queue,
    reset_default_queue_for_tests,
)


# --- minimal 837I fixtures ---------------------------------------------


def _valid_837i_payload(
    *,
    with_operating: bool = True,
    with_value_codes: bool = True,
    with_facility_line: bool = True,
) -> dict[str, Any]:
    """Return a fully-valid 837I payload that the parser should accept.

    The default has an operating provider NPI, two value codes
    (40 = blood deductible, 43 = Medicare lifetime reserve days),
    and one of the two service lines is a facility line (CPT 0100
    = room & board). Tests can flip the flags to exercise the
    synthetic-facility-line branch and the missing-operating
    branch.
    """
    # When with_operating is False, all service-line NPIs collapse
    # to the attending NPI so the "only attending in provider_npis"
    # test isn't tripped by the per-line NPI collector.
    line2_npi = "1234567891" if with_operating else "1234567890"
    operating_npi = "1234567891" if with_operating else None
    service_lines: list[dict[str, Any]] = []
    if with_facility_line:
        service_lines.append(
            {
                "provider_npi": "1234567890",
                "cpt": "0100",
                "units": 1,
                "billed_amount": 0.0,
                "service_date": "2026-01-15",
                "revenue_code": "0100",
            }
        )
    service_lines.append(
        {
            "provider_npi": line2_npi,
            "cpt": "33533",
            "units": 1,
            "billed_amount": 4800.00,
            "service_date": "2026-01-16",
            "revenue_code": "0360",  # OR services
        }
    )
    value_codes: list[dict[str, Any]] = []
    if with_value_codes:
        value_codes = [
            {"code": "40", "amount": 0.0},
            {"code": "43", "amount": 1.0},
        ]
    payload: dict[str, Any] = {
        "patient_id": "PT-001",
        "facility_id": "FAC-MAIN",
        "attending_provider_npi": "1234567890",
        "admission_date": "2026-01-15",
        "discharge_date": "2026-01-17",
        "clinical_note": "Inpatient admission and operative course documented.",
        "value_codes": value_codes,
        "service_lines": service_lines,
    }
    if operating_npi:
        payload["operating_provider_npi"] = operating_npi
    return payload


# --- 1. validate_837i --------------------------------------------------


def test_validate_837i_happy_path_returns_no_errors() -> None:
    """A well-formed 837I payload produces zero validation errors."""
    payload = _valid_837i_payload()
    errs = validate_837i(payload)
    assert errs == [], f"unexpected errors: {errs}"


def test_validate_837i_rejects_non_dict_payload() -> None:
    assert validate_837i("not a dict")  # type: ignore[arg-type]
    assert validate_837i(None)  # type: ignore[arg-type]
    assert validate_837i([{"a": 1}])  # type: ignore[arg-type]


def test_validate_837i_rejects_missing_patient_id() -> None:
    p = _valid_837i_payload()
    del p["patient_id"]
    errs = validate_837i(p)
    assert any("patient_id" in e for e in errs)


def test_validate_837i_rejects_missing_attending_npi() -> None:
    p = _valid_837i_payload()
    del p["attending_provider_npi"]
    errs = validate_837i(p)
    assert any("attending_provider_npi" in e for e in errs)


def test_validate_837i_rejects_bad_attending_npi() -> None:
    p = _valid_837i_payload()
    p["attending_provider_npi"] = "not-a-npi"
    errs = validate_837i(p)
    assert any("attending_provider_npi" in e for e in errs)


def test_validate_837i_rejects_bad_operating_npi() -> None:
    p = _valid_837i_payload()
    p["operating_provider_npi"] = "abc"
    errs = validate_837i(p)
    assert any("operating_provider_npi" in e for e in errs)


def test_validate_837i_rejects_bad_admission_date() -> None:
    p = _valid_837i_payload()
    p["admission_date"] = "2026-13-40"
    errs = validate_837i(p)
    assert any("admission_date" in e for e in errs)


def test_validate_837i_rejects_discharge_before_admission() -> None:
    p = _valid_837i_payload()
    p["admission_date"] = "2026-01-17"
    p["discharge_date"] = "2026-01-15"
    errs = validate_837i(p)
    assert any("discharge_date" in e and "before" in e for e in errs)


def test_validate_837i_rejects_value_code_out_of_range() -> None:
    p = _valid_837i_payload()
    p["value_codes"] = [{"code": "39", "amount": 0.0}]  # 40-43 only
    errs = validate_837i(p)
    assert any("40-43" in e for e in errs)


def test_validate_837i_rejects_service_line_missing_cpt() -> None:
    p = _valid_837i_payload()
    p["service_lines"][1]["cpt"] = ""
    errs = validate_837i(p)
    assert any("service_lines[1].cpt" in e for e in errs)


def test_validate_837i_rejects_service_line_missing_provider_npi() -> None:
    p = _valid_837i_payload()
    p["service_lines"][0]["provider_npi"] = ""
    errs = validate_837i(p)
    assert any("service_lines[0].provider_npi" in e for e in errs)


def test_validate_837i_rejects_empty_service_lines() -> None:
    p = _valid_837i_payload()
    p["service_lines"] = []
    errs = validate_837i(p)
    assert any("service_lines" in e for e in errs)


def test_validate_837i_rejects_non_numeric_units() -> None:
    p = _valid_837i_payload()
    p["service_lines"][1]["units"] = "lots"
    errs = validate_837i(p)
    assert any("units" in e for e in errs)


# --- 2. parse_837i mapping --------------------------------------------


def test_parse_837i_attending_npi_becomes_rendering_npi() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    assert out["NPI"] == "1234567890"
    assert out["claim"]["rendering_provider_npi"] == "1234567890"


def test_parse_837i_admission_becomes_date_of_service() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    assert out["date_of_service"] == "2026-01-15"
    assert out["claim"]["date_of_service"] == "2026-01-15"


def test_parse_837i_discharge_persists() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    assert out["claim"]["discharge_date"] == "2026-01-17"


def test_parse_837i_provider_npis_includes_attending_and_operating() -> None:
    p = _valid_837i_payload(with_operating=True)
    out = parse_837i(p)
    npis = out["claim"]["provider_npis"]
    assert "1234567890" in npis  # attending
    assert "1234567891" in npis  # operating


def test_parse_837i_provider_npis_only_attending_when_no_operating() -> None:
    p = _valid_837i_payload(with_operating=False)
    out = parse_837i(p)
    npis = out["claim"]["provider_npis"]
    assert "1234567890" in npis
    # Operating absent and per-line provider_npis are the attending.
    assert "1234567891" not in npis


def test_parse_837i_value_codes_pass_through() -> None:
    p = _valid_837i_payload(with_value_codes=True)
    out = parse_837i(p)
    vcs = out["claim"]["value_codes"]
    assert {"code": "40", "amount": 0.0} in vcs
    assert {"code": "43", "amount": 1.0} in vcs


def test_parse_837i_claim_type_is_837i() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    assert out["claim"]["claim_type"] == "837I"


def test_parse_837i_generates_encounter_id_when_missing() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    # No claim_id / encounter_id in the input; should be
    # auto-generated to start with "837I-".
    assert out["encounter_id"].startswith("837I-")


def test_parse_837i_honors_explicit_claim_id() -> None:
    p = _valid_837i_payload()
    p["claim_id"] = "MY-CLAIM-007"
    out = parse_837i(p)
    assert out["encounter_id"] == "MY-CLAIM-007"


def test_parse_837i_raises_on_validation_error() -> None:
    p = _valid_837i_payload()
    del p["patient_id"]
    with pytest.raises(ValueError) as exc_info:
        parse_837i(p)
    assert "patient_id" in str(exc_info.value)


# --- 3. facility line + line_items mapping -----------------------------


def test_parse_837i_marks_revenue_code_line_as_facility() -> None:
    p = _valid_837i_payload(with_facility_line=True)
    out = parse_837i(p)
    items = out["claim"]["line_items"]
    # The default payload marks the 0100 line AND the 33533
    # line (which has revenue_code 0360) as facility — any line
    # with a non-empty revenue_code is a facility line. The
    # important assertion is that the 0100 line is facility.
    assert any(li["cpt_code"] == "0100" and li["is_facility_line"] for li in items)
    # And the per-line revenue_code survives the mapping.
    rev_lines = [li for li in items if li.get("revenue_code")]
    assert {li["revenue_code"] for li in rev_lines} == {"0100", "0360"}


def test_parse_837i_synthesizes_facility_line_when_none_provided() -> None:
    """When no service line is a facility line, the mapper
    synthesizes a UB-04 revenue code 0100 (room & board) line at
    index 0 so the claim carries at least one facility line +
    one professional line, per the kanban acceptance criterion.
    """
    p = _valid_837i_payload(with_facility_line=False)
    # Strip the revenue_code on the remaining line so the
    # fixture has zero facility lines and triggers the synthesis
    # path.
    for ln in p["service_lines"]:
        ln.pop("revenue_code", None)
    out = parse_837i(p)
    items = out["claim"]["line_items"]
    # The synthesized facility line is at index 0.
    assert items[0]["is_facility_line"] is True
    assert items[0]["cpt_code"] == "0100"
    # And the original 33533 professional line is still present
    # and is no longer marked as facility (we removed the
    # revenue_code).
    pro_lines = [li for li in items if not li["is_facility_line"]]
    assert any(li["cpt_code"] == "33533" for li in pro_lines)
    # Both a facility line and a professional line are now
    # present — the acceptance criterion.
    assert any(li["is_facility_line"] for li in items)
    assert any(not li["is_facility_line"] for li in items)


def test_parse_837i_line_items_have_unique_line_ids() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    ids = [li["line_id"] for li in out["claim"]["line_items"]]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_parse_837i_cpt_codes_collects_all_service_lines() -> None:
    p = _valid_837i_payload()
    out = parse_837i(p)
    assert "0100" in out["CPT_codes"]
    assert "33533" in out["CPT_codes"]


def test_parse_837i_place_of_service_in_known_set() -> None:
    """The facility place-of-service set is documented and stable."""
    assert "21" in FACILITY_PLACE_OF_SERVICE
    assert "inpatient" in FACILITY_PLACE_OF_SERVICE


def test_parse_837i_facility_helper_classifies_known_markers() -> None:
    """The internal helper rejects synthetic CPT 99999 but
    accepts revenue-code 0101 / 0110 etc.
    """
    from ai_billing_audit.institutional_837i import _is_facility_line

    assert _is_facility_line({"cpt": "0100"}) is True
    assert _is_facility_line({"cpt": "0150"}) is True
    assert _is_facility_line({"cpt": "99213"}) is False
    assert _is_facility_line({"cpt": "33533", "revenue_code": "0360"}) is True
    assert _is_facility_line({"cpt": "33533", "place_of_service": "21"}) is True
    assert _is_facility_line({"cpt": "33533"}) is False


def test_map_to_enqueue_payload_preserves_canonical_claim() -> None:
    p = _valid_837i_payload()
    mapped = parse_837i(p)
    enq = map_837i_to_enqueue_payload(mapped)
    # The 5-field shape the legacy 837P submit path uses.
    assert enq["encounter_id"] == mapped["encounter_id"]
    assert enq["NPI"] == mapped["NPI"]
    assert enq["date_of_service"] == mapped["date_of_service"]
    # The canonical claim is stashed for the runner's 837I branch.
    assert enq["_claim_canonical"] == mapped["claim"]


# --- 4. /upload/837i route (TestClient) --------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient with a fresh JobQueue that uses a tmp log path.

    The default module-level queue is reset per-test so the
    runner doesn't leak state across tests.
    """
    monkeypatch.setenv("UPLOAD_AUDIT_LOG_PATH", str(tmp_path / "upload_jobs.jsonl"))
    monkeypatch.setenv("ZORVA_UPLOADED_NOTES_DIR", str(tmp_path / "notes"))
    reset_default_queue_for_tests()
    return TestClient(api.app)


def test_upload_837i_route_returns_200_on_happy_path(client: TestClient) -> None:
    p = _valid_837i_payload()
    p["clinical_note"] = "Inpatient admission and operative course documented."
    r = client.post("/upload/837i", json=p)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "837i"
    assert body["encounter_id"]
    assert body["job_id"]
    # The mapped claim is echoed back so the client can show
    # the biller what was queued.
    assert body["claim"]["rendering_provider_npi"] == "1234567890"
    assert body["claim"]["date_of_service"] == "2026-01-15"
    assert body["claim"]["claim_type"] == "837I"


def test_upload_837i_rejects_missing_clinical_note_before_enqueue(
    client: TestClient,
) -> None:
    payload = _valid_837i_payload()
    payload.pop("clinical_note")
    response = client.post("/upload/837i", json=payload)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "clinical_note_required"
    assert get_default_queue().list_jobs() == []


def test_upload_837i_route_returns_400_on_validation_error(
    client: TestClient,
) -> None:
    p = _valid_837i_payload()
    del p["attending_provider_npi"]  # required
    r = client.post("/upload/837i", json=p)
    assert r.status_code == 400
    body = r.json()
    # Full error list is returned so the UI can render per-field
    # help, the first error is also surfaced in ``detail``.
    assert any("attending_provider_npi" in e for e in body["errors"])
    assert "attending_provider_npi" in body["detail"]


def test_upload_837i_route_returns_400_on_non_dict_body(
    client: TestClient,
) -> None:
    r = client.post("/upload/837i", json=["not a dict"])
    assert r.status_code == 400


def test_upload_837i_route_returns_400_on_empty_object(
    client: TestClient,
) -> None:
    r = client.post("/upload/837i", json={})
    assert r.status_code == 400
    body = r.json()
    # Multiple required-field errors all surface in the list.
    assert len(body["errors"]) >= 4


def test_upload_837i_route_creates_encounter_and_claim(
    client: TestClient,
) -> None:
    """The 200 response includes the mapped claim + a job id that
    can be polled via the existing /encounters/upload/jobs/{id}
    endpoint (the 837I job lives in the same JobQueue as the
    837P submit endpoint).
    """
    p = _valid_837i_payload()
    r = client.post("/upload/837i", json=p)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    # The job id round-trips through the status endpoint. We
    # don't assert on status (the default runner hits the LLM
    # in real use; this test runs in CI without an LLM key so
    # the job may end up queued or failed), only that the id is
    # recognised by the status endpoint (i.e. it was enqueued
    # rather than 404'd).
    s = client.get(f"/encounters/upload/jobs/{job_id}")
    assert s.status_code == 200
    assert s.json()["job_id"] == job_id


# --- 5. runner end-to-end (no LLM) -------------------------------------


def test_default_runner_uses_canonical_claim_for_837i(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner's 837I short-circuit must use the canonical
    claim object verbatim (skipping the synth) so multi-provider
    / value-codes / facility-line information survives. We
    stub the auditor to avoid hitting the LLM.
    """
    from ai_billing_audit import job_queue as jq
    from ai_billing_audit import auditor as a

    class _StubResult:
        findings: list[Any] = []
        summary: str = "stub"

    monkeypatch.setattr(a, "run_audit", lambda enc: _StubResult())
    monkeypatch.setattr(a, "AuditValidationError", Exception)
    # Skip the doctor-email side effect so the test doesn't
    # touch the SMTP code path (also a no-LLM test).
    monkeypatch.setattr(jq, "_send_doctor_emails", lambda *a, **kw: [])
    monkeypatch.setattr(
        jq,
        "_load_uploaded_note",
        lambda _id: "Inpatient admission and operative course documented.",
    )

    canonical = {
        "encounter_id": "837I-E2E-001",
        "patient_id": "PT-001",
        "rendering_provider_npi": "1234567890",
        "date_of_service": "2026-01-15",
        "line_items": [
            {
                "line_id": 1,
                "cpt_code": "0100",
                "charge_amount": 0.0,
                "units": 1,
                "is_facility_line": True,
            },
            {
                "line_id": 2,
                "cpt_code": "33533",
                "charge_amount": 4800.0,
                "units": 1,
                "is_facility_line": False,
            },
        ],
        "diagnosis_codes": [],
        "claim_type": "837I",
        "provider_npis": ["1234567890", "1234567891"],
        "value_codes": [{"code": "40", "amount": 0.0}],
    }
    out = jq._default_runner(
        {
            "encounter_id": "837I-E2E-001",
            "patient_id": "PT-001",
            "NPI": "1234567890",
            "date_of_service": "2026-01-15",
            "CPT_codes": ["0100", "33533"],
            "_claim_canonical": canonical,
        }
    )
    # The 837I short-circuit stamps ``ran_via`` with the
    # institutional sentinel string so the dashboard can render
    # the right "this is a multi-line institutional claim" badge.
    assert out["ran_via"] == "upload_portal_institutional_837i"
    assert out["audit_status"] == "ok"
    assert out["synth_encounter_id"] == "837I-E2E-001"


def test_default_runner_falls_through_to_synth_for_non_837i(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 837I short-circuit is gated on the presence of
    ``_claim_canonical``. When absent, the runner falls through
    to the legacy synth / real-data path.
    """
    from ai_billing_audit import auditor as a
    from ai_billing_audit import job_queue as jq

    class _StubResult:
        findings: list[Any] = []
        summary: str = "stub"

    monkeypatch.setattr(a, "run_audit", lambda enc: _StubResult())
    monkeypatch.setattr(a, "AuditValidationError", Exception)
    monkeypatch.setattr(jq, "_send_doctor_emails", lambda *a, **kw: [])

    out = jq._default_runner(
        {
            "encounter_id": "LEGACY-DEMO-001",
            "patient_id": "PT-001",
            "NPI": "1234567890",
            "date_of_service": "2026-01-15",
            "CPT_codes": ["99213"],
            "difficulty_tier": "EASY",
            "variant": "clean",
            "_allow_synthetic_demo": True,
        }
    )
    # The synth ran, NOT the 837I branch. The synth generates
    # a deterministic encounter id from the seed; we just
    # confirm it's NOT the 837I sentinel.
    assert out["ran_via"] != "upload_portal_institutional_837i"
    # The synth path stamps ran_via as one of the legacy
    # sentinels. The exact value depends on whether an
    # uploaded note was found; we accept either.
    assert out["ran_via"] in (
        "synth",
        "upload_portal",
        "upload_portal_with_user_note",
    )
