"""Validate a generated mapping document against the assignment's contract.

Independent of assembly on purpose: assembly produces the document, this
re-derives every invariant from the schema files and complains loudly. Run it on
any mapping.json, including one produced by something else.

    python validate.py                     # validates output/mapping.json
    python validate.py path/to/mapping.json --report out.txt

Exits non-zero when any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from src.config import MAPPING_VERSION, OUTPUT_DIR, TABLE_PAIRS
from src.loader import (
    destination_paths,
    load_destination_schema,
    load_source_schema,
    source_field_names,
)
from src.models import MappingDocument
from src.sentence import describe_problem


class Report:
    """Accumulates failures so one run reports every problem, not just the first."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures: list[str] = []

    def check(self, condition: bool, label: str, detail: str = "") -> bool:
        if condition:
            self.lines.append(f"  PASS  {label}")
        else:
            message = f"{label}{': ' + detail if detail else ''}"
            self.lines.append(f"  FAIL  {message}")
            self.failures.append(message)
        return condition

    def note(self, text: str) -> None:
        self.lines.append(text)

    def render(self) -> str:
        status = "FAILED" if self.failures else "PASSED"
        header = [
            "Schema Field Mapper -- validation report",
            "=" * 60,
            "",
        ]
        footer = [
            "",
            "=" * 60,
            f"RESULT: {status}  ({len(self.failures)} failure(s))",
        ]
        if self.failures:
            footer.append("")
            footer += [f"  - {failure}" for failure in self.failures]
        return "\n".join(header + self.lines + footer) + "\n"


def _is_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_document(raw: dict) -> Report:
    report = Report()
    source = load_source_schema()
    destination = load_destination_schema()

    # -- structure -------------------------------------------------------
    report.note("Document structure")
    try:
        document = MappingDocument.model_validate(raw)
        report.check(True, "matches the required JSON structure")
    except ValidationError as exc:
        # `extra="forbid"` on every model means unknown keys land here too.
        report.check(False, "matches the required JSON structure", str(exc))
        report.note("")
        report.note("Structural validation failed; per-table checks skipped.")
        return report

    report.check(
        document.mapping_version == MAPPING_VERSION,
        "mapping_version is '1.0'",
        f"got {document.mapping_version!r}",
    )
    report.check(
        document.source == source.label, "source label", f"got {document.source!r}"
    )
    report.check(
        document.destination == destination.label,
        "destination label",
        f"got {document.destination!r}",
    )
    report.check(
        _is_iso8601(document.generated_at),
        "generated_at is a valid ISO 8601 timestamp",
        f"got {document.generated_at!r}",
    )
    report.check(
        len(document.tables) == len(TABLE_PAIRS),
        f"exactly {len(TABLE_PAIRS)} table mappings",
        f"got {len(document.tables)}",
    )

    expected_pairs = [(p.source_table, p.destination_collection) for p in TABLE_PAIRS]
    actual_pairs = [(t.source_table, t.destination_collection) for t in document.tables]
    report.check(
        actual_pairs == expected_pairs,
        "table pairs match the configured pairing",
        f"got {actual_pairs}",
    )

    # -- per table -------------------------------------------------------
    total_covered = 0

    for table in document.tables:
        report.note("")
        report.note(f"{table.source_table} -> {table.destination_collection}")

        if table.source_table not in source.tables:
            report.check(False, "source table exists", table.source_table)
            continue

        inventory = source_field_names(source, table.source_table)
        paths = destination_paths(destination, table.destination_collection)

        mapped = [m.source_field for m in table.field_mappings]
        unmapped_source = list(table.unmapped_source_fields)

        # Coverage: mapped union unmapped must be exactly the source inventory.
        covered = mapped + unmapped_source
        total_covered += len(covered)

        report.check(
            sorted(set(covered)) == sorted(inventory),
            "coverage: mapped + unmapped == source inventory",
            f"missing {sorted(set(inventory) - set(covered))}, "
            f"unexpected {sorted(set(covered) - set(inventory))}",
        )

        duplicates = sorted({f for f in covered if covered.count(f) > 1})
        report.check(
            not duplicates,
            "no source field appears twice",
            f"duplicated: {duplicates}",
        )

        both = sorted(set(mapped) & set(unmapped_source))
        report.check(
            not both,
            "no source field is both mapped and unmapped",
            f"in both: {both}",
        )

        # Destination paths must exist in this collection's inventory.
        unknown = sorted(
            {m.destination_field for m in table.field_mappings} - set(paths)
        )
        report.check(
            not unknown,
            "every destination_field exists in the collection",
            f"unknown: {unknown}",
        )

        selected = [m.destination_field for m in table.field_mappings]
        duplicate_targets = sorted({p for p in selected if selected.count(p) > 1})
        report.check(
            not duplicate_targets,
            "no destination path is selected twice",
            f"duplicated: {duplicate_targets}",
        )

        # unmapped_destination_fields must be exactly the set difference.
        expected_unmapped = [p for p in paths if p not in set(selected)]
        report.check(
            table.unmapped_destination_fields == expected_unmapped,
            "unmapped_destination_fields equals inventory minus selected",
            f"expected {expected_unmapped}, got {table.unmapped_destination_fields}",
        )

        # Table-level fields.
        report.check(
            0.0 <= table.confidence <= 1.0,
            "table confidence within 0..1",
            f"got {table.confidence}",
        )
        problem = describe_problem(table.reasoning)
        report.check(
            problem is None, "table reasoning is one plain-English sentence", problem or ""
        )

        # Per-mapping fields.
        bad_confidence = [
            m.source_field
            for m in table.field_mappings
            if not 0.0 <= m.confidence <= 1.0
        ]
        report.check(
            not bad_confidence,
            "every confidence within 0..1",
            f"out of range: {bad_confidence}",
        )

        bad_reasoning = [
            f"{m.source_field} ({describe_problem(m.reasoning)})"
            for m in table.field_mappings
            if describe_problem(m.reasoning)
        ]
        report.check(
            not bad_reasoning,
            "every reasoning is one plain-English sentence",
            "; ".join(bad_reasoning),
        )

        missing_transform = [
            m.source_field for m in table.field_mappings if not m.type_transform
        ]
        report.check(
            not missing_transform,
            "every mapping states a type_transform",
            f"missing: {missing_transform}",
        )

        report.note(
            f"        {len(table.field_mappings)} mapped, "
            f"{len(unmapped_source)} unmapped source, "
            f"{len(table.unmapped_destination_fields)} unmapped destination"
        )

    # -- totals ----------------------------------------------------------
    report.note("")
    report.note("Totals")
    expected_total = len(source.all_fields)
    report.check(
        total_covered == expected_total,
        f"source coverage is exactly {expected_total} fields",
        f"got {total_covered}",
    )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mapping", nargs="?", type=Path, default=OUTPUT_DIR / "mapping.json"
    )
    parser.add_argument(
        "--report", type=Path, default=OUTPUT_DIR / "validation_report.txt"
    )
    args = parser.parse_args()

    if not args.mapping.exists():
        print(f"no mapping document at {args.mapping}", file=sys.stderr)
        return 2

    raw = json.loads(args.mapping.read_text(encoding="utf-8"))
    report = validate_document(raw)

    text = report.render()
    print(text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(f"[report written to {args.report}]")

    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
