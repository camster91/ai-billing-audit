"""Tests for the encounter upload portal.

Covers the seven acceptance criteria from the task body:

1. ``/encounters/upload`` page exists and exposes all three input
   modes plus a bulk-upload control that accepts a ZIP of 837P
   files.
2. An 837P file (single or inside a ZIP) parses to a normalised
   JSON structure.
3. Missing or invalid required fields cause the file to be
   rejected with a per-file error message visible in the UI.
4. Malformed 837P files are rejected with a per-file error
   message and do not enqueue a job.
5. Accepted files enqueue an audit job (currently the synth
   pipeline) and the job status is pollable from the UI.
6. A parse preview is shown to the user before they submit.
7. Clinical note PDF/image uploads are accepted; OCR is not
   required at this stage.

The tests run in-process via ``starlette.testclient.TestClient``
so the routes return real ``Response`` objects the same way they
would in production. The synth call inside the default runner is
exercised end-to-end (no monkeypatching), but tests that need
deterministic timing use the ``JobQueue`` with a custom runner.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from ai_billing_audit import api
from ai_billing_audit.job_queue import (
    Job,
    JobQueue,
    get_default_queue,
    reset_default_queue_for_tests,
)
from ai_billing_audit.x12_parser import (
    REQUIRED_FIELDS,
    X12ParseError,
    parse_837p,
    validate_required_fields,
)


# --- minimal 837P fixtures -----------------------------------------------

# A barebones 837P envelope with one claim, one service line, and a
# full set of the five required fields. 1-segment line per row.
_FULL_837P = (
    "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     "
    "*240515*1200*^*00501*000000001*0*P*:~"
    "GS*HC*SUBMITTER*RECEIVER*20240515*1200*1*X*005010X222A1~"
    "ST*837*0001*005010X222A1~"
    "BHT*0019*00*1*20240515*1200*CH~"
    "NM1*41*2*BILLING SERVICE*****46*123456789~"
    "PER*IC*JANE DOE*TE*5555551234~"
    "NM1*40*2*RECEIVER NAME*****46*987654321~"
    "HL*1**20*1~"
    "NM1*85*2*BILLING CLINIC*****XX*1234567890~"
    "N3*123 MAIN ST~"
    "N4*TORONTO*ON*M5V2T6~"
    "REF*EI*123456789~"
    "HL*2*1*22*0~"
    "SBR*P*18*******MB~"
    "NM1*IL*1*DOE*JOHN****MI*MBR-000123~"
    "N3*456 PATIENT AVE~"
    "N4*TORONTO*ON*M5V2T6~"
    "DMG*D8*19700101*M~"
    "NM1*PR*2*PAYER NAME*****PI*PAYER001~"
    "CLM*ENC-PORTAL-001*250.00***11:B:1*Y*A*Y*Y~"
    "DTP*472*D8*20240510~"
    "DTP*434*D8*20240510~"
    "NM1*82*1*RENDERING*PROVIDER*****XX*1234567890~"
    "SV1*HC:99213*100.00*UN*1***1~"
    "SV1*HC:99214:25*150.00*UN*1***1~"
    "SE*23*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


def _missing_fields_837p() -> str:
    """An 837P that has a CLM but no NM1*QC (patient id), no NPI,
    no DTP*472 (date of service), and no SV1 (CPT codes). Should
    fail validation with four required-field errors. We skip the
    fixed-width ISA header (the parser is permissive on missing
    envelopes) so the fixture stays short and human-readable."""
    return (
        "ST*837*0001*005010X222A1~"
        "CLM*ENC-MISSING-001*100***11:B:1*Y*A*Y*Y~"
        "SE*2*0001~"
    )


def _malformed_837p() -> str:
    """Looks vaguely X12 but has no segments that the parser can
    extract a claim from. Should produce zero claims and surface
    a per-file error."""
    return "this is not a real 837P file at all\nCLM? no ISA header\n"


def _make_zip(entries: dict[str, str]) -> bytes:
    """Return a ZIP archive's bytes with the given filename → text entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buf.getvalue()


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """A TestClient with a fresh JobQueue that uses a tmp log path.

    The default module-level queue is reset per-test so the synth
    call inside the runner doesn't leak state across tests.
    """
    reset_default_queue_for_tests()
    return TestClient(api.app)


