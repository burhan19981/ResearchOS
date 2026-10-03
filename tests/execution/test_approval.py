"""Execution approval: human-only, correct project/entity/state, LLM
cannot approve, agents cannot approve, unapproved execution rejected,
approved execution accepted."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from researchos.db import repository
from researchos.db.models import ExecutionBackend
from researchos.planning.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError
from researchos.execution import approval as approval_module
from researchos.execution.errors import ExecutionNotApprovedError
from researchos.execution.orchestrator import execute_run, request_run
from researchos.execution.contracts import PythonModuleTarget
from tests.execution.fakes import FakeExecutionEngine


def _create_run(session_factory: sessionmaker, *, project_id, experiment_id, spec_id, dataset_version_id):
    s = session_factory()
    try:
        run = repository.create_run(
            s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
            experiment_specification_id=spec_id, dataset_version_id=dataset_version_id,
            execution_backend=ExecutionBackend.LOCAL_PYTHON,
        )
        s.commit()
        return run.id
    finally:
        s.close()


def test_pending_run_has_no_execution_approval(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    assert approval_module.is_execution_approved(run_id, session_factory=session_factory) is False


def test_human_can_approve_execution(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    approval_module.approve_run_execution(run_id, actor="user:pi", session_factory=session_factory)
    assert approval_module.is_execution_approved(run_id, session_factory=session_factory) is True


def test_agent_cannot_approve_execution(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    with pytest.raises(HumanOnlyActionError):
        approval_module.approve_run_execution(run_id, actor="agent:planner", session_factory=session_factory)
    assert approval_module.is_execution_approved(run_id, session_factory=session_factory) is False


def test_reject_execution_leaves_it_unapproved(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    approval_module.reject_run_execution(run_id, actor="user:pi", session_factory=session_factory)
    assert approval_module.is_execution_approved(run_id, session_factory=session_factory) is False


def test_cannot_redecide_an_already_decided_execution_approval(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    approval_module.approve_run_execution(run_id, actor="user:pi", session_factory=session_factory)
    with pytest.raises(ApprovalAlreadyDecidedError):
        approval_module.approve_run_execution(run_id, actor="user:pi", session_factory=session_factory)


def test_changes_requested_reopens_a_fresh_pending_round(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    run_id = _create_run(
        session_factory, project_id=project_id, experiment_id=experiment_id,
        spec_id=approved_experiment_specification_id, dataset_version_id=approved_dataset_version_id,
    )
    approval_module.request_changes_run_execution(run_id, actor="user:pi", comment="need timeout raised", session_factory=session_factory)
    # A fresh decision is possible after changes-requested (not "already decided").
    approval_module.approve_run_execution(run_id, actor="user:pi", session_factory=session_factory)
    assert approval_module.is_execution_approved(run_id, session_factory=session_factory) is True


def test_approving_unknown_run_raises(session_factory):
    with pytest.raises(CandidateNotFoundError):
        approval_module.approve_run_execution(999999, actor="user:pi", session_factory=session_factory)


def test_execute_run_rejects_unapproved_run(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    engine = FakeExecutionEngine()
    with pytest.raises(ExecutionNotApprovedError):
        execute_run(run.id, actor="user:pi", engine=engine, config=execution_config, session_factory=session_factory)
    assert engine.requests == []


def test_execute_run_proceeds_once_approved(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = request_run(
        project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
        actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
        session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)
    engine = FakeExecutionEngine()
    result = execute_run(run.id, actor="user:pi", engine=engine, config=execution_config, session_factory=session_factory)
    assert result.status.value == "succeeded"
    assert len(engine.requests) == 1
