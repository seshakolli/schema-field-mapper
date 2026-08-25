"""Run the mapping stage over every source field and persist the results.

Stage 4 only -- no final assembly. Validated proposals are written to
`output/stages/field_mappings.json` so assembly can consume them later without
re-running the model, and a review table plus summary are printed for a human to
read before anything is assembled.

    python -m scripts.run_mapping
    python -m scripts.run_mapping --no-cache
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.backends.base import BackendError
from src.config import STAGE_DIR, TABLE_PAIRS
from src.llm import StructuredCallError, StructuredClient
from src.loader import load_destination_schema, load_source_schema
from src.stages.map_fields import FieldMappingResult, map_field

try:  # optional convenience, not a hard dependency
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

LOW_CONFIDENCE = 0.85


def _cell(value, width: int) -> str:
    text = "-" if value is None else str(value)
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--out", type=Path, default=STAGE_DIR / "field_mappings.json")
    args = parser.parse_args()

    source = load_source_schema()
    destination = load_destination_schema()
    client = StructuredClient(use_cache=not args.no_cache)

    print(f"backend: {client.backend_name}    model: {client.model}")
    print(f"cache:   {'disabled' if args.no_cache else 'enabled'}")
    print()

    results: list[FieldMappingResult] = []
    failures: list[dict] = []

    for pair in TABLE_PAIRS:
        for field in source.tables[pair.source_table].fields:
            qualified = f"{pair.source_table}.{field.name}"
            try:
                result = map_field(field, destination, client)
            except (StructuredCallError, BackendError) as exc:
                failures.append(
                    {
                        "source_table": pair.source_table,
                        "source_field": field.name,
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    }
                )
                print(f"  FAILED  {qualified}: {type(exc).__name__}: {exc}")
                continue

            results.append(result)
            marker = (
                result.proposal.destination_field
                if result.is_match
                else "NO_MATCH"
            )
            print(
                f"  {qualified:<26} -> {marker:<26} "
                f"{result.proposal.confidence:.2f}  "
                f"{result.outcome.attempts} attempt(s)"
            )

    _persist(args.out, client, results, failures)
    print()
    _review_table(source, results)
    print()
    _summary(source, results, failures)


def _persist(path: Path, client, results, failures) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": "field_mappings",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": client.backend_name,
        "model": client.model,
        "results": [r.model_dump() for r in results],
        "failures": failures,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print()
    print(f"[persisted {len(results)} proposals to {path}]")


def _review_table(source, results: list[FieldMappingResult]) -> None:
    types = {
        (f.table, f.name): f.type for f in source.all_fields
    }

    print("REVIEW TABLE")
    print("=" * 200)
    header = (
        f"{'table':<11} {'field':<15} {'src type':<14} {'destination':<26} "
        f"{'type_transform':<34} {'conf':>5} {'att':>3} {'origin':<26} retry"
    )
    print(header)
    print("-" * 200)

    for r in results:
        print(
            f"{_cell(r.source_table, 11)} {_cell(r.source_field, 15)} "
            f"{_cell(types[(r.source_table, r.source_field)], 14)} "
            f"{_cell(r.proposal.destination_field or 'NO_MATCH', 26)} "
            f"{_cell(r.proposal.type_transform, 34)} "
            f"{r.proposal.confidence:>5.2f} {r.outcome.attempts:>3} "
            f"{_cell(r.outcome.describe(), 26)} "
            f"{'yes' if r.outcome.rejections else 'no'}"
        )

    print()
    print("REASONING AND NOTES")
    print("=" * 200)
    for r in results:
        print(f"{r.source_table}.{r.source_field}")
        print(f"  reasoning: {r.proposal.reasoning}")
        print(f"  notes:     {r.proposal.notes if r.proposal.notes else 'null'}")
        for rejection in r.outcome.rejections:
            print(f"  REJECTED:  {rejection}")


def _summary(source, results: list[FieldMappingResult], failures: list[dict]) -> None:
    matches = [r for r in results if r.is_match]
    no_match = [r for r in results if not r.is_match]
    low = [r for r in results if r.proposal.confidence < LOW_CONFIDENCE]
    retried = [r for r in results if r.outcome.attempts > 1 or r.outcome.rejections]

    # Duplicate destinations within one table/collection pair -- reported for
    # review only, never auto-corrected.
    per_pair: dict[str, Counter] = defaultdict(Counter)
    for r in matches:
        per_pair[f"{r.source_table} -> {r.destination_collection}"][
            r.proposal.destination_field
        ] += 1
    duplicates = {
        pair: {path: n for path, n in counts.items() if n > 1}
        for pair, counts in per_pair.items()
    }
    duplicates = {pair: dup for pair, dup in duplicates.items() if dup}

    outside = [
        f"{r.source_table}.{r.source_field} -> {r.proposal.destination_field}"
        for r in matches
        if r.proposal.destination_field not in r.candidates
    ]

    print("SUMMARY")
    print("=" * 72)
    print(f"  source fields in schema:      {len(source.all_fields)}")
    print(f"  source fields processed:      {len(results)}")
    print(f"  matches:                      {len(matches)}")
    print(f"  NO_MATCH:                     {len(no_match)}")
    print(f"  confidence < {LOW_CONFIDENCE}:            {len(low)}")
    if low:
        for r in sorted(low, key=lambda r: r.proposal.confidence):
            print(
                f"      {r.source_table}.{r.source_field:<16} "
                f"{r.proposal.confidence:.2f}  "
                f"{r.proposal.destination_field or 'NO_MATCH'}"
            )
    print(f"  fields requiring retries:     {len(retried)}")
    for r in retried:
        print(f"      {r.source_table}.{r.source_field}: {r.outcome.rejections}")
    print(f"  backend/validation failures:  {len(failures)}")
    for failure in failures:
        print(f"      {failure['source_table']}.{failure['source_field']}: {failure['detail']}")

    print(f"  duplicate destinations:       {len(duplicates)} pair(s)")
    for pair, dup in duplicates.items():
        for path, n in dup.items():
            offenders = [
                f"{r.source_field}"
                for r in matches
                if r.proposal.destination_field == path
                and f"{r.source_table} -> {r.destination_collection}" == pair
            ]
            print(f"      {pair}: {path} chosen {n}x by {offenders}")

    print(
        f"  every choice within shortlist: "
        f"{'YES' if not outside else 'NO -- ' + ', '.join(outside)}"
    )
    print(f"  NO_MATCH fields:              {[r.source_field for r in no_match] or 'none'}")


if __name__ == "__main__":
    main()
