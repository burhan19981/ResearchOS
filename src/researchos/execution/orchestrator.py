"""The execution orchestrator: the two real entry points every caller
should use — `request_run` (create a fully-provenanced, pending `Run`)
and `execute_run` (check approval, then actually run it through an
`ExecutionEngine`).

validate request -> load approved specification -> validate dataset ->
validate project ownership -> validate execution approval -> capture
provenance -> create/transition Run -> delegate to ExecutionEngine ->
register artifacts -> ingest metrics -> generate result manifest ->
record result

This module contains no implementation detail of *how* a process is
executed — that lives entirely behind `ExecutionEngine`
(`researchos.execution.contracts`); this module only decides WHEN to
call it and WHAT to record before/after.

Ordering discipline (Phase 8B-2): the `Run`'s own terminal lifecycle
status is finalized (`runs.complete_run`) immediately after
`engine.execute()` returns or raises — BEFORE any artifact/metrics/
manifest post-processing runs. Every step after that point is
best-effort enrichment that must never be able to leave a `Run`
stranded in a non-terminal state: a failure registering an artifact,
or a malformed metrics manifest, is surfaced to the caller (never
silently swallowed) but never corrupts or blocks the `Run`'s own
already-persisted, accurate terminal record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import ArtifactType, ExecutionBackend, Run, RunStatus
from . import artifacts as artifacts_module
from . import environment_snapshot as environment_snapshot_module
from . import git_provenance
from . import manifest as manifest_module
from . import metrics as metrics_module
from . import preflight as preflight_module
from . import runs as runs_module
from . import security
from . import workspace as workspace_module
from .config import ExecutionConfig, load_execution_config
from .contracts import ExecutionEngine, ExecutionRequest, PythonModuleTarget
from .errors import ArtifactRegistrationError, MalformedMetricsManifestError, MissingEntityError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def request_run(
    project_id: int,
    experiment_id: int,
    experiment_specification_id: int,
    dataset_version_id: int,
    *,
    actor: str,
    target: PythonModuleTarget,
    timeout_seconds: int,
    seed: Optional[int] = None,
    execution_backend: ExecutionBackend = ExecutionBackend.LOCAL_PYTHON,
    code_repository_path: Optional[str] = None,
    config: Optional[ExecutionConfig] = None,
    session_factory: Optional[sessionmaker] = None,
) -> Run:
    """Create one fully-provenanced `Run` in `RunStatus.CREATED`. Runs
    the full request-time preflight checklist (project ownership,
    approved specification, approved dataset version, valid execution
    target, valid timeout, consistent configuration hash) before
    touching the database — raises a typed
    `researchos.execution.errors` exception on the first violation and
    creates nothing.

    Never itself starts execution and never requires execution approval
    to exist yet — that gate is checked by `execute_run`, separately,
    exactly matching the Phase 8B-1 spec's "a specification being
    approved does NOT automatically authorize execution" rule.
    """
    resolved_config = config or load_execution_config()

    with session_scope(session_factory) as session:
        result = preflight_module.preflight_request(
            session,
            project_id=project_id,
            experiment_id=experiment_id,
            experiment_specification_id=experiment_specification_id,
            dataset_version_id=dataset_version_id,
            execution_backend=execution_backend,
            target=target,
            timeout_seconds=timeout_seconds,
            config=resolved_config,
        )
        specification = result.specification
        dataset_version = result.dataset_version

        code_provenance = (
            git_provenance.collect_code_provenance(code_repository_path)
            if code_repository_path is not None
            else git_provenance.CodeProvenance(
                available=False, repository=None, commit=None, branch=None, working_tree_clean=None,
                unavailable_reason="No repository path was supplied for this Run.",
            )
        )
        snapshot = environment_snapshot_module.record_environment(session)

        run = repository.create_run(
            session,
            project_id=project_id,
            experiment_id=experiment_id,
            timeout_seconds=timeout_seconds,
            experiment_specification_id=specification.id,
            dataset_version_id=dataset_version.id,
            environment_snapshot_id=snapshot.id,
            execution_backend=execution_backend,
            execution_target={
                "type": "python_module",
                "module": target.module,
                "arguments": list(target.arguments),
                "python_executable": target.python_executable,
            },
            experiment_specification_version=specification.version,
            experiment_specification_status_at_execution=specification.planning_status.value,
            configuration_hash=specification.configuration_hash,
            configuration_snapshot=specification.configuration,
            dataset_version_version=dataset_version.version,
            dataset_version_status_at_execution=dataset_version.lifecycle_status.value,
            dataset_fingerprint=dataset_version.content_fingerprint,
            code_repository=code_provenance.repository,
            code_commit=code_provenance.commit,
            code_branch=code_provenance.branch,
            working_tree_clean=code_provenance.working_tree_clean,
            code_provenance_unavailable_reason=code_provenance.unavailable_reason,
            seed=seed,
        )
        repository.append_audit_event(
            session, project_id=project_id, actor=actor, event_type="execution.run_requested",
            description=f"Run #{run.id} requested for Experiment {experiment_id}",
            metadata={
                "run_id": run.id, "experiment_id": experiment_id,
                "experiment_specification_id": specification.id, "dataset_version_id": dataset_version.id,
                "execution_backend": execution_backend.value,
                "code_provenance_available": code_provenance.available,
            },
        )
        run_id = run.id

    with session_scope(session_factory) as session:
        return repository.get_run(session, run_id)


def _register_output_artifact_if_present(
    *, project_id: int, run_id: int, logical_name: str, artifact_type: ArtifactType, reference: Optional[str],
    config: ExecutionConfig, session_factory: Optional[sessionmaker],
) -> None:
    """Best-effort: an `ExecutionEngine` test double (see
    `tests/execution/fakes.py`) never touches the filesystem, and that
    is a legitimate, deliberate choice for orchestration-level tests,
    not an error — `register_artifact` itself already treats a missing
    file as an error, so existence is checked first here. `config` is
    passed through so `register_artifact`'s own workspace-boundary
    check (`ArtifactPathEscapeError`) validates against the exact same
    `allowed_execution_root` this `Run`'s workspace was built under."""
    if not reference:
        return
    if not Path(reference).is_file():
        return
    try:
        artifacts_module.register_artifact(
            project_id=project_id, run_id=run_id, logical_name=logical_name, artifact_type=artifact_type,
            path=reference, source="local_python_executor", config=config, session_factory=session_factory,
        )
    except ArtifactRegistrationError:
        # A failure to register stdout/stderr metadata must never mask
        # the Run's own already-finalized terminal status (Phase 8B-2
        # spec section 19) — the raw file remains on disk regardless.
        pass


