"""Tests for the scenario schema (task t_4b9a34ae).

Acceptance criteria from the task body:
  * the schema validates against the example
  * downstream tasks can consume it without further interpretation

This test suite covers both halves. The structural tests pin the
schema's required fields, enums, and patterns. The acceptance test
round-trips the example through the validator and asserts every
downstream consumer (sampler, rubric) can read it as-is.

The test resolves the schema + example paths from the installed
``scenario_schema`` module, so it works whether the package is on
PYTHONPATH (project repo) or in a sibling directory (scratch workspace).
"""

from __future__ import annotations

import json

import jsonschema
import pytest

import ai_billing_audit.scenario_schema as ss  # noqa: E402


# Resolve the schema and example paths from the installed module.
# ``ss.SCHEMA_PATH`` is the schema's own on-disk location; the example
# lives one directory up under data/ (in the project repo) or next to
# the module (in the scratch workspace). Try both.
_SCHEMA_PATH = ss.SCHEMA_PATH
_EXAMPLE_CANDIDATES = [
    _SCHEMA_PATH.parent / "data" / "example_scenario.json",  # project layout
    _SCHEMA_PATH.parent / "example_scenario.json",  # workspace layout
]
_EXAMPLE_PATH = next(
    (p for p in _EXAMPLE_CANDIDATES if p.exists()),
    _EXAMPLE_CANDIDATES[0],  # fall back; the fixtures will fail loudly
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def example_payload() -> dict:
    return json.loads(_EXAMPLE_PATH.read_text())


@pytest.fixture
def schema_doc() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


# ---------------------------------------------------------------------------
# Schema structural tests
# ---------------------------------------------------------------------------


class TestSchemaShape:
    def test_schema_is_draft_2020_12(self, schema_doc):
        assert schema_doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_has_id(self, schema_doc):
        assert schema_doc["$id"].startswith("https://")

    def test_schema_root_disallows_additional_properties(self, schema_doc):
        """Downstream consumers rely on the schema being closed at the root.

        If a new top-level key appears, the schema should say so
        explicitly rather than silently accepting it.
        """
        assert schema_doc["additionalProperties"] is False

    def test_schema_required_fields(self, schema_doc):
        assert set(schema_doc["required"]) == {
            "scenario_id",
            "metadata",
            "input",
            "expected_output",
        }

    def test_metadata_required_fields(self, schema_doc):
        meta = schema_doc["properties"]["metadata"]
        assert meta["additionalProperties"] is False
        assert set(meta["required"]) == {
            "payer",
            "specialty",
            "em_code",
            "num_problems",
            "mdm_tier",
            "difficulty",
        }

    def test_input_required_fields(self, schema_doc):
        inp = schema_doc["properties"]["input"]
        assert set(inp["required"]) == {"chief_complaint", "patient", "history_items"}

    def test_expected_output_required_fields(self, schema_doc):
        eo = schema_doc["properties"]["expected_output"]
        assert set(eo["required"]) == {
            "diagnosis_codes",
            "mdm_rationale",
            "code_selection",
        }


class TestMetadataEnums:
    @pytest.fixture
    def metadata_props(self, schema_doc):
        return schema_doc["properties"]["metadata"]["properties"]

    def test_payer_enum(self, metadata_props):
        assert metadata_props["payer"]["enum"] == [
            "UHC",
            "Aetna",
            "BCBS",
            "Medicare",
            "Medicaid",
        ]

    def test_specialty_enum(self, metadata_props):
        assert metadata_props["specialty"]["enum"] == [
            "primary_care",
            "ortho",
            "derm",
            "gi",
            "cardiology",
        ]

    def test_em_code_enum_includes_full_office_outpatient_range(self, metadata_props):
        em = metadata_props["em_code"]["enum"]
        # The 9,450-cell count in the task body uses 99202-99215
        # exclusively. The schema may include more (inpatient,
        # discharge) so the rubric can cover them, but the office
        # range must be present.
        for code in [
            "99202",
            "99203",
            "99204",
            "99205",
            "99211",
            "99212",
            "99213",
            "99214",
            "99215",
        ]:
            assert code in em, f"missing office/outpatient code {code}"

    def test_num_problems_range(self, metadata_props):
        np = metadata_props["num_problems"]
        assert np["minimum"] == 1
        assert np["maximum"] == 3

    def test_mdm_tier_enum(self, metadata_props):
        assert metadata_props["mdm_tier"]["enum"] == [
            "Minimal",
            "Moderate",
            "High",
        ]

    def test_difficulty_enum(self, metadata_props):
        assert metadata_props["difficulty"]["enum"] == ["easy", "medium", "hard"]


# ---------------------------------------------------------------------------
# Example round-trip tests (the acceptance test)
# ---------------------------------------------------------------------------


class TestExampleAcceptance:
    """The acceptance test from the task body: the example validates."""

    def test_example_validates_against_schema(self, example_payload):
        """The single explicit acceptance criterion from t_4b9a34ae."""
        # Should not raise.
        ss.validate_scenario(example_payload)
        assert ss.validate_scenario(example_payload) is example_payload

    def test_example_validates_with_pure_jsonschema(self, example_payload, schema_doc):
        """Round-trip through a fresh jsonschema validator (no custom code).

        This is what the sampler and the rubric will do: load the
        schema, validate the example. We must agree.
        """
        jsonschema.validate(example_payload, schema_doc)

    def test_schema_module_exposes_expected_api(self):
        for name in (
            "SCENARIO_SCHEMA",
            "SCHEMA_PATH",
            "ScenarioValidationError",
            "load_schema",
            "validate_scenario",
        ):
            assert hasattr(ss, name), f"missing public symbol {name}"

    def test_schema_path_points_to_sibling_json(self):
        assert ss.SCHEMA_PATH.name == "scenario_schema.json"
        assert ss.SCHEMA_PATH.exists()


# ---------------------------------------------------------------------------
# Negative tests — the schema rejects bad input
# ---------------------------------------------------------------------------


class TestRejectsBadInput:
    def test_missing_scenario_id_rejected(self, example_payload):
        del example_payload["scenario_id"]
        with pytest.raises(ss.ScenarioValidationError) as ei:
            ss.validate_scenario(example_payload)
        assert any("scenario_id" in e for e in ei.value.errors)

    def test_missing_metadata_rejected(self, example_payload):
        del example_payload["metadata"]
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_missing_input_rejected(self, example_payload):
        del example_payload["input"]
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_missing_expected_output_rejected(self, example_payload):
        del example_payload["expected_output"]
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_payer_rejected(self, example_payload):
        example_payload["metadata"]["payer"] = "Kaiser"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_em_code_rejected(self, example_payload):
        example_payload["metadata"]["em_code"] = "99299"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_num_problems_out_of_range_rejected(self, example_payload):
        example_payload["metadata"]["num_problems"] = 4
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_num_problems_zero_rejected(self, example_payload):
        example_payload["metadata"]["num_problems"] = 0
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_mdm_tier_rejected(self, example_payload):
        example_payload["metadata"]["mdm_tier"] = "Mild"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_difficulty_rejected(self, example_payload):
        example_payload["metadata"]["difficulty"] = "trivial"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_icd10_code_rejected(self, example_payload):
        example_payload["expected_output"]["diagnosis_codes"][0]["code"] = "11.9"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_invalid_cpt_code_rejected(self, example_payload):
        example_payload["expected_output"]["code_selection"][0]["code"] = "99214.5"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_empty_history_items_rejected(self, example_payload):
        example_payload["input"]["history_items"] = []
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_empty_diagnosis_codes_rejected(self, example_payload):
        example_payload["expected_output"]["diagnosis_codes"] = []
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_empty_code_selection_rejected(self, example_payload):
        example_payload["expected_output"]["code_selection"] = []
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_unknown_top_level_key_rejected(self, example_payload):
        example_payload["stray_key"] = "should not be here"
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario(example_payload)

    def test_non_dict_rejected(self):
        with pytest.raises(ss.ScenarioValidationError):
            ss.validate_scenario("not a dict")


# ---------------------------------------------------------------------------
# Post-schema invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_surgery_flag_without_modifier_25_rejected(self, example_payload):
        example_payload["expected_output"]["code_selection"][0]["modifier"] = "59"
        with pytest.raises(ss.ScenarioValidationError) as ei:
            ss.validate_scenario(example_payload)
        assert any("modifier '25'" in e for e in ei.value.errors)

    def test_num_problems_mismatch_with_diagnosis_codes_rejected(self, example_payload):
        # The example has 3 diagnosis codes; advertise 4 problems
        # so the count is below the floor (codes < num_problems).
        # The invariant is `codes >= num_problems`, not `==`,
        # because real billing lists more codes than "problems
        # addressed" (chronic conditions contribute to MDM and
        # are billed in addition to the acute problem).
        example_payload["metadata"]["num_problems"] = 4
        with pytest.raises(ss.ScenarioValidationError) as ei:
            ss.validate_scenario(example_payload)
        assert any("num_problems" in e for e in ei.value.errors)

    def test_office_outpatient_em_code_accepted_silently(self, example_payload):
        # 99214 is in the office range; should not trigger the warning.
        ss.validate_scenario(example_payload)  # no raise

    def test_inpatient_em_code_emits_warning(self, example_payload):
        # 99221 is an initial inpatient code; outside the office range
        # the v1 variability matrix uses. The schema accepts it
        # (broader than the v1 sample distribution) but the validator
        # surfaces it.
        example_payload["metadata"]["em_code"] = "99221"
        with pytest.raises(ss.ScenarioValidationError) as ei:
            ss.validate_scenario(example_payload)
        assert any("office/outpatient" in e for e in ei.value.errors)


# ---------------------------------------------------------------------------
# Downstream-consumer tests — sampler and rubric can read the schema
# ---------------------------------------------------------------------------


class TestDownstreamCanConsume:
    """Acceptance: 'downstream tasks can consume it without further interpretation.'"""

    def test_sampler_can_read_scenario_id(self, example_payload):
        # The sampler in t_43ff3e89 keys on scenario_id.
        assert isinstance(example_payload["scenario_id"], str)
        assert example_payload["scenario_id"].startswith("sc_")

    def test_sampler_can_read_six_axes(self, example_payload):
        # The sampler draws 100 from a 9,450-cell space; it needs to
        # read the six variability-matrix axes.
        meta = example_payload["metadata"]
        for axis in (
            "payer",
            "specialty",
            "em_code",
            "num_problems",
            "mdm_tier",
            "difficulty",
        ):
            assert axis in meta, f"sampler needs metadata.{axis}"

    def test_rubric_can_read_diagnosis_codes(self, example_payload):
        # The rubric in t_221a3d69 keys on diagnosis code + description.
        codes = example_payload["expected_output"]["diagnosis_codes"]
        assert all("code" in c and "description" in c for c in codes)
        assert any(c.get("is_primary") for c in codes), (
            "exactly one code should be primary"
        )

    def test_rubric_can_read_mdm_rationale(self, example_payload):
        rationale = example_payload["expected_output"]["mdm_rationale"]
        assert len(rationale) > 50, "rationale should be a paragraph, not a sentence"

    def test_auditor_can_read_input_block(self, example_payload):
        inp = example_payload["input"]
        assert inp["chief_complaint"]
        assert inp["patient"]["age"] >= 0
        assert inp["patient"]["sex"] in ("M", "F", "O")
        assert len(inp["history_items"]) >= 1


# ---------------------------------------------------------------------------
# Sanity: the example is structurally a real scenario, not a synthetic stub
# ---------------------------------------------------------------------------


class TestExampleIsRealistic:
    def test_example_chief_complaint_is_clinical(self, example_payload):
        cc = example_payload["input"]["chief_complaint"]
        # Should mention age and a clinical situation, not a placeholder.
        assert "patient" in cc.lower() or any(c.isdigit() for c in cc)

    def test_example_history_has_hpi_ros_pfsh(self, example_payload):
        cats = {item["category"] for item in example_payload["input"]["history_items"]}
        assert "HPI" in cats
        assert "ROS" in cats
        assert "PFSH" in cats

    def test_example_modifier_25_present_for_surgery(self, example_payload):
        em_line = next(
            c
            for c in example_payload["expected_output"]["code_selection"]
            if c["code"].startswith("992")
        )
        assert em_line.get("modifier") == "25"

    def test_example_uses_office_outpatient_em_code(self, example_payload):
        em = example_payload["metadata"]["em_code"]
        assert em in {
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

    def test_example_md_rationale_mentions_problems_data_risk(self, example_payload):
        # The rubric checks the rationale for the three MDM axes.
        r = example_payload["expected_output"]["mdm_rationale"].lower()
        # problems: at least one of {problem, illness, condition, diagnosis}
        assert any(w in r for w in ("problem", "illness", "condition", "diagnosis"))
        # data: at least one of {data, review, lab, imaging, record, log}
        assert any(
            w in r for w in ("data", "review", "lab", "imaging", "log", "record")
        )
        # risk: "risk" appears
        assert "risk" in r
