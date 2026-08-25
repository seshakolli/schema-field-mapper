"""Phase 3 tests: the scoped mapping call, with the Anthropic client mocked.

Nothing here touches the network. A stub stands in for the SDK client and
returns scripted responses, which lets the retry and rejection paths be tested
directly rather than inferred.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.candidates import shortlist_for_field
from src.config import DEFAULT_MODEL, PAIR_BY_SOURCE_TABLE
from src.llm import StructuredCallError, StructuredClient, prompt_fingerprint
from src.loader import load_destination_schema, load_source_schema
from src.models import FieldMappingProposal
from src.prompts.field_mapping import SYSTEM_PROMPT, build_user_prompt
from src.sentence import is_one_sentence
from src.stages.map_fields import _source_type_preserved, map_field, map_fields


@pytest.fixture(scope="module")
def source():
    return load_source_schema()


@pytest.fixture(scope="module")
def destination():
    return load_destination_schema()


def field(source, table: str, name: str):
    return next(f for f in source.tables[table].fields if f.name == name)


# --------------------------------------------------------------------------
# Stub SDK client
# --------------------------------------------------------------------------


class StubResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class StubMessages:
    """Stands in for `client.messages`, replaying a scripted list of answers."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("the stub ran out of scripted responses")

        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            # Validate through the real model, so a malformed payload fails the
            # same way the SDK would.
            return StubResponse(FieldMappingProposal.model_validate(item))
        return StubResponse(item)


class StubClient:
    def __init__(self, script):
        self.messages = StubMessages(script)

    @property
    def calls(self):
        return self.messages.calls


def make_client(script, **kwargs) -> tuple[StructuredClient, StubClient]:
    """A StructuredClient wired to a stub, with caching off unless requested."""
    stub = StubClient(script)
    kwargs.setdefault("use_cache", False)
    kwargs.setdefault("cache_dir", None)
    return StructuredClient(client=stub, **kwargs), stub


MATCH = {
    "destination_field": "employment.startDate",
    "type_transform": "DATETIME -> ISODate",
    "confidence": 0.93,
    "reasoning": "The legacy hire date is the start of the employment period.",
    "notes": "Assume UTC unless the source system records a local timezone.",
}

NO_MATCH = {
    "destination_field": None,
    "type_transform": None,
    "confidence": 0.9,
    "reasoning": "The destination employee document carries no date of birth.",
    "notes": None,
}


# --------------------------------------------------------------------------
# Prompt scoping -- the assignment's central constraint
# --------------------------------------------------------------------------


def test_prompt_contains_only_the_one_field_and_its_shortlist(source, destination):
    src = field(source, "emp_master", "hire_dt")
    candidates = shortlist_for_field(src, destination, "employees")
    prompt = build_user_prompt(src, "employees", candidates)

    assert "hire_dt" in prompt
    assert "emp_master" in prompt

    # No other source column may appear.
    for other in source.all_fields:
        if other.name in {"hire_dt", "city"}:  # `city` is a destination path too
            continue
        assert other.name not in prompt, f"{other.name} leaked into the prompt"


def test_prompt_excludes_the_rest_of_the_destination_schema(source, destination):
    src = field(source, "emp_master", "hire_dt")
    candidates = shortlist_for_field(src, destination, "employees")
    shortlisted = {c.destination_field for c in candidates}
    prompt = build_user_prompt(src, "employees", candidates)

    for dst in destination.all_fields:
        if dst.path in shortlisted:
            continue
        assert f"path: {dst.path}" not in prompt


def test_prompt_omits_the_deterministic_candidate_score(source, destination):
    """Retrieval rank must not colour the model's confidence."""
    src = field(source, "emp_master", "rec_stat")
    candidates = shortlist_for_field(src, destination, "employees")
    prompt = build_user_prompt(src, "employees", candidates)

    for candidate in candidates:
        assert f"{candidate.score:.3f}" not in prompt
    assert "score" not in prompt.lower()


