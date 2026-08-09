"""Tests for the CSV upload endpoint.

Acceptance criteria from the task body:

* Kareo + OSCAR + Office Ally column dictionaries, with a small
  example CSV for each in ``tests/fixtures/csv/``.
* Unknown format returns 400 with a helpful error.
* Per-row errors don't abort the whole batch — partial success is OK.
* Audit enqueue uses the existing job-queue path (same as JSON
  upload); verified via ``JobQueue`` with a no-op runner.
* Tests covering: Kareo sample, OSCAR sample, Office Ally sample,
  mixed-format row rejection, unknown format 400.

The tests run in-process via ``starlette.testclient.TestClient`` so
the route handlers execute the same code path as production.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient


# IMPORTANT: env must be set BEFORE importing api so the bearer
# middleware in create_app() sees AUDIT_ALLOW_NO_AUTH=1 at
# construction time.
os.environ["AUDIT_ALLOW_NO_AUTH"] = "1"
os.environ["AUDIT_BEARER_TOKEN"] = ""

from ai_billing_audit import api  # noqa: E402
from ai_billing_audit.csv_ingest import (  # noqa: E402
    HEADER_DICTIONARY,
    REQUIRED_DICTIONARY,
    detect_format,
    ingest_csv,
    normalize_row,
    parse_csv,
)
from ai_billing_audit.job_queue import (  # noqa: E402
    JobQueue,
    reset_default_queue_for_tests,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv"


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Starlette TestClient with AUTH off and a fresh job queue."""
    reset_default_queue_for_tests()
    monkeypatch.setattr(api, "load_uploaded_note_for_encounter", lambda _id: "note")
    return TestClient(api.app)


@pytest.fixture
def tmp_log_queue(tmp_path: Path) -> JobQueue:
    """JobQueue with a tmp log path and a no-op runner.

    The default runner calls the synth agent (which hits the real
    LLM via Ollama). For these tests we don't care about the audit
    output — we only verify that the enqueue path is invoked with
    the right shape.
    """
    log = tmp_path / "jobs.jsonl"
    return JobQueue(log_path=log, worker_count=2, runner=lambda enc: {"echo": enc})


# --- 1. format detection ---------------------------------------------------


def test_detect_format_kareo() -> None:
    headers = [
        "Procedure Code",
        "Charge",
        "Date Of Service",
        "Patient ID",
        "Provider NPI",
        "Encounter ID",
    ]
    assert detect_format(headers) == "kareo"


def test_detect_format_oscar() -> None:
    headers = [
        "billingcode",
        "billing_amount",
        "service_date",
        "demographic_no",
        "practitioner_no",
    ]
    assert detect_format(headers) == "oscar"


def test_detect_format_office_ally() -> None:
    headers = ["CPT", "Amount", "DOS", "PatientID", "ProviderNPI"]
    assert detect_format(headers) == "office_ally"


def test_detect_format_case_insensitive() -> None:
    """Kareo's headers come back in mixed case from real exports."""
    headers = ["procedure code", "CHARGE", "date of service"]
    assert detect_format(headers) == "kareo"


def test_detect_format_whitespace_tolerant() -> None:
    """Real Kareo exports sometimes have leading/trailing spaces."""
    headers = [" Procedure Code ", " Charge", " Date Of Service "]
    assert detect_format(headers) == "kareo"


def test_detect_format_unknown() -> None:
    assert detect_format(["Foo", "Bar", "Baz"]) == "unknown"
    assert detect_format([]) == "unknown"


def test_header_dictionary_has_all_three_systems() -> None:
    """The three required PM systems are present in the dictionary."""
    assert set(HEADER_DICTIONARY.keys()) >= {
        "kareo",
        "oscar",
        "office_ally",
    }
    # Each system has the three required columns we test against.
    for fmt in ("kareo", "oscar", "office_ally"):
        required = REQUIRED_DICTIONARY[fmt]
        assert "procedure_code" in [_norm(h) for h in HEADER_DICTIONARY[fmt]] or any(
            c.lower().replace(" ", "")
            in [h.lower().replace(" ", "") for h in HEADER_DICTIONARY[fmt]]
            for c in required
        ), f"{fmt!r} missing required column"


