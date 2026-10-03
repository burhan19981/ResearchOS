"""Preflight validation: missing entity, wrong project, invalid state,
unsupported backend, invalid execution target, invalid timeout,
inconsistent provenance."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import DatasetLifecycleStatus, ExecutionBackend, PlanningApprovalStatus
from researchos.execution.config import ExecutionConfig
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.errors import (
    InvalidExecutionTargetError,
    MissingEntityError,
    ProvenanceError,
    TimeoutConfigurationError,
    UpstreamNotApprovedError,
)
from researchos.execution.orchestrator import request_run
from researchos.execution.preflight import preflight_request
from researchos.specification.fingerprint import compute_configuration_hash


def test_preflight_rejects_unknown_project(session_factory, execution_config):
    s = session_factory()
    try:
        with pytest.raises(MissingEntityError):
            preflight_request(
                s, project_id=999999, experiment_id=1, experiment_specification_id=1, dataset_version_id=1,
                execution_backend=ExecutionBackend.LOCAL_PYTHON,
                target=PythonModuleTarget(module="tests.execution._local_target"),
                timeout_seconds=30, config=execution_config,
            )
    finally:
        s.close()


def test_preflight_rejects_unapproved_specification(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        candidate_spec = repository.create_experiment_specification(
            s, project_id=project_id, experimental_design_id=approved_experimental_design_id,
            dataset_version_id=approved_dataset_version_id, planning_status=PlanningApprovalStatus.CANDIDATE,
        )
        s.commit()
        spec_id = candidate_spec.id
    finally:
        s.close()

    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(UpstreamNotApprovedError):
        request_run(
            project_id, experiment_id, spec_id, approved_dataset_version_id, actor="agent:orchestrator",
            target=target, timeout_seconds=30, config=execution_config, session_factory=session_factory,
        )


def test_preflight_rejects_dataset_version_that_is_only_valid_not_approved(
    session_factory, project_id, experiment_id, approved_experimental_design_id, dataset_record_id, execution_config
):
    s = session_factory()
    try:
        merely_valid_version = repository.create_dataset_version(
            s, project_id=project_id, dataset_record_id=dataset_record_id, format="classification",
            lifecycle_status=DatasetLifecycleStatus.VALID,
        )
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experimental_design_id=approved_experimental_design_id,
            dataset_version_id=merely_valid_version.id, planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id, dataset_version_id = spec.id, merely_valid_version.id
    finally:
        s.close()

    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(UpstreamNotApprovedError):
        request_run(
            project_id, experiment_id, spec_id, dataset_version_id, actor="agent:orchestrator",
            target=target, timeout_seconds=30, config=execution_config, session_factory=session_factory,
        )


def test_preflight_rejects_unsupported_execution_backend(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(InvalidExecutionTargetError):
        request_run(
            project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, execution_backend=ExecutionBackend.DOCKER,
            config=execution_config, session_factory=session_factory,
        )


def test_preflight_rejects_module_outside_allowlist(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config
):
    target = PythonModuleTarget(module="os.system_abuse", arguments=())
    with pytest.raises(InvalidExecutionTargetError):
        request_run(
            project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )


def test_preflight_rejects_empty_module_allowlist_fail_closed(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id
):
    empty_config = ExecutionConfig(allowed_module_prefixes=())
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=())
    with pytest.raises(InvalidExecutionTargetError):
        request_run(
            project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=empty_config,
            session_factory=session_factory,
        )


@pytest.mark.parametrize("bad_timeout", [0, -1, 999999999])
def test_preflight_rejects_invalid_timeout(
    session_factory, project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id, execution_config, bad_timeout
):
    target = PythonModuleTarget(module="tests.execution._local_target", arguments=())
    with pytest.raises(TimeoutConfigurationError):
        request_run(
            project_id, experiment_id, approved_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=bad_timeout, config=execution_config,
            session_factory=session_factory,
        )


def test_preflight_rejects_configuration_hash_mismatch(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        real_config = {"seed": 1}
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experimental_design_id=approved_experimental_design_id,
            dataset_version_id=approved_dataset_version_id, configuration=real_config,
            configuration_hash="not-the-real-hash-at-all",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    target = PythonModuleTarget(module="tests.execution._local_target", arguments=())
    with pytest.raises(ProvenanceError):
        request_run(
            project_id, experiment_id, spec_id, approved_dataset_version_id, actor="agent:orchestrator",
            target=target, timeout_seconds=30, config=execution_config, session_factory=session_factory,
        )
