"""Stage 5 -- deterministic assembly of the deliverable.

Reads the persisted, validated proposals from stage 4 and folds them into the
JSON document the assignment specifies. No model is involved and no judgement is
made here: every value is either copied from a proposal, taken from the fixed
table-pair configuration, or computed by set arithmetic over the schema
inventories.

Two decisions are worth stating, both settled by reading the brief:

* A source column with no semantic equivalent goes into `unmapped_source_fields`
  and gets no `field_mappings` entry. The brief authorizes null only for `notes`,
  and provides `unmapped_source_fields` as the home for such a column.
* `unmapped_destination_fields` is the collection's inventory minus the paths
  actually selected -- a set difference, never a hand-written list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from src.config import MAPPING_VERSION, TABLE_PAIRS
from src.loader import destination_paths, source_field_names
from src.models import (
    DestinationSchema,
    FieldMapping,
    MappingDocument,
    SourceSchema,
    TableMapping,
)
from src.stages.map_fields import FieldMappingResult


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assemble_table(
    pair,
    results: list[FieldMappingResult],
    source: SourceSchema,
    destination: DestinationSchema,
) -> TableMapping:
    """Fold one table pair's proposals into a table mapping."""
    ordered = source_field_names(source, pair.source_table)
    by_field = {r.source_field: r for r in results}

    missing = [name for name in ordered if name not in by_field]
    if missing:
        raise ValueError(
            f"{pair.source_table}: no mapping-stage result for {missing}; "
            f"assembly requires a decision for every source column"
        )

    field_mappings: list[FieldMapping] = []
    unmapped_source: list[str] = []

    # Source-schema order, so the document reads like the schema it describes.
    for name in ordered:
        result = by_field[name]
        proposal = result.proposal

        if not proposal.is_match:
            unmapped_source.append(name)
            continue

        field_mappings.append(
            FieldMapping(
                source_field=name,
                destination_field=proposal.destination_field,
                type_transform=proposal.type_transform,
                confidence=proposal.confidence,
                reasoning=proposal.reasoning,
                notes=proposal.notes,
            )
        )

    selected = {m.destination_field for m in field_mappings}
    inventory = destination_paths(destination, pair.destination_collection)

    # Set difference against the real inventory, in inventory order.
    unmapped_destination = [path for path in inventory if path not in selected]

    return TableMapping(
        source_table=pair.source_table,
        destination_collection=pair.destination_collection,
        confidence=pair.confidence,
        reasoning=pair.reasoning,
        field_mappings=field_mappings,
        unmapped_source_fields=unmapped_source,
        unmapped_destination_fields=unmapped_destination,
    )


def assemble(
    results: Iterable[FieldMappingResult],
    source: SourceSchema,
    destination: DestinationSchema,
    generated_at: str | None = None,
) -> MappingDocument:
    """Build the complete mapping document from stage-4 results."""
    by_table: dict[str, list[FieldMappingResult]] = {}
    for result in results:
        by_table.setdefault(result.source_table, []).append(result)

    unexpected = set(by_table) - {p.source_table for p in TABLE_PAIRS}
    if unexpected:
        raise ValueError(f"results for unconfigured tables: {sorted(unexpected)}")

    return MappingDocument(
        mapping_version=MAPPING_VERSION,
        source=source.label,
        destination=destination.label,
        generated_at=generated_at or _iso_now(),
        tables=[
            assemble_table(pair, by_table.get(pair.source_table, []), source, destination)
            for pair in TABLE_PAIRS
        ],
    )
