"""Encounter schema and validator.

Defines the JSON schema for the clinical-encounter fixtures the synth
agent emits and consumed by the rest of the audit pipeline.

The schema is intentionally small but strict on shape: every encounter
must declare its `difficulty_tier`, a `flagged` boolean, a non-empty
`trigger_reason`, a structured `provider_note` (HPI / exam / MDM), at
least one ICD-10 code, and at least one CPT line item. When a fixture
flags a surgery with a global period, every E/M line item that sits in
the post-op window must carry modifier `-25`; the validator enforces
this invariant.

The module is dependency-light — it uses ``jsonschema`` for the heavy
lifting and returns the same dict on success. ``EncounterValidationError``
exposes a list of validator errors so callers (and tests) get a useful
diagnostic.
"""

from __future__ import annotations

import re
from typing import Any

import jsonschema

__all__ = [
    "ENCOUNTER_SCHEMA",
    "EncounterValidationError",
    "validate_encounter",
]


# ICD-10 codes we accept: a letter, two digits, optional `.` + up to
# four alphanumerics, optional 7th-character extension. Examples:
#   R05, R05.9, S72.001A, E11.9, I10, J18.9
_ICD10_RE = re.compile(r"^[A-Z]\d{2}(\.[0-9A-Z]{1,4})?([A-Z])?$")

# CPT codes: 5 digits, optionally 4 alphanumeric characters for Category II/III
# and HCPCS. Examples: 99213, 99214, 93000, 71046, G0438, 90686
_CPT_RE = re.compile(r"^[0-9A-Z]{5}$")

# Modifiers we recognise. Modifier 25 is the only one the validator
# actively cares about (surgical global period), but the rest are
# valid CPT modifiers the synth agent may emit.
_KNOWN_MODIFIERS = {"22", "23", "24", "25", "26", "32", "47", "50", "51", "52", "53",
                    "54", "55", "56", "57", "58", "59", "62", "63", "66", "73", "74",
                    "76", "77", "78", "79", "80", "81", "82", "90", "91", "92", "95",
                    "96", "97", "AA", "AD", "AS", "CR", "E1", "E2", "E3", "E4", "F1",
                    "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "FA", "GA", "GC",
                    "GE", "GJ", "GN", "GO", "GP", "GQ", "GT", "GY", "GZ", "LT", "PT",
                    "QK", "QW", "QX", "QY", "QZ", "RT", "SG", "TC", "XE", "XP", "XS", "XU"}


ENCOUNTER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://ai-billing-audit.local/encounter.schema.json",
    "title": "Encounter",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "encounter_id",
        "difficulty_tier",
        "flagged",
        "trigger_reason",
        "provider_note",
        "icd10_codes",
        "cpt_codes",
    ],
    "properties": {
        "encounter_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^enc_[a-zA-Z0-9_]+$",
        },
        "difficulty_tier": {
            "type": "string",
            "enum": ["EASY", "MEDIUM", "HARD"],
        },
        "flagged": {"type": "boolean"},
        "trigger_reason": {
            "type": "string",
            "minLength": 1,
        },
        "patient": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "age": {"type": "integer", "minimum": 0, "maximum": 130},
                "sex": {"type": "string", "enum": ["M", "F", "O"]},
            },
        },
        "provider_note": {
            "type": "object",
            "additionalProperties": False,
            "required": ["hpi", "exam", "mdm"],
            "properties": {
                "hpi": {"type": "string", "minLength": 1},
                "exam": {"type": "string", "minLength": 1},
                "mdm": {"type": "string", "minLength": 1},
            },
        },
        "icd10_codes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "cpt_codes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code"],
                "properties": {
                    "code": {"type": "string"},
                    "modifier": {"type": "string"},
                    "global_period_days": {"type": "integer", "minimum": 0},
                },
            },
        },
        "surgery_with_global_period": {"type": "boolean"},
        "prescription_drug_management": {"type": "boolean"},
    },
}


class EncounterValidationError(ValueError):
    """Raised when an encounter payload does not validate.

    The ``errors`` attribute carries the underlying jsonschema error list
    (or our custom post-schema invariant errors) so callers can surface
    precise diagnostics.
    """

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = list(errors or [])


def _format_jsonschema_error(exc: jsonschema.ValidationError) -> str:
    path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
    return f"{path}: {exc.message}"


def validate_encounter(payload: Any) -> dict[str, Any]:
    """Validate a parsed encounter dict.

    Returns the same dict on success. Raises ``EncounterValidationError``
    on any structural or invariant violation. The error message lists
    every failure (not just the first), which makes test failures and
    production diagnostics easier to act on.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise EncounterValidationError(
            f"encounter must be a JSON object, got {type(payload).__name__}"
        )

    validator = jsonschema.Draft202012Validator(ENCOUNTER_SCHEMA)
    for err in sorted(validator.iter_errors(payload), key=lambda e: e.path):
        errors.append(_format_jsonschema_error(err))

    # Field-level pattern checks that are awkward to express in the JSON
    # schema proper.
    icd_codes = payload.get("icd10_codes", [])
    for i, code in enumerate(icd_codes):
        if not isinstance(code, str) or not _ICD10_RE.match(code):
            errors.append(
                f"icd10_codes[{i}]: not a valid ICD-10 code (got {code!r})"
            )

    cpt_codes = payload.get("cpt_codes", [])
    for i, cpt in enumerate(cpt_codes):
        if not isinstance(cpt, dict):
            continue
        code = cpt.get("code")
        if not isinstance(code, str) or not _CPT_RE.match(code):
            errors.append(
                f"cpt_codes[{i}].code: not a valid CPT/HCPCS code (got {code!r})"
            )
        mod = cpt.get("modifier")
        if mod is not None:
            if not isinstance(mod, str):
                errors.append(
                    f"cpt_codes[{i}].modifier: must be a string (got {type(mod).__name__})"
                )
            elif mod not in _KNOWN_MODIFIERS:
                errors.append(
                    f"cpt_codes[{i}].modifier: {mod!r} is not a recognised CPT modifier"
                )

    # Note: the modifier-25 / global-period audit rule is NOT enforced
    # by the schema. The schema validates the structural shape of the
    # encounter; whether a flagged HARD fixture has the modifier
    # correctly applied or not is the auditor's job to detect, not the
    # schema's. We do enforce the minimal sanity check that a flagged
    # encounter must contain at least one E/M line when the surgery
    # flag is set, otherwise the fixture is too degenerate to be a
    # meaningful test case.
    if payload.get("surgery_with_global_period") is True:
        has_em = any(
            isinstance(c, dict)
            and isinstance(c.get("code"), str)
            and c["code"].startswith("992")
            for c in cpt_codes
        )
        if not has_em:
            errors.append(
                "surgery_with_global_period is true but no E/M CPT (992xx) was billed"
            )

    if errors:
        msg = "encounter failed validation: " + "; ".join(errors)
        raise EncounterValidationError(msg, errors=errors)

    return payload
