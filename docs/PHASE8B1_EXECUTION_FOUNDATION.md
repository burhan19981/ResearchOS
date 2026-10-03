> Historical implementation notes. For current setup, status, and security boundaries, see [the README](../README.md) and [SECURITY.md](../SECURITY.md). Historical test counts describe earlier development checkpoints.

# Phase 8B-1: Execution Foundation

Date: 2026-09-18
Scope: the foundation for turning an approved `ExperimentSpecification`
into one actual, provenanced, human-authorized execution instance (a
`Run`) — the `Run` domain model and lifecycle, a provider-neutral
execution contract, the one real executor (`LocalPythonExecutor`),
environment/code/configuration/dataset provenance, execution approval,
preflight validation, timeout/failure handling, and stdout/stderr/
artifact metadata foundations. **Phase 8B-1 does not execute real
research experiments** — no ML training, no inference, no metrics, no
checkpoints, no GPU scheduling, no Docker/Slurm/cloud execution. No
real LLM or scholarly API call was made anywhere in this phase's
implementation or test suite, and the LLM boundary established in
Phase 6/7/8A is unchanged: nothing in `researchos.execution` calls an
LLM at all.

## 1. Purpose

Phase 8A produces an *approved, execution-ready specification* — a
description of what should run. Phase 8B-1 is the foundation for
actually running it: it defines what a "real execution" means as a
first-class, auditable scientific record (a `Run`), how a human
authorizes one, how it is actually invoked as a controlled local
process, and how every fact needed to reproduce it later (environment,
code, configuration, dataset) is captured at the moment it runs — never
assumed, never reconstructed after the fact.

```
Approved ExperimentSpecification + Approved DatasetVersion
        │
        ▼
   request_run()          researchos.execution.orchestrator
        │                 (preflight: project/approval/target/timeout/
        │                  provenance-consistency checks)
        ▼
   Run (CREATED)          researchos.db.models.Run — fully provenanced
        │                 already: specification/dataset snapshots,
        │                 environment snapshot, code provenance (or an
        │                 explicit "unavailable" reason)
        ▼
 Human Execution Approval  researchos.execution.approval
   (EXECUTION_APPROVAL:<run_id>)
        │
        ▼
   execute_run()          Run: CREATED -> QUEUED -> RUNNING
        │
        ▼
   ExecutionEngine.execute()   researchos.execution.contracts
        │                      LocalPythonExecutor (real, this phase)
        ▼
   Run: terminal (SUCCEEDED / FAILED / CANCELLED / TIMEOUT)
        │
        ▼
   ArtifactMetadata (STDOUT/STDERR references, sha256, size)
```

## 2. Architecture

```
ResearchOS Domain (researchos.execution.orchestrator / .runs / .preflight / .approval)
        │
        ▼
Execution Contract (researchos.execution.contracts — pure dataclasses + a Protocol)
        │
        ▼
Execution Engine
        │
        ├── LocalPythonExecutor    IMPLEMENTED (researchos.execution.local_executor)
        │
        ├── DockerExecutor         interface-only (ExecutionEngine Protocol), not implemented
        ├── RemoteGPUExecutor      interface-only, not implemented
        ├── SlurmExecutor          interface-only, not implemented
        └── CloudExecutor          interface-only, not implemented
```

The domain layer (`orchestrator`/`runs`/`preflight`/`approval`) never
imports `subprocess`, never knows a process is being spawned, and never
constructs a shell command — it only ever calls
`ExecutionEngine.execute(request)`. `LocalPythonExecutor` is the only
module in this phase that imports `subprocess` for actual process
execution (`researchos.execution.git_provenance` and
`researchos.execution.environment_snapshot` also import it, but only
for fixed, hardcoded, never-caller-influenced `git`/`nvidia-smi`
invocations — see §11 and §15). Future backends
(`DockerExecutor`/`RemoteGPUExecutor`/`SlurmExecutor`/`CloudExecutor`)
are named in `ExecutionBackend` (`researchos.db.models`) as the target
vocabulary and would implement the same `ExecutionEngine` `Protocol`,
but nothing beyond that vocabulary exists yet — `researchos.execution.
preflight` rejects any of them as an unsupported backend today.

