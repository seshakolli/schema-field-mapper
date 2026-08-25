"""Fixed configuration for the mapping run.

The table/collection pairing is NOT inferred. The assignment states it
outright -- the example JSON pairs `emp_master` with `employees`, and the
trailing comments give `dept_info -> departments` and `locations -> locations`.
Asking an LLM to rediscover a pairing the brief hands us would add cost, add a
failure mode, and prove nothing, so it lives here as deterministic config.

The table-level `confidence` and `reasoning` in the deliverable are likewise
fixed: they describe entity pairings we were given, not judgements we made.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"
STAGE_DIR = OUTPUT_DIR / "stages"
CACHE_DIR = OUTPUT_DIR / ".cache"

SOURCE_SCHEMA_PATH = DATA_DIR / "source_mysql.json"
TARGET_SCHEMA_PATH = DATA_DIR / "target_mongo.json"

MAPPING_VERSION = "1.0"

# LLM settings.
#
# The backend is the model runtime. `claude-code` shells out to the Claude Code
# CLI and needs no API key -- it is the default so a fresh clone can run the
# pipeline with nothing but Claude Code installed. `anthropic-api` uses the SDK
# and needs ANTHROPIC_API_KEY, which the SDK reads itself; no key is ever read,
# stored or logged by this project.
#
# The model is resolved late, from CLAUDE_MODEL, so a run can be pointed at a
# different model without touching code. It is also part of the response cache
# key, so switching models never serves an answer produced by the other one.
DEFAULT_BACKEND = "claude-code"
BACKEND_ENV_VAR = "LLM_BACKEND"

DEFAULT_MODEL = "claude-sonnet-5"
MODEL_ENV_VAR = "CLAUDE_MODEL"
MAX_TOKENS = 2000


def _env(name: str, default: str) -> str:
    """An environment override, ignoring empty and whitespace-only values."""
    return os.environ.get(name, "").strip() or default


def resolve_model() -> str:
    """The model for this run: $CLAUDE_MODEL if set and non-empty, else the default."""
    return _env(MODEL_ENV_VAR, DEFAULT_MODEL)


def resolve_backend_name() -> str:
    """The backend for this run: $LLM_BACKEND if set and non-empty, else the default."""
    return _env(BACKEND_ENV_VAR, DEFAULT_BACKEND)

# How many times a single field-mapping call may be re-issued after a rejected
# response. Small on purpose: a response that fails validation three times is a
# prompt problem, not a transient one.
MAX_ATTEMPTS = 3


class TablePair(BaseModel):
    """One source table paired with its destination collection."""

    source_table: str
    destination_collection: str
    confidence: float
    reasoning: str


TABLE_PAIRS: list[TablePair] = [
    TablePair(
        source_table="emp_master",
        destination_collection="employees",
        confidence=0.97,
        reasoning=(
            "Both represent the core employee entity; the destination groups the "
            "same attributes into sub-documents rather than flat columns."
        ),
    ),
    TablePair(
        source_table="dept_info",
        destination_collection="departments",
        confidence=0.96,
        reasoning=(
            "Both represent the department entity, including the self-referencing "
            "parent relationship and the department head reference."
        ),
    ),
    TablePair(
        source_table="locations",
        destination_collection="locations",
        confidence=0.98,
        reasoning=(
            "Both represent the physical office location entity with the same "
            "address, country and timezone attributes."
        ),
    ),
]

PAIR_BY_SOURCE_TABLE: dict[str, TablePair] = {p.source_table: p for p in TABLE_PAIRS}
