"""Provenance: specification id/version, dataset version/fingerprint,
configuration hash, code commit/branch/dirty state, environment
snapshot — all captured at request_run() time, never inferred later."""

from __future__ import annotations

import subprocess

import pytest

from researchos.db import repository
from researchos.execution import approval as approval_module
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.orchestrator import execute_run, request_run
from tests.execution.fakes import FakeExecutionEngine


def _make_git_repo(tmp_path):
    repo = tmp_path / "coderepo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


def test_run_captures_specification_and_dataset_version_provenance(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    s = session_factory()
    try:
        spec = repository.get_experiment_specification(s, approved_experiment_specification_id)
        dataset_version = repository.get_dataset_version(s, approved_dataset_version_id)
    finally:
        s.close()

    assert run.experiment_specification_id == approved_experiment_specification_id
    assert run.experiment_specification_version == spec.version
    assert run.experiment_specification_status_at_execution == spec.planning_status.value
    assert run.configuration_hash == spec.configuration_hash
    assert run.configuration_snapshot == spec.configuration

    assert run.dataset_version_id == approved_dataset_version_id
    assert run.dataset_version_version == dataset_version.version
    assert run.dataset_version_status_at_execution == dataset_version.lifecycle_status.value
    assert run.dataset_fingerprint == dataset_version.content_fingerprint


def test_run_without_repository_path_records_explicit_unavailable_reason(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    assert run.code_commit is None
    assert run.code_provenance_unavailable_reason is not None
    assert run.working_tree_clean is None


def test_run_records_real_git_commit_branch_and_clean_tree(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config, tmp_path
):
    repo = _make_git_repo(tmp_path)
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        code_repository_path=str(repo), session_factory=session_factory,
    )
    assert run.code_commit is not None and len(run.code_commit) == 40
    assert run.code_branch is not None
    assert run.working_tree_clean is True
    assert run.code_provenance_unavailable_reason is None


def test_run_records_dirty_working_tree(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config, tmp_path
):
    repo = _make_git_repo(tmp_path)
    (repo / "file.txt").write_text("modified, uncommitted")
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        code_repository_path=str(repo), session_factory=session_factory,
    )
    assert run.working_tree_clean is False


def test_run_captures_an_environment_snapshot(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    assert run.environment_snapshot_id is not None
    s = session_factory()
    try:
        snapshot = repository.get_environment_snapshot(s, run.environment_snapshot_id)
        assert snapshot is not None
        assert snapshot.python_version is not None
    finally:
        s.close()


def test_two_runs_on_same_machine_share_one_environment_snapshot(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run_a = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    run_b = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    assert run_a.environment_snapshot_id == run_b.environment_snapshot_id


def test_seed_recorded_exactly_when_provided_never_fabricated(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run_no_seed = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    assert run_no_seed.seed is None

    run_seeded = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, seed=1234, config=execution_config,
        session_factory=session_factory,
    )
    assert run_seeded.seed == 1234
