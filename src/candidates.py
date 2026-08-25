"""Stage 3 -- deterministic candidate generation.

Given one source column and the destination collection it is paired with, rank
that collection's leaf paths and return a shortlist. No LLM is involved: the
point of this stage is to narrow ~25 destination paths down to a handful, so the
next stage can be handed one source table plus a small candidate set rather than
both schemas at once.

The shortlist is a recall device, not a decision. It is expected to contain
wrong answers -- choosing among them, or rejecting all of them, is the mapping
stage's job. A column with no true equivalent (`dob`) still gets its nearest
neighbours, so the model can see them and conclude "none of these".

Scoring is a weighted sum of five deterministic signals, each in [0, 1]:

    name  0.50  concept overlap between the column name and the leaf path
    ref   0.20  PK/FK structure agrees with the destination reference
    type  0.12  SQL type is compatible with the BSON type
    desc  0.10  source comment overlaps the destination path/comment
    fuzzy 0.08  character similarity, as a tie-breaker

Every component is reported alongside the total, so a ranking can be explained
and argued with.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from src.config import PAIR_BY_SOURCE_TABLE
from src.models import DestinationField, DestinationSchema, SourceField
from src.vocabulary import ABBREVIATIONS, STOPWORDS, canonicalize

DEFAULT_TOP_K = 5

WEIGHTS = {
    "name": 0.50,
    "ref": 0.20,
    "type": 0.12,
    "desc": 0.10,
    "fuzzy": 0.08,
}

# How much a match on the leaf name counts vs. a match on the whole dotted path.
# The leaf carries the meaning; the parent path is supporting context. In
# `compensation.baseSalary`, `baseSalary` is the signal and `compensation` only
# corroborates.
LEAF_WEIGHT = 0.7
PATH_WEIGHT = 0.3

_SPLIT_RE = re.compile(r"[^0-9a-zA-Z]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Split an identifier or comment into lowercase word tokens.

    Handles snake_case, camelCase, dotted paths and free-text comments alike:
    `fullName.firstName` becomes [full, name, first, name], and
    `A=Active, I=Inactive` becomes [a, active, i, inactive].
    """
    if not text:
        return []
    spaced = _CAMEL_RE.sub(" ", text)
    return [t.lower() for t in _SPLIT_RE.split(spaced) if t]


def concepts(text: str) -> set[str]:
    """Tokenize, expand abbreviations, fold synonyms, drop filler.

    The result is the comparable unit used by every name-based signal. Order and
    repetition are discarded on purpose: `dept_id` and `id_dept` mean the same
    thing.
    """
    result: set[str] = set()

    for token in tokenize(text):
        for word in ABBREVIATIONS.get(token, (token,)):
            if word in STOPWORDS:
                continue
            # Single leftover characters are noise once abbreviations are
            # expanded (the A and I in "A=Active, I=Inactive"). Genuine
            # single-letter abbreviations such as the f in f_name are expanded
            # above, so nothing meaningful is lost here.
            if len(word) < 2:
                continue
            result.add(canonicalize(word))

    return result


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _coverage(needle: set[str], haystack: set[str]) -> float:
    """Fraction of `needle` present in `haystack`. Asymmetric on purpose."""
    if not needle:
        return 0.0
    return len(needle & haystack) / len(needle)


# --------------------------------------------------------------------------
# Type compatibility
# --------------------------------------------------------------------------


def sql_type_family(sql_type: str) -> str:
    """Reduce a MySQL type to a coarse family."""
    upper = sql_type.upper()
    if upper.startswith("TINYINT(1)"):
        return "boolean"
    if upper.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT")):
        return "integer"
    if upper.startswith(("DECIMAL", "NUMERIC", "FLOAT", "DOUBLE")):
        return "decimal"
    if upper.startswith(("DATETIME", "TIMESTAMP")):
        return "datetime"
    if upper.startswith(("DATE", "TIME")):
        return "date"
    if upper.startswith(("VARCHAR", "CHAR", "TEXT")):
        return "string"
    return "unknown"


# (sql family, bson type) -> compatibility. Missing pairs score 0.
TYPE_COMPATIBILITY: dict[tuple[str, str], float] = {
    ("integer", "ObjectId"): 1.00,   # relational key -> document reference
    ("integer", "Number"): 0.85,
    ("decimal", "Number"): 1.00,
    ("boolean", "Boolean"): 1.00,
    ("boolean", "Number"): 0.40,
    ("date", "ISODate"): 1.00,
    ("datetime", "ISODate"): 1.00,
    ("string", "String"): 1.00,
    ("string", "ObjectId"): 0.35,    # a code column can still back a reference
    ("string", "Boolean"): 0.35,     # single-char flags widen to booleans
    ("string", "Number"): 0.25,
    ("unknown", "String"): 0.20,
}


def type_score(source: SourceField, destination: DestinationField) -> float:
    family = sql_type_family(source.type)
    score = TYPE_COMPATIBILITY.get((family, destination.type), 0.0)

    # A CHAR(1) coded flag is a boolean in disguise, and the comment usually
    # says so. Give it more credit than an arbitrary string-to-boolean pair.
    if family == "string" and destination.type == "Boolean":
        if source.type.upper().startswith("CHAR(1)"):
            score = max(score, 0.70)

    return score