def _norm(s: str) -> str:
    return s.lower().replace(" ", "").replace("_", "")


# --- 2. parse_csv ----------------------------------------------------------


def test_parse_csv_kareo() -> None:
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    rows = parse_csv(raw)
    assert len(rows) == 3
    # Original header names preserved verbatim (case-sensitive).
    assert "Procedure Code" in rows[0]
    assert rows[0]["Procedure Code"] == "99213"
    assert rows[0]["Charge"] == "150.00"
    assert rows[0]["Patient ID"] == "MBR-0001"


def test_parse_csv_oscar() -> None:
    raw = (FIXTURES_DIR / "oscar_sample.csv").read_bytes()
    rows = parse_csv(raw)
    assert len(rows) == 3
    assert rows[0]["billingcode"] == "99213"
    assert rows[0]["billing_amount"] == "150.00"
    assert rows[1]["service_date"] == "2024-05-16"


def test_parse_csv_office_ally() -> None:
    raw = (FIXTURES_DIR / "office_ally_sample.csv").read_bytes()
    rows = parse_csv(raw)
    assert len(rows) == 3
    assert rows[0]["CPT"] == "99213"
    assert rows[1]["DOS"] == "05/16/2024"


def test_parse_csv_empty_returns_empty_list() -> None:
    assert parse_csv(b"") == []


def test_parse_csv_handles_utf8_bom() -> None:
    """Office Ally sometimes emits a UTF-8 BOM."""
    raw = "\ufeffCPT,Amount,DOS\n99213,150.00,2024-05-15\n".encode("utf-8")
    rows = parse_csv(raw)
    assert len(rows) == 1
    # BOM should be stripped — the key is "CPT" not "\ufeffCPT".
    assert "CPT" in rows[0]


# --- 3. normalize_row ------------------------------------------------------


def test_normalize_row_kareo() -> None:
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    rows = parse_csv(raw)
    normalised = normalize_row(rows[0], "kareo")
    assert normalised["procedure_code"] == "99213"
    assert normalised["billed_amount"] == "150.00"
    assert normalised["date_of_service"] == "2024-05-15"
    assert normalised["patient_id"] == "MBR-0001"
    assert normalised["NPI"] == "1234567890"
    assert normalised["encounter_id"] == "ENC-KAR-001"
    assert normalised["modifiers"] == ["25"]
    assert normalised["dx_codes"] == ["E11.9"]
    # The audit-pipeline shape is in ``_encounter``.
    enc = normalised["_encounter"]
    assert enc["encounter_id"] == "ENC-KAR-001"
    assert enc["patient_id"] == "MBR-0001"
    assert enc["NPI"] == "1234567890"
    assert enc["date_of_service"] == "2024-05-15"
    # Modifier attached to CPT code with a dash.
    assert enc["CPT_codes"] == ["99213-25"]


def test_normalize_row_oscar() -> None:
    raw = (FIXTURES_DIR / "oscar_sample.csv").read_bytes()
    rows = parse_csv(raw)
    normalised = normalize_row(rows[0], "oscar")
    assert normalised["procedure_code"] == "99213"
    assert normalised["billed_amount"] == "150.00"
    assert normalised["date_of_service"] == "2024-05-15"
    assert normalised["patient_id"] == "1001"
    assert normalised["encounter_id"] == "APPT-001"


def test_normalize_row_office_ally() -> None:
    raw = (FIXTURES_DIR / "office_ally_sample.csv").read_bytes()
    rows = parse_csv(raw)
    normalised = normalize_row(rows[0], "office_ally")
    assert normalised["procedure_code"] == "99213"
    assert normalised["billed_amount"] == "150.00"
    assert normalised["date_of_service"] == "2024-05-15"
    assert normalised["patient_id"] == "MBR-OA-1"
    assert normalised["encounter_id"] == "CLM-OA-001"
    assert normalised["modifiers"] == ["25"]


