"""Phase 2 tests: normalization, scoring, inventory safety and hard cases.

The semantic cases at the bottom are the ones that matter. They assert that the
*intended* destination survives shortlisting -- not that the generator picks it,
which is the mapping stage's decision.
"""

from __future__ import annotations

import pytest

from src.candidates import (
    DEFAULT_TOP_K,
    concepts,
    rank_candidates,
    reference_score,
    score_pair,
    shortlist_for_field,
    shortlist_for_table,
    sql_type_family,
    tokenize,
    type_score,
)
from src.config import PAIR_BY_SOURCE_TABLE
from src.loader import destination_paths, load_destination_schema, load_source_schema


@pytest.fixture(scope="module")
def source():
    return load_source_schema()


@pytest.fixture(scope="module")
def destination():
    return load_destination_schema()


def field(source, table: str, name: str):
    return next(f for f in source.tables[table].fields if f.name == name)


def dest_field(destination, collection: str, path: str):
    return next(f for f in destination.collections[collection].fields if f.path == path)


def shortlist(source, destination, table: str, name: str, top_k: int = DEFAULT_TOP_K):
    pair = PAIR_BY_SOURCE_TABLE[table]
    return shortlist_for_field(
        field(source, table, name),
        destination,
        pair.destination_collection,
        top_k=top_k,
    )


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def test_tokenize_splits_snake_case():
    assert tokenize("mgr_emp_id") == ["mgr", "emp", "id"]


def test_tokenize_splits_camel_case_and_dotted_paths():
    assert tokenize("fullName.firstName") == ["full", "name", "first", "name"]
    assert tokenize("stateOrProvince") == ["state", "or", "province"]


def test_tokenize_handles_free_text_comments():
    assert tokenize("A=Active, I=Inactive") == ["a", "active", "i", "inactive"]


def test_tokenize_of_empty_text_is_empty():
    assert tokenize("") == []


def test_concepts_expand_abbreviations():
    assert concepts("dept_cd") == {"department", "code"}
    assert concepts("tz_cd") == {"timezone", "code"}
    # `emp` expands to employee, which then folds onto the `person` concept.
    assert concepts("emp_id") == {"person", "id"}
    assert concepts("emp_id") == concepts("employeeId")


def test_concepts_expand_single_letter_abbreviations():
    """`f_name` / `l_name` are conventional, so f and l are real abbreviations."""
    assert concepts("f_name") == {"first", "name"}
    assert concepts("l_name") == {"last", "name"}


def test_concepts_drop_structural_filler():
    """`is` and `at` carry no signal; the meaningful word survives."""
    assert concepts("isActive") == {"status"}
    assert concepts("createdAt") == {"create"}


def test_concepts_drop_stray_single_characters_from_comments():
    """The A and I in "A=Active, I=Inactive" are noise, the words are not."""
    assert concepts("A=Active, I=Inactive") == {"status"}


def test_concepts_fold_synonyms_onto_one_canonical_concept():
    assert concepts("hire_dt") == concepts("startDate")
    assert concepts("term_dt") == concepts("endDate")
    assert concepts("mgr") == concepts("supervisor")


def test_concepts_keep_unrelated_words_apart():
    """`state` (province) must not be folded into the status group."""
    assert concepts("state_prov") == {"state", "province"}
    assert "status" not in concepts("state_prov")


# --------------------------------------------------------------------------
# Type compatibility
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("TINYINT(1)", "boolean"),
        ("INT", "integer"),
        ("DECIMAL(12,2)", "decimal"),
        ("DATETIME", "datetime"),
        ("DATE", "date"),
        ("VARCHAR(50)", "string"),
        ("CHAR(1)", "string"),
        ("GEOMETRY", "unknown"),
    ],
)
def test_sql_type_family(sql, expected):
    assert sql_type_family(sql) == expected


def test_type_score_rewards_compatible_pairs(source, destination):
    assert type_score(
        field(source, "emp_master", "is_remote"),
        dest_field(destination, "employees", "employment.isRemote"),
    ) == 1.0
    assert type_score(
        field(source, "emp_master", "hire_dt"),
        dest_field(destination, "employees", "employment.startDate"),
    ) == 1.0


