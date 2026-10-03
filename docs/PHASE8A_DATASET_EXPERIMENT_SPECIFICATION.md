> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 8A: Dataset & Experiment Specification Layer

Date: 2026-09-17
Scope: converts approved research planning (Phase 7) into execution-ready,
reproducible specifications — immutable, fingerprinted dataset versions
and concrete, structured experiment specifications grounded in approved
upstream artifacts, with human approval integrated through the same
`Approval`/`AuditEvent` tables Phase 4/6/7 all use. **Phase 8A does not
execute anything** — no training, no inference, no subprocess/GPU/CUDA/
Docker/remote execution, no checkpoints, no metrics, no logs from real
runs. No real LLM or scholarly API call was made anywhere in this
phase's implementation or test suite.

## Core Principle

Carried over directly from Phase 6/7: an LLM-generated specification
never becomes authoritative merely because the LLM produced it. Every
`ExperimentSpecification` this layer persists starts as `CANDIDATE` and
requires an explicit human decision before it means anything more than
"the system produced a proposal worth reviewing." `DatasetVersion`
additionally passes through deterministic, machine-checkable validation
*before* human approval is even meaningful — but validation still never
substitutes for approval, and `APPROVED` never means "scientifically
optimal" or "scientifically valid research evidence," only "approved
for system use under this project's defined process."

```
Approved Planning (Phase 7: ExperimentalDesign, MethodologyPlan, ...)
        │
        ├─────────────────────┐
        ▼                     ▼
DatasetVersion          (ExperimentalDesign, already approved)
  (DRAFT -> VALIDATING -> VALID/INVALID -> APPROVED, human-gated)
        │                     │
        └──────────┬──────────┘
                    ▼
        Experiment Specification Generation
                    │  researchos.specification.experiment_specifications
                    ▼
        Candidate ExperimentSpecification
                    │
                    ▼
             Human Approval
                    │
                    ▼
        Execution-ready artifact  ─────▶  Phase 8B (not built here)
```

## Package Independence Decision

`researchos.specification` is a **direct continuation** of the Phase 7
planning chain, not an independent sibling package the way Phase 6 and
Phase 7 were deliberately kept apart from each other. It consumes Phase
7 entities directly (`ExperimentalDesign`, `MethodologyPlan`,
`ContributionCandidate`, `ResearchQuestion`) and reuses Phase 7's
generic mechanics **directly, by import** rather than duplicating them a
third time:

- `researchos.planning.orchestration` (`require_in_project`,
  `require_status`, `require_approved`, `snapshot`) — used as-is; it was
  already fully generic, with no planning-specific coupling.
- `researchos.planning.llm_call` (`resolve_provider`, `call_structured`)
  — used as-is.
- `researchos.planning.validation` (`require_object_response`,
  `validate_no_hallucinated_references`) — used as-is.
- `researchos.planning.errors`' generic types (`UnknownPlanningEntityError`,
  `CrossProjectReferenceError`, `UpstreamNotApprovedError`,
  `InvalidPlanningReferenceError`, `InvalidPlanningResponseError`,
  `CandidateNotFoundError`, `ApprovalAlreadyDecidedError`,
  `HumanOnlyActionError`) — used as-is.
- `researchos.planning.types.PlanningContext` — used as-is for
  `ExperimentSpecification` generation context.
- `researchos.db.approval_dispatch` — used as-is, exactly as instructed
  ("do not create a second generic approval engine").

Only concepts genuinely new to Phase 8A get their own type:
`SpecificationError`, `DatasetValidationError`,
`InvalidLifecycleTransitionError`, `ConfigurationValidationError` (see
`researchos.specification.errors`).

## DatasetRecord vs. DatasetVersion

`DatasetRecord` (Phase 3) is **completely untouched** — it remains the
logical dataset identity (a name + one registered location). Verified
directly: `git diff` for this phase touches zero lines of the
`DatasetRecord` class or the `dataset_records` table.

`DatasetVersion` (new) is an immutable scientific version of that
identity:

```
DatasetRecord "Widget Stress Test Corpus"
├── DatasetVersion v1  (DRAFT)
├── DatasetVersion v2  (supersedes v1; APPROVED)
└── DatasetVersion v3  (supersedes v2; DRAFT)
```