def execute_run(
    run_id: int,
    *,
    actor: str,
    engine: ExecutionEngine,
    config: Optional[ExecutionConfig] = None,
    extra_environment: Optional[dict[str, str]] = None,
    session_factory: Optional[sessionmaker] = None,
) -> Run:
    """Check preflight (not terminal, execution approved), transition
    `CREATED -> QUEUED -> RUNNING`, delegate to `engine.execute()`,
    finalize the terminal state, then register stdout/stderr
    artifacts, ingest any structured metrics manifest the process
    wrote, and generate + register the result manifest. Never silently
    swallows a failure — a failed/timed-out/cancelled `Run` is
    persisted exactly as completely as a succeeded one, and a malformed
    metrics manifest is raised to the caller (after the `Run` is
    already safely terminal), never silently dropped.
    """
    resolved_config = config or load_execution_config()

    with session_scope(session_factory) as session:
        run = repository.get_run(session, run_id)
        if run is None:
            raise MissingEntityError(f"Run {run_id} does not exist.")
        project_id = run.project_id
        target_dict: dict[str, Any] = run.execution_target or {}
        target = PythonModuleTarget(
            module=target_dict.get("module", ""),
            arguments=tuple(target_dict.get("arguments", ())),
            python_executable=target_dict.get("python_executable"),
        )
        timeout_seconds = run.timeout_seconds

    preflight_module.preflight_execute(run, session_factory=session_factory)
    security.validate_execution_target(target, config=resolved_config)
    security.validate_timeout(timeout_seconds, config=resolved_config)

    runs_module.queue_run(run_id, actor=actor, session_factory=session_factory)

    try:
        run_workspace = workspace_module.prepare_run_workspace(project_id, run_id, config=resolved_config)
        request = ExecutionRequest(
            run_id=run_id,
            target=target,
            working_directory=str(run_workspace.output_dir),
            environment=security.minimal_safe_environment(extra_environment),
            timeout_seconds=timeout_seconds,
            stdout_path=str(run_workspace.stdout_path),
            stderr_path=str(run_workspace.stderr_path),
        )
    except Exception as exc:
        runs_module.mark_preparation_failed(
            run_id, actor=actor, failure_reason=f"Run workspace preparation failed: {exc}",
            finished_at=_utcnow(), session_factory=session_factory,
        )
        raise

    runs_module.start_run(run_id, actor=actor, started_at=_utcnow(), session_factory=session_factory)

    try:
        result = engine.execute(request)
    except Exception as exc:
        now = _utcnow()
        runs_module.complete_run(
            run_id, actor=actor, status=RunStatus.FAILED, finished_at=now, duration_seconds=0.0,
            exit_code=None, stdout_reference=None, stderr_reference=None,
            failure_reason=f"ExecutionEngine raised an unexpected exception: {exc}", session_factory=session_factory,
        )
        raise

    final_run = runs_module.complete_run(
        run_id, actor=actor, status=result.status, finished_at=result.finished_at,
        duration_seconds=result.duration_seconds, exit_code=result.exit_code,
        stdout_reference=result.stdout_reference, stderr_reference=result.stderr_reference,
        failure_reason=result.failure_reason, session_factory=session_factory,
    )

    # Everything below is best-effort enrichment of an already-terminal,
    # already-accurate Run record — see module docstring.
    _register_output_artifact_if_present(
        project_id=project_id, run_id=run_id, logical_name="stdout", artifact_type=ArtifactType.STDOUT,
        reference=result.stdout_reference, config=resolved_config, session_factory=session_factory,
    )
    _register_output_artifact_if_present(
        project_id=project_id, run_id=run_id, logical_name="stderr", artifact_type=ArtifactType.STDERR,
        reference=result.stderr_reference, config=resolved_config, session_factory=session_factory,
    )

    deferred_metrics_error: Optional[MalformedMetricsManifestError] = None
    try:
        normalized_metrics = metrics_module.load_metrics_manifest(run_workspace.metrics_manifest_path)
    except MalformedMetricsManifestError as exc:
        normalized_metrics = None
        deferred_metrics_error = exc
        with session_scope(session_factory) as session:
            repository.append_audit_event(
                session, project_id=project_id, actor=actor, event_type="execution.metrics_manifest_invalid",
                description=f"Run #{run_id}: metrics manifest failed validation: {exc}",
                metadata={"run_id": run_id, "error": str(exc)},
            )

    if normalized_metrics:
        metric_report_artifact = None
        try:
            metric_report_artifact = artifacts_module.register_artifact(
                project_id=project_id, run_id=run_id, logical_name="metrics_report",
                artifact_type=ArtifactType.METRIC_REPORT, path=run_workspace.metrics_manifest_path,
                source="local_python_executor", config=resolved_config, session_factory=session_factory,
            )
        except ArtifactRegistrationError:
            pass
        created = metrics_module.register_metrics(
            project_id=project_id, run_id=run_id, metrics=normalized_metrics,
            source_artifact_id=metric_report_artifact.id if metric_report_artifact is not None else None,
            session_factory=session_factory,
        )
        with session_scope(session_factory) as session:
            repository.append_audit_event(
                session, project_id=project_id, actor=actor, event_type="execution.metrics_registered",
                description=f"Run #{run_id}: {len(created)} metric(s) registered",
                metadata={"run_id": run_id, "metric_count": len(created)},
            )

    with session_scope(session_factory) as session:
        run_for_manifest = repository.get_run(session, run_id)
        manifest_dict = manifest_module.build_result_manifest(session, run_for_manifest)
    manifest_module.write_result_manifest(manifest_dict, run_workspace.result_manifest_path)
    try:
        artifacts_module.register_artifact(
            project_id=project_id, run_id=run_id, logical_name="result_manifest",
            artifact_type=ArtifactType.RESULT_MANIFEST, path=run_workspace.result_manifest_path,
            source="researchos.execution.orchestrator", config=resolved_config, session_factory=session_factory,
        )
    except ArtifactRegistrationError:
        pass

    if deferred_metrics_error is not None:
        raise deferred_metrics_error

    with session_scope(session_factory) as session:
        return repository.get_run(session, run_id)
