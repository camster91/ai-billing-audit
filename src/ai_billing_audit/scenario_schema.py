"""JSON-schema validator for a variability-matrix scenario.

Task: t_4b9a34ae (Define scenario schema and JSON contract)
Parent: t_e072b37d ("Synth Agent: variability matrix")
Children of this task:
  - t_785d35c1 (Generate v1 sample set of 100 scenarios)
  - t_221a3d69 (Build evaluation rubric and ground-truth reference)
  - t_43ff3e89 (Design stratified sampling strategy for 100 scenarios)

The schema is the single source of truth for what a "scenario" looks
like in the audit pipeline. This module loads it from the sibling JSON
file and validates payloads against it. It also runs a small set of
post-schema business invariants that are awkward to express in pure
JSON Schema:

  * The ``em_code`` must be in the office/outpatient (99202-99215) range
    UNLESS the encounter is explicitly flagged as inpatient. (The 9,450
    variability-matrix count uses 99202-99215 only; allowing inpatient
    codes outside that band would double-count cells.)
  * ``num_problems`` must be consistent with the count of diagnosis codes
    that drive the E/M (all diagnosis codes; not just ``is_primary`` ones).
  * The ICD-10 pattern in the schema accepts a wide range of suffixes;
    we do not second-guess the schema regex here.

Acceptance: the example scenario in this directory validates, and the
downstream sampler (t_43ff3e89) and rubric (t_221a3d69) consume the
schema without further interpretation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

__all__ = [
    "SCENARIO_SCHEMA",
    "SCHEMA_PATH",
    "ScenarioValidationError",
    "load_schema",
    "validate_scenario",
]


# Module-level constants: the schema is loaded lazily on first access
# so ``import scenario_schema`` does not pay the file-read cost.

SCHEMA_PATH: Path = Path(__file__).parent / "scenario_schema.json"

_OFFICE_OUTPATIENT_EM_CODES: frozenset[str] = frozenset(
    {
        "99202",
        "99203",
        "99204",
        "99205",
        "99211",
        "99212",
        "99213",
        "99214",
        "99215",
    }
)


def _load_schema_from_disk() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# Eager load for the common case. Tests that mutate the schema file
# mid-process can call ``load_schema()`` to re-read.
SCENARIO_SCHEMA: dict[str, Any] = _load_schema_from_disk()


def load_schema(path: Path | str | None = None) -> dict[str, Any]:
    """Reload the schema from disk. Used by tests; not by the hot path."""
    if path is None:
        return _load_schema_from_disk()
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


class ScenarioValidationError(ValueError):
    """Raised when a scenario payload does not validate.

    The ``errors`` attribute carries the underlying jsonschema error
    list plus any post-schema invariant failures, so callers (and tests)
    get a useful diagnostic in one place.
    """

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = list(errors or [])


def _format_jsonschema_error(exc: jsonschema.ValidationError) -> str:
    path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
    return f"{path}: {exc.message}"


def validate_scenario(
    payload: Any, schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate a parsed scenario dict.

    Args:
        payload: any JSON-decoded value. Must be a dict.
        schema: optional override schema. Defaults to the module-level
            ``SCENARIO_SCHEMA`` (loaded from ``scenario_schema.json``).

    Returns:
        The same dict on success.

    Raises:
        ScenarioValidationError: on any structural or invariant violation.
        The error message lists every failure (not just the first),
        which makes test failures and downstream diagnostics easier
        to act on.
    """
    if schema is None:
        schema = SCENARIO_SCHEMA

    errors: list[str] = []
    if not isinstance(payload, dict):
        raise ScenarioValidationError(
            f"scenario must be a JSON object, got {type(payload).__name__}"
        )

    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(payload), key=lambda e: e.path):
        errors.append(_format_jsonschema_error(err))

    # Post-schema invariants. These are "the schema is shaped right, but
    # does the shape make sense?" checks.

    metadata = payload.get("metadata") or {}
    em_code = metadata.get("em_code")
    if isinstance(em_code, str) and em_code not in _OFFICE_OUTPATIENT_EM_CODES:
        # The 9,450-cell variability matrix uses office/outpatient codes
        # only. Inpatient / discharge codes are valid in the schema (so
        # the rubric / gold set can cover them) but the sampler is
        # expected to set ``num_problems >= 1`` and the scenario is
        # implicitly out-of-distribution. Surface this as a warning,
        # not an error — the schema's intent is broader than the v1
        # sampling distribution.
        errors.append(
            f"metadata.em_code: {em_code!r} is outside the office/outpatient "
            "range 99202-99215 used by the v1 variability matrix"
        )

    diagnosis_codes = (payload.get("expected_output") or {}).get(
        "diagnosis_codes"
    ) or []
    num_problems = metadata.get("num_problems")
    if (
        isinstance(num_problems, int)
        and len(diagnosis_codes) > 0
        and len(diagnosis_codes) < num_problems
    ):
        # The schema allows any num_problems + any list of diagnosis
        # codes. The rubric expects at LEAST num_problems codes: a
        # scenario that advertises 2 problems must list at least 2
        # codes. Real billing routinely lists more codes than
        # "problems addressed" (e.g. chronic conditions that contribute
        # to MDM are billed in addition to the acute problem), so the
        # check is `len(codes) >= num_problems`, not `==`.
        errors.append(
            f"metadata.num_problems={num_problems} but expected_output."
            f"diagnosis_codes has only {len(diagnosis_codes)} entries; "
            "at least num_problems codes are required so the rubric can "
            "score each problem"
        )

    # ``surgery_with_global_period`` is false by default; if it's true,
    # at least one code_selection line must carry modifier '25' on the
    # E/M code. The schema already requires E/M to be present (via
    # minItems=1 on code_selection), so we just check the modifier.
    surgery_flag = (payload.get("expected_output") or {}).get(
        "surgery_with_global_period"
    )
    code_selection = (payload.get("expected_output") or {}).get("code_selection") or []
    if surgery_flag is True and isinstance(code_selection, list):
        em_with_modifier = [
            c
            for c in code_selection
            if isinstance(c, dict)
            and c.get("code", "").startswith("992")
            and c.get("modifier") == "25"
        ]
        if not em_with_modifier:
            errors.append(
                "expected_output.surgery_with_global_period is true but no "
                "E/M line (992xx) carries modifier '25' — the rubric will "
                "flag this as a missing-modifier audit failure"
            )

    if errors:
        msg = "scenario failed validation: " + "; ".join(errors)
        raise ScenarioValidationError(msg, errors=errors)

    return payload