def test_char1_flag_is_treated_as_a_boolean_candidate(source, destination):
    """CHAR(1) status codes are booleans in disguise; score above plain string."""
    assert type_score(
        field(source, "dept_info", "dept_stat"),
        dest_field(destination, "departments", "isActive"),
    ) == pytest.approx(0.70)


def test_type_score_is_zero_for_incompatible_pairs(source, destination):
    assert type_score(
        field(source, "emp_master", "hire_dt"),
        dest_field(destination, "employees", "contact.email"),
    ) == 0.0


# --------------------------------------------------------------------------
# Reference structure
# --------------------------------------------------------------------------


def test_primary_key_scores_against_document_identity(source, destination):
    assert reference_score(
        field(source, "dept_info", "dept_id"),
        dest_field(destination, "departments", "_id"),
    ) == 1.0


def test_foreign_key_scores_against_paired_reference(source, destination):
    """`mgr_emp_id` -> emp_master, and emp_master is paired with employees."""
    assert reference_score(
        field(source, "emp_master", "mgr_emp_id"),
        dest_field(destination, "employees", "employment.managerId"),
    ) == 1.0


def test_foreign_key_scores_zero_against_a_reference_to_another_entity(source, destination):
    assert reference_score(
        field(source, "emp_master", "mgr_emp_id"),
        dest_field(destination, "employees", "department.departmentId"),
    ) == 0.0


def test_non_key_column_earns_no_reference_credit(source, destination):
    assert reference_score(
        field(source, "emp_master", "work_email"),
        dest_field(destination, "employees", "contact.email"),
    ) == 0.0


# --------------------------------------------------------------------------
# Scoring mechanics
# --------------------------------------------------------------------------


def test_every_signal_and_the_total_stay_within_range(source, destination):
    for src in source.all_fields:
        collection = PAIR_BY_SOURCE_TABLE[src.table].destination_collection
        for dst in destination.collections[collection].fields:
            breakdown = score_pair(src, dst)
            for signal in ("name", "ref", "type", "desc", "fuzzy"):
                assert 0.0 <= getattr(breakdown, signal) <= 1.0
            assert 0.0 <= breakdown.total() <= 1.0


def test_ranking_is_deterministic(source, destination):
    first = shortlist(source, destination, "emp_master", "rec_stat")
    second = shortlist(source, destination, "emp_master", "rec_stat")
    assert [c.destination_field for c in first] == [c.destination_field for c in second]
    assert [c.score for c in first] == [c.score for c in second]


def test_candidates_are_ordered_by_descending_score(source, destination):
    scores = [c.score for c in shortlist(source, destination, "emp_master", "dept_id")]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# Shortlist size and inventory safety
# --------------------------------------------------------------------------


def test_default_shortlist_size_is_five(source, destination):
    assert len(shortlist(source, destination, "emp_master", "emp_cd")) == DEFAULT_TOP_K


@pytest.mark.parametrize("top_k", [1, 3, 8])
def test_shortlist_size_is_configurable(source, destination, top_k):
    assert len(shortlist(source, destination, "emp_master", "emp_cd", top_k)) <= top_k


def test_shortlist_can_return_fewer_than_top_k(source, destination):
    """Zero-scoring paths are dropped, so a small collection can run short."""
    result = shortlist(source, destination, "locations", "loc_id", top_k=20)
    assert len(result) < 20


def test_invalid_top_k_is_rejected(source, destination):
    with pytest.raises(ValueError, match="top_k"):
        rank_candidates(field(source, "emp_master", "emp_id"), [], top_k=0)


def test_candidates_never_leave_the_configured_collection(source, destination):
    """The inventory guard: nothing outside the paired collection can surface."""
    for table, pair in PAIR_BY_SOURCE_TABLE.items():
        allowed = set(destination_paths(destination, pair.destination_collection))
        shortlists = shortlist_for_table(
            source.tables[table].fields,
            destination,
            pair.destination_collection,
            top_k=25,
        )
        for candidates in shortlists.values():
            assert {c.destination_field for c in candidates} <= allowed