def test_prompt_carries_the_metadata_the_transform_reasoning_needs(source, destination):
    src = field(source, "emp_master", "mgr_emp_id")
    prompt = build_user_prompt(
        src, "employees", shortlist_for_field(src, destination, "employees")
    )
    assert "INT" in prompt
    assert "references emp_master.emp_id" in prompt


def test_prompt_includes_the_source_comment(source, destination):
    src = field(source, "emp_master", "rec_stat")
    prompt = build_user_prompt(
        src, "employees", shortlist_for_field(src, destination, "employees")
    )
    assert "A=Active, I=Inactive, T=Terminated" in prompt


def test_system_prompt_states_the_rubric_and_forbids_invention():
    assert "0.95-1.00" in SYSTEM_PROMPT
    assert "below 0.70" in SYSTEM_PROMPT
    assert "Never invent" in SYSTEM_PROMPT
    assert "one plain-English sentence" in SYSTEM_PROMPT


def test_system_prompt_separates_type_similarity_from_equivalence():
    assert "Datatype compatibility is not semantic equivalence" in SYSTEM_PROMPT


def test_prompt_handles_an_empty_shortlist(source, destination):
    src = field(source, "emp_master", "hire_dt")
    prompt = build_user_prompt(src, "employees", [])
    assert "the answer must be null" in prompt


# --------------------------------------------------------------------------
# Valid selection
# --------------------------------------------------------------------------


