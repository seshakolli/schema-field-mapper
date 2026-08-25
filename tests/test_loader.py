"""Phase 1 tests: ingestion, flattening and inventory counts.

The counts below were verified by hand against the assignment document. They
are the contract the rest of the pipeline relies on -- if a schema file is
edited and a count moves, that is a regression, not a surprise.
"""

from __future__ import annotations

import pytest

from src.config import PAIR_BY_SOURCE_TABLE, TABLE_PAIRS
from src.loader import (
    destination_path_set,
    destination_paths,
    flatten_fields,
    load_destination_schema,
    load_source_schema,
    source_field_names,
)


@pytest.fixture(scope="module")
def source():
    return load_source_schema()


@pytest.fixture(scope="module")
def destination():
    return load_destination_schema()


# --------------------------------------------------------------------------
# Source field counts
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table, expected",
    [("emp_master", 19), ("dept_info", 7), ("locations", 8)],
)
def test_source_table_field_counts(source, table, expected):
    assert len(source.tables[table].fields) == expected


def test_source_total_field_count(source):
    assert len(source.all_fields) == 34


def test_source_tables_are_exactly_the_three_in_the_assignment(source):
    assert set(source.tables) == {"emp_master", "dept_info", "locations"}


# --------------------------------------------------------------------------
# Destination leaf counts
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "collection, expected",
    [("employees", 25), ("departments", 7), ("locations", 8)],
)
def test_destination_collection_leaf_counts(destination, collection, expected):
    assert len(destination.collections[collection].fields) == expected


def test_destination_total_leaf_count(destination):
    assert len(destination.all_fields) == 40


# --------------------------------------------------------------------------
# Flattening
# --------------------------------------------------------------------------


def test_nested_paths_use_dot_notation(destination):
    paths = destination_paths(destination, "employees")
    for expected in [
        "fullName.firstName",
        "fullName.lastName",
        "employment.isRemote",
        "employment.managerId",
        "compensation.baseSalary",
        "contact.email",
        "department.departmentId",
        "location.timezone",
        "meta.createdAt",
    ]:
        assert expected in paths


def test_sub_document_nodes_are_not_emitted_as_leaves(destination):
    """`fullName` is a container; only its children are mappable targets."""
    paths = destination_path_set(destination, "employees")
    for container in ["fullName", "employment", "compensation", "contact",
                      "department", "location", "meta"]:
        assert container not in paths


def test_top_level_fields_have_no_prefix(destination):
    paths = destination_paths(destination, "employees")
    assert "_id" in paths
    assert "employeeCode" in paths


def test_flatten_preserves_declaration_order():
    fields = {
        "_id": {"type": "ObjectId", "description": None},
        "outer": {
            "type": "Object",
            "fields": {
                "a": {"type": "String", "description": None},
                "b": {"type": "Object", "fields": {"c": {"type": "Number", "description": None}}},
            },
        },
        "tail": {"type": "String", "description": None},
    }
    assert [f.path for f in flatten_fields("x", fields)] == [
        "_id",
        "outer.a",
        "outer.b.c",
        "tail",
    ]


def test_flatten_rejects_empty_sub_document():
    with pytest.raises(ValueError, match="no fields"):
        flatten_fields("x", {"empty": {"type": "Object", "fields": {}}})


def test_destination_field_helpers(destination):
    by_path = {f.path: f for f in destination.collections["employees"].fields}

    nested = by_path["fullName.firstName"]
    assert nested.is_nested and nested.name == "firstName" and nested.parent_path == "fullName"

    flat = by_path["_id"]
    assert not flat.is_nested and flat.parent_path is None

    ref = by_path["employment.managerId"]
    assert ref.is_reference and ref.references.as_text() == "employees._id"


# --------------------------------------------------------------------------
# Source field metadata
# --------------------------------------------------------------------------


def test_source_field_constraint_flags(source):
    by_name = {f.name: f for f in source.tables["emp_master"].fields}

    assert by_name["emp_id"].is_primary_key and by_name["emp_id"].is_unique
    assert not by_name["emp_id"].is_nullable

    assert not by_name["f_name"].is_nullable       # NOT NULL
    assert by_name["dob"].is_nullable              # no constraint

    assert by_name["dept_id"].is_foreign_key
    assert by_name["dept_id"].references.as_text() == "dept_info.dept_id"


def test_inline_comments_are_preserved_as_descriptions(source):
    by_name = {f.name: f for f in source.tables["emp_master"].fields}
    assert by_name["rec_stat"].description == "A=Active, I=Inactive, T=Terminated"
    assert by_name["is_remote"].description == "0 or 1"


# --------------------------------------------------------------------------
# Fixed pairing configuration
# --------------------------------------------------------------------------


def test_table_pairs_match_the_assignment():
    assert [(p.source_table, p.destination_collection) for p in TABLE_PAIRS] == [
        ("emp_master", "employees"),
        ("dept_info", "departments"),
        ("locations", "locations"),
    ]


def test_every_pair_resolves_against_both_schemas(source, destination):
    for pair in TABLE_PAIRS:
        assert pair.source_table in source.tables
        assert pair.destination_collection in destination.collections


def test_every_source_table_is_paired(source):
    assert set(PAIR_BY_SOURCE_TABLE) == set(source.tables)


def test_source_field_names_are_addressable(source):
    assert source_field_names(source, "dept_info") == [
        "dept_id", "dept_cd", "dept_nm", "parent_dept_id",
        "dept_head_id", "cost_ctr_cd", "dept_stat",
    ]