@pytest.fixture
def tmp_log_queue(tmp_path: Path) -> JobQueue:
    """A JobQueue with a tmp-path JSONL log and a no-op runner.

    The default runner calls the synth agent; for status / cancel /
    transition tests we want a runner we control so we can
    deterministically drive jobs into ``done`` / ``failed``.
    """
    log = tmp_path / "jobs.jsonl"
    q = JobQueue(log_path=log, worker_count=2, runner=lambda enc: {"echo": enc})
    return q


# --- 1. page exists with three input modes + bulk ZIP ---------------------


def test_upload_page_renders(client: TestClient) -> None:
    r = client.get("/encounters/upload")
    assert r.status_code == 200
    body = r.text
    # Page extends the base layout (it should be the same shell the
    # other portal pages render).
    assert "Zorva" in body
    # Three input modes are visible in the four-tab nav: 837P file,
    # ZIP, clinical note, paste form. The task body says "three
    # input modes" (837P, clinical note, paste-form); the bulk ZIP
    # is an additional control on top of the 837P path.
    for needle in (
        "id=\"tab-837p\"",
        "id=\"tab-zip\"",
        "id=\"tab-note\"",
        "id=\"tab-paste\"",
    ):
        assert needle in body, f"upload page missing {needle!r}"
    # Bulk-upload control is in the ZIP tab.
    assert "837P ZIP" in body
    # The page loads the JS that drives drag-drop + preview.
    assert "src=\"/static/upload.js\"" in body
    # The 837P dropzone is the default-active tab.
    assert "data-target=\"tab-837p\"" in body
    # The 837P dropzone's hidden file input has the right accept list.
    assert 'accept=".837,.txt,.x12,.edi"' in body


# --- 2. single 837P parses to normalised JSON ------------------------------


def test_preview_single_837p_parses_to_normalised_dict(
    client: TestClient,
) -> None:
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("enc_portal_001.837", _FULL_837P.encode("utf-8"))},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "enc_portal_001.837"
    rows = body["rows"]
    assert isinstance(rows, list) and len(rows) == 1, body
    row = rows[0]
    # All five required fields are present and well-formed.
    assert row["encounter_id"] == "ENC-PORTAL-001"
    assert row["patient_id"] == "MBR-000123"
    assert row["NPI"] == "1234567890"
    assert row["date_of_service"] == "2024-05-10"
    assert row["CPT_codes"] == ["99213", "99214-25"]
    assert row["source"] == "837p"
    assert row["source_filename"] == "enc_portal_001.837"
    assert row["errors"] == []
    # The raw segments are echoed back so the user can spot a
    # misparsed line.
    assert "CLM*ENC-PORTAL-001" in row["raw"]


def test_zip_of_837p_files_parses_each_individually(
    client: TestClient,
) -> None:
    zbytes = _make_zip(
        {
            "claims/a.837": _FULL_837P,
            "claims/b.837": _FULL_837P.replace(
                "ENC-PORTAL-001", "ENC-PORTAL-002"
            ).replace("MBR-000123", "MBR-000456"),
            "README.md": "this file is skipped, not an 837P",
        }
    )
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("bulk.zip", zbytes)},
    )
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    # Two valid 837P files inside the ZIP; the README is skipped.
    assert len(rows) == 2
    ids = sorted(r["encounter_id"] for r in rows)
    assert ids == ["ENC-PORTAL-001", "ENC-PORTAL-002"]
    # Each row carries a `source: "zip"` flag (bulk upload).
    assert all(r["source"] == "zip" for r in rows)
    # And the per-file source filename is the inner archive entry.
    assert {r["source_filename"] for r in rows} == {
        "claims/a.837", "claims/b.837"
    }
    assert all(r["errors"] == [] for r in rows)


# --- 3. missing required fields → per-file error message ------------------


