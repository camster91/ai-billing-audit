from __future__ import annotations

import pytest

from ai_billing_audit.claim_schema import (
    CLAIM_SCHEMA_VERSION,
    ClaimSchemaError,
    normalize_claim,
    validate_claim,
)


def test_legacy_aliases_normalize_to_one_versioned_contract() -> None:
    claim = normalize_claim(
        {
            "encounter_id": "enc-1",
            "patient_id": "patient-1",
            "npi": "1234567890",
            "date_of_service": "2024-05-15",
            "procedure_codes": ["99213"],
            "dx_codes": ["Z0000"],
            "source": "csv:kareo",
        }
    )

    assert claim["schema_version"] == CLAIM_SCHEMA_VERSION
    assert claim["NPI"] == "1234567890"
    assert claim["CPT_codes"] == ["99213"]
    assert claim["diagnosis_codes"] == ["Z0000"]
    assert claim["source"] == "csv:kareo"
    assert "dx_codes" not in claim


def test_conflicting_alias_is_rejected() -> None:
    with pytest.raises(ClaimSchemaError, match="conflicting claim fields"):
        normalize_claim(
            {
                "NPI": "1234567890",
                "npi": "0987654321",
            }
        )


def test_validation_reports_missing_contract_fields() -> None:
    assert validate_claim({}) == [
        "missing encounter_id",
        "missing date_of_service",
        "missing CPT_codes",
    ]