Every `DatasetVersion` has a required `dataset_record_id` FK — creating
one always means registering a version *of* an existing logical
dataset, never a version floating with no identity. Fields: `version`
(int), `supersedes_id` (self-FK, lineage — see Versioning below),
`description`, `source_uri`, `format`, `sample_count`,
`split_definition`/`class_definition`/`preprocessing_definition`/
`augmentation_definition` (structured JSON, not one column per
sub-field — matching Phase 7's `components`/`assumptions`/`risks`
precedent), `content_fingerprint`/`metadata_fingerprint` (deterministic
sha256 hex digests), `lifecycle_status`, `validation_result` (the most
recent validation outcome, JSON), and generation provenance columns
(nullable — a manually-registered version has no `provider`/`model`).

## ExperimentalDesign vs. ExperimentSpecification vs. Experiment

Three distinct entities, deliberately not merged:

| Entity | Phase | Meaning |
|---|---|---|
| `ExperimentalDesign` | 7 | The scientific design — baselines, ablations, metrics **as description** |
| `ExperimentSpecification` | 8A | A concrete, structured, executable configuration implementing one approved design against one approved dataset version |
| `Experiment` | 3 | The actual execution/tracking record — status, `started_at`/`completed_at`, real metrics. **Phase 8A never creates, starts, or completes one.** |

`Experiment`/`ExperimentResult` (Phase 3) are **completely untouched** —
verified directly (`git diff` touches zero lines of either class).
`Experiment.dataset_version` (a pre-existing free-text string column,
unrelated to the new `DatasetVersion` entity despite the similar name)
is also untouched. A future Phase 8B may link an `Experiment` back to
the `ExperimentSpecification` it executed; that FK does not exist yet
and is intentionally not built here.

`ExperimentSpecification.configuration` is a validated, domain-agnostic
JSON document — no ML-specific field (`learning_rate`, `batch_size`,
`epochs`) is hardcoded into the schema anywhere, since ResearchOS must
support CV, NLP, systems research, and software engineering alike.

## Baselines

Phase 7's `ExperimentalDesign.baselines` is an unstructured JSON list of
strings — inspected first, and found inadequate for the structured
fields this phase needs (name, version, source, implementation
reference, configuration, rationale). `BaselineSpecification` (new) is
the smallest reusable addition: a plain child table of one
`ExperimentSpecification`, purely descriptive, never executed by Phase
8A, with no specific ML baseline hardcoded anywhere — every baseline is
caller/LLM-supplied.

## Versioning

Both `DatasetVersion` and `ExperimentSpecification` reuse the exact
`supersedes_id` self-FK + `UniqueConstraint(supersedes_id)` lineage
pattern Phase 7's post-implementation audit established for
`ContributionCandidate`/`ExperimentalDesign` — not reinvented. A given
row can be superseded by at most one later version (an unbranching
lineage); independent, unrelated versions/specifications each start
their own lineage at `version=1` rather than sharing a project-wide
counter (unlike `MethodologyPlan`, which genuinely is one evolving
project-wide plan).

`DatasetVersion` adds one additional rule Phase 7's entities didn't
need: `supersedes_id` must belong to the **same** `dataset_record_id` —
a version's lineage never crosses logical datasets (enforced in
`researchos.db.repository.create_dataset_version`, tested in
`tests/specification/test_dataset_versions.py::test_parent_version_must_belong_to_same_dataset_record`).

Approved artifacts are never silently overwritten: regeneration always
creates a new row; nothing in this layer ever runs an `UPDATE` on an
existing row's *content* columns (`update_dataset_version`/
`update_experiment_specification` exist for status transitions only,
never called by the generation services to mutate content).

## Dataset Lifecycle

`DatasetLifecycleStatus`: `DRAFT` → `VALIDATING` → (`VALID` or
`INVALID`) → `APPROVED`; `DEPRECATED` is a separate terminal state a
human/future process can apply. Deliberately a **separate vocabulary**
from `PlanningApprovalStatus` — a dataset version passes through
deterministic, machine-checkable validation before human approval is
even meaningful, unlike every other Phase 7 planning artifact, which
has nothing analogous to validate first.

- `researchos.specification.dataset_versions.validate_dataset_version()`
  runs the registered `DatasetValidator` for the version's own `format`
  against its *stored metadata* and transitions
  `DRAFT`/`INVALID` → `VALIDATING` → `VALID`/`INVALID`. Raises
  `InvalidLifecycleTransitionError` if the version is already `APPROVED`
  or `DEPRECATED` (immutable).
