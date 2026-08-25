# Design write-up

How the pipeline is structured, why, and what I would change with more time.

Throughout, I try to be explicit about **what the assignment supplied** versus
**what the pipeline inferred**. Getting that line wrong is the easiest way to
overclaim.

---

## 1. How the constraint shaped the architecture

The brief states that you cannot pass both schemas to an LLM in one prompt and
receive a finished mapping. Both schemas are small enough to fit in any modern
context window, so I read this as a requirement about *design*, not about tokens:
demonstrate decomposition rather than delegation.

I took the strict reading — no prompt ever contains either schema in full — since
it costs nothing and removes any argument that the constraint was skirted. The
literal wording is narrower ("in a single prompt **and** receive a finished
mapping"), but the strict version is the defensible one.

That decision drives everything else. If a single request can only see a fragment
of the problem, then something deterministic has to decide which fragment, and
something deterministic has to reassemble the answers. The model is left with the
one part that genuinely needs judgement:

```
ingestion → candidate generation → scoped LLM mapping → validation → assembly
   det.           det.                  model              det.        det.
```

Four of five stages have no model call. The LLM answers one question, 34 times.

## 2. What one LLM request sees

**System prompt** (fixed for the whole run): the role, six rules, a confidence
rubric, and transformation guidance. The guidance is written in general terms —
"a foreign key becoming a document reference needs a lookup from the legacy
integer identifier" — and never names a column or table. A test iterates all 34
source field names and all three table names and asserts none appears in the
system prompt, because guidance that names the answer is not guidance.

**User prompt** (per field): the source table name, one column with its type,
nullability, key/FK metadata and SQL comment, the destination collection name,
and up to five candidate paths with their types and comments. Nothing else.

```
SOURCE TABLE: emp_master
SOURCE COLUMN:
  name:        rec_stat
  type:        CHAR(1)
  nullable:    yes
  comment:     A=Active, I=Inactive, T=Terminated

DESTINATION COLLECTION: employees
CANDIDATE DESTINATION FIELDS (choose exactly one, or null):
  - path: employment.status
    type: String
    comment: active / inactive / terminated
  - path: department.code
    type: String
  ... (3 more)

Which candidate, if any, is the semantic equivalent of `rec_stat`?
```

Two deliberate omissions. The **deterministic candidate score is withheld** —
retrieval rank and semantic confidence are different judgements and showing one
would contaminate the other. And **no other column's answer is visible**, so the
34 decisions are independent and reproducible in any order.

`python -m scripts.smoke_test --dry-run` prints these prompts without calling
anything.

## 3. Candidate generation

Five deterministic signals, weighted:

```
score = 0.50·name + 0.20·ref + 0.12·type + 0.10·desc + 0.08·fuzzy
```

- **name (0.50)** — both sides tokenized (snake_case, camelCase, dot paths),
  abbreviations expanded (`cd`→code, `nm`→name, `dt`→date, `sal`→salary,
  `lvl`→level, `stat`→status), synonyms folded onto a canonical concept
  (`hire`≈`start`, `term`≈`end`, `active`≈`status`), filler dropped. Then Jaccard
  overlap against the leaf name, blended 70/30 with overlap against the full path
  so a matching parent (`compensation`, `meta`) corroborates without dominating.
- **ref (0.20)** — two structural rules: a primary key scores against `_id`; a
  foreign key scores against a destination reference pointing at the collection
  its target table is paired with. This is what separates
  `dept_id → department.departmentId` (0.933) from `dept_id → _id` (0.391)
  inside `employees`.
- **type (0.12)** — coarse SQL-family × BSON-type compatibility. A bonus, never a
  gate: a type mismatch cannot remove a path from consideration.
- **desc (0.10)** — SQL comments compared against destination path and comment.
  This is what makes `dept_stat → isActive` work at all.
- **fuzzy (0.08)** — `difflib` character similarity, tie-breaking only.

Every entry in the vocabulary is keyed on a general word, never on a
source→destination pair. `state` is deliberately *not* in the status group so
`state_prov` cannot drift toward `isActive`.

Result: all 33 mappable source fields had their intended destination in the
shortlist and ranked first; `dob` correctly had no semantic destination.
`output/candidate_report.md` shows every score and component.

### Why no embeddings or vector database

With 34 source columns and 40 destination paths, an exhaustive scored comparison
is 850 operations — microseconds. A vector store would add a dependency, an
index-build step and an opaque similarity number, in exchange for recall the
lexical scorer already achieves at 100%. It would also be *less* explainable: I
can point at the exact signal that put `employment.startDate` at the top of
`hire_dt`'s list, which matters when a reviewer disputes a mapping.

At a few hundred tables this calculus flips — see §9.

## 4. Confidence semantics

Confidence is a **heuristic rating of certainty in the decision returned**, not a
statistical probability, and it is kept strictly separate from the deterministic
candidate score. The rubric:

| Range | Meaning |
|---|---|
| 0.95–1.00 | essentially certain |
| 0.85–0.94 | strong; a rename, nesting change or type conversion is involved |
| 0.70–0.84 | plausible, but requires meaningful interpretation |
| < 0.70 | ambiguous; a human should review |

One subtlety cost a full run to find. Initially the rubric said confidence on a
null result "expresses how certain you are that no candidate is equivalent" —
and the model still sometimes reported `dob` at **0.05**, reading the number as
confidence *in a match*. The same decision scored 0.97 on other runs. The fix was
to state the symmetry explicitly: *a well-founded null is a HIGH confidence
answer, not a low one — never lower the number merely because you selected
nothing.* `dob` has scored 0.97 consistently since.

## 5. NO_MATCH handling

The brief never authorizes a null `destination_field`. It marks `notes` as
nullable explicitly, and it provides `unmapped_source_fields` as a first-class
array — so a column with no equivalent belongs there, not in a field mapping with
a null destination. Internally a null destination represents NO_MATCH; assembly
routes those columns into `unmapped_source_fields`, and the final document
contains no null destination at all.

Coverage is then defined as
`mapped source fields ∪ unmapped_source_fields = complete source inventory`,
asserted at 34 by `validate.py`.

The prompt states that returning nothing is a correct and valuable answer, and
that datatype compatibility is not semantic equivalence. `dob` is the test case:
four of its five candidates are `ISODate`, all type-compatible, none of them a
birth date.

## 6. Primary and foreign keys becoming ObjectIds

Relational identity does not survive a document migration unchanged, and the
mapping has to say so without pretending the fields are unrelated.

- **Primary keys → `_id`.** All three map, with `INT primary key -> ObjectId` and
  notes describing generation plus a legacy-ID→ObjectId lookup for traceability.
  This needed an explicit prompt rule: on an earlier run `locations.loc_id`
  returned NO_MATCH, reasoning that a regenerated identifier "is not itself
  equivalent to any listed candidate" — while `emp_id` and `dept_id` mapped
  normally in the same run. The guidance now states generically that regeneration
  is a value-migration concern belonging in `type_transform`/`notes`, and does
  not make the fields semantically unrelated.
- **Foreign keys → ObjectId references.** All five (`dept_id`, `mgr_emp_id`,
  `office_loc_id`, `parent_dept_id`, `dept_head_id`) map, each with notes calling
  for a lookup table built during migration and null handling for absent
  references. The candidate scorer helps here: an FK only earns its reference
  bonus against a destination path that references the *paired* collection.

## 7. Deterministic safeguards

Everything a computer can check, a computer checks:

- **Path authorization.** A chosen path must be in the shortlist it was offered.
  Anything else is rejected and retried with the reason. The model can only
  select from a validated set, never introduce a path.
- **Source type preservation.** `type_transform`'s left-hand side must repeat the
  declared type intact — `CHAR` fails for a `CHAR(1)` column, `DECIMAL` fails for
  `DECIMAL(12,2)`. Generic, compared against whatever the schema declared. This
  came from an observed regression: an early run returned `CHAR -> String`.
- **One plain-English sentence.** `src/sentence.py` checks length, single line,
  terminal punctuation and exactly one sentence, masking abbreviations first so
  `e.g. USD` is not read as a sentence break.
- **Coherence.** A match must state a transform; a non-match must not.
- **Structural.** Pydantic models with `extra="forbid"` on every output model, so
  the deliverable cannot grow a stray key and confidence cannot leave 0–1.
- **Set arithmetic, never judgement.** `unmapped_destination_fields` is the
  collection inventory minus the paths actually selected — computed, never
  written by hand, and recomputed independently in a test.

### Backend isolation

Each `claude -p` invocation runs from a **fresh empty temporary directory**,
removed when the call returns, with tools disabled and `--max-turns 1`. This
matters for honesty as much as security: without it, a reader could reasonably
ask whether a CLI running inside the repository had quietly read `data/` or an
earlier mapping. It cannot. Tests assert the working directory is passed, is
empty, is outside the repository, differs per call, and is cleaned up.

### Caching and retries

Successful, validated responses are cached on disk under a SHA-256 of
`{system prompt, user prompt, response schema, model, backend}`. Model and
backend are part of the key, so switching either never replays the other's
answer. Only validated responses are cached — a rejected answer is never
persisted.

Retries are bounded at three per field and **informed**: the validation error is
appended to the prompt so the model is told what was wrong rather than re-rolling
blindly. Transport failures (missing binary, non-zero exit, timeout) are a
distinct error class and fail fast, since retrying a missing binary is pointless.
In the final run, all 34 fields were accepted on the first attempt.

## 8. Validation strategy

`validate.py` is independent of assembly on purpose. Assembly builds the
document; the validator re-derives every invariant from the schema files and
reports *all* failures rather than stopping at the first. It fails loudly on:
structural violations and extra keys, coverage not exactly 34, a source field
appearing twice or in both lists, a destination path not in the collection,
duplicate destination paths within a pair, incorrect unmapped lists, reasoning
that is not one sentence, confidence outside 0–1, and an invalid `generated_at`.

The test suite (276 tests, no network) includes 17 corruption tests that mutate
the real document and assert the specific check fires.

## 9. Edge cases worth naming

- **`dob` has no destination.** `employees` carries no birth date. Four
  type-compatible `ISODate` candidates were offered and correctly rejected at
  0.97 confidence. It is the one entry in `unmapped_source_fields`.
- **`rec_stat` vs `dept_stat`.** Near-identical source patterns — both `CHAR(1)`,
  both A/I-coded — with different destinations: `rec_stat → employment.status`
  via `CHAR(1) code -> String enum` (A/I/T → active/inactive/terminated), and
  `dept_stat → isActive` via `CHAR(1) code -> Boolean` (A → true, I → false). The
  pipeline resolves both correctly and unprompted; the SQL comments carry the
  signal, which is why comments are preserved from schema file into prompt.
- **`hire_dt` / `term_dt` are semantic renames.** `hire`→`startDate` and
  `term`→`endDate` share no meaningful token. Lexical matching alone would miss
  them; the synonym groups get them onto the shortlist and the model confirms the
  meaning. This is precisely the division of labour the architecture is for.
- **FK ID resolution.** Five foreign keys need a legacy-integer→ObjectId lookup
  built during migration. Every one says so in `notes`.
- **Denormalized `employees.department.*` and `employees.location.*`.** These
  duplicate data from the other two entities. I mapped table→collection only:
  each `field_mappings` array sits inside one table pair with one
  `destination_collection`, and each mapping has a single scalar
  `destination_field`, so the specified format cannot express a fan-out. The
  seven denormalized paths appear in `employees`'s
  `unmapped_destination_fields`, where they are visible rather than hidden. Their
  values come from a join at migration time. `stateOrProvince` and `postalCode`
  exist in the `locations` collection but not in `employees.location`, so the
  denormalization is asymmetric — worth knowing before writing the migration.

## 10. Supplied versus inferred

| Decision | Source |
|---|---|
| Three table/collection pairs | **Supplied** by the assignment; fixed configuration in `src/config.py` |
| Output JSON structure and literals | **Supplied**; encoded in Pydantic models |
| `emp_id → _id` as a worked example | **Supplied** in the brief's sample |
| All 33 field-level mappings | **Inferred** by the pipeline |
| Type transforms and value-transform notes | **Inferred** |
| Confidence scores | **Inferred** |
| `dob` as unmapped | **Inferred** |
| Candidate shortlists | **Computed** deterministically |
| Unmapped destination lists | **Computed** by set difference |

The table-level `confidence` and `reasoning` values describe pairings we were
given. **No LLM discovered the table pairs**, and the write-up should not be read
as claiming otherwise.

## 11. Limitations

- **Confidence is a calibrated heuristic, not a probability.** Its value is
  ranking what a human should review first, not measuring likelihood.
- **Sampling variance is real.** Across runs, confidences drift by ±0.05 and
  notes get reworded; one run produced a garbled `dept_stat` note that I re-ran
  under a guard requiring the mapping itself to stay put. Destination selections
  were stable in every run but one, which the `loc_id` prompt fix addressed.
- **No gold standard.** I hand-checked all 34 mappings, but there is no labelled
  reference set, so I cannot quote precision/recall.
- **Single-pass.** There is no independent verification stage; I judged the
  propose-and-validate loop sufficient at this size and did not want to add a
  stage without evidence it helps.
- **`f`→`first` / `l`→`last`** is the least general vocabulary entry. It is a
  real schema convention, but it would misfire on a column like `l_code`.
- **No fan-out mapping**, by the format-driven argument in §9. If the interviewer
  intended fan-out, the output shape would need extending — which the brief's
  "matches this schema exactly" appears to forbid.
- **Denormalized paths are documented, not populated.** The mapping says where
  their values come from; it does not specify the join.

## 12. Scaling to much larger schemas

The architecture is already the one that scales; the components change.

- **Candidate generation** moves to embeddings with an ANN index once the
  destination inventory reaches thousands of paths, keeping the lexical scorer as
  a re-ranker so shortlists stay explainable.
- **Table pairing** stops being configuration and becomes its own retrieval +
  LLM stage, working over per-table summaries rather than full schemas — the same
  scoping discipline one level up.
- **Cost is linear in source columns** and the calls are independent, so the
  mapping stage parallelizes trivially; the Batch API halves cost where latency
  is not critical.
- **Human review scales by confidence.** At 34 fields you read all of them; at
  3,400 you read the low-confidence tail and the unmapped lists, which is exactly
  what the output is organized to support.

## 13. What I would improve in production

1. **A labelled evaluation set.** Hand-label a few hundred mappings and measure
   precision/recall on exact destination path. Without it, prompt iteration is
   guesswork — this is the first thing I would add.
2. **Constrain decoding to the shortlist.** A per-request enum of the candidate
   paths would make an unauthorized path structurally impossible rather than
   caught after the fact. I kept the explicit guard here because an observable
   rejection is more informative than one that cannot happen, but in production
   I would have both.
3. **Consensus on low-confidence fields.** Re-run anything under ~0.85 two or
   three times and flag disagreement, rather than treating a single sample as the
   answer — this directly targets the variance in §11.
4. **Human-in-the-loop review queue.** The output is a migration *proposal*. I
   would never execute a migration from it unreviewed; the natural product is a
   review UI sorted by confidence with accept/override/annotate.
5. **Round-trip validation against real data.** Run the transforms over a sample
   extract and check that values land, enums resolve and FK lookups hit — a
   mapping that type-checks can still be wrong about meaning.
6. **Structured logging and cost accounting** per field, so a large run can be
   monitored and priced rather than inferred from a log file.
