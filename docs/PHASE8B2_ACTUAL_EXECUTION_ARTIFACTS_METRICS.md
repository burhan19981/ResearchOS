> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 8B-2: Actual Execution, Artifacts, and Metrics

Date: 2026-09-18
Scope: turns the Phase 8B-1 execution foundation into a real, controlled
execution subsystem — actual `LocalPythonExecutor` invocation inside a
deterministic, project/run-isolated workspace; streaming SHA-256
artifact registration; a generic, domain-neutral metrics model fed only
by a structured JSON manifest (never stdout parsing); a generated,
deterministic result manifest; richer (still best-effort, never
required) environment capture; and complete failure/timeout handling so
a `Run` can never be left stranded in a non-terminal state. **Phase
8B-2 still implements no real research experiment** — no ML training,
no inference, no domain-specific logic of any kind. No real LLM or
scholarly API call was made anywhere in this phase's implementation or
test suite, and nothing in `researchos.execution` calls an LLM at all.

## Architecture

```
Approved ExperimentSpecification + Approved DatasetVersion
        │
        ▼
   request_run()                 (unchanged from Phase 8B-1)
        │
        ▼
   Run (CREATED, fully provenanced)
        │
        ▼
 Human Execution Approval          EXECUTION_APPROVAL:<run_id>
        │
        ▼
   execute_run()
        │  1. preflight (approval, target, timeout)
        │  2. Run: CREATED -> QUEUED
        │  3. prepare_run_workspace()        <project_id>/<run_id>/...
        │  4. Run: QUEUED -> RUNNING
        │  5. ExecutionEngine.execute()      LocalPythonExecutor, real subprocess
        │  6. Run: RUNNING -> terminal        (finalized BEFORE anything below)
        ▼
   ------------- best-effort enrichment, never corrupts the Run above -------------
        │  7. register_artifact()  for stdout, stderr (streaming sha256)
        │  8. load_metrics_manifest() + register_metrics()  IF the process wrote one
        │  9. build_result_manifest() + write + register_artifact("result_manifest")
   ----------------------------------------------------------------------------------
        ▼
   Run (terminal) + ArtifactMetadata rows + Metric rows + result_manifest.json
```

The domain layer (`orchestrator`/`preflight`/`runs`/`approval`/
`artifacts`/`metrics`/`manifest`/`workspace`) still never imports
`subprocess` and never knows a process is being spawned — only
`local_executor.py`, `git_provenance.py`, and `environment_snapshot.py`
do, exactly as in Phase 8B-1. This package remains a direct
continuation of the Phase 7/8A/8B-1 chain: `researchos.execution.
manifest`/`environment_snapshot` reuse `researchos.specification.
fingerprint`'s canonicalization directly; `preflight`/`context`-style
checks continue to reuse `researchos.planning.orchestration`/`errors`.

## Ordering Discipline (the key design decision of this phase)

A `Run`'s terminal lifecycle status is finalized (`runs.complete_run`)
**immediately** after `ExecutionEngine.execute()` returns or raises —
*before* any artifact, metrics, or manifest post-processing runs.
Everything after that point (steps 7-9 above) is best-effort
enrichment that must never be able to leave a `Run` stranded: a failure
registering an artifact, or a malformed metrics manifest, is surfaced
to the caller as a raised exception (never silently swallowed) but
never blocks or corrupts the `Run`'s own already-persisted, accurate
terminal record. See `researchos.execution.orchestrator.execute_run`'s
own module docstring for the same statement in code.

## Run Lifecycle

Unchanged from Phase 8B-1 except for **one** new edge:

```
CREATED -> QUEUED -> RUNNING -> SUCCEEDED
                              -> FAILED
                              -> CANCELLED
                              -> TIMEOUT
QUEUED -> FAILED   (new in Phase 8B-2)
```