# --------------------------------------------------------------------------
# Reference structure
# --------------------------------------------------------------------------


def reference_score(source: SourceField, destination: DestinationField) -> float:
    """Reward agreement between relational keys and document references.

    Two general structural rules, neither tied to a particular column:

    * a primary key corresponds to the document identity field `_id`;
    * a foreign key corresponds to a destination reference that points at the
      collection its target table is paired with.
    """
    if source.is_primary_key and destination.path == "_id":
        return 1.0

    if source.references and destination.references:
        pair = PAIR_BY_SOURCE_TABLE.get(source.references.entity)
        if pair and pair.destination_collection == destination.references.entity:
            return 1.0

    return 0.0


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


class ScoreBreakdown(BaseModel):
    """Per-signal contributions, kept for explainability and for the report."""

    name: float
    ref: float
    type: float
    desc: float
    fuzzy: float

    def total(self) -> float:
        return round(sum(WEIGHTS[key] * getattr(self, key) for key in WEIGHTS), 4)


class Candidate(BaseModel):
    """One ranked destination path for one source field."""

    destination_field: str
    destination_type: str
    destination_description: Optional[str] = None
    score: float = Field(ge=0.0, le=1.0)
    breakdown: ScoreBreakdown

    def as_line(self) -> str:
        b = self.breakdown
        return (
            f"{self.score:.3f}  {self.destination_field:<26} {self.destination_type:<9}"
            f"name {b.name:.2f}  ref {b.ref:.2f}  type {b.type:.2f}  "
            f"desc {b.desc:.2f}  fuzzy {b.fuzzy:.2f}"
        )


def score_pair(source: SourceField, destination: DestinationField) -> ScoreBreakdown:
    """Score one (source column, destination leaf) pair across all five signals."""
    source_concepts = concepts(source.name)
    leaf_concepts = concepts(destination.name)
    path_concepts = concepts(destination.path)

    # Name: symmetric overlap with the leaf, blended with overlap across the
    # full path, so a matching parent such as `compensation` or `meta` helps a
    # little without letting a large sub-document dominate.
    name = (
        LEAF_WEIGHT * _jaccard(source_concepts, leaf_concepts)
        + PATH_WEIGHT * _jaccard(source_concepts, path_concepts)
    )

    # Description: the SQL comment is often the clearest statement of intent.
    # "A=Active, I=Inactive" points straight at `isActive`. Compare it against
    # the destination path and its own comment, taking the better direction.
    source_desc = concepts(source.description or "")
    dest_desc = concepts(destination.description or "")
    desc = max(
        _coverage(source_desc, path_concepts | dest_desc),
        _coverage(dest_desc, source_concepts | source_desc),
    )

    fuzzy = SequenceMatcher(
        None,
        " ".join(sorted(source_concepts)),
        " ".join(sorted(leaf_concepts)),
    ).ratio()

    return ScoreBreakdown(
        name=round(name, 4),
        ref=round(reference_score(source, destination), 4),
        type=round(type_score(source, destination), 4),
        desc=round(desc, 4),
        fuzzy=round(fuzzy, 4),
    )


def rank_candidates(
    source: SourceField,
    destination_fields: Iterable[DestinationField],
    top_k: int = DEFAULT_TOP_K,
) -> list[Candidate]:
    """Rank destination leaves for one source field, best first.

    Zero-scoring paths are dropped: offering the model a path with no signal at
    all is noise rather than recall. Ties break on the destination path, so runs
    are reproducible.
    """
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    scored: list[Candidate] = []
    for destination in destination_fields:
        breakdown = score_pair(source, destination)
        total = breakdown.total()
        if total <= 0.0:
            continue
        scored.append(
            Candidate(
                destination_field=destination.path,
                destination_type=destination.type,
                destination_description=destination.description,
                score=total,
                breakdown=breakdown,
            )
        )

    scored.sort(key=lambda c: (-c.score, c.destination_field))
    return scored[:top_k]


def shortlist_for_field(
    source: SourceField,
    destination_schema: DestinationSchema,
    collection: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[Candidate]:
    """Shortlist candidates for one source field within one destination collection.

    Candidates are drawn only from the flattened inventory of `collection`, so a
    path belonging to another collection cannot be proposed here or anywhere
    downstream.
    """
    if collection not in destination_schema.collections:
        raise KeyError(f"unknown destination collection: {collection!r}")

    return rank_candidates(
        source,
        destination_schema.collections[collection].fields,
        top_k=top_k,
    )


def shortlist_for_table(
    source_fields: Iterable[SourceField],
    destination_schema: DestinationSchema,
    collection: str,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, list[Candidate]]:
    """Shortlists for every column of one source table, keyed by column name."""
    return {
        field.name: shortlist_for_field(field, destination_schema, collection, top_k)
        for field in source_fields
    }
