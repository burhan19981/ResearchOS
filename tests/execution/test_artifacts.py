"""Artifact registration: create-only, streaming-hashed, never
overwritten; missing-file and cross-project rejection; and the
workspace-boundary enforcement `register_artifact` itself performs
(path traversal, absolute paths outside the workspace, cross-project/
cross-run paths, symlink escape) — never relying solely on a
well-behaved caller."""

from __future__ import annotations

import os

import pytest

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import ArtifactType, ExecutionBackend
from researchos.execution.artifacts import register_artifact
from researchos.execution.config import ExecutionConfig
from researchos.execution.errors import ArtifactPathEscapeError, DuplicateArtifactError, MissingArtifactFileError
from researchos.execution.workspace import prepare_run_workspace


def _make_run(session_factory, project_id, experiment_id):
    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        s.commit()
        return run.id
    finally:
        s.close()


def _workspace_file(config, project_id, run_id, name, content="content"):
    """Create a real file INSIDE this run's authorized workspace and
    return its path — the only kind of path `register_artifact` now
    accepts."""
    workspace = prepare_run_workspace(project_id, run_id, config=config)
    path = workspace.output_dir / name
    path.write_text(content)
    return path


def test_register_artifact_records_hash_size_and_reference(session_factory, project_id, experiment_id, execution_config):
    run_id = _make_run(session_factory, project_id, experiment_id)
    path = _workspace_file(execution_config, project_id, run_id, "output.txt", "some output")

    artifact = register_artifact(
        project_id=project_id, run_id=run_id, logical_name="output", artifact_type=ArtifactType.LOG,
        path=path, config=execution_config, session_factory=session_factory,
    )
    assert artifact.logical_name == "output"
    assert artifact.artifact_type == ArtifactType.LOG
    assert artifact.reference == str(path.resolve())
    assert artifact.size_bytes == len("some output")
    assert len(artifact.content_hash) == 64


def test_register_artifact_missing_file_raises(session_factory, project_id, experiment_id, execution_config):
    run_id = _make_run(session_factory, project_id, experiment_id)
    workspace = prepare_run_workspace(project_id, run_id, config=execution_config)
    with pytest.raises(MissingArtifactFileError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="ghost", artifact_type=ArtifactType.LOG,
            path=workspace.output_dir / "does_not_exist.txt", config=execution_config, session_factory=session_factory,
        )


def test_duplicate_logical_name_rejected(session_factory, project_id, experiment_id, execution_config):
    run_id = _make_run(session_factory, project_id, experiment_id)
    path = _workspace_file(execution_config, project_id, run_id, "a.txt", "a")
    register_artifact(
        project_id=project_id, run_id=run_id, logical_name="same_name", artifact_type=ArtifactType.LOG,
        path=path, config=execution_config, session_factory=session_factory,
    )
    with pytest.raises(DuplicateArtifactError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="same_name", artifact_type=ArtifactType.OTHER,
            path=path, config=execution_config, session_factory=session_factory,
        )
    s = session_factory()
    try:
        artifacts = repository.list_artifact_metadata(s, project_id, run_id=run_id)
    finally:
        s.close()
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == ArtifactType.LOG


def test_same_logical_name_on_different_runs_is_allowed(session_factory, project_id, experiment_id, execution_config):
    run_a = _make_run(session_factory, project_id, experiment_id)
    run_b = _make_run(session_factory, project_id, experiment_id)
    path_a = _workspace_file(execution_config, project_id, run_a, "shared_name.txt", "content")
    path_b = _workspace_file(execution_config, project_id, run_b, "shared_name.txt", "content")

    register_artifact(
        project_id=project_id, run_id=run_a, logical_name="stdout", artifact_type=ArtifactType.STDOUT,
        path=path_a, config=execution_config, session_factory=session_factory,
    )
    # Must not raise — logical_name uniqueness is scoped per-run, not global.
    register_artifact(
        project_id=project_id, run_id=run_b, logical_name="stdout", artifact_type=ArtifactType.STDOUT,
        path=path_b, config=execution_config, session_factory=session_factory,
    )


def test_registered_artifact_metadata_is_immutable_no_update_function_exists():
    assert not hasattr(repository, "update_artifact_metadata")


def test_register_artifact_rejects_cross_project_run(
    session_factory, project_id, second_project_id, experiment_id, execution_config
):
    """`run_id` genuinely belongs to `project_id`, but the caller
    (wrongly) claims `second_project_id`, using a path that is
    genuinely inside *second_project_id's own* workspace subtree — so
    the path-boundary check alone would not catch this; the
    project-ownership check inside `repository.create_artifact_metadata`
    is what rejects it, proving the two checks are independent layers."""
    run_id = _make_run(session_factory, project_id, experiment_id)
    path = _workspace_file(execution_config, second_project_id, run_id, "x.txt", "x")

    with pytest.raises(NotFoundError):
        register_artifact(
            project_id=second_project_id, run_id=run_id, logical_name="x", artifact_type=ArtifactType.LOG,
            path=path, config=execution_config, session_factory=session_factory,
        )