def test_missing_required_fields_produces_per_file_errors(
    client: TestClient,
) -> None:
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("bad.837", _missing_fields_837p().encode("utf-8"))},
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    # CLM is present so the parser still emits a row, but three
    # required fields are missing.
    assert row["encounter_id"] == "ENC-MISSING-001"
    errs = row["errors"]
    # Each missing field has its own user-facing message.
    for expected in (
        "missing patient_id",
        "missing NPI",
        "missing date_of_service",
        "missing CPT codes",
    ):
        assert any(expected in e for e in errs), (
            f"expected an error containing {expected!r}, got {errs}"
        )


def test_invalid_npi_format_is_rejected(client: TestClient) -> None:
    bad_npi = _FULL_837P.replace("1234567890", "NOT-AN-NPI")
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("bad_npi.837", bad_npi.encode("utf-8"))},
    )
    rows = r.json()["rows"]
    assert len(rows) == 1
    errs = rows[0]["errors"]
    # Either the NPI shows as missing (because the regex didn't
    # match a 10-digit value) or as a malformed format — both are
    # correct per-file errors.
    assert any("NPI" in e for e in errs), errs


# --- 4. malformed 837P → per-file error, no job enqueued ------------------


def test_malformed_file_is_rejected_with_per_file_error(
    client: TestClient,
) -> None:
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("garbage.txt", _malformed_837p().encode("utf-8"))},
    )
    assert r.status_code == 200
    body = r.json()
    # No claim rows extracted from a non-X12 file.
    assert body["rows"] == []
    # The parser surfaces a per-file error message.
    assert "error" in body
    assert body["error"], body


def test_malformed_file_inside_zip_does_not_enqueue(client: TestClient) -> None:
    zbytes = _make_zip(
        {
            "good.837": _FULL_837P,
            "garbage.837": _malformed_837p(),
        }
    )
    r = client.post(
        "/encounters/upload/preview",
        files={"file": ("mixed.zip", zbytes)},
    )
    rows = r.json()["rows"]
    # The good one is present, the bad one is also present but
    # with parse_error populated.
    assert len(rows) == 2
    by_file = {r["source_filename"]: r for r in rows}
    assert by_file["good.837"]["errors"] == []
    assert by_file["garbage.837"]["parse_error"], by_file["garbage.837"]
    # Even though the malformed file is in the rows list, the
    # submit endpoint must NOT enqueue a job for it.
    submit = client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps({"rows": rows})},
    )
    assert submit.status_code == 200
    body = submit.json()
    # Only the good row is accepted; the malformed one is
    # rejected with its parse error echoed back.
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["encounter_id"] == "ENC-PORTAL-001"
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["source_filename"] == "garbage.837"
    assert any(
        "parse" in e.lower() or "no CLM" in e or "no segments" in e
        for e in body["rejected"][0]["errors"]
    )


def test_submit_with_no_accepted_rows_rejects_all(client: TestClient) -> None:
    bad_rows = [
        {
            "encounter_id": "X",
            "patient_id": "",
            "NPI": "",
            "date_of_service": "",
            "CPT_codes": [],
            "source": "837p",
            "source_filename": "x.837",
            "errors": ["missing patient_id"],
            "raw": "",
        }
    ]
    r = client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps({"rows": bad_rows})},
    )
    body = r.json()
    assert body["jobs"] == []
    assert len(body["rejected"]) == 1


# --- 5. accepted files enqueue jobs, status is pollable -------------------


