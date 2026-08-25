"""Stage 4 -- scoped semantic mapping, one source field per LLM call.

For each source column the pipeline builds a prompt containing that column and
its deterministic shortlist, and asks for a single decision: which candidate is
the semantic equivalent, or none of them. Neither schema is ever sent whole, and
no request sees another column's answer.

The guard that matters lives in `_authorized`: a destination path the model did
not receive is rejected outright and the call is retried with the reason. The
model cannot introduce a path into the mapping, only select one the
deterministic stage already validated against the collection inventory.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.candidates import Candidate, DEFAULT_TOP_K, shortlist_for_field
from src.config import PAIR_BY_SOURCE_TABLE
from src.llm import CallOutcome, StructuredClient
from src.models import DestinationSchema, FieldMappingProposal, SourceField
from src.prompts.field_mapping import SYSTEM_PROMPT, build_user_prompt
from src.sentence import describe_problem


class FieldMappingResult(BaseModel):
    """One column's outcome, with the provenance needed to audit it.

    `candidate_score` travels alongside `proposal.confidence` but never merges
    with it: the first is deterministic retrieval rank, the second is the
    model's semantic judgement. Conflating them would make either meaningless.
    """

    source_table: str
    source_field: str
    destination_collection: str
    candidates: list[str]
    candidate_score: Optional[float] = None
    proposal: FieldMappingProposal
    outcome: CallOutcome

    @property
    def is_match(self) -> bool:
        return self.proposal.is_match


def _source_type_preserved(declared: str, type_transform: str) -> bool:
    """True when the transform's left-hand side repeats the declared type intact.

    Generic, not per-column: it compares against whatever the schema declared,
    so "CHAR" fails for a CHAR(1) column and "DECIMAL" fails for DECIMAL(12,2),
    while a qualifier such as "CHAR(1) code" passes.
    """
    left = type_transform.split("->", 1)[0]
    return declared.upper().replace(" ", "") in left.upper().replace(" ", "")


def _authorized(candidates: list[Candidate], source_field: SourceField):
    """Build the validator that rejects any path outside the shortlist."""
    allowed = {c.destination_field for c in candidates}

    def validate(proposal: FieldMappingProposal) -> None:
        chosen = proposal.destination_field

        # The assignment requires one plain-English sentence, so enforce it
        # rather than trusting the instruction to have been followed.
        problem = describe_problem(proposal.reasoning)
        if problem:
            raise ValueError(problem)

        if chosen is not None and chosen not in allowed:
            raise ValueError(
                f"'{chosen}' was not among the candidate destination fields. "
                f"Choose exactly one of {sorted(allowed)}, or null."
            )

        # A match without a stated conversion is an incomplete answer; a
        # non-match with one is incoherent. Both are worth a retry.
        if chosen is not None and not proposal.type_transform:
            raise ValueError(
                "type_transform is required when a destination_field is chosen."
            )

        # The left-hand side must carry the declared source type intact --
        # "CHAR" for a CHAR(1) column loses the precision the migration needs.
        if chosen is not None and not _source_type_preserved(
            source_field.type, proposal.type_transform
        ):
            raise ValueError(
                f"type_transform must begin with the declared source type "
                f"'{source_field.type}' exactly, including any length or "
                f"precision; got '{proposal.type_transform}'."
            )
        if chosen is None and proposal.type_transform:
            raise ValueError(
                "type_transform must be null when destination_field is null."
            )

    return validate


def map_field(
    source_field: SourceField,
    destination_schema: DestinationSchema,
    client: StructuredClient,
    collection: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
) -> FieldMappingResult:
    """Map one source column against its paired destination collection."""
    collection = collection or PAIR_BY_SOURCE_TABLE[source_field.table].destination_collection
    candidates = shortlist_for_field(source_field, destination_schema, collection, top_k)

    proposal, outcome = client.call(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(source_field, collection, candidates),
        response_model=FieldMappingProposal,
        validate=_authorized(candidates, source_field),
    )

    chosen = proposal.destination_field
    score = next(
        (c.score for c in candidates if c.destination_field == chosen),
        None,
    )

    return FieldMappingResult(
        source_table=source_field.table,
        source_field=source_field.name,
        destination_collection=collection,
        candidates=[c.destination_field for c in candidates],
        candidate_score=score,
        proposal=proposal,
        outcome=outcome,
    )


def map_fields(
    source_fields: list[SourceField],
    destination_schema: DestinationSchema,
    client: StructuredClient,
    top_k: int = DEFAULT_TOP_K,
) -> list[FieldMappingResult]:
    """Map a list of source columns, one independent call each."""
    return [
        map_field(field, destination_schema, client, top_k=top_k)
        for field in source_fields
    ]
