"""Project isolation: every cross-entity reference on a Run (or on the
orchestrator's request_run) must be rejected when it crosses a project
boundary — never silently mixed."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.errors import CrossProjectReferenceError
from researchos.execution.orchestrator import request_run


def test_repository_create_run_rejects_cross_project_specification(
    session_factory, project_id, second_project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    # approved_experiment_specification_id belongs to project_id; asking
    # to create a Run under second_project_id referencing it must fail.
    s = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.create_run(
                s, project_id=second_project_id, experiment_id=experiment_id, timeout_seconds=30,
                experiment_specification_id=approved_experiment_specification_id,
                dataset_version_id=approved_dataset_version_id,
            )
    finally:
        s.close()


def test_repository_create_run_rejects_cross_project_experiment(
    session_factory, project_id, second_project_id, approved_experiment_specification_id, approved_dataset_version_id
):
    s = session_factory()
    try:
        other_experiment = repository.register_experiment(s, project_id=second_project_id, name="Other Exp")
        s.commit()
        with pytest.raises(NotFoundError):
            repository.create_run(
                s, project_id=project_id, experiment_id=other_experiment.id, timeout_seconds=30,
                experiment_specification_id=approved_experiment_specification_id,
                dataset_version_id=approved_dataset_version_id,
            )
    finally:
        s.close()


def test_repository_create_run_rejects_cross_project_dataset_version(
    session_factory, project_id, second_project_id, experiment_id, approved_experiment_specification_id
):
    s = session_factory()
    try:
        other_record = repository.register_dataset(
            s, project_id=second_project_id, name="Other DS", version="raw", path_or_uri="s3://other/",
        )
        other_version = repository.create_dataset_version(
            s, project_id=second_project_id, dataset_record_id=other_record.id, format="classification",
        )
        s.commit()
        with pytest.raises(NotFoundError):
            repository.create_run(
                s, project_id=project_id, experiment_id=experiment_id, timeout_seconds=30,
                experiment_specification_id=approved_experiment_specification_id,
                dataset_version_id=other_version.id,
            )
    finally:
        s.close()


def test_request_run_rejects_cross_project_specification(
    session_factory, project_id, second_project_id, experiment_id, approved_experiment_specification_id,
    approved_dataset_version_id, execution_config,
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(CrossProjectReferenceError):
        request_run(
            second_project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )


def test_request_run_rejects_cross_project_experiment(
    session_factory, project_id, second_project_id, approved_experiment_specification_id,
    approved_dataset_version_id, execution_config,
):
    s = session_factory()
    try:
        other_experiment = repository.register_experiment(s, project_id=second_project_id, name="Other Exp")
        s.commit()
        other_experiment_id = other_experiment.id
    finally:
        s.close()
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(CrossProjectReferenceError):
        request_run(
            project_id, other_experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )


def test_request_run_rejects_cross_project_dataset_version(
    session_factory, project_id, second_project_id, experiment_id, approved_experimental_design_id, execution_config,
):
    """Uses a specification with NO `dataset_version_id` recorded
    (unlike `approved_experiment_specification_id`, which already has
    one set) so this test isolates the cross-project check itself,
    rather than tripping the Phase 8B-3 provenance-consistency check
    (`specification.dataset_version_id != dataset_version_id`) first —
    that check has its own dedicated test,
    `tests/execution/test_integration.py::
    test_request_run_rejects_dataset_version_inconsistent_with_specification`."""
    s = session_factory()
    try:
        other_record = repository.register_dataset(
            s, project_id=second_project_id, name="Other DS", version="raw", path_or_uri="s3://other/",
        )
        other_version = repository.create_dataset_version(
            s, project_id=second_project_id, dataset_record_id=other_record.id, format="classification",
        )
        from researchos.db.models import PlanningApprovalStatus

        unlinked_spec = repository.create_experiment_specification(
            s, project_id=project_id, experimental_design_id=approved_experimental_design_id,
            dataset_version_id=None, planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        other_version_id = other_version.id
        unlinked_spec_id = unlinked_spec.id
    finally:
        s.close()
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(CrossProjectReferenceError):
        request_run(
            project_id, experiment_id, unlinked_spec_id, other_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )
