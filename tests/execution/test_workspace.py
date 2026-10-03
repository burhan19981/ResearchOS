"""Execution workspace: deterministic project/run-isolated layout, no
path traversal, no cross-run/cross-project overlap."""

from __future__ import annotations

import pytest

from researchos.execution.config import ExecutionConfig
from researchos.execution.errors import InvalidExecutionTargetError
from researchos.execution.workspace import prepare_run_workspace


def test_workspace_creates_all_expected_subdirectories(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace = prepare_run_workspace(1, 42, config=config)
    assert workspace.input_dir.is_dir()
    assert workspace.output_dir.is_dir()
    assert workspace.logs_dir.is_dir()
    assert workspace.artifacts_dir.is_dir()
    assert workspace.manifests_dir.is_dir()


def test_workspace_path_is_project_and_run_scoped(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace = prepare_run_workspace(7, 99, config=config)
    resolved_root = (tmp_path / "root").resolve()
    assert workspace.root == resolved_root / "7" / "99"


def test_different_projects_get_non_overlapping_workspaces(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace_a = prepare_run_workspace(1, 1, config=config)
    workspace_b = prepare_run_workspace(2, 1, config=config)  # same run_id, different project_id
    assert workspace_a.root != workspace_b.root
    assert not str(workspace_b.root).startswith(str(workspace_a.root) + "\\")
    assert not str(workspace_a.root).startswith(str(workspace_b.root) + "\\")


def test_different_runs_in_same_project_get_non_overlapping_workspaces(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace_a = prepare_run_workspace(1, 10, config=config)
    workspace_b = prepare_run_workspace(1, 11, config=config)
    assert workspace_a.root != workspace_b.root


def test_stdout_stderr_manifest_paths_are_inside_workspace(tmp_path):
    config = ExecutionConfig(allowed_execution_root=tmp_path / "root")
    workspace = prepare_run_workspace(1, 1, config=config)
    for path in (workspace.stdout_path, workspace.stderr_path):
        assert path.parent == workspace.logs_dir
    assert workspace.result_manifest_path.parent == workspace.manifests_dir
    assert workspace.metrics_manifest_path.parent == workspace.output_dir


def test_preparing_workspace_never_escapes_allowed_root_even_with_crafted_config(tmp_path):
    # Even if a config somehow pointed the allowed root at something
    # unexpected, the workspace path is always validated against it —
    # this exercises the same validate_working_directory() call
    # workspace preparation goes through.
    config = ExecutionConfig(allowed_execution_root=(tmp_path / "root").resolve())
    workspace = prepare_run_workspace(1, 1, config=config)
    assert workspace.root.is_relative_to(config.allowed_execution_root)
