> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 8B-3: Research Experiment Integration

Date: 2026-09-18
Scope: the integration layer connecting research planning through
execution — `Experiment` -> `ExperimentSpecification` -> `Run` ->
execution -> artifacts -> metrics — with complete, derived (not
caller-trusted) provenance. Phase 8B-3 adds exactly one schema
relationship (`ExperimentSpecification.experiment_id`), one
provenance-consistency hardening to the existing Phase 8B-1 preflight
checklist, and one new module
(`researchos.execution.integration`) providing two high-level entry
points: `create_run_from_specification` and `prepare_run`. **Phase
8B-3 still implements no real research experiment** — no ML training,
no inference, no domain-specific logic, no PPE/FastViT/RetinaNet/YOLO
anywhere in the core. No real LLM or scholarly API call was made
anywhere in this phase's implementation or test suite.

## Architecture

```
Research Question -> Contribution Candidate -> Methodology Plan
        -> Dataset Requirement -> DatasetVersion -> ExperimentalDesign
        -> ExperimentSpecification (linked to its Experiment)
                │
                ▼
        create_run_from_specification()      researchos.execution.integration
                │  derives experiment_id, dataset_version_id, and
                │  (by default) the execution target FROM the
                │  specification itself — nothing for a caller to
                │  independently supply and possibly get wrong
                ▼
        Run (CREATED, fully provenanced)      researchos.execution.orchestrator.request_run
                │
                ▼
        prepare_run()                         READY / BLOCKED, read-only, optional
                │
                ▼
        Human Execution Approval               EXECUTION_APPROVAL:<run_id> (unchanged from 8B-1)
                │
                ▼
        execute_run()                          researchos.execution.orchestrator (unchanged from 8B-2)
                │
                ▼
        Run (terminal) + Artifacts + Metrics + Result Manifest
                │
                ▼
        Research Results   <- NOT produced by this phase; scientific
                                interpretation belongs to a later
                                Analysis/Scientific Review phase
```

`researchos.execution.integration` does not duplicate anything Phase
8B-1/8B-2 already built. `create_run_from_specification` is a thin,
validating wrapper around `researchos.execution.orchestrator.
request_run`; `prepare_run` is a thin, non-raising wrapper around the
exact same `researchos.execution.preflight.preflight_execute` that
`orchestrator.execute_run` itself calls before queuing. The preflight
checklist itself has exactly one home
(`researchos.execution.preflight`) — nothing about Phase 8B-3 competes
with it, only reuses it.

## Experiment / Specification / Run Distinction

Preserved exactly as named in the Phase 8B-3 spec, with one added link:

- **`Experiment`** (Phase 3, unchanged fields) — the research
  experiment *concept/identity* ("Baseline RetinaNet experiment").