- `researchos.specification.approval.approve_dataset_version()` requires
  `lifecycle_status VALID` as a precondition — checked in a small
  pre-flight lookup *before* delegating to the shared
  `approval_dispatch`, so the dispatcher itself stays completely
  generic and unaware of this entity-specific rule. A human `REJECT`
  lands on `INVALID` (the same value automated validation failure
  produces — both mean "not fit for use," reached differently, not a
  redundant extra value); `request_changes` sends the version back to
  `DRAFT` rather than inventing a sixth state.

No scientific judgment is ever encoded in this lifecycle: `APPROVED`
means only "approved for system use under this project's defined
process."

## Dataset Validation

`researchos.specification.validators.DatasetValidator` is a
provider/adapter-oriented interface, mirroring the exact registry shape
`researchos.evidence.adapters` already established
(`get_validator()`/`available_formats()` ~ `get_adapter()`/
`available_sources()`) rather than hardcoding one dataset format into
the core. Validation is **deterministic and offline**: it operates only
on a `DatasetVersion`'s own already-stored metadata fields
(`sample_count`, `split_definition`, `class_definition`, `source_uri`)
— never on a real file at `source_uri`, which would require an
execution boundary this phase deliberately does not build.

Two validators are implemented: `GenericStructuralValidator` (the
domain-agnostic default — internal consistency checks: non-negative
sample count, well-formed split definition, split proportions/counts
that look sane) and `ClassificationDatasetValidator` (label sets exist
across CV, NLP, and tabular ML alike, so this is not a CV-specific
format). **COCO/YOLO-style annotation-schema validators are
deliberately not implemented** — see Limitations.

Every outcome distinguishes `is_valid` (false whenever `errors` is
non-empty), `errors`, and `warnings` (never affect `is_valid`) —
verified deterministic across repeated calls with identical input in
`tests/specification/test_validators.py`.

## Fingerprinting

`researchos.specification.fingerprint` is one canonicalization utility
(`json.dumps(..., sort_keys=True, separators=(",", ":"), default=str)`
then `hashlib.sha256(...).hexdigest()`) shared by **both** dataset
fingerprints and `ExperimentSpecification.configuration_hash` — reusing
the exact convention already established in
`researchos.evidence.cache.make_cache_key`, not a newly-invented scheme.

- `content_fingerprint` covers what makes a version a *different
  dataset* — `source_uri`, `format`, `sample_count`, `split_definition`,
  `class_definition`.
- `metadata_fingerprint` covers descriptive information that does not
  itself define the data — `description`, `preprocessing_definition`,
  `augmentation_definition`.

This split is a deliberate, documented design choice. Both fingerprints
are verified independent of dict/JSON key ordering and independent of
each other (`tests/specification/test_dataset_versions.py`).

## Configuration Hash

`ExperimentSpecification.configuration_hash` uses the same
canonicalization utility, verified deterministic regardless of the
LLM response's JSON key ordering
(`test_configuration_hash_is_deterministic_regardless_of_key_order`).
No secret is ever stored in `configuration`: a deny-list check
(`_find_forbidden_config_keys` in
`researchos.specification.experiment_specifications`) recursively scans
every key (case-insensitive substring match against `api_key`,
`secret`, `password`, `token`, `credential`, `access_key`,
`private_key`, ...) and raises `ConfigurationValidationError`,
rejecting the whole specification, if any match is found — configuration
is planning data, not a secret store.

## Approved-Upstream Enforcement & Provenance Snapshot

`researchos.specification.context.build_experiment_specification_context()`
enforces, before any LLM call: `experimental_design_id` and
`dataset_version_id` are both explicit (never inferred), must exist in
the caller's project, and must both be approved
(`planning_status APPROVED` for the design via
`orchestration.require_approved`; `lifecycle_status APPROVED` for the
dataset version via `orchestration.require_status` with the
`DatasetLifecycleStatus` vocabulary). `research_question_ids` must be
explicit and non-empty. Every generated `ExperimentSpecification`
records a full generation-time snapshot — id/version/status-at-generation
for the design, the dataset version, and (when present) the
methodology plan — as sibling columns, never relying on the live FK
alone; if an upstream artifact's status later changes, the historical
specification remains fully auditable (see No Cascading Invalidation).

## No Cascading Invalidation