This package is a **direct continuation** of the Phase 7/8A chain, not
an independent sibling: it imports `researchos.planning.orchestration`
(`require_in_project`, `require_status`), `researchos.planning.errors`'
generic reference-checking types, and
`researchos.specification.fingerprint` (`canonicalize`, `sha256_hex`,
`compute_configuration_hash`) directly rather than declaring a fourth
copy of any of them.

## 3. Run vs. Experiment

`Experiment` (Phase 3, `researchos.db.models.Experiment`) remains the
scientific *concept* — completely untouched by this phase (`git diff`
against `models.py`/`repository.py` shows zero removed lines; see §23
of the independent audit below). A `Run` (new, this phase) is one
actual execution instance of that concept:

```
Experiment "Widget Alloy Ablation"
├── Run 1  (2026-09-18, seed=1, SUCCEEDED)
├── Run 2  (2026-09-18, seed=2, FAILED — CUDA... no wait, CPU-only OOM)
└── Run 3  (2026-09-19, seed=1, re-run after a code fix, SUCCEEDED)
```

`Experiment.status`/`started_at`/`completed_at` (Phase 3's own,
pre-existing execution-tracking fields) are left exactly as they were —
Phase 8B-1 does not repurpose or write to them; a future phase may
decide how (or whether) `Experiment`-level status should roll up from
its `Run`s, but that decision is explicitly deferred, not made here.

## 4. Execution Contract

`researchos.execution.contracts` defines three pure dataclasses and one
`Protocol`, with no I/O of their own:

- **`PythonModuleTarget`** — `module: str`, `arguments: tuple[str, ...]`,
  `python_executable: Optional[str]`. There is no field capable of
  holding a shell string; this is a structural guarantee, not a
  runtime check.
- **`ExecutionRequest`** — `run_id`, `target`, `working_directory`,
  `environment` (an already-minimal, explicit mapping — never
  `os.environ`), `timeout_seconds`, `stdout_path`, `stderr_path`.
  Assembled by the orchestrator only after every
  `researchos.execution.security` check has passed.
- **`ExecutionResult`** — `status` (must be one of `RunStatus.
  {SUCCEEDED, FAILED, CANCELLED, TIMEOUT}`, enforced by
  `__post_init__`), `exit_code`, `started_at`, `finished_at`,
  `duration_seconds`, `stdout_reference`, `stderr_reference`,
  `failure_reason`, `backend`, and a free-form `metadata` dict for
  genuinely engine-specific extras the domain layer must not depend on.
- **`ExecutionEngine`** (`Protocol`) — one method,
  `execute(request) -> ExecutionResult`. `LocalPythonExecutor`
  implements it; a future `DockerExecutor` etc. would too, without the
  orchestrator changing at all.

There is deliberately no `execute(command: str)`-shaped API anywhere —
see §15 (Security Model) for why that specific shape is the thing being
avoided, not merely discouraged.

## 5. LocalPythonExecutor

`researchos.execution.local_executor.LocalPythonExecutor` runs exactly

```python
subprocess.run(
    [python_executable, "-m", module, *arguments],
    cwd=working_directory, env=environment, timeout=timeout_seconds,
    stdout=<file>, stderr=<file>, shell=False,
)
```

— never a shell string, never string concatenation of untrusted input.
`environment` always comes from
`researchos.execution.security.minimal_safe_environment`, never
`os.environ` passed straight through (see §15). stdout/stderr are
written directly to files at `request.stdout_path`/`stderr_path` (never
held only in memory, never written to a database column — see §16). It
defensively re-validates the module name and argument types at the
start of `execute()` even though the orchestrator already validated
them, so a future caller that somehow reaches this executor directly
(bypassing the orchestrator) still fails closed.

## 6. Future Adapters

