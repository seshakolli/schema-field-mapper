"""Data models for the schema field mapper.

Two families of models live here:

* Schema models (`SourceField`, `DestinationField`, ...) describe the two input
  schemas after normalization. They are the deterministic backbone of the
  pipeline: every prompt is built from them and every LLM answer is checked
  against them.
* Output models (`FieldMapping`, `TableMapping`, `MappingDocument`) describe the
  deliverable JSON. Field declaration order is deliberate -- Pydantic preserves
  it on serialization, so the emitted document matches the key order shown in
  the assignment.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Schema models
# --------------------------------------------------------------------------


class Reference(BaseModel):
    """A foreign-key / document-reference target."""

    entity: str
    field: str

    def as_text(self) -> str:
        return f"{self.entity}.{self.field}"


class SourceField(BaseModel):
    """One column of one MySQL table."""

    table: str
    name: str
    type: str
    constraints: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    references: Optional[Reference] = None

    @property
    def qualified_name(self) -> str:
        return f"{self.table}.{self.name}"

    @property
    def is_primary_key(self) -> bool:
        return "PRIMARY KEY" in self.constraints

    @property
    def is_unique(self) -> bool:
        return "UNIQUE" in self.constraints or self.is_primary_key

    @property
    def is_nullable(self) -> bool:
        return not (self.is_primary_key or "NOT NULL" in self.constraints)

    @property
    def is_foreign_key(self) -> bool:
        return self.references is not None


class DestinationField(BaseModel):
    """One leaf path of one MongoDB collection.

    `path` is always the dot-notation path relative to the document root, which
    is exactly the value the deliverable expects in `destination_field`.
    """

    collection: str
    path: str
    type: str
    description: Optional[str] = None
    references: Optional[Reference] = None

    @property
    def name(self) -> str:
        """Leaf name without the parent path."""
        return self.path.rsplit(".", 1)[-1]

    @property
    def parent_path(self) -> Optional[str]:
        return self.path.rsplit(".", 1)[0] if "." in self.path else None

    @property
    def is_nested(self) -> bool:
        return "." in self.path

    @property
    def is_reference(self) -> bool:
        return self.references is not None


class SourceTable(BaseModel):
    name: str
    description: Optional[str] = None
    fields: list[SourceField]

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


class DestinationCollection(BaseModel):
    name: str
    description: Optional[str] = None
    fields: list[DestinationField]

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.fields]


class SourceSchema(BaseModel):
    database: str
    type: str
    label: str
    tables: dict[str, SourceTable]

    @property
    def all_fields(self) -> list[SourceField]:
        return [f for t in self.tables.values() for f in t.fields]


class DestinationSchema(BaseModel):
    database: str
    type: str
    label: str
    collections: dict[str, DestinationCollection]

    @property
    def all_fields(self) -> list[DestinationField]:
        return [f for c in self.collections.values() for f in c.fields]


# --------------------------------------------------------------------------
# Internal LLM response model
# --------------------------------------------------------------------------


class FieldMappingProposal(BaseModel):
    """What the model returns for one source column.

    Internal only. A null `destination_field` means NO_MATCH -- the column has
    no semantic equivalent in the destination collection. Assembly later routes
    those into `unmapped_source_fields`; the deliverable never carries a
    field_mapping with a null destination.
    """

    model_config = {"extra": "forbid"}

    destination_field: Optional[str] = Field(
        default=None,
        description=(
            "One destination path copied verbatim from the supplied candidates, "
            "or null if none of them is semantically equivalent."
        ),
    )
    type_transform: Optional[str] = Field(
        default=None,
        description=(
            "Datatype conversion in the form 'SOURCE_TYPE -> DestinationType'. "
            "Null only when destination_field is null."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Heuristic semantic confidence per the rubric, not a statistical "
            "probability."
        ),
    )
    reasoning: str = Field(
        description="Exactly one plain-English sentence explaining the decision."
    )
    notes: Optional[str] = Field(
        default=None,
        description=(
            "Value-level transform logic required at migration time, or null "
            "when the value copies across directly."
        ),
    )

    @property
    def is_match(self) -> bool:
        return self.destination_field is not None


# --------------------------------------------------------------------------
# Output models -- these define the deliverable JSON exactly
# --------------------------------------------------------------------------


class FieldMapping(BaseModel):
    """One row of `field_mappings`. Exactly the six keys the assignment lists."""

    model_config = {"extra": "forbid"}

    source_field: str
    destination_field: str
    type_transform: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    notes: Optional[str] = None


class TableMapping(BaseModel):
    model_config = {"extra": "forbid"}

    source_table: str
    destination_collection: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    field_mappings: list[FieldMapping]
    unmapped_source_fields: list[str]
    unmapped_destination_fields: list[str]


class MappingDocument(BaseModel):
    model_config = {"extra": "forbid"}

    mapping_version: str
    source: str
    destination: str
    generated_at: str
    tables: list[TableMapping]