Rejecting or deprecating an upstream `DatasetVersion`/`ExperimentalDesign`
after an `ExperimentSpecification` was already generated from its
approved state does **not** automatically reject, delete, or mutate the
specification — its `planning_status` and its stored generation-time
snapshot both remain exactly as they were. No reconciliation/staleness-
surfacing process is built in this phase (see Limitations, mirroring
Phase 7's own identical deferral).

## Human Approval

Two new gate types, both via `researchos.db.approval_dispatch` (no
second approval engine): `DATASET_VERSION_APPROVAL:<id>`,
`EXPERIMENT_SPECIFICATION_APPROVAL:<id>`. Every decision function
requires a human actor (`is_human_actor`) and raises `HumanOnlyActionError`
immediately for an agent actor, before any row is touched — verified
for both gate types.

```python
from researchos import specification

specification.approval.approve_dataset_version(dataset_version_id, actor="user:pi")
specification.approval.approve_experiment_specification(spec_id, actor="user:pi")
```

## LLM Boundaries

`researchos.specification.dataset_versions` makes **no LLM call at
all** — a dataset version's factual properties (fingerprints, sample
counts, split definitions) describe real, already-acquired or
already-planned data supplied by the researcher/system registering it;
an LLM has no way to know a real dataset's actual sample count, and
inventing one would be exactly the kind of fabricated fact this project
forbids throughout.

`researchos.specification.experiment_specifications` is the **only**
module in this package that talks to an LLM, exclusively through
`researchos.planning.llm_call.resolve_provider()`/`call_structured()` —
never `anthropic`/`openai` directly (verified via static AST inspection
in `tests/specification/test_security.py`, not merely a grep). One
versioned prompt: `experiment_specification_generation.v1`
(`researchos.specification.prompts`). No schema field offers
`planning_status`/approval — the generation service always hard-codes
`PlanningApprovalStatus.CANDIDATE`, verified by a test that sneaks a
`"planning_status": "approved"` key into a fake response and confirms
it has no effect.

## Repository Boundaries

New repository functions follow the exact explicit-session,
no-hidden-commit convention: `create_dataset_version`,
`get_dataset_version`, `list_dataset_versions`, `update_dataset_version`,
`create_experiment_specification`, `get_experiment_specification`,
`list_experiment_specifications`, `update_experiment_specification`,
`link_experiment_specification_question`,
`list_experiment_specification_questions`,
`link_experiment_specification_contribution`,
`list_experiment_specification_contributions`,
`create_baseline_specification`, `get_baseline_specification`,
`list_baseline_specifications`. None of them infer "latest" — every
function takes explicit ids. Cross-project/missing-entity checks raise
the generic `NotFoundError` (matching the existing, explicitly-documented
Phase 7 boundary: repository = existence/integrity only; richer typed
`CrossProjectReferenceError`/`UnknownPlanningEntityError` are
`researchos.planning.orchestration`'s responsibility, reused here
unchanged).

## Database Changes

One migration (`migrations/versions/984437859de2_dataset_and_experiment_specification_.py`),
chained onto Phase 7's head (`18d5e18a097f`). Five new tables
(`dataset_versions`, `experiment_specifications`,
`baseline_specifications`, `experiment_specification_contributions`,
`experiment_specification_questions`); `evidence_links.subject_type`'s
CHECK constraint widened by hand for two new `EvidenceSubjectType`
members (`DATASET_VERSION`, `EXPERIMENT_SPECIFICATION`) — autogenerate
does not detect CHECK-constraint value-set changes on an
already-existing enum column, the same gap Phase 7's own migration
documented.

**No NOT-NULL-without-`server_default` risk this time**: every new
column lives on a brand-new table created fresh in this migration —
unlike Phase 6/7, nothing here adds a `NOT NULL` column to an
already-existing table, so there is nothing to backfill. Verified
directly (not assumed) by `tests/specification/test_migration.py`,
which upgrades against a database seeded with real pre-existing Phase 7
rows (`ResearchQuestion`, `ContributionCandidate`, `MethodologyPlan`,
`ExperimentalDesign`, `DatasetRecord`) and confirms every row survives
untouched.

## Testing

`tests/specification/` (97 tests, `pytest tests/specification -q`).
Every test injects a `FakeLLMProvider` (`tests/specification/fakes.py`)
via `provider=` — no test in this suite makes, or could make, a real
LLM or scholarly API call. Fixtures follow the exact pattern established
in every prior phase's test package: a fresh temporary SQLite database
per test, migrated via the real Alembic path.

