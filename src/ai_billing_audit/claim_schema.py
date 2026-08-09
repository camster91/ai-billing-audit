"""Versioned claim contract shared by every ingest path.

Ingest adapters may accept the historical field aliases, but the queue and
auditor receive one stable shape.  Keeping this boundary deliberately small
lets old JSONL records remain readable while preventing new alias drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CLAIM_SCHEMA_VERSION = "claim.v1"

_ALIASES = {
    "npi": "NPI",
    "rendering_provider_npi": "NPI",
    "provider_npi": "NPI",
    "cpt_codes": "CPT_codes",
    "procedure_codes": "CPT_codes",
    "icd10_codes": "diagnosis_codes",
    "dx_codes": "diagnosis_codes",
}
_CANONICAL_LIST_FIELDS = {"CPT_codes", "diagnosis_codes", "modifiers"}


class ClaimSchemaError(ValueError):
    """Raised when a claim cannot be normalized to the v1 contract."""


def _as_list(value: Any, field: str) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, bytes)):
        return [value.decode() if isinstance(value, bytes) else value]
    if not isinstance(value, (list, tuple)):
        raise ClaimSchemaError(f"{field} must be a list")
    return list(value)


def normalize_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical, versioned copy of an ingest claim.

    Compatibility aliases are accepted only when they do not conflict with
    their canonical field. Unknown non-contract metadata is retained so older
    upload paths and audit provenance do not lose information.
    """
    if not isinstance(claim, Mapping):
        raise ClaimSchemaError("claim must be an object")

    normalized = dict(claim)
    for alias, canonical in _ALIASES.items():
        if alias not in claim:
            continue
        if canonical in claim and claim[canonical] not in (None, [], ""):
            if claim[canonical] != claim[alias]:
                raise ClaimSchemaError(
                    f"conflicting claim fields: {canonical} and {alias}"
                )
        else:
            normalized[canonical] = claim[alias]
        normalized.pop(alias, None)

    for field in _CANONICAL_LIST_FIELDS:
        normalized[field] = _as_list(normalized.get(field), field)

    normalized["encounter_id"] = str(normalized.get("encounter_id") or "").strip()
    normalized["patient_id"] = str(normalized.get("patient_id") or "").strip()
    normalized["NPI"] = str(normalized.get("NPI") or "").strip()
    normalized["schema_version"] = CLAIM_SCHEMA_VERSION
    return normalized


def validate_claim(claim: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors without exposing input values."""
    try:
        normalized = normalize_claim(claim)
    except ClaimSchemaError as exc:
        return [str(exc)]
    errors: list[str] = []
    for field in ("encounter_id", "date_of_service"):
        if not normalized.get(field):
            errors.append(f"missing {field}")
    if not normalized["CPT_codes"]:
        errors.append("missing CPT_codes")
    return errors


__all__ = [
    "CLAIM_SCHEMA_VERSION",
    "ClaimSchemaError",
    "normalize_claim",
    "validate_claim",
]