def test_normalize_row_missing_procedure_raises() -> None:
    with pytest.raises(ValueError, match="missing procedure_code"):
        normalize_row({"Charge": "100", "Date Of Service": "2024-05-15"}, "kareo")


def test_normalize_row_bad_amount_raises() -> None:
    with pytest.raises(ValueError, match="amount"):
        normalize_row(
            {
                "Procedure Code": "99213",
                "Charge": "free",
                "Date Of Service": "2024-05-15",
            },
            "kareo",
        )


def test_normalize_row_bad_date_raises() -> None:
    with pytest.raises(ValueError, match="date"):
        normalize_row(
            {
                "Procedure Code": "99213",
                "Charge": "100",
                "Date Of Service": "not-a-date",
            },
            "kareo",
        )


def test_normalize_row_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="unknown format"):
        normalize_row({"Procedure Code": "99213"}, "fake_pm")


def test_normalize_row_currency_symbol_stripped() -> None:
    """PM exports sometimes prefix the amount with a dollar sign."""
    row = {
        "Procedure Code": "99213",
        "Charge": "$150.00",
        "Date Of Service": "2024-05-15",
    }
    normalised = normalize_row(row, "kareo")
    assert normalised["billed_amount"] == "150.00"


def test_normalize_row_thousands_comma_stripped() -> None:
    row = {
        "Procedure Code": "99213",
        "Charge": "1,500.00",
        "Date Of Service": "2024-05-15",
    }
    normalised = normalize_row(row, "kareo")
    assert normalised["billed_amount"] == "1500.00"


def test_normalize_row_us_slash_date_parsed() -> None:
    row = {
        "Procedure Code": "99213",
        "Charge": "100.00",
        "Date Of Service": "05/16/2024",
    }
    normalised = normalize_row(row, "kareo")
    assert normalised["date_of_service"] == "2024-05-16"


def test_normalize_row_negative_amount_rejected() -> None:
    """Credit memos should not be audited as claims."""
    row = {
        "Procedure Code": "99213",
        "Charge": "-50.00",
        "Date Of Service": "2024-05-15",
    }
    with pytest.raises(ValueError, match="negative"):
        normalize_row(row, "kareo")


# --- 4. ingest_csv (full pipeline) ----------------------------------------