def test_employee_shortlists_cannot_reach_location_only_paths(source, destination):
    """`stateOrProvince` exists only on locations, never on employees."""
    for candidates in shortlist_for_table(
        source.tables["emp_master"].fields, destination, "employees", top_k=25
    ).values():
        assert "stateOrProvince" not in {c.destination_field for c in candidates}


def test_unknown_collection_is_rejected(source, destination):
    with pytest.raises(KeyError, match="unknown destination collection"):
        shortlist_for_field(
            field(source, "emp_master", "emp_id"), destination, "not_a_collection"
        )


def test_every_source_field_gets_a_shortlist(source, destination):
    covered = 0
    for table, pair in PAIR_BY_SOURCE_TABLE.items():
        shortlists = shortlist_for_table(
            source.tables[table].fields, destination, pair.destination_collection
        )
        assert set(shortlists) == {f.name for f in source.tables[table].fields}
        covered += len(shortlists)
    assert covered == 34


# --------------------------------------------------------------------------
# Difficult semantic cases
# --------------------------------------------------------------------------

HARD_CASES = [
    ("emp_master", "emp_cd", "employeeCode"),
    ("emp_master", "f_name", "fullName.firstName"),
    ("emp_master", "l_name", "fullName.lastName"),
    ("emp_master", "hire_dt", "employment.startDate"),
    ("emp_master", "term_dt", "employment.endDate"),
    ("emp_master", "dept_id", "department.departmentId"),
    ("emp_master", "mgr_emp_id", "employment.managerId"),
    ("emp_master", "job_lvl_cd", "employment.jobLevel"),
    ("emp_master", "base_sal", "compensation.baseSalary"),
    ("emp_master", "office_loc_id", "location.locationId"),
    ("emp_master", "rec_stat", "employment.status"),
    ("emp_master", "created_ts", "meta.createdAt"),
    ("emp_master", "updated_ts", "meta.updatedAt"),
    ("dept_info", "parent_dept_id", "parentDepartmentId"),
    ("dept_info", "dept_head_id", "headEmployeeId"),
    ("dept_info", "dept_stat", "isActive"),
    ("locations", "country_cd", "country"),
    ("locations", "tz_cd", "timezone"),
]


@pytest.mark.parametrize("table, name, expected", HARD_CASES)
def test_intended_target_survives_shortlisting(source, destination, table, name, expected):
    """The contract: recall. The intended path must reach the mapping stage."""
    paths = [c.destination_field for c in shortlist(source, destination, table, name)]
    assert expected in paths


@pytest.mark.parametrize("table, name, expected", HARD_CASES)
def test_intended_target_currently_ranks_first(source, destination, table, name, expected):
    """Quality check, one step stronger than the contract above.

    A drop to rank 2 is not a failure of the pipeline -- the mapping stage would
    still see the right path -- but it is a scoring regression worth reviewing.
    """
    assert shortlist(source, destination, table, name)[0].destination_field == expected


def test_primary_keys_shortlist_document_identity(source, destination):
    for table, name in [("emp_master", "emp_id"), ("dept_info", "dept_id"), ("locations", "loc_id")]:
        assert shortlist(source, destination, table, name)[0].destination_field == "_id"


def test_status_codes_diverge_by_destination_shape(source, destination):
    """Near-identical source patterns, different targets: enum vs boolean."""
    assert shortlist(source, destination, "emp_master", "rec_stat")[0].destination_field == "employment.status"
    assert shortlist(source, destination, "dept_info", "dept_stat")[0].destination_field == "isActive"


def test_field_without_an_equivalent_is_not_forced_to_a_confident_match(source, destination):
    """`dob` has no destination. It still gets date neighbours to reason about,
    but nothing should look like a confident answer."""
    candidates = shortlist(source, destination, "emp_master", "dob")

    assert candidates, "dob should still receive nearby candidates to reject"
    assert candidates[0].score < 0.5, "no candidate should look convincing"
    assert "employment.startDate" in {c.destination_field for c in candidates}
