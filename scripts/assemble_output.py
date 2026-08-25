"""Assemble output/mapping.json from the persisted mapping-stage artifact.

Deterministic and offline: it reads `output/stages/field_mappings.json`, folds
it into the deliverable, and writes the result. The document is never hand-built
-- every field mapping comes from a validated stage-4 proposal.

    python -m scripts.assemble_output
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import OUTPUT_DIR, STAGE_DIR
from src.loader import load_destination_schema, load_source_schema
from src.stages.assemble import assemble
from src.stages.map_fields import FieldMappingResult


def load_results(path: Path) -> tuple[list[FieldMappingResult], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("failures"):
        raise SystemExit(
            f"the mapping stage recorded {len(payload['failures'])} failure(s); "
            f"resolve them before assembling"
        )
    results = [FieldMappingResult.model_validate(r) for r in payload["results"]]
    return results, payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", type=Path, default=STAGE_DIR / "field_mappings.json"
    )
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR / "mapping.json")
    args = parser.parse_args()

    results, payload = load_results(args.stage)
    source = load_source_schema()
    destination = load_destination_schema()

    print(f"stage artifact: {args.stage}")
    print(f"  produced by:  {payload.get('backend')} / {payload.get('model')}")
    print(f"  results:      {len(results)}")
    print()

    document = assemble(results, source, destination)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document.model_dump(), indent=2) + "\n", encoding="utf-8"
    )

    for table in document.tables:
        print(
            f"  {table.source_table:<11} -> {table.destination_collection:<12} "
            f"{len(table.field_mappings):>2} mapped, "
            f"{len(table.unmapped_source_fields)} unmapped source, "
            f"{len(table.unmapped_destination_fields)} unmapped destination"
        )

    print()
    print(f"[written to {args.out}]")


if __name__ == "__main__":
    main()