# ===========================================================================
# Workspace-boundary enforcement (register_artifact's own invariant —
# never relying solely on the orchestrator having already validated).
# ===========================================================================


def test_register_artifact_rejects_relative_traversal_out_of_workspace(
    session_factory, project_id, experiment_id, execution_config
):
    run_id = _make_run(session_factory, project_id, experiment_id)
    workspace = prepare_run_workspace(project_id, run_id, config=execution_config)
    # A file that genuinely exists, but only reachable by walking "../.."
    # out of the authorized run workspace back up to the shared root.
    escape_target = execution_config.allowed_execution_root / "escaped.txt"
    escape_target.write_text("should not be registrable")
    traversal_path = workspace.output_dir / ".." / ".." / ".." / "escaped.txt"

    with pytest.raises(ArtifactPathEscapeError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="escaped", artifact_type=ArtifactType.LOG,
            path=traversal_path, config=execution_config, session_factory=session_factory,
        )
    # Nothing was registered.
    s = session_factory()
    try:
        assert repository.list_artifact_metadata(s, project_id, run_id=run_id) == []
    finally:
        s.close()


def test_register_artifact_rejects_absolute_path_outside_workspace(
    session_factory, project_id, experiment_id, execution_config, tmp_path
):
    run_id = _make_run(session_factory, project_id, experiment_id)
    outside_dir = tmp_path / "entirely_unrelated_directory"
    outside_dir.mkdir()
    outside_file = outside_dir / "not_yours.txt"
    outside_file.write_text("private data from somewhere else")

    with pytest.raises(ArtifactPathEscapeError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="outside", artifact_type=ArtifactType.LOG,
            path=outside_file, config=execution_config, session_factory=session_factory,
        )


def test_register_artifact_rejects_path_inside_a_different_runs_workspace(
    session_factory, project_id, experiment_id, execution_config
):
    run_a = _make_run(session_factory, project_id, experiment_id)
    run_b = _make_run(session_factory, project_id, experiment_id)
    other_runs_file = _workspace_file(execution_config, project_id, run_b, "belongs_to_run_b.txt")

    with pytest.raises(ArtifactPathEscapeError):
        register_artifact(
            project_id=project_id, run_id=run_a, logical_name="stolen", artifact_type=ArtifactType.LOG,
            path=other_runs_file, config=execution_config, session_factory=session_factory,
        )


def test_register_artifact_rejects_path_inside_a_different_projects_workspace(
    session_factory, project_id, second_project_id, experiment_id, execution_config
):
    run_id = _make_run(session_factory, project_id, experiment_id)
    other_project_file = _workspace_file(execution_config, second_project_id, 999999, "not_yours.txt")

    with pytest.raises(ArtifactPathEscapeError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="stolen", artifact_type=ArtifactType.LOG,
            path=other_project_file, config=execution_config, session_factory=session_factory,
        )


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks on Windows normally requires elevated privileges")
def test_register_artifact_rejects_symlink_escaping_the_workspace(
    session_factory, project_id, experiment_id, execution_config, tmp_path
):
    run_id = _make_run(session_factory, project_id, experiment_id)
    workspace = prepare_run_workspace(project_id, run_id, config=execution_config)

    secret_target = tmp_path / "secret_outside_workspace.txt"
    secret_target.write_text("this must not become an artifact")
    symlink_path = workspace.output_dir / "innocent_looking_name.txt"
    symlink_path.symlink_to(secret_target)

    with pytest.raises(ArtifactPathEscapeError):
        register_artifact(
            project_id=project_id, run_id=run_id, logical_name="sneaky", artifact_type=ArtifactType.LOG,
            path=symlink_path, config=execution_config, session_factory=session_factory,
        )


def test_register_artifact_accepts_valid_path_genuinely_inside_workspace(
    session_factory, project_id, experiment_id, execution_config
):
    run_id = _make_run(session_factory, project_id, experiment_id)
    path = _workspace_file(execution_config, project_id, run_id, "valid.txt", "valid content")
    artifact = register_artifact(
        project_id=project_id, run_id=run_id, logical_name="valid", artifact_type=ArtifactType.LOG,
        path=path, config=execution_config, session_factory=session_factory,
    )
    assert artifact.reference == str(path.resolve())
