# Schema Field Mapper

Maps every field in a legacy MySQL HR schema (`legacy_hrm`) onto its semantically
equivalent field in a modern MongoDB people platform (`people_platform`), and
emits a single JSON mapping document with a type transform, a confidence score,
a one-sentence rationale and any value-transform notes for each field.

**Deliverable:** [`output/mapping.json`](output/mapping.json)

---

## The constraint

The assignment states it directly:

> You cannot pass both schemas to an LLM in a single prompt and receive a
> finished mapping.

Both schemas would comfortably fit in a context window, so this is not a size
limit — it is a design requirement. The pipeline therefore decomposes the
problem rather than delegating it: each model request sees exactly one source
column and a short list of candidate destination paths, and returns one
decision.

**No prompt in this project ever contains either schema in full.** That is a
stricter guarantee than the assignment asks for — the brief restricts the
one-shot case of passing both schemas *and* receiving a finished mapping. The
stronger version costs nothing here and removes any question of whether the
constraint was skirted.

## Architecture

```
schema ingestion / normalization      deterministic  (src/loader.py)
            ↓
deterministic candidate generation    deterministic  (src/candidates.py)
            ↓
scoped one-field LLM mapping          model          (src/stages/map_fields.py)
            ↓
deterministic validation              deterministic  (src/stages/map_fields.py, validate.py)
            ↓
final JSON assembly                   deterministic  (src/stages/assemble.py)
```

Four of the five stages contain no model call. The LLM is asked one question, 34
times: *of these candidates, which is the semantic equivalent of this column — or
is none of them?*

**Why retrieval is separated from semantic reasoning.** Narrowing ~25 destination
paths to five is a mechanical similarity problem: token overlap, abbreviation
expansion, type compatibility, key structure. Deciding that `hire_dt` means the
same thing as `employment.startDate` is a judgement about meaning. Splitting them
keeps each stage testable in isolation, makes the shortlist explainable
(`output/candidate_report.md` shows every score), and means the model's
confidence reflects semantics rather than string similarity — the retrieval score
is deliberately withheld from the prompt.

**Why table pairs are configuration.** The assignment supplies all three pairings
outright (`emp_master → employees` in the example, `dept_info → departments` and
`locations → locations` in its comments). They live in `src/config.py` as fixed
configuration. Asking a model to rediscover a mapping the brief hands us would
add cost and a failure mode while proving nothing. The table-level `confidence`
and `reasoning` in the output describe pairings we were **given**, not pairings
the pipeline inferred.

**How hallucinated paths are prevented.** The MongoDB schema is flattened into an
inventory of 40 dot-notation leaf paths. A shortlist can only contain paths from
the paired collection's inventory, and after every response the chosen path is
checked against the shortlist it was offered. A path outside that set is rejected
and the call retried with the reason appended — so the model can only *select*
from a validated set, never introduce a path. `validate.py` re-checks this
independently against the schema files.

**How NO_MATCH works.** A column with no semantic equivalent gets `null` for
`destination_field` internally. The prompt states plainly that returning nothing
is a correct and valuable answer, and that datatype compatibility is not semantic
equivalence. In the final document those columns appear in
`unmapped_source_fields` — never as a field mapping with a null destination,
which the assignment's format does not sanction.

## Model runtime

**Default: Claude Code.** The pipeline shells out to the `claude` CLI in
non-interactive print mode — one invocation per field, JSON output, tools
disabled, `--max-turns 1`. **No API key is required**, only an installed and
authenticated Claude Code. Each invocation runs from a fresh empty temporary
directory, so a call cannot reach repository files or project context even
incidentally.

**Optional: Anthropic API.** Set `LLM_BACKEND=anthropic-api` to use the Messages
API with native structured output instead. This needs `ANTHROPIC_API_KEY`, which
the SDK reads from the environment. Both backends sit behind one interface, so
caching, retries, validation and the authorization guard are identical either
way.

Note that this backend is implemented and unit-tested against a stubbed client,
but it was **not exercised against the live API** in this submission — no key was
available, so every result here was produced through Claude Code.

## Prerequisites

- Python 3.12+ (the version this project has been tested on)
- **Claude Code** installed and authenticated (`claude --version`) — default backend
- *or* an `ANTHROPIC_API_KEY` if you prefer the API backend

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env      # optional; only to override defaults
```

## Commands

```bash
python -m pytest tests/ -q          # 276 tests, no network, no API key needed
python -m scripts.candidate_report  # deterministic shortlists for all 34 fields
python -m scripts.run_mapping       # stage 4: map all fields (calls the model)
python -m scripts.assemble_output   # stage 5: build output/mapping.json
python validate.py                  # validate the deliverable; non-zero on failure
```

Useful during development:

```bash
python -m scripts.smoke_test --dry-run    # print the exact prompts, call nothing
python -m scripts.smoke_test --no-cache   # four representative fields, live
```

`run_mapping` writes validated proposals to `output/stages/field_mappings.json`;
`assemble_output` reads that artifact. The deliverable is always produced from
the pipeline, never hand-assembled.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BACKEND` | `claude-code` | `claude-code` or `anthropic-api` |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Model id or Claude Code alias |
| `CLAUDE_CLI` | `claude` | Path to the Claude Code binary if not on `PATH` |
| `ANTHROPIC_API_KEY` | — | Required **only** for `anthropic-api` |

All are read from the shell or a local `.env`. **No API key or secret is ever
committed**: `.env` is git-ignored, `.env.example` contains only placeholders,
and the project never reads, logs or stores a credential — each backend leaves
authentication entirely to the SDK or the CLI.

## Project structure

```
data/                     both schemas as structured JSON, comments preserved
src/
  loader.py               ingestion, MongoDB flattening, field inventories
  candidates.py           deterministic shortlist scoring
  vocabulary.py           abbreviation and synonym tables
  config.py               fixed table pairs, model/backend resolution
  models.py               schema models and the deliverable's output models
  sentence.py             one-plain-English-sentence check
  llm.py                  cache, retry, validation orchestration
  backends/               claude-code and anthropic-api transports
  prompts/field_mapping.py  the system and per-field prompts
  stages/                 map_fields.py (stage 4), assemble.py (stage 5)
scripts/                  runnable entry points
tests/                    276 tests
validate.py               independent validator for any mapping.json
output/
  mapping.json            the deliverable
  validation_report.txt   validator output
  candidate_report.md     shortlists and scores for all 34 fields
  stages/                 validated stage-4 proposals
```

## Result

| | |
|---|---|
| Source fields | **34** (`emp_master` 19, `dept_info` 7, `locations` 8) |
| Destination leaf fields | **40** (`employees` 25, `departments` 7, `locations` 8) |
| Mapped | **33** |
| Unmapped source | **1** — `emp_master.dob`, which has no destination field |
| Unmapped destination | **7** — the denormalized `employees.department.*` / `employees.location.*` paths, whose values come from a join rather than an `emp_master` column |
| Retries needed | 0 |
| Validation | passes, 0 failures |

Produced with the `claude-code` backend on `claude-sonnet-5`. See
[`WRITEUP.md`](WRITEUP.md) for prompt design and decision rationale.
