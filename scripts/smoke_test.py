"""Run the mapping stage against the live model for a handful of fields.

A deliberately small, cheap check that the prompt and the structured-output
contract hold against the real backend before spending a full run.

    python -m scripts.smoke_test
    python -m scripts.smoke_test --dry-run          # print prompts, call nothing
    python -m scripts.smoke_test --field emp_master.dob --no-cache

Uses the configured backend (LLM_BACKEND, default `claude-code`, which needs no
API key -- only an installed and authenticated Claude Code). Environment is read
from the shell or a local .env, which is git-ignored.
"""

from __future__ import annotations

import argparse
import json

from src.candidates import shortlist_for_field
from src.config import PAIR_BY_SOURCE_TABLE
from src.llm import StructuredClient
from src.loader import load_destination_schema, load_source_schema
from src.prompts.field_mapping import SYSTEM_PROMPT, build_user_prompt
from src.stages.map_fields import map_field

try:  # optional convenience, not a hard dependency
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_FIELDS = [
    "emp_master.hire_dt",
    "emp_master.rec_stat",
    "dept_info.dept_stat",
    "emp_master.dob",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        help="qualified source field (table.column); repeatable",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact prompts that would be sent, without calling the API",
    )
    args = parser.parse_args()

    targets = args.fields or DEFAULT_FIELDS
    source = load_source_schema()
    destination = load_destination_schema()
    client = StructuredClient(use_cache=not args.no_cache)

    if not args.dry_run:
        print(f"backend: {client.backend_name}    model: {client.model}")
        print()

    if args.dry_run:
        print("SYSTEM PROMPT")
        print("-" * 72)
        print(SYSTEM_PROMPT)

    for qualified in targets:
        table, name = qualified.split(".", 1)
        field = next(f for f in source.tables[table].fields if f.name == name)

        if args.dry_run:
            collection = PAIR_BY_SOURCE_TABLE[table].destination_collection
            candidates = shortlist_for_field(field, destination, collection)
            print()
            print("=" * 72)
            print(f"USER PROMPT -- {qualified}")
            print("-" * 72)
            print(build_user_prompt(field, collection, candidates))
            continue

        result = map_field(field, destination, client)

        print("=" * 72)
        print(f"{qualified}  ({field.type})")
        print(f"  shortlist:  {result.candidates}")
        print(
            f"  attempts:   {result.outcome.attempts}"
            f"   origin: {result.outcome.describe()}"
            f"   rejections: {result.outcome.rejections or 'none'}"
        )
        print(f"  retrieval score: {result.candidate_score}")
        print("  proposal:")
        print(
            "\n".join(
                "    " + line
                for line in json.dumps(
                    result.proposal.model_dump(), indent=2
                ).splitlines()
            )
        )

    print("=" * 72)


if __name__ == "__main__":
    main()