`DockerExecutor`, `RemoteGPUExecutor`, `SlurmExecutor`, `CloudExecutor`
are named in `ExecutionBackend` (the column vocabulary on `Run.
execution_backend`) as the target architecture, but **none has any
implementation** — not even a stub class — in Phase 8B-1. Each would,
in a future phase, be a new module implementing
`researchos.execution.contracts.ExecutionEngine`, requiring no change
to `researchos.execution.orchestrator`, `.preflight`, `.runs`, or
`.approval`. `researchos.execution.preflight.preflight_request` rejects
any `execution_backend` other than `LOCAL_PYTHON` today with a typed
`InvalidExecutionTargetError`, so a `Run` can never be silently created
against a backend that does not actually exist yet.

## 7. Run Lifecycle

```
CREATED -> QUEUED -> RUNNING -> SUCCEEDED
                              -> FAILED
                              -> CANCELLED
                              -> TIMEOUT
```

`CREATED`, `QUEUED`, `RUNNING` are transient; `SUCCEEDED`/`FAILED`/
`CANCELLED`/`TIMEOUT` are terminal. `TIMEOUT` is kept distinct from
`FAILED` (rather than folded into it) because "the code raised/exited
non-zero" and "we killed it because it exceeded its declared timeout"
are different scientific facts a reviewer needs to be able to tell
apart at a glance, without reading `failure_reason` text — this is the
one addition beyond the spec's minimum six states, and it is load-
bearing for exactly that reason.

`researchos.execution.runs` holds the complete, hardcoded transition
table (`_ALLOWED_TRANSITIONS`) and enforces it via
`researchos.db.repository.update_run_lifecycle`'s `expected_status`
parameter — every transition is an atomic compare-and-swap: the row's
*current* status must equal what the caller expects, or a
`ConcurrencyConflictError` (translated to
`researchos.execution.errors.InvalidRunStateError`) is raised instead
of a blind overwrite. No terminal state has any outgoing edge in the
table at all, which is what makes terminal-run immutability (§17)
actually hold for every real call path through this module.

**Known, deliberate limitation:** there is no `CREATED -> CANCELLED` or
`QUEUED -> CANCELLED` edge — the Phase 8B-1 spec's own transition list
only names `RUNNING -> CANCELLED`. A `Run` a human never approves simply
stays `CREATED` forever (an orphaned but harmless, non-terminal row).
Pre-execution cancellation is left to a future phase rather than added
here without being asked for.

## 8. Execution Approval

`researchos.execution.approval` implements human execution approval
directly on top of the same `repository.create_approval_request`/
`record_approval_decision`/`get_approval_by_stage` primitives
`researchos.db.approval_dispatch.decide()` itself is built from — it is
not a second approval framework, only a second caller of the first
one's underlying primitives, using the exact same lazy
create-the-pending-row-on-first-decision pattern
`approval_dispatch._get_or_create_pending_approval` already
established.

It deliberately does **not** go through
`approval_dispatch.EntitySpec`/`decide()` the convenience wrapper
`researchos.intelligence.approval`/`researchos.planning.approval`/
`researchos.specification.approval` all use, because that wrapper
assumes an approval decision directly overwrites the entity's own
status column with one of three symmetric values. A `Run`'s `status` is
a *lifecycle*, not an approval-decision vocabulary — there is no
`RunStatus.APPROVED`, because "approved" does not replace a `Run`'s
lifecycle position, it only unlocks the `CREATED -> QUEUED` edge.
Reusing the wrapper here would require inventing a `RunStatus` value
that collides with `CREATED`'s own meaning. This is a documented,
deliberate architecture decision, not an oversight or an unexamined
duplication.

Gate identity: **`EXECUTION_APPROVAL:<run_id>`**, not
`<execution_request_id>` — there is no separate `ExecutionRequest`
entity (see §9). Human-only enforcement (`is_human_actor`, the same
Phase 4 `"agent:"`-prefix convention every other gate uses) is checked
before any database write. A specification being `APPROVED` (Phase 8A)
does **not** automatically authorize execution — `preflight_execute`
checks `approval.is_execution_approved(run_id)` completely separately
from the specification-approval check `preflight_request` already ran
at `Run`-creation time.