- **`ExperimentSpecification`** (Phase 8A) — *what should be executed*
  for that concept ("RetinaNet configuration version 3"). Phase 8B-3
  adds `experiment_id` (nullable `SET NULL` FK to `experiments.id`,
  matching every other upstream link already on this table) — the link
  that entity's own docstring had explicitly flagged as future work
  since Phase 8A ("A future Phase 8B may link an Experiment back to
  the ExperimentSpecification it executed, but that link does not
  exist yet").
- **`Run`** (Phase 8B-1) — *one actual execution instance* ("Run #17
  using specification version 3"). Unchanged shape; still references
  `experiment_id`/`experiment_specification_id`/`dataset_version_id`
  independently, each captured as an immutable snapshot at creation.

No entity was collapsed, duplicated, or renamed. `ExperimentSpecification.
experiment_id` is nullable specifically because every pre-existing
Phase 8A specification has no such link to backfill (none ever
existed before this migration) — nullable at the database level, but
`create_run_from_specification` *requires* it to be set (a typed
`UnlinkedSpecificationError`, not a database constraint — the same
"repository stays a low-level, permissive primitive; a service layer
enforces the stricter rule" boundary this codebase uses throughout,
e.g. Phase 8A's `DatasetVersion.lifecycle_status` VALID precondition).

## Run Creation

`researchos.execution.integration.create_run_from_specification(project_id,
experiment_specification_id, *, requested_by, timeout_seconds, target=None,
seed=None, execution_backend=LOCAL_PYTHON, code_repository_path=None,
config=None, session_factory=None)`:

1. Loads the specification; `MissingEntityError` if it does not exist.
2. `CrossProjectReferenceError` if it belongs to a different project.
3. `UnlinkedSpecificationError` if `experiment_id` is unset.
4. `SpecificationMissingDatasetVersionError` if `dataset_version_id` is
   unset.
5. Derives `experiment_id`/`dataset_version_id` directly from the
   specification's own columns — there is nothing left for a caller to
   independently supply and possibly get wrong.
6. Derives the execution target from `specification.configuration
   ['execution']` unless an explicit `target=` override is given (see
   Execution Target Integration below).
7. Delegates to `orchestrator.request_run` for everything else — full
   approval/dataset-approval/configuration-hash/security preflight,
   unchanged from Phase 8B-1/8B-2.
8. Appends one `execution.run_created_from_specification` audit event
   on top of `request_run`'s own `execution.run_requested` — a record
   specific to this higher-level entry point having been used.

`researchos.execution.orchestrator.request_run` (the lower-level,
Phase 8B-1 entry point that still requires the caller to pass
`experiment_id`/`dataset_version_id` explicitly) remains available and
unchanged in its public shape — it now additionally *validates* those
caller-supplied values against the specification's own recorded links
(see Provenance Consistency Hardening below), rather than trusting
them silently.

## Experiment Integration

`Experiment` gained exactly one new relationship,
`experiment_specifications` (back-populated from `ExperimentSpecification.
experiment`), and nothing else — `Experiment.runs` (Phase 8B-1) was
already sufficient for reaching every `Run` an `Experiment` has. No
direct `Experiment -> ExperimentalDesign`/`DatasetVersion`/
`MethodologyPlan` relationship was added: those remain reachable
transitively through `ExperimentSpecification` (which already links to
all three from Phase 8A), avoiding the "redundant relationships that
can become contradictory" the Phase 8B-3 spec explicitly warns
against — `ExperimentSpecification` is the one source of truth for
which upstream planning artifacts a given execution-ready
configuration was grounded in.

## Specification Integration / Validation

Before `Run` creation, the specification is validated by reusing
`researchos.execution.preflight.preflight_request` in full — approval
status, dataset approval, configuration-hash-matches-configuration-
content, execution-target/timeout security checks — **not
reimplemented**, only additionally hardened with the provenance-
consistency check below. `create_run_from_specification` adds no
second validation system.

## Provenance Consistency Hardening

A real gap existed in the Phase 8B-1 preflight: `request_run` accepted
a caller-supplied `dataset_version_id` (and `experiment_id`) without
ever checking it against what the specification *itself* had already
recorded — a caller could create a `Run` referencing a `DatasetVersion`
the specification was never actually validated against. Phase 8B-3
closes this in `preflight.preflight_request` itself (so it protects
both `request_run` and, transitively, `create_run_from_specification`):

```python
if specification.experiment_id is not None and specification.experiment_id != experiment_id:
    raise ProvenanceError(...)
if specification.dataset_version_id is not None and specification.dataset_version_id != dataset_version_id:
    raise ProvenanceError(...)
```

A specification with no link recorded (both were nullable before this
phase) imposes no constraint — only an actual disagreement is refused.

## Dataset Version Integration

Unchanged from Phase 8B-1/8A: a `Run` always references an explicit
`DatasetVersion` id and its content fingerprint, never a name/alias/
"latest". Phase 8B-3's contribution is exclusively the consistency
check above — no new dataset-fingerprint verification mechanism was
added (Phase 8A's own validation lifecycle is reused as-is).

## Configuration Integration

`compute_configuration_hash` (Phase 8A) is reused unchanged — no
second hash is ever computed for the same configuration content, and
`Run.configuration_hash` is a creation-time snapshot exactly as Phase
8B-1 established. There is no code path anywhere in `researchos.
execution` that recomputes and silently replaces a `Run`'s own
`configuration_hash` after creation.

## Execution Target Integration

The one genuinely new translation Phase 8B-3 performs:
`ExperimentSpecification` -> `ExecutionRequest`. Convention (`_derive_
execution_target` in `researchos.execution.integration`): an optional
`"execution"` key inside `ExperimentSpecification.configuration`:

```json
{
  "execution": {
    "module": "my_experiments.smoke_test",
    "arguments": ["--seed", "1"],
    "python_executable": null
  }
}
```

Deliberately just execution mechanics (module + argv + optional
interpreter override) — no domain-specific vocabulary of any kind,
matching Phase 8A's own "no ML-specific fields hardcoded into the
schema" rule for `configuration` as a whole. `create_run_from_
specification` reads this via `PythonModuleTarget` — the exact same
Phase 8B-1 contract type, `ExecutionRequest`, `ExecutionEngine`, and
`LocalPythonExecutor` — with no second execution abstraction and no
implementation detail of subprocess execution leaking into this
integration layer. An explicit `target=` argument overrides derivation
entirely, for a specification that does not encode one (or a caller
that wants to run something else against the same specification's
other provenance).

## Domain Neutrality

No CV/NLP/ML vocabulary exists anywhere in `researchos.execution`,
including this phase's new module — `configuration['execution']` only
ever describes *how to invoke a process*, never *what kind of research
it performs*. `PPE`/`FastViT`/`RetinaNet`/`YOLO`/`PyTorch`/`TensorFlow`
do not appear anywhere in this package (verified by grep during the
independent audit). A future domain-specific adapter is expected to be
one *consumer* of this architecture (an `ExperimentSpecification`
generator/config producer for a particular research domain), never a
change to the architecture itself.

## Preparation vs. Execution

`researchos.execution.integration.prepare_run(run_id)` answers "is
this `Run` ready to execute?" **without** starting it — no lifecycle
transition happens inside `prepare_run` at all (confirmed by a
dedicated test: calling it twice, or many times, never changes
`Run.status`). It returns a `PrepareOutcome(ready: bool, reasons:
list[str], error: Optional[BaseException])`:

- `ready=True` — the exact same `preflight_execute` check
  `execute_run` itself is about to run would pass.
- `ready=False` — `reasons` holds the human-readable message(s);
  `error` holds the *exact* exception object `execute_run` would
  itself raise (so a caller that wants to `raise outcome.error` gets
  identical typed-exception behavior to calling `execute_run` directly
  and catching it).

`execute_run` requires READY (via its own, unchanged internal call to
`preflight_execute`) *and* explicit execution approval — nothing about
`prepare_run` grants or substitutes for approval; it is purely
diagnostic. `execution.run_prepared`/`execution.run_blocked` audit
events are recorded either way.

## Actual Execution Integration

`execute_run` itself (Phase 8B-1/8B-2) is **unchanged** — Phase 8B-3
does not modify its internals, only adds `create_run_from_specification`/
`prepare_run` as new callers/companions sitting in front of it. No
execution logic is duplicated: `LocalPythonExecutor`, `ExecutionRequest`,
workspace preparation, artifact registration, metrics ingestion, and
result-manifest generation all behave exactly as documented in
docs/PHASE8B2_ACTUAL_EXECUTION_ARTIFACTS_METRICS.md.

## Artifacts / Metrics

Both reused exactly as Phase 8B-2 built them — `ArtifactMetadata`/
`Metric` rows created through the integration entry point are
byte-for-byte the same shape and same registration path as rows
created through `orchestrator.execute_run` directly (because they
*are* the same code path). This layer knows which artifacts/metrics
belong to which `Run` and nothing more — it never interprets a metric
value, never ranks runs, and never infers a checkpoint/model/plot
artifact's scientific meaning.

## Audit Trail

New event types, all via the existing `AuditEvent` mechanism (no
second audit system):

| Event | Emitted by |
|---|---|
| `execution.run_created_from_specification` | `create_run_from_specification`, after `request_run` succeeds |
| `execution.run_prepared` | `prepare_run`, when `preflight_execute` passes |
| `execution.run_blocked` | `prepare_run`, when `preflight_execute` raises |

Unchanged from earlier phases: `execution.run_requested`/`run_queued`/
`run_started`/`run_succeeded`/`run_failed`/`run_cancelled`/
`run_timed_out`/`run_preparation_failed` (Run lifecycle, `researchos.
execution.runs`), `execution.execution_requested`/`execution_approved`/
`execution_rejected`/`execution_changes_requested` (approval,
`researchos.execution.approval`), `execution.metrics_manifest_invalid`/
`metrics_registered` (`researchos.execution.orchestrator`).

## Idempotency

- `execute_run` called twice on the same `Run`: the second call raises
  `InvalidRunStateError` (`assert_not_terminal`, unchanged from Phase
  8B-1) — a terminal `Run` can never be silently re-executed.
- `prepare_run` called any number of times: always safe, read-only,
  idempotent by construction (it performs no write to `Run` itself).
- Retry-after-failure/-timeout: not automatic anywhere — a new attempt
  always means `create_run_from_specification` again, producing a
  brand-new `Run` row with its own independently-captured provenance
  (unchanged Phase 8B-1 reproducibility model — a `Run` is never a
  versioned artifact).

## Concurrency

Reuses the exact Phase 8B-1 optimistic-concurrency primitive
(`repository.update_run_lifecycle`'s `expected_status` compare-and-
swap) — no new concurrency model was introduced. A competing "queue
this Run" attempt against a `Run` another caller has already moved past
`CREATED` is rejected by the same CAS check every other lifecycle
transition already relies on.

## Project Isolation

Maintained across every entity this phase touches: `create_run_from_
specification` checks the specification's own `project_id` before
doing anything else; the derived `experiment_id`/`dataset_version_id`
can never cross a project boundary because `repository.create_
experiment_specification` already refuses to link a specification to
an out-of-project `Experiment`/`DatasetVersion` at creation time (so a
cross-project link is structurally unconstructable in the first
place, verified directly rather than assumed); `Metric`/`ArtifactMetadata`
project-scoping is unchanged from Phase 8B-2.

## Security

No change to the Phase 8B-1/8B-2 security boundary. The new
`configuration['execution']` -> `PythonModuleTarget` translation still
passes through the exact same `researchos.execution.security.
validate_execution_target` fail-closed allowlist before anything is
ever spawned — a malicious module name embedded in a specification's
`configuration` is rejected exactly as it would be if passed directly
to `request_run` (verified by a dedicated test). No new subprocess
usage, no `shell=True`, no `eval`/`exec`, no artifact-path or
cross-project bypass was introduced by this integration layer.

## Scientific-vs-Execution Semantics

`RunStatus.SUCCEEDED` means only "the requested executable process
completed successfully" — never a scientific conclusion. Nothing in
`researchos.execution` (including this phase's new module):

- approves an `ExperimentSpecification`/`ContributionCandidate`/
  anything else as a side effect of a successful `Run` (verified by a
  before/after `Approval` snapshot test — the *only* new `Approval` row
  a full create-run-from-specification-through-execution flow produces
  is the execution approval itself).
- modifies `ContributionCandidate.planning_status` based on metric
  values (verified directly — no code path in this package ever reads
  a `Metric.value` to make a decision).
- ranks, compares, or judges metrics as "good"/"bad" — a `Metric` row
  is an observation, full stop; interpretation belongs to a later
  Analysis/Scientific Review phase this package does not implement.

## Workflow Boundary

`researchos.workflow` (Phase 4) is **not modified** and is never
automatically advanced by anything in this phase —
`ResearchProject.current_stage` is verified unchanged by a full
create-run-through-execution flow. `researchos.execution` still
imports only the read-only `workflow.policy.is_human_actor` helper
(the same Phase 4 `"agent:"`-prefix convention every other approval
gate already uses), confirmed by a static AST check that no module in
this package imports `researchos.workflow.service` (the state-machine
authority) at all.

## LLM Boundary

Unchanged: no `anthropic`/`openai` import anywhere in `researchos.
execution` (verified by the existing AST security tests, which cover
every module including this phase's new one). No LLM can create,
approve, or influence a `Run`'s execution approval, provenance, or
lifecycle transition.

## Database

One new nullable column: `experiment_specifications.experiment_id`
(`SET NULL` FK to `experiments.id`, indexed). No new table. No
existing column, constraint, or relationship removed or altered beyond
this one addition — `git diff` against `models.py`/`repository.py`
confirms this remains a pure addition (aside from the one import-line
widening every prior phase's own diff also needed).

## Migration

`migrations/versions/91a24a97a7d4_research_experiment_integration.py`
(revises `a4d80d49ae32`). No populated-database backfill risk: the new
column is nullable and every pre-existing specification has nothing to
backfill from (the link never existed before this migration).
Verified directly: fresh upgrade, `alembic check` (zero drift),
downgrade removes the column cleanly, re-upgrade round-trips, an
upgrade against a database seeded with a real pre-existing Phase 8A
specification row leaves `experiment_id` correctly `NULL` (never
fabricated), and a downgrade from Phase 8B-3 preserves a row's other
data untouched.

## Testing

`tests/execution/test_integration.py` (33 new tests) plus 4 new
Phase-8B-3-specific migration tests appended to `tests/execution/
test_migration.py` (37 new tests total), plus targeted
fixture additions to `tests/execution/conftest.py`
(`linked_experiment_specification_id` — an APPROVED specification
genuinely linked to an `Experiment` and carrying a valid
`configuration['execution']` block, distinct from the Phase 8B-1/8B-2
`approved_experiment_specification_id` fixture, which is deliberately
left unlinked so it still exercises the lower-level `request_run` path
and the new Phase 8B-3 rejection paths). Also: one Phase 8B-1 test
(`test_request_run_rejects_cross_project_dataset_version`) was updated
— not weakened — to isolate the original cross-project guarantee from
the new provenance-consistency check that now fires first for that
exact input combination (both checks independently reject the
operation; the test now constructs a specification with no
`dataset_version_id` recorded so the original check is what's
exercised, with the new check's own dedicated test added alongside
it). Six stale migration-head literals were updated across `tests/
planning/test_migration.py`, `tests/specification/test_migration.py`,
and `tests/execution/test_migration.py` — the same class of fix every
prior phase needed, precisely documented at each site.

| Area | Covers |
|---|---|
| Run creation (A) | Valid derivation, unapproved/missing/wrong-project specification, unlinked specification, missing dataset version, missing/malformed execution block, explicit target override, provenance-inconsistent caller-supplied ids |
| Provenance (B) | Full snapshot matches specification/dataset, structural immutability |
| Preparation (C) | READY, BLOCKED with reason, no status mutation, unknown run_id |
| Execution (D) | Success, non-zero exit, timeout, launch failure — all through the integration entry point |
| Idempotency (E) | Execute twice rejected, prepare twice safe, terminal run stays BLOCKED-by-immutability |
| Concurrency (F) | Competing queue attempts, CAS rejection |
| Artifacts/Metrics (G/H) | stdout/stderr/result_manifest/metrics_report registered, metrics attached to the correct Run |
| Audit (I) | Full event-type coverage across the create → prepare → approve → execute → complete/fail lifecycle |
| Security (J) | Structurally-impossible cross-project dataset linkage, malicious module in a specification's configuration rejected |
| Scientific semantics (K) | No auto-approval, no metric-driven contribution mutation, no workflow-stage advancement, static import check |

Full-suite regression after this phase: **830 passed, 1 skipped**, 0
failed (793 Phase 1-8B-2 + 37 new Phase 8B-3; the one skip is Phase
8B-2's symlink-escape test, environment-gated on Windows without
Developer Mode/administrator privileges — unrelated to this phase),
including the entire prior
suite unmodified in behavior beyond the one re-scoped test and the
documented stale-literal updates above.

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\execution\test_integration.py -v
```

## Explicit Future PPE/Domain-Adapter Boundary

Nothing in Phase 8B-3 executes, trains, or even references PPE,
FastViT, RetinaNet, YOLO, or any computer-vision-specific concept —
verified by grep during the independent audit finding zero matches
anywhere in `researchos.execution`. The `configuration['execution']`
convention this phase introduces is intentionally the *only* new
surface a domain-specific adapter would need: a future PPE/CV adapter
would generate `ExperimentSpecification` rows (through Phase 8A's
existing `researchos.specification` generation service, linked via the
new `experiment_id`) whose `configuration['execution']` names *that
adapter's own* allowlisted module — ResearchOS core never needs to
know what that module does. `ExecutionBackend.DOCKER`/`REMOTE_GPU`/
`SLURM`/`CLOUD` remain interface-only, unimplemented. No real PPE
experiment, GPU training run, or thesis-specific logic was executed,
referenced, or hard-coded anywhere in this phase's implementation or
test suite — only a tiny, deterministic, already-existing test target
(`tests/execution/_local_target.py`) was used to demonstrate success/
failure/timeout/structured-metrics behavior.
