"""End-to-end failure handling through the orchestrator: a failed/timed-
out run is a valid scientific record — status, exit code, failure
reason, stdout/stderr references, and provenance all survive, and
ArtifactMetadata rows are recorded for the captured output files."""

from __future__ import annotations

from pathlib import Path

import pytest

from researchos.db import repository
from researchos.db.models import ArtifactType, RunStatus
from researchos.execution import approval as approval_module
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.errors import MalformedMetricsManifestError
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.orchestrator import execute_run, request_run


def _requested_and_approved(session_factory, project_id, experiment_id, spec_id, dataset_version_id, config, *, mode, extra_args=(), timeout_seconds=10):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", mode, *extra_args))
    run = request_run(
        project_id, experiment_id, spec_id, dataset_version_id, actor="agent:orchestrator", target=target,
        timeout_seconds=timeout_seconds, config=config, session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)
    return run.id


def test_real_failure_is_persisted_with_full_record(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run_id = _requested_and_approved(
        session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        execution_config, mode="fail", extra_args=("--exit-code", "42"),
    )
    result = execute_run(
        run_id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )
    assert result.status.value == "failed"
    assert result.exit_code == 42
    assert result.failure_reason is not None
    assert result.stdout_reference is not None
    assert result.stderr_reference is not None
    assert result.experiment_specification_id == approved_experiment_specification_id
    assert result.dataset_version_id == approved_dataset_version_id
    assert result.started_at is not None and result.finished_at is not None


def test_timeout_is_persisted_as_terminal_timeout_not_silent_success(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run_id = _requested_and_approved(
        session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        execution_config, mode="sleep", extra_args=("--sleep-seconds", "5"), timeout_seconds=1,
    )
    result = execute_run(
        run_id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )
    assert result.status.value == "timeout"
    assert result.exit_code is None
    assert "timeout" in result.failure_reason.lower()


def test_artifact_metadata_recorded_for_captured_stdout_and_stderr(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run_id = _requested_and_approved(
        session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        execution_config, mode="fail", extra_args=("--exit-code", "5"),
    )
    execute_run(
        run_id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )
    s = session_factory()
    try:
        artifacts = repository.list_artifact_metadata(s, project_id, run_id=run_id)
    finally:
        s.close()
    types = {a.artifact_type for a in artifacts}
    assert ArtifactType.STDOUT in types
    assert ArtifactType.STDERR in types
    for artifact in artifacts:
        assert artifact.content_hash is not None and len(artifact.content_hash) == 64
        assert artifact.size_bytes is not None and artifact.size_bytes >= 0


def test_successful_run_also_records_artifacts(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run_id = _requested_and_approved(
        session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        execution_config, mode="success",
    )
    execute_run(
        run_id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )
    s = session_factory()
    try:
        artifacts = repository.list_artifact_metadata(s, project_id, run_id=run_id)
    finally:
        s.close()
    # stdout + stderr + the generated result manifest (Phase 8B-2) — no
    # metrics.json was written by this run, so no METRIC_REPORT artifact.
    types = {a.artifact_type for a in artifacts}
    assert types == {ArtifactType.STDOUT, ArtifactType.STDERR, ArtifactType.RESULT_MANIFEST}
    assert len(artifacts) == 3


def test_process_launch_failure_persisted_as_failed_never_stuck_running(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    # A python_executable that does not exist on disk — a genuine
    # process launch failure (FileNotFoundError from subprocess.run),
    # not a bad exit code. It must also be in the allowlist so
    # preflight/security validation (a purely structural check — it
    # never verifies the path actually exists) lets the request through
    # and the failure genuinely comes from the OS at launch time.
    fake_python = r"C:\definitely\not\a\real\python.exe"
    broken_config = execution_config.__class__(
        allowed_module_prefixes=execution_config.allowed_module_prefixes,
        allowed_python_executables=(fake_python,),
        allowed_execution_root=execution_config.allowed_execution_root,
    )
    target = PythonModuleTarget(
        module="tests.execution._local_target", arguments=("--mode", "success"), python_executable=fake_python,
    )
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=broken_config,
        session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)

    result = execute_run(
        run.id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=broken_config,
        session_factory=session_factory,
    )
    assert result.status == RunStatus.FAILED
    assert result.exit_code is None
    assert "launch" in result.failure_reason.lower()


def test_malformed_metrics_manifest_raises_but_run_stays_terminal_and_accurate(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run_id = _requested_and_approved(
        session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        execution_config, mode="metrics_bad",
    )
    with pytest.raises(MalformedMetricsManifestError):
        execute_run(
            run_id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
            extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
        )
    # The Run itself still reached a correct, accurate terminal state —
    # the malformed manifest never corrupted or blocked its own record.
    s = session_factory()
    try:
        run = repository.get_run(s, run_id)
    finally:
        s.close()
    assert run.status == RunStatus.SUCCEEDED
    assert run.exit_code == 0
    # And no metrics were partially ingested from the malformed manifest.
    s = session_factory()
    try:
        stored_metrics = repository.list_metrics(s, project_id, run_id=run_id)
    finally:
        s.close()
    assert stored_metrics == []
