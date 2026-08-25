"""Render the deterministic candidate shortlists for every source field.

Inspection aid only. The pipeline never reads this file, and nothing here is
ground truth -- it exists so a human can see what the scorer is doing and argue
with the ranking before the LLM stage is wired up.

    python -m scripts.candidate_report [--top-k N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.candidates import DEFAULT_TOP_K, WEIGHTS, shortlist_for_field
from src.config import OUTPUT_DIR, TABLE_PAIRS
from src.loader import load_destination_schema, load_source_schema


def build_report(top_k: int) -> str:
    source = load_source_schema()
    destination = load_destination_schema()

    weights = "  ".join(f"{k} {v:.2f}" for k, v in WEIGHTS.items())
    lines: list[str] = [
        "# Candidate report",
        "",
        "Deterministic shortlists produced by `src/candidates.py`. Inspection",
        "aid only -- not consumed by the pipeline and not ground truth.",
        "",
        f"Shortlist size: top {top_k}.  Weights: {weights}",
        "",
    ]

    total_fields = 0

    for pair in TABLE_PAIRS:
        table = source.tables[pair.source_table]
        collection = destination.collections[pair.destination_collection]

        lines += [
            f"## {pair.source_table} -> {pair.destination_collection}",
            "",
            f"{len(table.fields)} source columns, "
            f"{len(collection.fields)} destination leaf paths.",
            "",
        ]

        for field in table.fields:
            total_fields += 1
            comment = f"  -- {field.description}" if field.description else ""
            constraints = " ".join(field.constraints)
            fk = f" FK->{field.references.as_text()}" if field.references else ""
            header = f"{field.name}  ({field.type}{' ' + constraints if constraints else ''}{fk}){comment}"

            lines += ["```", header, ""]

            candidates = shortlist_for_field(
                field, destination, pair.destination_collection, top_k=top_k
            )
            if not candidates:
                lines.append("  (no candidate scored above zero)")
            else:
                for rank, candidate in enumerate(candidates, start=1):
                    lines.append(f"  {rank}. {candidate.as_line()}")

            lines += ["```", ""]

    lines += [f"Total source fields covered: {total_fields}.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--out",
        type=Path,
        default=OUTPUT_DIR / "candidate_report.md",
        help="where to write the report",
    )
    args = parser.parse_args()

    report = build_report(args.top_k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"[written to {args.out}]")


if __name__ == "__main__":
    main()