## 9. Why No Separate `ExecutionRequest` Entity

Considered and deliberately rejected. A dedicated `ExecutionRequest`
would be 1:1 with exactly one `Run`, created immediately before it and
consumed immediately on approval — unlike `DatasetVersion`/
`ExperimentSpecification`, which are genuinely independent, multiply-
referenced, long-lived versioned artifacts with their own lineage. The
`Run` row itself, created in `RunStatus.CREATED` with its **full**
intended provenance already captured (specification/dataset snapshots,
environment, code provenance), already *is* the execution request —
`EXECUTION_APPROVAL:<run_id>` is exactly what authorizes the one
transition (`CREATED -> QUEUED`) that lets it actually run. Adding a
separate entity here would be symmetry for its own sake, not a
materially better design — see the spec's own instruction not to add
entities merely for theoretical purity.

## 10. Preflight

`researchos.execution.preflight` implements the full checklist as two
functions:

- **`preflight_request`** (called by `orchestrator.request_run`, before
  any `Run` row exists): project exists; `Experiment` exists and is in
  the same project; `ExperimentSpecification` exists, is in the same
  project, and is `planning_status APPROVED`; `DatasetVersion` exists,
  is in the same project, and is `lifecycle_status APPROVED` (not
  merely `VALID` — a human must have signed off, not just deterministic
  validation); execution backend is `LOCAL_PYTHON`; the execution
  target passes `researchos.execution.security`'s allowlist/structural
  checks; the timeout is within the configured bounds; the
  specification's stored `configuration_hash` is recomputed and
  compared against its own `configuration` content (a
  `ProvenanceError` if they disagree — guards against a specification
  row whose hash has drifted out of band from its content).
- **`preflight_execute`** (called by `orchestrator.execute_run`,
  immediately before queueing): the `Run` is not already terminal
  (`runs.assert_not_terminal`); a decided, `APPROVED` execution
  approval exists for this exact `run_id`.

Every failure raises a specific, typed
`researchos.execution.errors`/`researchos.planning.errors` exception —
`MissingEntityError`, `CrossProjectReferenceError`,
`UpstreamNotApprovedError`, `InvalidExecutionTargetError`,
`TimeoutConfigurationError`, `ProvenanceError`,
`ExecutionNotApprovedError`, `InvalidRunStateError` — never a bare
`ValueError`.

## 11. Environment Provenance

`ExperimentSpecification.configuration` (Phase 8A) describes what a
researcher *intends*; `Run.environment_snapshot_id` (this phase)
records what actually ran — a `Run` never overwrites or is compared
against a specification-declared "expected environment," because Phase
8A's `configuration` schema is deliberately domain-agnostic and has no
such field at all. `researchos.execution.environment_snapshot.
collect_environment_info()` gathers, purely via already-running-
interpreter introspection (`platform`, `sys`, `torch.__version__`/
`torch.cuda.*` if `torch` happens to be importable and CUDA happens to
be available — **CUDA is never assumed**): OS
name/version, architecture, Python/PyTorch/torchvision/CUDA/cuDNN
versions, GPU name, and a small fixed set of package versions. GPU
driver version is the one fact collected via a fixed, hardcoded
`nvidia-smi --query-gpu=driver_version --format=csv,noheader`
subprocess call (never any caller-influenced argv), wrapped so any
failure (not installed, no GPU, timeout) yields `None` rather than
raising — a best-effort fact, not a required one. No environment
*variable* is ever collected (a fundamentally different, much narrower
surface than the OS/library version facts actually gathered).

`EnvironmentSnapshot` (`researchos.db.models`) is **content-
addressable** (`UniqueConstraint` on `environment_hash`) and
deliberately **not project-scoped** — it describes a physical/virtual
machine's software stack, a fact about the world, not about any one
project, and the same snapshot row is legitimately shared by `Run`s
across different projects (`researchos.execution.environment_snapshot.
record_environment` looks up an existing row by hash before creating a
new one). `researchos.specification.fingerprint`'s `canonicalize`/
`sha256_hex` are reused directly for `compute_environment_hash` — not a
second hashing scheme.