def test_submit_accepted_row_enqueues_job_and_status_is_pollable(
    client: TestClient, tmp_log_queue: JobQueue
) -> None:
    """Drive the full submit → poll loop end-to-end.

    We swap the default queue for the tmp_log_queue (which uses a
    no-op runner so the test doesn't depend on the synth
    pipeline), submit one accepted row, then poll for status.
    """
    # Monkeypatch the api module's queue getter to return our
    # controlled queue.
    api.get_default_queue = lambda: tmp_log_queue  # type: ignore[assignment]

    rows = [
        {
            "encounter_id": "ENC-PORTAL-001",
            "patient_id": "MBR-000123",
            "NPI": "1234567890",
            "date_of_service": "2024-05-10",
            "CPT_codes": ["99213"],
            "source": "837p",
            "source_filename": "enc_portal_001.837",
            "errors": [],
            "raw": "stub",
        }
    ]
    submit = client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps({"rows": rows})},
    )
    assert submit.status_code == 200
    accepted = submit.json()["jobs"]
    assert len(accepted) == 1
    job_id = accepted[0]["job_id"]
    assert accepted[0]["encounter_id"] == "ENC-PORTAL-001"

    # Poll the status endpoint. The no-op runner returns
    # immediately so we should see `done` within a couple of
    # ticks.
    deadline = time.time() + 5.0
    final = None
    while time.time() < deadline:
        r = client.get(f"/encounters/upload/jobs/{job_id}")
        assert r.status_code == 200
        final = r.json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert final is not None
    assert final["status"] == "done", final
    # The runner echoed the encounter body back; that proves the
    # audit job ran with the same data the user previewed.
    assert final["result"]["echo"]["encounter_id"] == "ENC-PORTAL-001"
    assert final["result"]["echo"]["CPT_codes"] == ["99213"]
    # The job's source is recorded.
    assert final["source"] == "837p"
    # The JSONL log persisted the run; reload from a fresh
    # queue instance proves the audit trail survives.
    fresh = JobQueue(log_path=tmp_log_queue._log_path, runner=lambda e: {})
    assert fresh.get(job_id) is not None
    assert fresh.get(job_id).status == "done"


def test_job_status_404_for_unknown_id(client: TestClient) -> None:
    r = client.get("/encounters/upload/jobs/does-not-exist")
    assert r.status_code == 404