| File | Covers |
|---|---|
| `test_dataset_versions.py` | Creation, retrieval, project isolation, versioning (v1→v2, independent lineages, branching rejected), parent-version-same-dataset-record rule, cross-project parent rejection, fingerprint determinism/independence, lifecycle transitions, immutability after APPROVED |
| `test_validators.py` | Valid/invalid/warnings distinction, deterministic behavior, registry/adapter selection, no filesystem/network access |
| `test_experiment_specifications.py` | Generation, versioning/supersedes, duplicate-version rejection, cross-project rejection, approved-upstream enforcement (missing/wrong-project/rejected/unapproved), provenance snapshot, configuration hash determinism, secret-key rejection, RQ/Contribution associations |
| `test_llm_provider_integration.py` | Provider abstraction, malformed response, hallucinated/unknown/cross-project ids, LLM cannot self-assign APPROVED, LLM output never mutates upstream entities, no secrets in prompts/audit events |
| `test_approval.py` | Human-only on both gate types, candidate-status protection, dataset-version VALID precondition, audit metadata correctness, rejection terminal, changes-requested reopens a round |
| `test_security.py` | Secret-key configuration rejection (top-level/nested/in-list), static AST verification of no subprocess/exec/eval/file/network/provider-SDK calls anywhere in the package |
| `test_migration.py` | Upgrade/downgrade round-trip, CHECK constraints, FKs, unique constraints, populated-database upgrade preserving real Phase 7 rows, no stray temp tables |

Full-suite regression after this phase: **593/593 passing** (496
pre-existing + 97 new), including the entire Phase 4/5/6/7 suite
unmodified in behavior.

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\specification -v
```

## Limitations

- **No format-specific dataset validators (COCO, YOLO, ...)** —
  implementing them would require hardcoding CV-specific annotation-
  schema assumptions not yet justified by actual project usage;
  `GenericStructuralValidator`/`ClassificationDatasetValidator` cover
  the domain-agnostic and classification-label cases only.
- **No reconciliation/staleness-surfacing process** — mirrors Phase 7's
  own identical, deliberate deferral: a downstream specification whose
  upstream was later rejected/deprecated keeps its stale generation-time
  snapshot by design; nothing proactively surfaces this to a reviewer.
- **No `Experiment` linkage** — `ExperimentSpecification` has no FK to
  `Experiment` (Phase 3) yet; that connection belongs to Phase 8B, which
  will actually execute a specification and needs to record which one it
  ran.
- **No workflow-stage gating** — `STAGE_08_DATASET`/`STAGE_09_EXPERIMENTAL_DESIGN`
  transitions are not gated on any Phase 8A approval existing;
  `researchos.workflow.service` is untouched.
- **Configuration schema is unconstrained beyond "valid JSON object,
  no secret-shaped keys"** — no per-domain configuration schema
  validation exists yet (e.g. a CV-specific or NLP-specific required-
  field set); `configuration_schema_version` exists precisely so a
  future phase can add versioned, stricter schemas without breaking
  already-persisted specifications.

## Explicit Phase 8B Boundary

Phase 8A produces execution-ready *specifications*. It does not, and
must not be read as implying it can, execute anything: no training, no
inference, no subprocess execution, no GPU/CUDA/Docker/remote execution,
no checkpoint generation, no metric calculation, no statistical
analysis, no plots from actual runs, no experiment logs from real runs,
no hyperparameter optimization, no cloud execution. `Experiment`/
`ExperimentResult` (Phase 3's execution-tracking entities) remain
completely untouched by this phase. Turning an approved
`ExperimentSpecification` into a real, running experiment is Phase 8B's
responsibility, not built here.

## Future Work

- Format-specific `DatasetValidator` implementations (COCO, YOLO, or
  others) once a concrete need is identified.
- A reconciliation view surfacing `ExperimentSpecification` rows whose
  recorded upstream snapshot no longer matches that upstream artifact's
  live status.
- Extending the workflow engine (Phase 4) to gate `STAGE_08`/`STAGE_09`
  transitions on at least one approved Phase 8A artifact — deliberately
  not done here.
- Phase 8B: actual execution, linking `Experiment` back to the
  `ExperimentSpecification` it ran, real metric/checkpoint recording.
- A real-LLM smoke test for `experiment_specification_generation.v1`
  (mirroring Phase 5.1/6/7's own deferred item) once the user is ready
  to supply credentials and approve real API calls.