## 12. Code Provenance

`researchos.execution.git_provenance.collect_code_provenance(path)`
uses only fixed, hardcoded `git` argv (`git rev-parse --is-inside-work-
tree`, `git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD`, `git
status --porcelain`) via `subprocess.run(..., shell=False)` — never a
caller-influenced command, never interpretable by an LLM. If `git` is
not installed, `path` is not a Git repository, or the repository has no
commits yet, this is represented explicitly:
`CodeProvenance(available=False, unavailable_reason=<why>)` — the
commit SHA is **never fabricated**. `Run.code_commit`/`code_branch`/
`working_tree_clean` are all `NULL` in that case, and
`Run.code_provenance_unavailable_reason` explains why, so a later
reviewer never mistakes "we don't know" for "there was no code."
`orchestrator.request_run`'s `code_repository_path` parameter is
optional — when omitted, the same explicit-unavailable representation
is used (`"No repository path was supplied for this Run."`), never
silently skipped.

## 13. Dataset Provenance

Every `Run` explicitly carries the exact `dataset_version_id` it used —
`preflight_request` never infers "the latest" dataset version for an
`Experiment`, and rejects a `dataset_version_id` that does not exist,
belongs to another project, or is not `lifecycle_status APPROVED`
before any `Run` row is created. At creation time, `Run` snapshots
`dataset_version_version`, `dataset_version_status_at_execution`, and
`dataset_fingerprint` (copied from `DatasetVersion.content_fingerprint`)
— so even if that `DatasetVersion` row is later deleted (`ON DELETE SET
NULL` on the live FK) or its lifecycle status changes, this `Run`'s own
record of exactly which dataset version, and what it looked like, at
execution time survives unchanged.

## 14. Configuration Provenance

`Run.configuration_hash`/`configuration_snapshot` are copied from the
`ExperimentSpecification` at `Run`-creation time — `configuration_hash`
is reused verbatim from `researchos.specification.fingerprint.
compute_configuration_hash` (Phase 8A's own canonical-JSON + sha256
convention: `json.dumps(..., sort_keys=True, separators=(",", ":"),
default=str)` then sha256 hex), **not reimplemented**. Preflight
recomputes this hash from the specification's live `configuration` and
compares it against the specification's own stored
`configuration_hash`, raising `ProvenanceError` on any mismatch — an
integrity guard against a specification row whose two columns have
drifted out of sync (e.g. a direct, out-of-band database edit).

## 15. Security Model

The primary defense is **structural, not a blacklist**:
`PythonModuleTarget.arguments` is always passed to `subprocess` as an
argv list with `shell=False` — shell metacharacters in an argument are
inert data there, never syntax, regardless of what
`researchos.execution.security` additionally rejects. There is no
`execute(command: str)`-shaped API anywhere in this package for an LLM
(or anything else) to smuggle `"python train.py && del ..."` through.

On top of that structural guarantee, `researchos.execution.security`
enforces, all fail-closed by default:

- **Module allowlist** — `validate_module_name` requires a
  dotted-identifier-only regex match *and* an explicit, non-empty,
  operator-configured `allowed_module_prefixes` (env var
  `RESEARCHOS_EXECUTION_ALLOWED_MODULE_PREFIXES`). An **empty**
  allowlist (the default) rejects *everything* — Phase 8B-1 ships no
  real training/inference module for anything to point at, so nothing
  can execute until an operator explicitly configures one.
- **Python executable allowlist** — `validate_python_executable`
  defaults to only `sys.executable`; any other path is rejected unless
  explicitly configured.
- **Working-directory root confinement** — `validate_working_directory`
  resolves the candidate path and requires it to be `relative_to()` a
  single configured `allowed_execution_root` — rejects any `..`
  traversal or absolute-path escape, even a valid-looking one.
