"""Schema ingestion, normalization and field inventories.

Stage 1-2 of the pipeline, and entirely deterministic. Both schemas are read
from `data/*.json` and turned into flat, addressable inventories:

* the MySQL side is already flat -- it just gets typed and qualified;
* the MongoDB side is flattened depth-first into dot-notation leaf paths
  (`fullName.firstName`, `employment.isRemote`), which is the exact form the
  deliverable's `destination_field` requires.

Nothing here calls an LLM. The inventories produced here are the ground truth
that later stages build prompts from and validate answers against -- a
destination path the model invents is rejected because it is not in this list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.config import SOURCE_SCHEMA_PATH, TARGET_SCHEMA_PATH
from src.models import (
    DestinationCollection,
    DestinationField,
    DestinationSchema,
    Reference,
    SourceField,
    SourceSchema,
    SourceTable,
)

# A sub-document node, as opposed to a leaf field.
OBJECT_TYPE = "Object"


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _reference(raw: Optional[dict[str, str]]) -> Optional[Reference]:
    """Normalize a FK / document ref, which names its entity differently per side."""
    if not raw:
        return None
    entity = raw.get("table") or raw.get("collection")
    if entity is None:
        raise ValueError(f"reference without a table/collection: {raw!r}")
    return Reference(entity=entity, field=raw["field"])


# --------------------------------------------------------------------------
# Source (MySQL)
# --------------------------------------------------------------------------


def load_source_schema(path: Path = SOURCE_SCHEMA_PATH) -> SourceSchema:
    raw = _read_json(path)
    tables: dict[str, SourceTable] = {}

    for table_name, table_raw in raw["tables"].items():
        fields = [
            SourceField(
                table=table_name,
                name=field_raw["name"],
                type=field_raw["type"],
                constraints=field_raw.get("constraints", []),
                description=field_raw.get("description"),
                references=_reference(field_raw.get("references")),
            )
            for field_raw in table_raw["fields"]
        ]
        _assert_unique([f.name for f in fields], f"table {table_name}")
        tables[table_name] = SourceTable(
            name=table_name,
            description=table_raw.get("description"),
            fields=fields,
        )

    return SourceSchema(
        database=raw["database"],
        type=raw["type"],
        label=raw["label"],
        tables=tables,
    )


# --------------------------------------------------------------------------
# Destination (MongoDB) -- flattening
# --------------------------------------------------------------------------


def flatten_fields(
    collection: str,
    fields_raw: dict[str, Any],
    prefix: str = "",
) -> list[DestinationField]:
    """Flatten a (possibly nested) MongoDB field tree into leaf paths.

    A node with `type == "Object"` is a sub-document and contributes no leaf of
    its own -- only its children do. Anything else is a leaf. Depth-first order
    is preserved so the inventory reads in the same order as the schema file.
    """
    leaves: list[DestinationField] = []

    for name, node in fields_raw.items():
        path = f"{prefix}{name}"

        if node["type"] == OBJECT_TYPE:
            children = node.get("fields")
            if not children:
                raise ValueError(f"sub-document '{path}' has no fields")
            leaves.extend(flatten_fields(collection, children, prefix=f"{path}."))
            continue

        leaves.append(
            DestinationField(
                collection=collection,
                path=path,
                type=node["type"],
                description=node.get("description"),
                references=_reference(node.get("references")),
            )
        )

    return leaves


def load_destination_schema(path: Path = TARGET_SCHEMA_PATH) -> DestinationSchema:
    raw = _read_json(path)
    collections: dict[str, DestinationCollection] = {}

    for collection_name, collection_raw in raw["collections"].items():
        fields = flatten_fields(collection_name, collection_raw["fields"])
        _assert_unique([f.path for f in fields], f"collection {collection_name}")
        collections[collection_name] = DestinationCollection(
            name=collection_name,
            description=collection_raw.get("description"),
            fields=fields,
        )

    return DestinationSchema(
        database=raw["database"],
        type=raw["type"],
        label=raw["label"],
        collections=collections,
    )


def _assert_unique(values: list[str], context: str) -> None:
    if len(set(values)) != len(values):
        duplicates = sorted({v for v in values if values.count(v) > 1})
        raise ValueError(f"duplicate field names in {context}: {duplicates}")


# --------------------------------------------------------------------------
# Inventories -- the lookup surface later stages validate against
# --------------------------------------------------------------------------


def source_field_names(schema: SourceSchema, table: str) -> list[str]:
    return schema.tables[table].field_names


def destination_paths(schema: DestinationSchema, collection: str) -> list[str]:
    return schema.collections[collection].paths


def source_field_index(schema: SourceSchema) -> dict[str, SourceField]:
    """Every source column, keyed by `table.column`."""
    return {f.qualified_name: f for f in schema.all_fields}


def destination_field_index(schema: DestinationSchema) -> dict[str, DestinationField]:
    """Every destination leaf, keyed by `collection.dotted.path`."""
    return {f"{f.collection}.{f.path}": f for f in schema.all_fields}


def destination_path_set(schema: DestinationSchema, collection: str) -> set[str]:
    """Valid `destination_field` values for one collection.

    This is the hallucination guard: an LLM-proposed path outside this set is
    rejected before it can reach the deliverable.
    """
    return set(destination_paths(schema, collection))