def test_valid_candidate_selection(source, destination):
    client, stub = make_client([MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.is_match
    assert result.proposal.destination_field == "employment.startDate"
    assert result.proposal.confidence == 0.93
    assert result.outcome.attempts == 1
    assert len(stub.calls) == 1


def test_result_records_the_shortlist_and_the_retrieval_score(source, destination):
    client, _ = make_client([MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert "employment.startDate" in result.candidates
    assert result.candidate_score == pytest.approx(0.650, abs=1e-3)
    # The two numbers are tracked separately and must not have been merged.
    assert result.candidate_score != result.proposal.confidence


def test_no_match_is_represented_as_a_null_destination(source, destination):
    client, _ = make_client([NO_MATCH])
    result = map_field(field(source, "emp_master", "dob"), destination, client)

    assert not result.is_match
    assert result.proposal.destination_field is None
    assert result.proposal.type_transform is None
    assert result.candidate_score is None


def test_each_field_is_a_separate_call(source, destination):
    client, stub = make_client([MATCH, NO_MATCH])
    results = map_fields(
        [field(source, "emp_master", "hire_dt"), field(source, "emp_master", "dob")],
        destination,
        client,
    )

    assert len(results) == 2
    assert len(stub.calls) == 2
    # No call carries another column's prompt.
    assert "dob" not in stub.calls[0]["messages"][0]["content"]


def test_the_request_uses_the_configured_model_and_structured_output(source, destination):
    client, stub = make_client([MATCH])
    map_field(field(source, "emp_master", "hire_dt"), destination, client)

    call = stub.calls[0]
    assert call["model"] == client.model
    assert call["output_format"] is FieldMappingProposal
    assert call["system"] == SYSTEM_PROMPT


# --------------------------------------------------------------------------
# Rejection and retry
# --------------------------------------------------------------------------


def test_hallucinated_destination_is_rejected_then_recovered(source, destination):
    invented = dict(MATCH, destination_field="employment.hireDate")
    client, stub = make_client([invented, MATCH])

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.proposal.destination_field == "employment.startDate"
    assert result.outcome.attempts == 2
    assert len(stub.calls) == 2
    assert "employment.hireDate" in result.outcome.rejections[0]


def test_the_retry_prompt_carries_the_rejection_reason(source, destination):
    invented = dict(MATCH, destination_field="not.a.real.path")
    client, stub = make_client([invented, MATCH])
    map_field(field(source, "emp_master", "hire_dt"), destination, client)

    retry_prompt = stub.calls[1]["messages"][0]["content"]
    assert "was rejected" in retry_prompt
    assert "not.a.real.path" in retry_prompt


def test_a_path_from_another_collection_is_unauthorized(source, destination):
    """`stateOrProvince` is real, but not in this collection or this shortlist."""
    wrong_collection = dict(MATCH, destination_field="stateOrProvince")
    client, _ = make_client([wrong_collection, MATCH])

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert result.proposal.destination_field == "employment.startDate"


def test_a_real_path_outside_the_shortlist_is_still_unauthorized(source, destination):
    """The shortlist, not the collection, is the authorization boundary."""
    src = field(source, "emp_master", "hire_dt")
    shortlisted = {
        c.destination_field for c in shortlist_for_field(src, destination, "employees")
    }
    outside = next(
        f.path
        for f in destination.collections["employees"].fields
        if f.path not in shortlisted
    )

    client, stub = make_client([dict(MATCH, destination_field=outside), MATCH])
    map_field(src, destination, client)
    assert len(stub.calls) == 2


def test_malformed_structured_output_is_rejected_then_recovered(source, destination):
    malformed = dict(MATCH)
    malformed.pop("reasoning")  # required field missing
    client, stub = make_client([malformed, MATCH])

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.outcome.attempts == 2
    assert "reasoning" in result.outcome.rejections[0]
    assert len(stub.calls) == 2


def test_out_of_range_confidence_is_rejected(source, destination):
    client, stub = make_client([dict(MATCH, confidence=1.4), MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.outcome.attempts == 2
    assert "confidence" in result.outcome.rejections[0]


def test_a_match_without_a_type_transform_is_rejected(source, destination):
    client, _ = make_client([dict(MATCH, type_transform=None), MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert result.outcome.attempts == 2


def test_a_non_match_with_a_type_transform_is_rejected(source, destination):
    incoherent = dict(NO_MATCH, type_transform="DATE -> ISODate")
    client, _ = make_client([incoherent, NO_MATCH])
    result = map_field(field(source, "emp_master", "dob"), destination, client)
    assert result.outcome.attempts == 2


def test_an_empty_structured_response_is_rejected(source, destination):
    client, _ = make_client([None, MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert result.outcome.attempts == 2


def test_retries_are_bounded_and_then_raise(source, destination):
    invented = dict(MATCH, destination_field="employment.hireDate")
    client, stub = make_client([invented, invented, invented], max_attempts=3)

    with pytest.raises(StructuredCallError, match="after 3 attempts"):
        map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert len(stub.calls) == 3


def test_retry_budget_is_configurable(source, destination):
    invented = dict(MATCH, destination_field="employment.hireDate")
    client, stub = make_client([invented, MATCH], max_attempts=1)

    with pytest.raises(StructuredCallError, match="after 1 attempt"):
        map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert len(stub.calls) == 1


# --------------------------------------------------------------------------
# Confidence bounds
# --------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", [-0.1, 1.01, 2.0])
def test_confidence_outside_the_unit_interval_is_invalid(confidence):
    with pytest.raises(ValidationError):
        FieldMappingProposal.model_validate(dict(MATCH, confidence=confidence))


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_within_the_unit_interval_is_valid(confidence):
    assert FieldMappingProposal.model_validate(
        dict(MATCH, confidence=confidence)
    ).confidence == confidence


def test_unknown_fields_in_the_response_are_rejected(source, destination):
    with pytest.raises(ValidationError):
        FieldMappingProposal.model_validate(dict(MATCH, extra_key="surprise"))


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------


def test_a_cached_response_skips_the_api(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")

    client, stub = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    first = map_field(src, destination, client)
    assert first.outcome.from_cache is False
    assert len(stub.calls) == 1

    # A second client over the same cache directory, scripted to fail if called.
    warm, warm_stub = make_client([], cache_dir=tmp_path, use_cache=True)
    second = map_field(src, destination, warm)

    assert second.outcome.from_cache is True
    assert second.proposal.destination_field == first.proposal.destination_field
    assert warm_stub.calls == []


def test_cache_is_bypassed_when_disabled(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")
    client, _ = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    map_field(src, destination, client)

    cold, cold_stub = make_client([MATCH], cache_dir=tmp_path, use_cache=False)
    assert map_field(src, destination, cold).outcome.from_cache is False
    assert len(cold_stub.calls) == 1


def test_a_different_prompt_gets_a_different_cache_key():
    base = prompt_fingerprint("sys", "user", "Model", "claude-opus-5")
    assert base != prompt_fingerprint("sys", "user2", "Model", "claude-opus-5")
    assert base != prompt_fingerprint("sys2", "user", "Model", "claude-opus-5")
    assert base != prompt_fingerprint("sys", "user", "Model", "other-model")
    assert base == prompt_fingerprint("sys", "user", "Model", "claude-opus-5")


def test_a_corrupt_cache_entry_falls_back_to_the_api(tmp_path, source, destination):
    src = field(source, "emp_master", "hire_dt")
    client, _ = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    map_field(src, destination, client)

    for path in tmp_path.glob("*.json"):
        path.write_text("{ not json", encoding="utf-8")

    recovered, stub = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    assert map_field(src, destination, recovered).is_match
    assert len(stub.calls) == 1


def test_only_validated_responses_are_cached(tmp_path, source, destination):
    """A rejected answer must never be written to the cache."""
    invented = dict(MATCH, destination_field="employment.hireDate")
    client, _ = make_client([invented, MATCH], cache_dir=tmp_path, use_cache=True)
    map_field(field(source, "emp_master", "hire_dt"), destination, client)

    cached = [p.read_text(encoding="utf-8") for p in tmp_path.glob("*.json")]
    assert len(cached) == 1
    assert "employment.hireDate" not in cached[0]


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_no_credential_is_needed_to_build_the_client():
    """The backend is constructed lazily, so importing costs nothing."""
    client = StructuredClient(client=None, use_cache=False, cache_dir=None)
    assert client._backend is None


def test_every_source_table_resolves_a_destination_collection(source):
    for table in source.tables:
        assert PAIR_BY_SOURCE_TABLE[table].destination_collection


# --------------------------------------------------------------------------
# Model selection
# --------------------------------------------------------------------------


def test_the_model_defaults_to_sonnet(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    assert StructuredClient(client=None, cache_dir=None).model == DEFAULT_MODEL
    assert DEFAULT_MODEL == "claude-sonnet-5"


def test_the_model_can_be_switched_by_environment_variable(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    assert StructuredClient(client=None, cache_dir=None).model == "claude-opus-5"


def test_an_empty_environment_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "   ")
    assert StructuredClient(client=None, cache_dir=None).model == DEFAULT_MODEL


def test_an_explicit_model_argument_wins(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    client = StructuredClient(client=None, model="claude-haiku-4-5", cache_dir=None)
    assert client.model == "claude-haiku-4-5"


def test_the_model_is_resolved_late_not_at_import(monkeypatch):
    """A .env loaded after import must still be honoured."""
    monkeypatch.setenv("CLAUDE_MODEL", "model-a")
    first = StructuredClient(client=None, cache_dir=None).model
    monkeypatch.setenv("CLAUDE_MODEL", "model-b")
    second = StructuredClient(client=None, cache_dir=None).model
    assert (first, second) == ("model-a", "model-b")


def test_the_request_sends_the_resolved_model(monkeypatch, source, destination):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    client, stub = make_client([MATCH])
    map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert stub.calls[0]["model"] == "claude-opus-5"


def test_switching_model_does_not_reuse_the_other_models_cache(
    tmp_path, monkeypatch, source, destination
):
    src = field(source, "emp_master", "hire_dt")

    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5")
    warm, _ = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    assert map_field(src, destination, warm).outcome.from_cache is False

    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    other, other_stub = make_client([MATCH], cache_dir=tmp_path, use_cache=True)
    assert map_field(src, destination, other).outcome.from_cache is False
    assert len(other_stub.calls) == 1


# --------------------------------------------------------------------------
# Reasoning shape
# --------------------------------------------------------------------------


def test_multi_sentence_reasoning_is_rejected_then_recovered(source, destination):
    wordy = dict(
        MATCH,
        reasoning="The hire date starts employment. A timezone assumption is needed.",
    )
    client, stub = make_client([wordy, MATCH])

    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)

    assert result.outcome.attempts == 2
    assert "exactly one sentence" in result.outcome.rejections[0]
    assert len(stub.calls) == 2


def test_unterminated_reasoning_is_rejected(source, destination):
    client, _ = make_client([dict(MATCH, reasoning="The hire date starts employment"), MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert "full stop" in result.outcome.rejections[0]


def test_the_reasoning_rejection_reaches_the_retry_prompt(source, destination):
    wordy = dict(MATCH, reasoning="One thing here. Another thing here.")
    client, stub = make_client([wordy, MATCH])
    map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert "exactly one sentence" in stub.calls[1]["messages"][0]["content"]


def test_accepted_reasoning_is_one_sentence(source, destination):
    client, _ = make_client([MATCH])
    result = map_field(field(source, "emp_master", "hire_dt"), destination, client)
    assert is_one_sentence(result.proposal.reasoning)


# --------------------------------------------------------------------------
# Source-type preservation in type_transform
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "declared, transform, expected",
    [
        ("CHAR(1)", "CHAR(1) code -> String enum", True),
        ("CHAR(1)", "CHAR(1) -> Boolean", True),
        ("CHAR(1)", "CHAR -> String", False),          # precision dropped
        ("VARCHAR(20)", "VARCHAR(20) -> String", True),
        ("VARCHAR(20)", "VARCHAR -> String", False),
        ("DECIMAL(12,2)", "DECIMAL(12,2) -> Number", True),
        ("DECIMAL(12,2)", "DECIMAL(12, 2) -> Number", True),   # spacing tolerated
        ("DECIMAL(12,2)", "DECIMAL -> Number", False),
        ("DATETIME", "DATETIME -> ISODate", True),
        ("DATETIME", "DATE -> ISODate", False),        # type changed
        ("INT", "INT primary key -> ObjectId", True),
        ("TINYINT(1)", "TINYINT(1) -> Boolean", True),
        ("TINYINT(1)", "TINYINT -> Boolean", False),
    ],
)
def test_source_type_preservation_rule(declared, transform, expected):
    assert _source_type_preserved(declared, transform) is expected


def test_the_rule_only_inspects_the_left_hand_side():
    """A destination that happens to name the type must not satisfy the rule."""
    assert _source_type_preserved("CHAR(1)", "CHAR -> CHAR(1)") is False


def test_a_shortened_source_type_is_rejected_then_recovered(source, destination):
    """`rec_stat` is CHAR(1); "CHAR -> String" loses the declared precision."""
    shortened = dict(
        MATCH,
        destination_field="employment.status",
        type_transform="CHAR -> String",
        reasoning="The coded record status maps to the employment status string.",
    )
    good = dict(shortened, type_transform="CHAR(1) code -> String enum")
    client, stub = make_client([shortened, good])

    result = map_field(field(source, "emp_master", "rec_stat"), destination, client)

    assert result.outcome.attempts == 2
    assert "CHAR(1)" in result.outcome.rejections[0]
    assert result.proposal.type_transform == "CHAR(1) code -> String enum"


def test_the_type_rejection_reason_reaches_the_retry_prompt(source, destination):
    shortened = dict(
        MATCH,
        destination_field="employment.status",
        type_transform="CHAR -> String",
        reasoning="The coded record status maps to the employment status string.",
    )
    good = dict(shortened, type_transform="CHAR(1) code -> String enum")
    client, stub = make_client([shortened, good])
    map_field(field(source, "emp_master", "rec_stat"), destination, client)

    assert "declared source type" in stub.calls[1]["messages"][0]["content"]


def test_a_no_match_is_unaffected_by_the_type_rule(source, destination):
    client, _ = make_client([NO_MATCH])
    result = map_field(field(source, "emp_master", "dob"), destination, client)
    assert result.outcome.attempts == 1


def test_the_prompt_demands_the_exact_declared_type():
    assert "including any length or precision" in SYSTEM_PROMPT
    assert 'write "CHAR(1)", not "CHAR"' in SYSTEM_PROMPT


def test_the_prompt_forbids_speculative_notes():
    assert "Do not speculate" in SYSTEM_PROMPT
    assert "concrete value-level work" in SYSTEM_PROMPT


# --------------------------------------------------------------------------
# Primary-key identity semantics
# --------------------------------------------------------------------------


def test_the_prompt_states_that_a_primary_key_matches_document_identity():
    assert "semantically equivalent: both are the row's or document's identity" in SYSTEM_PROMPT
    assert "natural identity candidate" in SYSTEM_PROMPT


def test_the_prompt_says_regeneration_is_a_migration_concern_not_a_mismatch():
    assert "newly generated identifier" in SYSTEM_PROMPT
    assert "does not make the two fields semantically unrelated" in SYSTEM_PROMPT


def test_the_identity_guidance_names_no_specific_field_or_table(source):
    """Guidance must be general; a hard-coded column name would be cheating."""
    for field_name in {f.name for f in source.all_fields}:
        assert field_name not in SYSTEM_PROMPT
    for table_name in source.tables:
        assert table_name not in SYSTEM_PROMPT


def test_identity_is_offered_as_a_candidate_for_every_primary_key(source, destination):
    """The guidance is only reachable if `_id` actually reaches the prompt."""
    for table, name in [
        ("emp_master", "emp_id"),
        ("dept_info", "dept_id"),
        ("locations", "loc_id"),
    ]:
        collection = PAIR_BY_SOURCE_TABLE[table].destination_collection
        candidates = shortlist_for_field(
            field(source, table, name), destination, collection
        )
        assert "_id" in [c.destination_field for c in candidates]


@pytest.mark.parametrize(
    "table, name", [("emp_master", "emp_id"), ("dept_info", "dept_id"), ("locations", "loc_id")]
)
def test_a_primary_key_mapped_to_identity_validates(source, destination, table, name):
    identity = {
        "destination_field": "_id",
        "type_transform": "INT primary key -> ObjectId",
        "confidence": 0.9,
        "reasoning": "The relational primary key is the document's identity field.",
        "notes": "Generate a new ObjectId and retain the legacy key for lookup resolution.",
    }
    client, _ = make_client([identity])
    result = map_field(field(source, table, name), destination, client)

    assert result.proposal.destination_field == "_id"
    assert result.outcome.attempts == 1


# --------------------------------------------------------------------------
# Confidence semantics
# --------------------------------------------------------------------------


def test_the_rubric_ties_confidence_to_the_returned_decision():
    assert "certainty in the decision you returned" in SYSTEM_PROMPT


def test_the_rubric_states_that_a_confident_null_is_high_confidence():
    assert "A well-founded null is therefore a HIGH confidence answer" in SYSTEM_PROMPT
    assert "never lower the number merely because you selected nothing" in SYSTEM_PROMPT


def test_a_confident_no_match_is_accepted(source, destination):
    """A high-confidence null must pass validation like any other answer."""
    confident_null = dict(NO_MATCH, confidence=0.97)
    client, _ = make_client([confident_null])
    result = map_field(field(source, "emp_master", "dob"), destination, client)

    assert not result.is_match
    assert result.proposal.confidence == 0.97
    assert result.outcome.attempts == 1