- **Timeout bounds** — `validate_timeout` requires an `int` within
  `[min_timeout_seconds, max_timeout_seconds]`.
- **Argument metacharacter rejection** (`&&`, `||`, `;`, `|`, `>`, `<`,
  `` ` ``, `$(`, newlines) — explicit defense-in-depth *on top of* the
  argv-list/`shell=False` primary defense, not a substitute for it; it
  exists so a future accidental switch to a shell string would trip a
  loud, explicit test failure rather than silently becoming
  exploitable.
- **Explicit-allowlist child environment** —
  `minimal_safe_environment` builds the child process's environment
  from a small fixed set of OS-required variable *names* (`PATH`,
  `SYSTEMROOT`, ...) plus whatever a caller explicitly supplies —
  **never** `os.environ` passed through wholesale — and rejects any
  caller-supplied variable whose *name* looks credential-shaped
  (`api_key`, `secret`, `password`, `token`, `credential`,
  `access_key`, `private_key` substrings), mirroring
  `researchos.specification.experiment_specifications`'s configuration-
  key convention applied to this package's own surface (environment
  variable names, not configuration JSON keys).

`researchos.execution`'s own `test_security.py` includes AST-based
static verification (mirroring `researchos.specification`'s
`test_security.py`) that no `shell=True` literal, `os.system`/
`eval`/`exec`, or direct `anthropic`/`openai` import exists anywhere in
the package, and that only `local_executor.py`/`git_provenance.py`/
`environment_snapshot.py` import `subprocess` at all.

## 16. Artifact Metadata

`ArtifactMetadata` (`researchos.db.models`) records `run_id`,
`artifact_type` (`STDOUT`/`STDERR`/`CHECKPOINT`/`MODEL`/`PLOT`/`LOG`/
`RESULT`/`OTHER` — Phase 8B-1 only ever creates `STDOUT`/`STDERR`
rows), `reference` (a filesystem path — never file bytes), `size_bytes`,
a sha256 `content_hash`, and `mime_type`. `LocalPythonExecutor` writes
stdout/stderr directly to files at `request.stdout_path`/`stderr_path`;
`researchos.execution.orchestrator._maybe_record_artifact` then hashes
and sizes each file (only if it actually exists on disk — a test-double
`ExecutionEngine` that never touches the filesystem is a legitimate,
deliberate choice for orchestration-level tests, not an error) and
records one `ArtifactMetadata` row per output. Nothing in this phase
ever stores a large binary in SQLite. `CHECKPOINT`/`MODEL`/`PLOT`/
`RESULT` rows, and the actual generation of anything to reference, are
Phase 8B-2's concern — the vocabulary exists now so a `Run` created in
this phase remains valid once that phase exists.

## 17. Project Isolation

Every persistent entity this phase adds is explicit about project
ownership: `Run.project_id`, `Run.experiment_id`,
`Run.experiment_specification_id`, `Run.dataset_version_id`, and
`ArtifactMetadata.project_id`/`run_id` are all checked at write time —
`repository.create_run` validates that `experiment_id` and (if given)
`experiment_specification_id`/`dataset_version_id` all exist **and**
belong to the caller's `project_id`, raising `NotFoundError` otherwise;
`researchos.execution.preflight`/`.orchestrator` layer that as typed
`CrossProjectReferenceError` (via
`researchos.planning.orchestration.require_in_project`, reused
directly). `EnvironmentSnapshot` is the one deliberate, documented
exception (see §11) — a content-addressable, cross-project-shared fact
about a machine, not project state.

## 18. Run Immutability

`researchos.db.repository.update_run_lifecycle` (and every other
repository setter) stays a small, uniform, entity-agnostic persistence
primitive with no immutability opinion of its own — exactly the same
architectural boundary Phase 7/8A documented for
`ContributionCandidate`/`DatasetVersion`/`ExperimentSpecification`. The
actual protection is service-level: `researchos.execution.runs`'s
transition table (`_ALLOWED_TRANSITIONS`) has **zero outgoing edges**
from any terminal status, so every real call path through `queue_run`/
`start_run`/`complete_run` refuses to move a terminal `Run` anywhere.
`researchos.execution.runs.assert_not_terminal` is the explicit guard
`preflight_execute` calls before ever attempting to re-queue an
existing `Run`. This is a documented service-level boundary, not an
unbreakable database-level one — a caller that bypasses this module and
calls `repository.update_run_lifecycle` directly with a fabricated
`expected_status` is not stopped by a trigger. No such call path exists
anywhere in `researchos.execution` itself.

## 19. Reproducibility Model

A `Run` is **not** a versioned artifact the way `DatasetVersion`/
`ExperimentSpecification` are (no `supersedes_id`, no `version` column)
— it is immutable once terminal, full stop. Re-running the same
experiment always means calling `request_run()` again, which creates a
brand-new `Run` row with its own independently-captured provenance;
there is no "Run v2" semantics anywhere in this phase.
`TERMINAL_STATUSES`/`assert_not_terminal` together are the idempotency
guard the spec asks for: an already-terminal `Run` can never be
silently re-executed in place — accidental request duplication at most
produces a second, independent, fully-provenanced `Run` (via a second
`request_run()` call), never a corrupted or overwritten first one.
Seeds are recorded exactly as given (`Run.seed`) and never fabricated
when absent — `seed=None` stays `None`, not a randomly-generated value.

## 20. Phase 8B-1 Boundaries (What Is *Not* Here)

Implemented: `Run` domain model + lifecycle; the execution contract
(`ExecutionRequest`/`ExecutionResult`/`ExecutionEngine`);
`LocalPythonExecutor`; `EnvironmentSnapshot`; code/configuration/
dataset provenance; execution approval; preflight validation; timeout
and failure handling; stdout/stderr reference + `ArtifactMetadata`
foundations; the security boundary; the repository layer; the
`b03b320a103c` migration; 112 tests; this document.

**Not implemented — explicitly deferred to Phase 8B-2 or later:** real
ML training or inference; YOLO/FastViT/RetinaNet or any other named
model's actual execution; CUDA/GPU-accelerated training; model
checkpoint generation; metric calculation or `ExperimentResult`
population from a `Run`; hyperparameter optimization; statistical
analysis or plotting; `DockerExecutor`/`RemoteGPUExecutor`/
`SlurmExecutor`/`CloudExecutor` real implementations (interfaces only);
`CREATED`/`QUEUED` cancellation edges; any automatic transition of
Phase 4's workflow stage graph (see §21); any link from `Run` back to
`Experiment.status`/`started_at`/`completed_at` (Phase 3's own fields
are untouched).

## 21. Workflow Boundary

Phase 4's `researchos.workflow` state machine (`WorkflowStage`,
`STAGE_11_EXPERIMENTS` included) is **not modified** and is never
automatically transitioned by anything in `researchos.execution` —
`Run` creation, approval, or completion never calls into
`researchos.workflow.service`. This is a deliberate scope boundary, not
an oversight: wiring `Run` completion into stage transitions is real
design work (does one `Run` completing advance a stage? all `Run`s for
an `Experiment`? does a `FAILED` `Run` block advancement?) that Phase
8B-1 explicitly leaves for a later phase to decide with its own design
review, rather than answering implicitly as a side effect of this one.

## Testing

`tests/execution/` (112 tests, `pytest tests/execution -q`). Every test
either uses `FakeExecutionEngine` (`tests/execution/fakes.py`, never
touches a real process) or `LocalPythonExecutor` against
`tests/execution/_local_target.py` — a tiny, deterministic,
test-only module (never project source, never anything that trains or
touches a real dataset) that prints a fixed marker, exits with a fixed
code, or sleeps a fixed duration, selected only via `argparse` flags,
never shell syntax. No test in this suite makes, or could make, a real
LLM or scholarly API call, and no test creates a database file under
`data/` or any large artifact.

| File | Covers |
|---|---|
| `test_run_model.py` | Creation, full lifecycle table (CREATED→QUEUED→RUNNING→each terminal), invalid transitions, terminal immutability, optimistic-concurrency conflicts, failed-run record completeness |
| `test_project_isolation.py` | Cross-project specification/experiment/dataset-version rejection, at both the repository and orchestrator layers |
| `test_approval.py` | Human-only, agent rejected, unapproved execution rejected, approved execution proceeds, already-decided/changes-requested semantics |
| `test_provenance.py` | Specification id/version/status, dataset version/fingerprint, configuration hash/snapshot, real git commit/branch/dirty-tree, git-unavailable explicit reason, environment snapshot dedup, seed never fabricated |
| `test_fingerprints.py` | Environment-hash determinism and key-order independence; confirms `compute_configuration_hash` is reused, not reimplemented |
| `test_preflight.py` | Missing entity, unapproved specification, dataset only `VALID` not `APPROVED`, unsupported backend, disallowed module, empty-allowlist fail-closed, invalid timeout, configuration-hash mismatch |
| `test_security.py` | Shell-injection module/argument attempts, path traversal, arbitrary executable, environment-variable leakage, AST static checks |
| `test_execution_contract.py` | `FakeExecutionEngine`, `LocalPythonExecutor` real success/failure/timeout, `ExecutionResult` terminal-status enforcement |
| `test_failure_handling.py` | End-to-end failure/timeout persistence through the orchestrator, `ArtifactMetadata` recorded for real captured output |
| `test_git_provenance.py` | Clean repo, dirty repo, non-repo directory, repo with no commits, nonexistent path — all against real temporary Git repositories |
| `test_migration.py` | Upgrade/downgrade round-trip, CHECK constraints, FKs, populated-Phase-8A-database upgrade preserving real rows, no stray temp tables |

Full-suite regression after this phase: **705/705 passing** (593
pre-existing + 112 new), including the entire Phase 4/5/6/7/8A suite
unmodified in behavior.

Run with:
```powershell
<repository-root>\.venv\Scripts\python.exe -m pytest tests\execution -v
```

## Migration

`migrations/versions/b03b320a103c_execution_foundation.py` adds three
new tables (`environment_snapshots`, `runs`, `artifact_metadata`) —
every new column lives on a brand-new table, so (exactly like
`984437859de2` before it) there is nothing to backfill and no NOT-NULL-
without-server_default risk on an existing table. `Experiment`/
`ExperimentResult` (Phase 3) and `DatasetVersion`/
`ExperimentSpecification` (Phase 8A) are completely untouched — no
column added, no CHECK constraint widened. Verified directly (not
assumed): fresh upgrade, `alembic check` (zero drift), downgrade→
upgrade round-trip, and an upgrade against a database seeded with real
pre-existing Phase 8A rows, confirming every one survives unchanged.

## Limitations

- **No real training/inference module ships with this phase** — the
  execution module allowlist is empty by default (fail-closed); nothing
  can execute until an operator explicitly configures
  `RESEARCHOS_EXECUTION_ALLOWED_MODULE_PREFIXES`.
- **No pre-`RUNNING` cancellation** — see §7's "Known, deliberate
  limitation."
- **No `Experiment`-level status rollup from its `Run`s** — deferred;
  `Experiment.status` stays exactly what Phase 3 left it.
- **`GPU driver version` collection depends on `nvidia-smi` being on
  `PATH`** — best-effort only; `None` on any CPU-only or non-NVIDIA
  machine.

## Future Work (Phase 8B-2 and beyond)

Real `ExecutionEngine` implementations for Docker/remote-GPU/Slurm/
cloud; actual ML training/inference against a `Run`'s captured
provenance; metric collection into `ExperimentResult` (or a new,
`Run`-scoped results table); checkpoint/model/plot artifact generation
and the corresponding `ArtifactMetadata` rows; hyperparameter
optimization; statistical analysis; deciding how (or whether) `Run`
completion should interact with Phase 4's workflow stage graph.
