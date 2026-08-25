"""Re-run one source field and update it in the persisted stage artifact.

For the case where a mapping is correct but its prose came out badly. The
mapping itself must not move: pass `--expect-destination` (and optionally
`--expect-transform`) and the new result is rejected if it disagrees, leaving
the artifact untouched.

    python -m scripts.refresh_field dept_info.dept_stat \
        --expect-destination isActive \
        --expect-transform "CHAR(1) code -> Boolean"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import STAGE_DIR
from src.llm import StructuredClient
from src.loader import load_destination_schema, load_source_schema
from src.stages.map_fields import map_field

try:  # optional convenience, not a hard dependency
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("field", help="qualified source field, e.g. dept_info.dept_stat")
    parser.add_argument("--expect-destination", required=True)
    parser.add_argument("--expect-transform")
    parser.add_argument("--artifact", type=Path, default=STAGE_DIR / "field_mappings.json")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the new result into the artifact (otherwise print only)",
    )
    args = parser.parse_args()

    table, name = args.field.split(".", 1)
    source = load_source_schema()
    destination = load_destination_schema()
    field = next(f for f in source.tables[table].fields if f.name == name)

    # Always a live call: the point is to replace a cached-in answer.
    client = StructuredClient(use_cache=False)
    print(f"backend: {client.backend_name}    model: {client.model}    cache: disabled")
    print()

    result = map_field(field, destination, client)
    proposal = result.proposal

    print(f"{args.field}  ({field.type})")
    print(f"  attempts: {result.outcome.attempts}   origin: {result.outcome.describe()}")
    print(json.dumps(proposal.model_dump(), indent=2))
    print()

    problems = []
    if proposal.destination_field != args.expect_destination:
        problems.append(
            f"destination is {proposal.destination_field!r}, "
            f"expected {args.expect_destination!r}"
        )
    if args.expect_transform and proposal.type_transform != args.expect_transform:
        problems.append(
            f"type_transform is {proposal.type_transform!r}, "
            f"expected {args.expect_transform!r}"
        )

    if problems:
        print("REJECTED -- the mapping moved; artifact left unchanged:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)

    print("ACCEPTED -- destination and transform unchanged.")

    if not args.apply:
        print("(dry run; pass --apply to update the artifact)")
        return

    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    replaced = 0
    for index, stored in enumerate(payload["results"]):
        if stored["source_table"] == table and stored["source_field"] == name:
            payload["results"][index] = result.model_dump()
            replaced += 1

    if replaced != 1:
        raise SystemExit(f"expected exactly one entry for {args.field}, found {replaced}")

    args.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[updated {args.field} in {args.artifact}]")


if __name__ == "__main__":
    main()