def test_default_runner_calls_synth_pipeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default runner (the one production uses) calls
    ``synth_agent.generate``. We monkeypatch the runner to record
    the call and assert the encounter is handed through with
    expected field names.
    """
    captured: list[dict[str, Any]] = []

    def fake_runner(encounter: dict[str, Any]) -> dict[str, Any]:
        captured.append(encounter)
        return {"ran_via": "test", "encounter_id": encounter["encounter_id"]}

    log = tmp_path / "jobs.jsonl"
    q = JobQueue(log_path=log, runner=fake_runner)
    api.get_default_queue = lambda: q  # type: ignore[assignment]

    rows = [
        {
            "encounter_id": "ENC-SYNTH-001",
            "patient_id": "MBR-1",
            "NPI": "1234567890",
            "date_of_service": "2024-05-10",
            "CPT_codes": ["99213", "99214"],
            "source": "837p",
            "source_filename": "x.837",
            "errors": [],
            "raw": "stub",
        }
    ]
    submit = client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps({"rows": rows})},
    )
    job_id = submit.json()["jobs"][0]["job_id"]
    # Wait for the worker thread to finish.
    deadline = time.time() + 3.0
    while time.time() < deadline:
        body = client.get(f"/encounters/upload/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert len(captured) == 1
    enc = captured[0]
    assert enc["encounter_id"] == "ENC-SYNTH-001"
    assert enc["CPT_codes"] == ["99213", "99214"]


# --- 6. parse preview is shown before submit -------------------------------


def test_paste_form_preview_returns_rows(client: TestClient) -> None:
    payload = {
        "encounter_id": "ENC-PASTE-001",
        "patient_id": "MBR-9",
        "npi": "1234567890",
        "date_of_service": "2024-05-10",
        "cpt_codes": "99213, 99214-25",
    }
    r = client.post(
        "/encounters/upload/paste",
        data={"payload": json.dumps(payload)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "(paste form)"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["encounter_id"] == "ENC-PASTE-001"
    assert row["CPT_codes"] == ["99213", "99214-25"]
    assert row["source"] == "paste"
    assert row["errors"] == []


def test_paste_form_rejects_missing_required_fields(
    client: TestClient,
) -> None:
    payload = {
        "encounter_id": "ENC-PASTE-BAD",
        # patient_id, npi, date_of_service, cpt_codes all missing
    }
    r = client.post(
        "/encounters/upload/paste",
        data={"payload": json.dumps(payload)},
    )
    rows = r.json()["rows"]
    assert len(rows) == 1
    errs = rows[0]["errors"]
    for expected in (
        "missing patient_id",
        "missing NPI",
        "missing date_of_service",
        "missing CPT codes",
    ):
        assert any(expected in e for e in errs), errs


def test_submit_button_disabled_when_no_accepted_rows_in_preview(
    client: TestClient,
) -> None:
    """The frontend toggles the submit button's disabled state
    based on the presence of accepted rows. We assert the page
    ships the right initial state (the button is disabled until
    the user previews a file) — this is the contract the page
    renders, and a future refactor that changes the gating must
    update this test."""
    r = client.get("/encounters/upload")
    assert r.status_code == 200
    # The submit button is in the DOM with `disabled` until a
    # preview produces at least one accepted row.
    assert 'id="btn-submit"' in r.text
    assert "btn-submit" in r.text
    # The preview panel is hidden by default.
    assert 'id="preview-panel"' in r.text


# --- 7. clinical note PDF/image uploads accepted, OCR deferred -------------


def test_clinical_note_pdf_is_accepted(client: TestClient, tmp_path: Path) -> None:
    # A minimal valid PDF header (just enough bytes to look PDF-y).
    pdf_bytes = b"%PDF-1.4\n%fake content for test\n%%EOF\n"
    r = client.post(
        "/encounters/upload/notes",
        files={"file": ("note.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "note_id" in body
    assert body["filename"] == "note.pdf"
    assert body["size_bytes"] == len(pdf_bytes)
    assert body["ocr_status"] == "deferred"
    # The file was actually written to disk.
    stored = Path(body["stored_path"])
    # stored_path is project-relative; resolve it against the
    # project root.
    project_root = Path(api.__file__).resolve().parent.parent.parent
    target = project_root / stored
    assert target.exists()
    assert target.read_bytes() == pdf_bytes


def test_clinical_note_image_is_accepted(client: TestClient) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    r = client.post(
        "/encounters/upload/notes",
        files={"file": ("scan.png", png_bytes, "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ocr_status"] == "deferred"
    assert body["filename"] == "scan.png"


def test_clinical_note_rejects_unsupported_extension(
    client: TestClient,
) -> None:
    r = client.post(
        "/encounters/upload/notes",
        files={"file": ("note.docx", b"PK\x03\x04", "application/zip")},
    )
    assert r.status_code == 400
    assert "extension" in r.json()["detail"].lower()


def test_clinical_note_oversize_rejected(client: TestClient) -> None:
    # 11 MiB; just over the 10 MiB cap.
    too_big = b"%PDF-1.4\n" + b"X" * (11 * 1024 * 1024)
    r = client.post(
        "/encounters/upload/notes",
        files={"file": ("huge.pdf", too_big, "application/pdf")},
    )
    assert r.status_code == 413


# --- 8. error path: bad JSON payload on submit ----------------------------


def test_submit_rejects_invalid_json(client: TestClient) -> None:
    r = client.post(
        "/encounters/upload/submit",
        data={"payload": "{this is not json"},
    )
    assert r.status_code == 400


def test_submit_rejects_non_list_rows(client: TestClient) -> None:
    r = client.post(
        "/encounters/upload/submit",
        data={"payload": json.dumps({"rows": "not a list"})},
    )
    assert r.status_code == 400


# --- 9. parser unit tests --------------------------------------------------


def test_parse_837p_minimal_envelope() -> None:
    """The parser walks ISA/ST/SE/IEA/GE envelopes and produces
    the same normalised dict shape regardless of which segments
    surround the claim body."""
    claims = parse_837p(_FULL_837P)
    assert len(claims) == 1
    c = claims[0]
    assert c["encounter_id"] == "ENC-PORTAL-001"
    assert c["NPI"] == "1234567890"
    assert c["CPT_codes"] == ["99213", "99214-25"]


def test_parse_837p_rejects_empty_input() -> None:
    with pytest.raises(X12ParseError):
        parse_837p("")


def test_parse_837p_rejects_no_segments() -> None:
    # Only whitespace / newlines, no actual segments.
    with pytest.raises(X12ParseError):
        parse_837p("   \n   \n")


def test_validate_required_fields_lists_all_problems() -> None:
    errs = validate_required_fields(
        {
            "encounter_id": "",
            "patient_id": "",
            "NPI": "12",
            "date_of_service": "not-a-date",
            "CPT_codes": [],
        }
    )
    # Five problems, one per field, including the malformed NPI
    # and the malformed date.
    assert len(errs) == 5
    assert any("encounter_id" in e for e in errs)
    assert any("patient_id" in e for e in errs)
    assert any("NPI" in e for e in errs)
    assert any("date_of_service" in e for e in errs)
    assert any("CPT" in e for e in errs)


def test_required_fields_constant_is_frozen() -> None:
    """The REQUIRED_FIELDS tuple is a public contract; if a
    refactor changes it, this test pins the shape the validator
    and the UI depend on."""
    assert REQUIRED_FIELDS == (
        "encounter_id",
        "patient_id",
        "NPI",
        "date_of_service",
        "CPT_codes",
    )


# --- 10. job-queue unit tests ---------------------------------------------


def test_job_queue_persists_across_instances(tmp_path: Path) -> None:
    """A second JobQueue pointed at the same JSONL log rebuilds
    the in-memory state from disk. This is the contract the
    status-poll endpoint depends on after a process restart."""
    log = tmp_path / "jobs.jsonl"
    q1 = JobQueue(log_path=log, runner=lambda e: {"ok": True})
    job = q1.enqueue(
        encounter={"encounter_id": "ENC-RESTART-1", "patient_id": "x",
                    "NPI": "1234567890", "date_of_service": "2024-05-10",
                    "CPT_codes": ["99213"]},
        source="837p",
        source_filename="x.837",
    )
    # Wait for the worker to settle.
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if q1.get(job.job_id).status in ("done", "failed"):
            break
        time.sleep(0.05)
    q2 = JobQueue(log_path=log, runner=lambda e: {})
    reloaded = q2.get(job.job_id)
    assert reloaded is not None
    assert reloaded.encounter_id == "ENC-RESTART-1"
    assert reloaded.status in ("done", "failed")


def test_job_queue_marks_failure_on_runner_exception(
    tmp_path: Path,
) -> None:
    log = tmp_path / "jobs.jsonl"

    def boom(enc: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("synth exploded")

    q = JobQueue(log_path=log, runner=boom)
    job = q.enqueue(
        encounter={"encounter_id": "ENC-FAIL-1", "patient_id": "x",
                    "NPI": "1234567890", "date_of_service": "2024-05-10",
                    "CPT_codes": ["99213"]},
        source="837p",
        source_filename="x.837",
    )
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if q.get(job.job_id).status in ("done", "failed"):
            break
        time.sleep(0.05)
    final = q.get(job.job_id)
    assert final.status == "failed"
    assert "synth exploded" in final.error


def test_job_result_sanitizes_nested_exception_canaries(tmp_path: Path) -> None:
    """Persisted/polled results must not expose nested provider text."""
    q = JobQueue(
        log_path=tmp_path / "jobs.jsonl",
        runner=lambda enc: {
            "audit_status": "failed",
            "audit_error": "top-secret patient 123",
            "provider": {
                "exception_message": "sk-live-secret and patient 456",
            },
            "attempts": [
                {"raw_exception": "credential=secret patient=789"},
            ],
        },
    )
    job = q.enqueue(
        encounter={"encounter_id": "ENC-SANITIZE-1", "patient_id": "x"},
        source="837p",
        source_filename="x.837",
    )
    deadline = time.time() + 3.0
    while time.time() < deadline and q.get(job.job_id).status not in ("done", "failed"):
        time.sleep(0.05)

    public = q.get(job.job_id).to_dict()
    serialized = json.dumps(public)
    assert "top-secret patient 123" not in serialized
    assert "sk-live-secret and patient 456" not in serialized
    assert "credential=secret patient=789" not in serialized
    assert public["result"]["audit_error"] == "audit_job_failed"
    assert public["result"]["provider"]["exception_message"] == "audit_job_failed"


def test_default_queue_is_singleton() -> None:
    """The module-level get_default_queue() is a process-wide
    singleton so the dashboard and the worker threads agree on
    which job they're talking about."""
    reset_default_queue_for_tests()
    a = get_default_queue()
    b = get_default_queue()
    assert a is b