`QUEUED -> FAILED` exists because Phase 8B-2 introduces real work
between "queued" and "running" — workspace preparation
(`prepare_run_workspace`) — that can genuinely fail (disk full,
permission denied) before the process ever starts. Without this edge,
such a failure would strand the `Run` in `QUEUED` forever, violating
"no Run stuck in a non-terminal state after a controlled failure."
This is the narrowest possible addition that satisfies that
requirement; it deliberately does **not** reopen the pre-`RUNNING`
*cancellation* question Phase 8B-1 left closed (see Cancellation,
below) — `mark_preparation_failed` only ever fires from inside
`execute_run` itself, in response to a genuine preparation exception,
never as a caller-invoked cancel.

Every other terminal-state invariant from Phase 8B-1 is unchanged:
`_ALLOWED_TRANSITIONS` still has zero outgoing edges from any terminal
status, so `researchos.execution.runs.assert_not_terminal` still
refuses to re-execute an already-decided `Run`.

## Actual Execution Behavior

`LocalPythonExecutor` (unchanged security model from Phase 8B-1 — see
that document's Security Model section for the full argv-list/
`shell=False`/allowlist reasoning) now additionally handles the one
failure mode Phase 8B-1 left uncaught: a genuine **process launch
failure** (`OSError`, e.g. `python_executable` does not exist). This is
now caught and converted into a `RunStatus.FAILED` `ExecutionResult`
with `exit_code=None` and a `failure_reason` explaining the launch
failure — never an uncaught exception that would leave the `Run`
stranded in `RUNNING`.

`researchos.execution.orchestrator.execute_run` additionally wraps
`engine.execute()` itself in a `try`/`except Exception`: if *any*
`ExecutionEngine` implementation (a future `DockerExecutor`, or a
misbehaving test double) raises instead of returning an
`ExecutionResult`, the `Run` is still finalized as `FAILED` with the
exception's message recorded, and the exception is re-raised to the
caller — robustness that does not depend on every current or future
executor implementation being perfectly well-behaved.

## Execution Workspace

```
<ExecutionConfig.allowed_execution_root>/<project_id>/<run_id>/
    input/        # reserved for future use — nothing writes here in Phase 8B-2
    output/        # LocalPythonExecutor's cwd; metrics.json (if any) is read from here
    logs/          # stdout.log, stderr.log
    artifacts/     # reserved for future non-log artifact placement
    manifests/     # the generated result_manifest.json
```

`researchos.execution.workspace.prepare_run_workspace(project_id,
run_id, config=...)` builds and validates this path via the same
`security.validate_working_directory` Phase 8B-1 already used — the
`<project_id>/<run_id>` segments are always built from trusted,
already-loaded `Run` columns (database-assigned integers), never from
caller-supplied strings, so there is no path-traversal surface: two
different projects, or two different runs in the same project, always
get non-overlapping directories by construction, and nothing here ever
overwrites another run's files.

## Artifact Model

