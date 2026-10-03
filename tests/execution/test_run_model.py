"""Run model + lifecycle: creation, deterministic transitions, invalid
transitions, terminal immutability."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from researchos.db import repository
from researchos.db.errors import ConcurrencyConflictError, NotFoundError
from researchos.db.models import ExecutionBackend, RunStatus
from researchos.execution import runs as runs_module
from researchos.execution.errors import InvalidRunStateError


def _create_run(session_factory: sessionmaker, *, project_id, experiment_id, spec_id, dataset_version_id, timeout_seconds=30):
    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=timeout_seconds,
            experiment_specification_id=spec_id, dataset_version_id=dataset_version_id,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        s.commit()
        return run.id
    finally:
        s.close()


def test_create_run_defaults_to_created_status(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    s = session_factory()
    try:
        run = repository.get_run(s, run_id)
        assert run.status == RunStatus.CREATED
        assert run.execution_backend == ExecutionBackend.LOCAL_PYTHON
    finally:
        s.close()


def test_create_run_rejects_unknown_experiment(session_factory, project_id, approved_experiment_specification_id, approved_dataset_version_id):
    s = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.create_run(
                s, project_id=project_id, experiment_id=999999, timeout_seconds=30,
                experiment_specification_id=approved_experiment_specification_id,
                dataset_version_id=approved_dataset_version_id,
            )
    finally:
        s.close()


def test_lifecycle_created_to_queued_to_running_to_succeeded(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    now = datetime.now(timezone.utc)
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    run = runs_module.complete_run(
        run_id, actor="user:pi", status=RunStatus.SUCCEEDED, finished_at=now, duration_seconds=1.0,
        exit_code=0, stdout_reference="ref://out", stderr_reference="ref://err", failure_reason=None,
        session_factory=session_factory,
    )
    assert run.status == RunStatus.SUCCEEDED
    assert run.exit_code == 0


@pytest.mark.parametrize("terminal_status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT])
def test_lifecycle_running_to_each_terminal_status(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, terminal_status
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    now = datetime.now(timezone.utc)
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    run = runs_module.complete_run(
        run_id, actor="user:pi", status=terminal_status, finished_at=now, duration_seconds=1.0,
        exit_code=None, stdout_reference=None, stderr_reference=None, failure_reason="reason",
        session_factory=session_factory,
    )
    assert run.status == terminal_status


def test_cannot_skip_queued_straight_to_running(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    with pytest.raises(InvalidRunStateError):
        runs_module.start_run(run_id, actor="user:pi", started_at=datetime.now(timezone.utc), session_factory=session_factory)


@pytest.mark.parametrize("terminal_status", [RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT])
def test_terminal_run_cannot_transition_back_to_running(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, terminal_status
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    now = datetime.now(timezone.utc)
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    runs_module.complete_run(
        run_id, actor="user:pi", status=terminal_status, finished_at=now, duration_seconds=1.0,
        exit_code=None, stdout_reference=None, stderr_reference=None, failure_reason=None,
        session_factory=session_factory,
    )
    with pytest.raises(InvalidRunStateError):
        runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    with pytest.raises(InvalidRunStateError):
        runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)


def test_assert_not_terminal_raises_for_terminal_run(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    now = datetime.now(timezone.utc)
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    run = runs_module.complete_run(
        run_id, actor="user:pi", status=RunStatus.FAILED, finished_at=now, duration_seconds=1.0,
        exit_code=1, stdout_reference=None, stderr_reference=None, failure_reason="boom",
        session_factory=session_factory,
    )
    with pytest.raises(InvalidRunStateError):
        runs_module.assert_not_terminal(run)


def test_mark_preparation_failed_transitions_queued_to_failed(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    """`QUEUED -> FAILED` (Phase 8B-2's one new edge): a Run must never
    be left stranded in QUEUED if workspace preparation fails before
    the process ever starts."""
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    now = datetime.now(timezone.utc)
    run = runs_module.mark_preparation_failed(
        run_id, actor="user:pi", failure_reason="workspace directory could not be created",
        finished_at=now, session_factory=session_factory,
    )
    assert run.status == RunStatus.FAILED
    assert run.exit_code is None
    assert run.stdout_reference is None
    assert run.failure_reason == "workspace directory could not be created"
    # Terminal now — cannot be started afterward.
    with pytest.raises(InvalidRunStateError):
        runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)


def test_mark_preparation_failed_rejected_from_created_directly(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    """Only `QUEUED -> FAILED` is allowed — `CREATED -> FAILED` is
    still refused, since preparation failures only happen after
    queueing."""
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    with pytest.raises(InvalidRunStateError):
        runs_module.mark_preparation_failed(
            run_id, actor="user:pi", failure_reason="x", finished_at=datetime.now(timezone.utc),
            session_factory=session_factory,
        )


def test_concurrency_conflict_when_expected_status_stale(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    s = session_factory()
    try:
        repository.update_run_lifecycle(s, run_id, expected_status=RunStatus.CREATED, new_status=RunStatus.QUEUED)
        s.commit()
        with pytest.raises(ConcurrencyConflictError):
            repository.update_run_lifecycle(s, run_id, expected_status=RunStatus.CREATED, new_status=RunStatus.QUEUED)
    finally:
        s.close()


def test_failed_run_preserves_full_scientific_record(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    now = datetime.now(timezone.utc)
    runs_module.queue_run(run_id, actor="user:pi", session_factory=session_factory)
    runs_module.start_run(run_id, actor="user:pi", started_at=now, session_factory=session_factory)
    run = runs_module.complete_run(
        run_id, actor="user:pi", status=RunStatus.FAILED, finished_at=now, duration_seconds=3.2,
        exit_code=137, stdout_reference="ref://stdout", stderr_reference="ref://stderr",
        failure_reason="Process exited with code 137.", session_factory=session_factory,
    )
    assert run.status == RunStatus.FAILED
    assert run.exit_code == 137
    assert run.stdout_reference == "ref://stdout"
    assert run.stderr_reference == "ref://stderr"
    assert run.failure_reason == "Process exited with code 137."
    assert run.started_at is not None and run.finished_at is not None
    assert run.duration_seconds == 3.2
    # Provenance survives a failure exactly as it would a success.
    assert run.experiment_specification_id == approved_experiment_specification_id
    assert run.dataset_version_id == approved_dataset_version_id
