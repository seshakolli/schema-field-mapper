"""Phase 5 tests: deterministic assembly and the validator.

Assembly is driven from stage-4 results, so these tests build results directly
rather than calling a model. The validator is exercised by corrupting a valid
document and asserting the specific check fires.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.config import OUTPUT_DIR, STAGE_DIR, TABLE_PAIRS
from src.llm import CallOutcome
from src.loader import destination_paths, load_destination_schema, load_source_schema
from src.models import FieldMappingProposal, MappingDocument
from src.stages.assemble import assemble
from src.stages.map_fields import FieldMappingResult
from validate import validate_document

STAGE_ARTIFACT = STAGE_DIR / "field_mappings.json"
MAPPING_PATH = OUTPUT_DIR / "mapping.json"

# The denormalized employee paths with no emp_master source column. Written out
# here as the expected answer; assembly derives it by set difference and must
# agree.
EXPECTED_EMPLOYEE_UNMAPPED = [
    "department.code",
    "department.name",
    "location.code",
    "location.name",
    "location.city",
    "location.country",
    "location.timezone",
]


@pytest.fixture(scope="module")
def source():
    return load_source_schema()


@pytest.fixture(scope="module")
def destination():
    return load_destination_schema()


@pytest.fixture(scope="module")
def stage_results():
    if not STAGE_ARTIFACT.exists():
        pytest.skip("no mapping-stage artifact; run scripts.run_mapping first")
    payload = json.loads(STAGE_ARTIFACT.read_text(encoding="utf-8"))
    return [FieldMappingResult.model_validate(r) for r in payload["results"]]


@pytest.fixture(scope="module")
def document(stage_results, source, destination) -> MappingDocument:
    return assemble(stage_results, source, destination)


@pytest.fixture(scope="module")
def raw(document) -> dict:
    return document.model_dump()


def corrupt(raw: dict, mutate) -> dict:
    clone = copy.deepcopy(raw)
    mutate(clone)
    return clone


def table_of(raw: dict, name: str) -> dict:
    return next(t for t in raw["tables"] if t["source_table"] == name)


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def test_top_level_keys_are_exactly_the_specified_ones(raw):
    assert list(raw) == [
        "mapping_version",
        "source",
        "destination",
        "generated_at",
        "tables",
    ]


def test_top_level_literals(raw):
    assert raw["mapping_version"] == "1.0"
    assert raw["source"] == "legacy_hrm (MySQL)"
    assert raw["destination"] == "people_platform (MongoDB)"


def test_generated_at_is_iso8601(raw):
    from datetime import datetime

    assert datetime.fromisoformat(raw["generated_at"])


def test_exactly_three_table_mappings_in_the_configured_order(raw):
    assert [(t["source_table"], t["destination_collection"]) for t in raw["tables"]] == [
        ("emp_master", "employees"),
        ("dept_info", "departments"),
        ("locations", "locations"),
    ]


def test_table_keys_are_exactly_the_specified_ones(raw):
    for table in raw["tables"]:
        assert list(table) == [
            "source_table",
            "destination_collection",
            "confidence",
            "reasoning",
            "field_mappings",
            "unmapped_source_fields",
            "unmapped_destination_fields",
        ]


def test_field_mapping_keys_are_exactly_the_six_specified(raw):
    for table in raw["tables"]:
        for mapping in table["field_mappings"]:
            assert list(mapping) == [
                "source_field",
                "destination_field",
                "type_transform",
                "confidence",
                "reasoning",
                "notes",
            ]


def test_table_metadata_comes_from_configuration(raw):
    """The pairs are given by the assignment, so their metadata is fixed."""
    for pair in TABLE_PAIRS:
        table = table_of(raw, pair.source_table)
        assert table["confidence"] == pair.confidence
        assert table["reasoning"] == pair.reasoning


# --------------------------------------------------------------------------
# Coverage and unmapped handling
# --------------------------------------------------------------------------


def test_dob_appears_only_in_unmapped_source_fields(raw):
    employees = table_of(raw, "emp_master")
    assert "dob" in employees["unmapped_source_fields"]
    assert "dob" not in [m["source_field"] for m in employees["field_mappings"]]


def test_no_field_mapping_has_a_null_destination(raw):
    for table in raw["tables"]:
        for mapping in table["field_mappings"]:
            assert mapping["destination_field"] is not None


def test_employees_has_18_mappings_and_one_unmapped_source(raw):
    employees = table_of(raw, "emp_master")
    assert len(employees["field_mappings"]) == 18
    assert employees["unmapped_source_fields"] == ["dob"]


def test_exactly_33_field_mappings_and_one_unmapped_source(raw):
    mappings = sum(len(t["field_mappings"]) for t in raw["tables"])
    unmapped = sum(len(t["unmapped_source_fields"]) for t in raw["tables"])
    assert (mappings, unmapped) == (33, 1)


def test_all_34_source_fields_are_covered_exactly_once(raw, source):
    covered: list[str] = []
    for table in raw["tables"]:
        covered += [
            f"{table['source_table']}.{m['source_field']}"
            for m in table["field_mappings"]
        ]
        covered += [
            f"{table['source_table']}.{name}"
            for name in table["unmapped_source_fields"]
        ]

    inventory = {f.qualified_name for f in source.all_fields}
    assert len(covered) == 34
    assert set(covered) == inventory
    assert len(set(covered)) == len(covered)


def test_employee_unmapped_destination_set_is_the_denormalized_paths(raw):
    employees = table_of(raw, "emp_master")
    assert employees["unmapped_destination_fields"] == EXPECTED_EMPLOYEE_UNMAPPED


def test_unmapped_destination_is_derived_by_set_difference(raw, destination):
    """Recomputed independently of assembly, from the flattened inventory."""
    for table in raw["tables"]:
        selected = {m["destination_field"] for m in table["field_mappings"]}
        inventory = destination_paths(destination, table["destination_collection"])
        assert table["unmapped_destination_fields"] == [
            path for path in inventory if path not in selected
        ]


def test_departments_and_locations_have_empty_unmapped_arrays(raw):
    for name in ["dept_info", "locations"]:
        table = table_of(raw, name)
        assert table["unmapped_source_fields"] == []
        assert table["unmapped_destination_fields"] == []


def test_the_three_primary_keys_map_to_document_identity(raw):
    for table_name, field_name in [
        ("emp_master", "emp_id"),
        ("dept_info", "dept_id"),
        ("locations", "loc_id"),
    ]:
        table = table_of(raw, table_name)
        mapping = next(
            m for m in table["field_mappings"] if m["source_field"] == field_name
        )
        assert mapping["destination_field"] == "_id"


# --------------------------------------------------------------------------
# Assembly behaviour
# --------------------------------------------------------------------------


def test_assembly_is_deterministic_apart_from_the_timestamp(
    stage_results, source, destination
):
    first = assemble(stage_results, source, destination, generated_at="2026-01-01T00:00:00+00:00")
    second = assemble(stage_results, source, destination, generated_at="2026-01-01T00:00:00+00:00")
    assert first.model_dump() == second.model_dump()


def test_field_mappings_follow_source_schema_order(raw, source):
    for table in raw["tables"]:
        order = [f.name for f in source.tables[table["source_table"]].fields]
        emitted = [m["source_field"] for m in table["field_mappings"]]
        assert emitted == [name for name in order if name in set(emitted)]


def test_assembly_refuses_a_missing_source_field(stage_results, source, destination):
    incomplete = [r for r in stage_results if r.source_field != "emp_cd"]
    with pytest.raises(ValueError, match="emp_cd"):
        assemble(incomplete, source, destination)


def test_assembly_refuses_results_for_an_unconfigured_table(
    stage_results, source, destination
):
    stray = stage_results[0].model_copy(update={"source_table": "not_a_table"})
    with pytest.raises(ValueError, match="unconfigured tables"):
        assemble(list(stage_results) + [stray], source, destination)


# --------------------------------------------------------------------------
# Validator -- the generated document
# --------------------------------------------------------------------------


def test_the_generated_document_validates(raw):
    report = validate_document(raw)
    assert report.failures == [], report.render()


def test_the_written_mapping_file_validates():
    if not MAPPING_PATH.exists():
        pytest.skip("no mapping.json; run scripts.assemble_output first")
    report = validate_document(json.loads(MAPPING_PATH.read_text(encoding="utf-8")))
    assert report.failures == [], report.render()


# --------------------------------------------------------------------------
# Validator -- corruption must fail loudly
# --------------------------------------------------------------------------


def _fails(raw: dict, mutate, expected: str) -> None:
    report = validate_document(corrupt(raw, mutate))
    assert report.failures, f"expected a failure mentioning {expected!r}"
    assert any(expected in failure for failure in report.failures), report.render()


def test_an_extra_top_level_property_fails(raw):
    _fails(raw, lambda d: d.update(secondary_mappings=[]), "structure")


def test_an_extra_field_mapping_property_fails(raw):
    def mutate(d):
        table_of(d, "locations")["field_mappings"][0]["priority"] = "high"

    _fails(raw, mutate, "structure")


def test_a_hallucinated_destination_path_fails(raw):
    def mutate(d):
        table_of(d, "emp_master")["field_mappings"][0]["destination_field"] = (
            "employment.hireDate"
        )

    _fails(raw, mutate, "destination_field exists")


def test_a_path_from_another_collection_fails(raw):
    def mutate(d):
        table_of(d, "emp_master")["field_mappings"][0]["destination_field"] = (
            "stateOrProvince"
        )

    _fails(raw, mutate, "destination_field exists")


def test_a_duplicated_source_field_fails(raw):
    def mutate(d):
        table = table_of(d, "locations")
        table["field_mappings"].append(copy.deepcopy(table["field_mappings"][0]))

    _fails(raw, mutate, "twice")


def test_a_duplicated_destination_path_fails(raw):
    def mutate(d):
        table = table_of(d, "locations")
        table["field_mappings"][1]["destination_field"] = table["field_mappings"][0][
            "destination_field"
        ]

    _fails(raw, mutate, "selected twice")


def test_a_source_field_in_both_lists_fails(raw):
    def mutate(d):
        table = table_of(d, "locations")
        table["unmapped_source_fields"].append(table["field_mappings"][0]["source_field"])

    _fails(raw, mutate, "both mapped and unmapped")


def test_a_missing_source_field_fails_coverage(raw):
    def mutate(d):
        table_of(d, "locations")["field_mappings"].pop()

    _fails(raw, mutate, "coverage")


def test_an_incorrect_unmapped_source_list_fails(raw):
    def mutate(d):
        table_of(d, "emp_master")["unmapped_source_fields"] = []

    _fails(raw, mutate, "coverage")


def test_an_incorrect_unmapped_destination_list_fails(raw):
    def mutate(d):
        table_of(d, "dept_info")["unmapped_destination_fields"] = ["code"]

    _fails(raw, mutate, "unmapped_destination_fields")


def test_a_confidence_outside_the_unit_interval_fails(raw):
    def mutate(d):
        table_of(d, "locations")["field_mappings"][0]["confidence"] = 1.7

    _fails(raw, mutate, "structure")


def test_multi_sentence_reasoning_fails(raw):
    def mutate(d):
        table_of(d, "locations")["field_mappings"][0]["reasoning"] = (
            "This is one sentence. This is a second sentence."
        )

    _fails(raw, mutate, "one plain-English sentence")


def test_a_missing_type_transform_fails(raw):
    def mutate(d):
        table_of(d, "locations")["field_mappings"][0]["type_transform"] = None

    _fails(raw, mutate, "type_transform")


def test_an_invalid_generated_at_fails(raw):
    _fails(raw, lambda d: d.update(generated_at="last Tuesday"), "ISO 8601")


def test_a_wrong_mapping_version_fails(raw):
    _fails(raw, lambda d: d.update(mapping_version="2.0"), "mapping_version")


def test_a_missing_table_fails(raw):
    _fails(raw, lambda d: d["tables"].pop(), "3 table mappings")


def test_a_rewired_table_pair_fails(raw):
    def mutate(d):
        table_of(d, "locations")["destination_collection"] = "departments"

    _fails(raw, mutate, "table pairs")