`ArtifactMetadata` (Phase 8B-1) gains `logical_name` (required,
`UniqueConstraint(run_id, logical_name)`), `source`, and `description`.
`researchos.execution.artifacts.register_artifact` is the **only** way
`researchos.execution` creates an `ArtifactMetadata` row: it
streaming-hashes the file (`researchos.execution.hashing.sha256_file`
— see below), then calls `repository.create_artifact_metadata`.
`researchos.db.repository` exposes **no** `update_artifact_metadata`
function anywhere — a second registration attempt with the same
`(run_id, logical_name)` raises `DuplicateArtifactError` (translated
from the table's own unique-constraint violation), never silently
overwriting a prior registration. `ArtifactType` gained `METRIC_REPORT`
and `RESULT_MANIFEST` (renamed from Phase 8B-1's never-actually-used
`RESULT` — verified by search before the migration was written that no
code anywhere had ever set that value).

Every `Run` that completes automatically gets `stdout`/`stderr`
artifacts registered (best-effort: only if the referenced file actually
exists — a `FakeExecutionEngine` test double never touches the
filesystem, and that's fine), plus a `result_manifest` artifact, plus a
`metrics_report` artifact if (and only if) the process wrote a metrics
manifest.

## SHA-256 Implementation

`researchos.execution.hashing.sha256_file` fixes Phase 8B-1's
`path.read_bytes()`-then-hash approach: it reads the file in fixed-size
(default 1 MiB) chunks via a single open file handle, updating one
`hashlib.sha256()` instance incrementally — bounded memory regardless
of file size. Verified directly (not assumed) against `hashlib`'s own
whole-file digest for an empty file, a small text file, a binary file,
and an 8 MiB pseudo-random file, at two different chunk sizes, to prove
the digest is identical regardless of how many chunks it took to read
the file.

## Metrics Model

`Metric` (new table): `run_id`, `name`, `value` (`Float`), `value_type`
(`INTEGER`/`FLOAT`), `unit`, `split`, `aggregation`, `threshold`,
`evaluation_protocol`, `source`, `source_artifact_id` (optional FK to
the `ArtifactMetadata` row the metric came from), `metadata` (JSON).
**No** uniqueness constraint on `(run_id, name)` — the same metric name
legitimately recurs across splits/evaluations, exactly like
`ExperimentResult.metric_name` (Phase 3) already established for the
identical reason. `researchos.db.repository` exposes no `update_metric`
function — rows are append-only; a correction is always a new row.

### Numeric Representation

`Metric.value` is stored as **`Float`** (IEEE-754 double), not
`Decimal`. This is a deliberate choice, not an oversight: metric values
(accuracy, loss, latency, throughput, ...) are empirical,
already-approximate measurements, not exact quantities like currency
where `Decimal`'s exact base-10 arithmetic actually matters — using
`Decimal` here would falsely imply a precision the underlying
measurement does not have, and every existing numeric metric-like
column in this codebase (`ExperimentResult.metric_value`, Phase 3)
already uses plain `float` for the same reason. The one piece of
information plain `Float` storage would otherwise lose — whether a
caller reported an integer count (`epoch=5`) or a continuous
measurement (`accuracy=0.953`) — is preserved explicitly via
`value_type` (`MetricValueType`).

**NaN/Infinity policy (explicit, not left ambiguous):** rejected
outright. `researchos.execution.metrics.validate_metrics_manifest`
reuses `researchos.db.models._validate_finite_number` (via `Metric`'s
own `@validates("value")`, and directly via `math.isfinite()` in the
manifest validator itself) to refuse any non-finite `value`/`threshold`
with a typed `InvalidMetricValueError` before it ever reaches the
database. Zero and negative values are fully supported (a loss of
`0.0`, a log-probability of `-3.2`, etc. are all valid).

## Structured Metric Collection

**Never regex-parsed from stdout** — Phase 8B-2 spec section 14
explicitly forbids that. Instead, a process `LocalPythonExecutor` runs
MAY write a JSON file at one fixed, well-known path inside its own
working directory: `<run workspace>/output/metrics.json`
(`RunWorkspace.metrics_manifest_path`). `execute_run` checks for that
file's existence *only after* the process has already exited (never
before, never while it's running) and, only if present, validates and
ingests it via `researchos.execution.metrics`. A process that reports
no metrics at all is completely normal — most executions in this
generic foundation will not produce one.

### Schema (`METRICS_MANIFEST_SCHEMA_VERSION = "v1"`)

```json
{
  "schema_version": "v1",
  "metrics": [
    {"name": "accuracy", "value": 0.95, "unit": null, "split": "test",
     "aggregation": "mean", "threshold": null, "evaluation_protocol": null,
     "source": null, "metadata": {}}
  ]
}
```

**Compatibility policy (explicit):** both the top-level object and each
metric entry are validated **strictly** in `v1` — an unrecognized
top-level key, an unrecognized metric key, a missing `schema_version`,
or a `schema_version` this module does not recognize all raise
`MalformedMetricsManifestError`. Only `name` and `value` are required
per entry. A future schema version may relax this; `v1` does not,
matching `researchos.specification.experiment_specifications`'s
equally strict configuration validation — silently ignoring an
unrecognized field in a scientific record is exactly the kind of silent
data loss this project avoids everywhere else.

## Artifact + Metric Relationship

```
Run
├── Artifacts (ArtifactMetadata)
│    ├── stdout / stderr        (always, if the file exists)
│    ├── metrics_report         (only if metrics.json was written)
│    └── result_manifest        (always, generated after completion)
└── Metrics (Metric)
     ├── accuracy
     ├── precision
     └── ...  (only if metrics.json was written)
```

A `Metric`'s optional `source_artifact_id` points at the
`metrics_report` `ArtifactMetadata` row it came from when one exists —
metrics are never dependent on stdout parsing to be understood.

## Result Manifest

`researchos.execution.manifest.build_result_manifest` assembles one
deterministic JSON document per terminal `Run`
(`RESULT_MANIFEST_SCHEMA_VERSION = "v1"`) containing: schema/ResearchOS
version, project/experiment/run ids, specification id+version+
configuration hash, dataset version id+version+fingerprint, code
provenance (repository/commit/branch/working-tree-clean/unavailable
reason), environment snapshot id, execution backend/target/seed/
timeout/timestamps/duration/exit code/status/failure reason, every
registered artifact's logical name/type/reference/size/sha256/mime
type, and every registered metric's full field set. **No secrets, no
raw environment variable dump** — every field is an id, a version, a
hash, a timestamp, or an already-independently-recorded reference.
`json.dumps(..., sort_keys=True, indent=2)` keeps field *ordering*
deterministic; the values themselves (timestamps, durations) are not
forced deterministic, since they genuinely differ run to run by nature.
The manifest is written to `manifests/result_manifest.json` and
registered as its own `RESULT_MANIFEST` artifact — generated only
*after* the `Run` is already terminal, so it always reflects the
`Run`'s final, accurate state.

## Environment Capture

`researchos.execution.environment_snapshot.collect_environment_info`
(Phase 8B-1) gains: `cpu_model`/`cpu_count` (via `platform.processor()`/
`os.cpu_count()` — always available, no new dependency), best-effort
`total_memory_bytes` (Windows via `ctypes`+`GlobalMemoryStatusEx`,
Linux via `/proc/meminfo`; `None` on any other platform or failure — no
`psutil` dependency added), and `researchos_version`
(`researchos.__version__`). GPU detection is now queried via
`nvidia-smi` **independent of whether the installed PyTorch build can
use CUDA**, so "a GPU is physically present" and "this run's PyTorch can use CUDA"
are deliberately kept as distinguishable facts (`gpu_name`/
`gpu_driver_version` vs. `cuda_version`/`cudnn_version`). Every one of
these facts is best-effort: a missing `nvidia-smi`, a missing `torch`,
or a platform this module doesn't special-case for memory detection
never fails a CPU execution — verified directly by mocking each failure
mode and asserting `collect_environment_info()` still returns
successfully with the corresponding field(s) `None`.

## Provenance

Unchanged chain from Phase 8B-1, now additionally reflected in the
generated result manifest: `Run` -> `ExperimentSpecification` id +
version -> `DatasetVersion` id + version + fingerprint -> configuration
hash -> code provenance (known / explicitly unavailable, never
fabricated) -> `EnvironmentSnapshot` -> execution result -> registered
`ArtifactMetadata` rows -> registered `Metric` rows. Every "unavailable"
case (no git repository, no GPU, no `nvidia-smi`) is represented
explicitly as `None`/an explicit reason string — never silently
omitted from the schema and never inferred from something else.

## Failure Handling

Extends Phase 8B-1's failure model with: process launch failure (caught
`OSError` in `LocalPythonExecutor`, see Actual Execution Behavior
above), workspace-preparation failure (`QUEUED -> FAILED`, see Run
Lifecycle above), and malformed metrics manifest (raised to the caller
*after* the `Run` is already safely terminal, with an
`execution.metrics_manifest_invalid` audit event recorded — the `Run`'s
own status/exit_code/stdout/stderr reference are never affected by a
metrics-ingestion problem). Artifact registration failures (e.g. a
duplicate logical name, which should not normally occur given
`execute_run`'s own controlled flow) are caught and swallowed for the
automatic stdout/stderr/metrics_report/result_manifest registrations
specifically — a storage hiccup registering optional metadata must
never mask an already-accurate, already-persisted `Run` record.

## Timeout

Unchanged from Phase 8B-1: `subprocess.run(..., timeout=...)` raises
`TimeoutExpired`, which `LocalPythonExecutor` catches and converts into
a `RunStatus.TIMEOUT` `ExecutionResult` with whatever stdout/stderr was
captured before termination preserved at their normal reference paths.
`execute_run`'s ordering discipline (finalize the `Run` immediately,
enrich afterward) applies identically to a `TIMEOUT` outcome: the `Run`
reaches its terminal state first, then stdout/stderr/manifest
registration proceeds exactly as it would for any other terminal
status.

## Cancellation

**Deliberately not added in this phase.** `LocalPythonExecutor` remains
fully synchronous (`subprocess.run` blocks until the child process
exits, times out, or fails to launch) — there is no background
thread/process boundary across which a "cancel this running execution"
signal could even be delivered without a materially different executor
architecture. The Phase 8B-2 spec's own scope list does not include
runtime cancellation, and explicitly warns against "casually" adding
pre-`RUNNING` cancellation Phase 8B-1 deliberately left out. The
`RUNNING -> CANCELLED` transition itself still exists in
`RunStatus`/the transition table (inherited from Phase 8B-1) for a
future executor architecture that can support it — but no code path in
Phase 8B-2 ever produces it.

## Security Model

Unchanged core guarantees from Phase 8B-1 (see that document's Security
Model section) — structural argv-list execution, fail-closed module
allowlist, explicit-allowlist child environment, working-directory root
confinement. New in Phase 8B-2:

- **Artifact registration enforces workspace confinement itself**
  (hardened after the Phase 8B-2 independent audit's one LOW finding:
  the original design left this solely to a well-behaved caller).
  `register_artifact` now calls `researchos.execution.security.
  validate_artifact_path` unconditionally, before anything else — the
  `path` given must resolve strictly inside
  `<allowed_execution_root>/<project_id>/<run_id>/`, the exact `Run`'s
  own workspace, or `ArtifactPathEscapeError` is raised and nothing is
  registered. Because `Path.resolve()` both normalizes `..` segments
  and follows symlinks (for any path component that actually exists),
  one check catches relative traversal, an absolute path elsewhere on
  disk, a path under a *different* run's or project's own subtree
  (rejected by the same per-run-scoped containment check, not a
  separate cross-project rule), and a symlink planted inside the
  workspace pointing outside it. The check is engine-agnostic — it
  uses the same `ExecutionConfig.allowed_execution_root` concept any
  future `ExecutionEngine` would register artifacts under — so it
  never needs to change per backend, and it does not depend on the
  orchestrator continuing to only ever pass safe paths: the boundary
  now lives in the registration primitive itself.
- **Project isolation for `Metric`/`ArtifactMetadata`** — `create_metric`/
  `create_artifact_metadata` both validate that `run_id` belongs to the
  caller's `project_id`, exactly like every other Phase 8A/8B-1
  repository function; `list_metrics`/`list_artifact_metadata` are both
  `project_id`-scoped queries. `get_*`-by-id functions are **not**
  project-scoped, matching the established codebase-wide convention
  (`repository.get_run`, `get_experiment_specification`, etc. are all
  the same) — isolation is enforced at write/list time, not at read-
  by-trusted-id time.
- AST-based static verification (`tests/execution/test_security.py`)
  continues to confirm no `shell=True`, `os.system`, `eval`/`exec`, or
  direct provider-SDK import exists anywhere in the package, and that
  only `local_executor.py`/`git_provenance.py`/`environment_snapshot.py`
  import `subprocess` at all — none of the five new Phase 8B-2 modules
  (`hashing`, `workspace`, `artifacts`, `metrics`, `manifest`) do.

## Approval Model

Unchanged from Phase 8B-1: `EXECUTION_APPROVAL:<run_id>` remains the
one human execution-approval gate, checked by `preflight_execute`
completely separately from the `ExperimentSpecification`'s own
approval (checked by `preflight_request`). No LLM can create, satisfy,
or bypass either gate — `researchos.execution.approval` still requires
`is_human_actor(actor)` before recording any decision.

## Project Isolation

See Security Model above for the `Metric`/`ArtifactMetadata` specifics;
the execution workspace itself is project/run-isolated by construction
(see Execution Workspace above). Tests explicitly attempt cross-project
artifact and metric creation and assert rejection
(`tests/execution/test_artifacts.py::test_register_artifact_rejects_cross_project_run`,
`tests/execution/test_security.py::test_cross_project_metric_creation_rejected`).

## Reproducibility

A completed `Run`'s result manifest alone is sufficient to reconstruct
*what was executed and with what*: the exact `ExperimentSpecification`
version and configuration hash, the exact `DatasetVersion` version and
content fingerprint, the exact code commit (or an explicit reason none
was available), the exact environment snapshot, and every artifact/
metric the execution produced — all captured at the moment of
execution, none of it inferred after the fact or silently omitted when
unavailable.

## Database Changes

One new table (`metrics`) and two extended Phase 8B-1 tables
(`artifact_metadata` gains `logical_name`/`source`/`description` +
`UniqueConstraint(run_id, logical_name)`; `environment_snapshots` gains
`cpu_model`/`cpu_count`/`total_memory_bytes`/`researchos_version`).
`Run`/`Experiment`/`ExperimentSpecification`/`DatasetVersion` and every
other pre-existing table are completely untouched — verified via `git
diff` (zero removed lines in `models.py`/`repository.py` beyond one
widened import line) exactly as every prior phase's audit verified.

## Migration

`migrations/versions/a4d80d49ae32_actual_execution_artifacts_metrics.py`
(revises `b03b320a103c`). Populated-database safety: `artifact_metadata.
logical_name` is a new `NOT NULL` column on a table that may already
contain real Phase 8B-1 rows — a single literal `server_default`
cannot be used here (the new column also carries
`UniqueConstraint(run_id, logical_name)`, and two pre-existing rows for
the same `run_id` backfilled to the same literal default would
collide). Instead: the column is added nullable, backfilled per-row via
`UPDATE artifact_metadata SET logical_name = LOWER(artifact_type)`
(deterministic, and guaranteed non-colliding for every row Phase 8B-1
could actually have produced, since it never created two artifacts of
the same `artifact_type` for one `Run`), then altered to `NOT NULL`,
and only then does the unique constraint get added. Verified directly
(not assumed): fresh upgrade, `alembic check` (zero drift), downgrade→
re-upgrade round-trip, an upgrade against a database seeded with real
pre-existing Phase 8B-1 `artifact_metadata` rows (confirming correct,
non-colliding backfill), and an upgrade against a database seeded with
real pre-existing Phase 8A rows (confirming those are completely
untouched).

## Testing

`tests/execution/` (201 tests total, 1 skipped on Windows without
Developer Mode/administrator privileges — 112 carried over from Phase
8B-1 plus 89 new). No test makes a real LLM/scholarly API call,
requires CUDA or Docker, touches network, or writes outside a pytest
`tmp_path`/temporary database.

| File | Covers |
|---|---|
| `test_hashing.py` | Streaming SHA-256: empty/small/binary/8 MiB files, chunk-size independence, determinism |
| `test_artifacts.py` | Registration, duplicate logical name rejected, missing file rejected, same name across different runs allowed, cross-project rejected, no update function exists, workspace-boundary enforcement (`../` traversal, absolute path outside, a different run's/project's own workspace, symlink escape — skipped on Windows without Developer Mode/admin, which cannot create symlinks at all — and a genuinely valid path still succeeds) |
| `test_metrics.py` | Valid manifests, repeated names across splits, int/float/zero/negative, NaN/Infinity rejected, non-numeric rejected, malformed schema/unknown fields/missing required fields, append-only persistence |
| `test_manifest.py` | Full provenance chain present, artifact/metric references, no secrets, registered as its own artifact, deterministic key ordering |
| `test_workspace.py` | Subdirectory creation, project/run isolation, no path escape |
| `test_environment_capture.py` | Normal collection, missing/timeout/nonzero-exit `nvidia-smi`, parsed GPU info, missing torch, no secrets/raw env dump |
| `test_output_handling.py` | Empty output, 20,000-line large output fully captured, binary-safe stdout |
| `test_failure_handling.py` (extended) | Process launch failure, malformed-manifest-after-terminal-Run, existing Phase 8B-1 failure/timeout/artifact tests |
| `test_security.py` (extended) | Cross-project metric rejection, project-scoped metric listing, workspace path confinement, existing Phase 8B-1 injection/traversal/leakage/AST checks |
| `test_run_model.py` (extended) | `QUEUED -> FAILED` transition, existing Phase 8B-1 lifecycle tests |
| `test_migration.py` (extended) | New `metrics` table, `artifact_metadata` extensions, logical-name backfill against real Phase 8B-1 rows, widened `artifact_type` CHECK, Phase 8A rows surviving the new migration, existing Phase 8B-1 migration tests |

Full-suite regression after this phase: **793 passed, 1 skipped**, 0
failed (593 Phase 1-8A + 112 Phase 8B-1 + 89 new Phase 8B-2; the one
skip is the symlink-escape test, environment-gated on Windows without
Developer Mode/administrator privileges), including the entire prior
suite unmodified in behavior (only 9 stale migration-head literals
across `tests/planning/test_migration.py`, `tests/specification/
test_migration.py`, and `tests/execution/test_migration.py` were
updated — the same class of fix every prior phase needed, precisely
documented at each site).

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\execution -v
```

## Explicit Exclusions (this phase)

No ML training, inference, dataset preprocessing, or dataset
acquisition of any kind. No FastViT/RetinaNet/YOLO/PPE-specific logic.
No hyperparameter optimization, statistical analysis, scientific
conclusions, novelty claims, journal matching, manuscript generation,
or peer review. No `DockerExecutor`/`SlurmExecutor`/`RemoteGPUExecutor`/
`CloudExecutor` implementation (interfaces only, inherited from Phase
8B-1). No distributed execution or cross-machine scheduling. No
automatic workflow-stage transitions (`researchos.workflow` remains
completely untouched — see Phase 8B-1's own Workflow Boundary section,
unchanged here). No automatic scientific approval of any kind. No
arbitrary shell execution.

## Phase 8B-3 Boundary (Future Work)

Everything Phase 8B-2's own scope excludes above remains explicitly
deferred: real `ExecutionEngine` implementations for Docker/remote-GPU/
Slurm/cloud; actual ML training/inference against a `Run`'s captured
provenance and *real* metric production (this phase only proves the
generic metrics **channel**, never invents what a metric means); rich
artifact categories actually being generated (`CHECKPOINT`/`MODEL`/
`PLOT` — this phase only defines the vocabulary and records whatever a
process happens to produce); runtime cancellation of an in-flight
`Run`; `Experiment`-level status rollup from its `Run`s; workflow-stage
integration (does a completed `Run` ever advance `STAGE_11_EXPERIMENTS`?
— still an open design question, deliberately not answered implicitly
here).