def test_ingest_csv_kareo_returns_canonical_shape(tmp_log_queue: JobQueue) -> None:
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    result = ingest_csv(
        file_bytes=raw,
        payer_id="AHCIP",
        clinic_id="clinic-001",
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["detected_format"] == "kareo"
    assert result["accepted_count"] == 3
    assert result["rejected_count"] == 0
    assert result["errors"] == []
    # Three jobs enqueued, each with a job_id and an encounter_id.
    assert result["enqueued"] is not None
    assert len(result["enqueued"]) == 3
    for entry in result["enqueued"]:
        assert entry["job_id"]
        assert entry["encounter_id"]


def test_ingest_csv_without_enqueue_does_not_enqueue_jobs() -> None:
    """When enqueue=None, the pipeline returns the response shape
    without spinning the worker pool (used by tests / dry-runs)."""
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    result = ingest_csv(file_bytes=raw)
    assert result["accepted_count"] == 3
    assert result["detected_format"] == "kareo"
    assert result["enqueued"] is None


def test_ingest_csv_unknown_format(tmp_log_queue: JobQueue) -> None:
    raw = (FIXTURES_DIR / "unknown_format.csv").read_bytes()
    result = ingest_csv(
        file_bytes=raw,
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["detected_format"] == "unknown"
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 0
    # Top-level error message references the unknown header row.
    assert len(result["errors"]) == 1
    assert "unrecognised CSV format" in result["errors"][0]["reason"]
    assert "['Foo', 'Bar', 'Baz']" in result["errors"][0]["reason"]


def test_ingest_csv_partial_success_one_bad_row(tmp_log_queue: JobQueue) -> None:
    """A single bad row in the middle of an otherwise-good batch
    is rejected per-row; the rest of the batch is enqueued."""
    # Mix one good and one bad Kareo row.
    csv_text = (
        "Procedure Code,Charge,Date Of Service,Patient ID\n"
        "99213,150.00,2024-05-15,MBR-OK\n"
        "99214,not-a-number,2024-05-16,MBR-BAD-AMOUNT\n"
        "99215,75.00,2024-05-17,MBR-OK-2\n"
    )
    result = ingest_csv(
        file_bytes=csv_text.encode("utf-8"),
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["detected_format"] == "kareo"
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 1
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["row"] == 2
    assert "amount" in err["reason"].lower()
    # The two good rows made it into the queue.
    assert result["enqueued"] is not None
    assert len(result["enqueued"]) == 2


def test_ingest_csv_per_row_errors_preserve_row_numbers(
    tmp_log_queue: JobQueue,
) -> None:
    """The ``row`` field in each error is the 1-based CSV row index,
    counting the header as row 0 (so the first data row is row 1).
    This matches the convention the /encounters/upload/submit
    endpoint already uses."""
    csv_text = (
        "Procedure Code,Charge,Date Of Service\n"
        "99213,150.00,2024-05-15\n"  # row 1, OK
        "99214,225.00,bad-date\n"  # row 2, bad date
        ",100,2024-05-17\n"  # row 3, missing procedure
        "99215,75.00,2024-05-18\n"  # row 4, OK
    )
    result = ingest_csv(
        file_bytes=csv_text.encode("utf-8"),
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["accepted_count"] == 2
    assert result["rejected_count"] == 2
    error_rows = sorted(e["row"] for e in result["errors"])
    assert error_rows == [2, 3]


def test_ingest_csv_oscar_format(tmp_log_queue: JobQueue) -> None:
    raw = (FIXTURES_DIR / "oscar_sample.csv").read_bytes()
    result = ingest_csv(
        file_bytes=raw,
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["detected_format"] == "oscar"
    assert result["accepted_count"] == 3
    assert result["rejected_count"] == 0


def test_ingest_csv_office_ally_format(tmp_log_queue: JobQueue) -> None:
    raw = (FIXTURES_DIR / "office_ally_sample.csv").read_bytes()
    result = ingest_csv(
        file_bytes=raw,
        enqueue=tmp_log_queue.enqueue,
    )
    assert result["detected_format"] == "office_ally"
    assert result["accepted_count"] == 3
    assert result["rejected_count"] == 0


def test_ingest_csv_jobs_have_canonical_encounter_shape(
    tmp_log_queue: JobQueue,
) -> None:
    """The encounters enqueued onto the audit job-queue match the
    shape the rest of the pipeline expects."""
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    result = ingest_csv(
        file_bytes=raw,
        clinic_id="clinic-test",
        enqueue=tmp_log_queue.enqueue,
    )
    # First enqueued job's encounter is recoverable via
    # queue.find_by_encounter (with a short wait).
    import time

    first_enc_id = result["enqueued"][0]["encounter_id"]
    deadline = time.time() + 2.0
    job = None
    while time.time() < deadline:
        job = tmp_log_queue.find_by_encounter(first_enc_id, status="done")
        if job is not None:
            break
        time.sleep(0.05)
    assert job is not None, "job never finished"
    # Source was tagged "csv:kareo" so /encounters/upload can render
    # the source tag correctly in the dashboard.
    assert job.source == "csv:kareo"
    # tenant_id was the clinic_id passed in.
    assert job.tenant_id == "clinic-test"


# --- 5. HTTP endpoint /upload/csv -----------------------------------------


def test_upload_csv_kareo_returns_200_with_response_shape(
    client: TestClient,
) -> None:
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    r = client.post(
        "/upload/csv",
        files={"file": ("kareo_sample.csv", raw, "text/csv")},
        data={"payer_id": "AHCIP", "clinic_id": "clinic-001"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_format"] == "kareo"
    assert body["accepted_count"] == 3
    assert body["rejected_count"] == 0
    assert body["errors"] == []
    assert body["enqueued"] is not None
    assert len(body["enqueued"]) == 3


def test_upload_csv_rejects_rows_without_clinical_notes_before_enqueue(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "load_uploaded_note_for_encounter", lambda _id: None)
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()

    response = client.post(
        "/upload/csv",
        files={"file": ("kareo_sample.csv", raw, "text/csv")},
        data={"clinic_id": "clinic-no-notes"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 3
    assert body["enqueued"] == []
    assert all("clinical_note_required" in error["reason"] for error in body["errors"])


def test_upload_csv_oscar_returns_200(client: TestClient) -> None:
    raw = (FIXTURES_DIR / "oscar_sample.csv").read_bytes()
    r = client.post(
        "/upload/csv",
        files={"file": ("oscar_sample.csv", raw, "text/csv")},
        data={"clinic_id": "clinic-oscar"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_format"] == "oscar"
    assert body["accepted_count"] == 3


def test_upload_csv_office_ally_returns_200(client: TestClient) -> None:
    raw = (FIXTURES_DIR / "office_ally_sample.csv").read_bytes()
    r = client.post(
        "/upload/csv",
        files={"file": ("oa.csv", raw, "text/csv")},
        data={"clinic_id": "clinic-oa"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["detected_format"] == "office_ally"
    assert body["accepted_count"] == 3


def test_upload_csv_unknown_format_returns_400(client: TestClient) -> None:
    raw = (FIXTURES_DIR / "unknown_format.csv").read_bytes()
    r = client.post(
        "/upload/csv",
        files={"file": ("weird.csv", raw, "text/csv")},
        data={"clinic_id": "clinic-x"},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    # The error message names the actual header row + the supported
    # PM systems so the user knows how to fix the upload.
    assert "unrecognised CSV format" in detail
    assert "kareo" in detail
    assert "oscar" in detail
    assert "office_ally" in detail


def test_upload_csv_mixed_format_partial_success(client: TestClient) -> None:
    """A CSV with mostly good rows + one bad row → 200 with the
    per-row error in the response body (no 400, no abort)."""
    csv_text = (
        "Procedure Code,Charge,Date Of Service,Patient ID,Encounter ID\n"
        "99213,150.00,2024-05-15,MBR-001,ENC-MIX-001\n"
        "99214,not-a-number,2024-05-16,MBR-002,ENC-MIX-002\n"
        "99215,75.00,2024-05-17,MBR-003,ENC-MIX-003\n"
    )
    r = client.post(
        "/upload/csv",
        files={"file": ("mixed.csv", csv_text.encode("utf-8"), "text/csv")},
        data={"clinic_id": "clinic-mixed"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 1
    assert body["errors"][0]["row"] == 2


def test_upload_csv_empty_file_returns_400(client: TestClient) -> None:
    r = client.post(
        "/upload/csv",
        files={"file": ("empty.csv", b"", "text/csv")},
        data={"clinic_id": "clinic-empty"},
    )
    assert r.status_code == 400


def test_upload_csv_uses_job_queue_path(
    client: TestClient, tmp_log_queue: JobQueue
) -> None:
    """The endpoint feeds the parsed encounters into the SAME
    JobQueue the /encounters/upload/submit endpoint uses — verified
    by enqueuing via the CSV endpoint and reading the job back via
    the same ``get_default_queue`` the dashboard uses."""
    raw = (FIXTURES_DIR / "kareo_sample.csv").read_bytes()
    r = client.post(
        "/upload/csv",
        files={"file": ("kareo.csv", raw, "text/csv")},
        data={"clinic_id": "clinic-shared-queue"},
    )
    assert r.status_code == 200
    # Look up one of the enqueued jobs via the same queue.
    from ai_billing_audit.job_queue import get_default_queue

    queue = get_default_queue()
    body = r.json()
    job_id = body["enqueued"][0]["job_id"]
    job = queue.get(job_id)
    assert job is not None, "job not findable on the default queue"
    # The source tag identifies the CSV path so the dashboard can
    # render "csv:kareo" instead of the legacy "837p" tag.
    assert job.source == "csv:kareo"
