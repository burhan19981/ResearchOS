"""Phase 8B-3 integration layer: `create_run_from_specification`,
`prepare_run`, the `ExperimentSpecification.experiment_id` link, and
the provenance-consistency hardening added to `preflight_request`.
Exercises the full chain end to end through the new, high-level entry
points — never bypassing or duplicating the Phase 8B-1/8B-2 checks
those entry points are themselves built on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import PlanningApprovalStatus, RunStatus
from researchos.execution import approval as approval_module
from researchos.execution.contracts import PythonModuleTarget
from researchos.execution.errors import (
    CrossProjectReferenceError,
    InvalidExecutionTargetError,
    MissingEntityError,
    ProvenanceError,
    SpecificationMissingDatasetVersionError,
    UnlinkedSpecificationError,
    UpstreamNotApprovedError,
)
from researchos.execution.integration import create_run_from_specification, prepare_run
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.orchestrator import execute_run, request_run
from researchos.specification.fingerprint import compute_configuration_hash


def _approve_and_run(run_id, session_factory, config, *, engine=None):
    approval_module.approve_run_execution(run_id, actor="user:pi", session_factory=session_factory)
    return execute_run(
        run_id, actor="agent:orchestrator", engine=engine or LocalPythonExecutor(), config=config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )


# ===========================================================================
# A. Run creation
# ===========================================================================


def test_create_run_from_specification_derives_experiment_and_dataset(
    session_factory, project_id, experiment_id, linked_experiment_specification_id,
    approved_dataset_version_id, execution_config,
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator",
        timeout_seconds=30, config=execution_config, session_factory=session_factory,
    )
    assert run.experiment_id == experiment_id
    assert run.dataset_version_id == approved_dataset_version_id
    assert run.experiment_specification_id == linked_experiment_specification_id
    assert run.status == RunStatus.CREATED


def test_create_run_from_specification_rejects_unapproved_specification(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "success"]}}
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.CANDIDATE,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    with pytest.raises(UpstreamNotApprovedError):
        create_run_from_specification(
            project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
            config=execution_config, session_factory=session_factory,
        )


def test_create_run_from_specification_rejects_missing_specification(session_factory, project_id, execution_config):
    with pytest.raises(MissingEntityError):
        create_run_from_specification(
            project_id, 999999, requested_by="agent:orchestrator", timeout_seconds=30,
            config=execution_config, session_factory=session_factory,
        )


def test_create_run_from_specification_rejects_wrong_project(
    session_factory, project_id, second_project_id, linked_experiment_specification_id, execution_config
):
    with pytest.raises(CrossProjectReferenceError):
        create_run_from_specification(
            second_project_id, linked_experiment_specification_id, requested_by="agent:orchestrator",
            timeout_seconds=30, config=execution_config, session_factory=session_factory,
        )


def test_create_run_from_specification_rejects_unlinked_specification(
    session_factory, project_id, approved_experiment_specification_id, execution_config
):
    """`approved_experiment_specification_id` (the Phase 8B-1/8B-2
    fixture) deliberately has no `experiment_id` set."""
    with pytest.raises(UnlinkedSpecificationError):
        create_run_from_specification(
            project_id, approved_experiment_specification_id, requested_by="agent:orchestrator",
            timeout_seconds=30, config=execution_config, session_factory=session_factory,
        )


def test_create_run_from_specification_rejects_specification_with_no_dataset_version(
    session_factory, project_id, experiment_id, approved_experimental_design_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "success"]}}
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=None,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    with pytest.raises(SpecificationMissingDatasetVersionError):
        create_run_from_specification(
            project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
            config=execution_config, session_factory=session_factory,
        )


def test_create_run_from_specification_rejects_missing_execution_block(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"seed": 1}  # no "execution" key at all
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    with pytest.raises(InvalidExecutionTargetError):
        create_run_from_specification(
            project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
            config=execution_config, session_factory=session_factory,
        )


def test_explicit_target_override_bypasses_configuration_derivation(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"seed": 1}  # no "execution" key — would normally fail derivation
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    explicit_target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30, target=explicit_target,
        config=execution_config, session_factory=session_factory,
    )
    assert run.execution_target["module"] == "tests.execution._local_target"


def test_request_run_rejects_dataset_version_inconsistent_with_specification(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, dataset_record_id, execution_config
):
    """Provenance-consistency hardening: `request_run` (the lower-level
    entry point) must reject a caller-supplied `dataset_version_id`
    that disagrees with what the specification itself recorded — even
    though the mismatched dataset version independently exists,
    belongs to the same project, and is approved."""
    s = session_factory()
    try:
        from researchos.db.models import DatasetLifecycleStatus

        other_dataset_version = repository.create_dataset_version(
            s, project_id=project_id, dataset_record_id=dataset_record_id, format="classification",
            lifecycle_status=DatasetLifecycleStatus.APPROVED,
        )
        s.commit()
        other_dataset_version_id = other_dataset_version.id
    finally:
        s.close()

    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(ProvenanceError):
        request_run(
            project_id, experiment_id, linked_experiment_specification_id, other_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )


def test_request_run_rejects_experiment_inconsistent_with_specification(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        other_experiment = repository.register_experiment(s, project_id=project_id, name="A Different Experiment")
        s.commit()
        other_experiment_id = other_experiment.id
    finally:
        s.close()

    target = PythonModuleTarget(module="tests.execution._local_target", arguments=("--mode", "success"))
    with pytest.raises(ProvenanceError):
        request_run(
            project_id, other_experiment_id, linked_experiment_specification_id, approved_dataset_version_id,
            actor="agent:orchestrator", target=target, timeout_seconds=30, config=execution_config,
            session_factory=session_factory,
        )


# ===========================================================================
# B. Provenance
# ===========================================================================


def test_run_provenance_snapshot_matches_specification(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, approved_dataset_version_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    s = session_factory()
    try:
        spec = repository.get_experiment_specification(s, linked_experiment_specification_id)
        dataset_version = repository.get_dataset_version(s, approved_dataset_version_id)
    finally:
        s.close()

    assert run.project_id == project_id
    assert run.experiment_specification_version == spec.version
    assert run.configuration_hash == spec.configuration_hash
    assert run.dataset_version_version == dataset_version.version
    assert run.dataset_fingerprint == dataset_version.content_fingerprint


def test_provenance_snapshot_is_byte_identical_across_the_full_lifecycle(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    """Behavioral immutability: every provenance field captured at
    `Run` creation — specification/dataset ids and versions,
    configuration hash, dataset fingerprint, experiment id — must be
    byte-identical from `CREATED` all the way through to the
    terminal state. Nothing in the real `queue_run`/`start_run`/
    `complete_run` call chain (the only functions that ever call
    `repository.update_run_lifecycle`) passes any provenance field
    through it — only lifecycle fields (status, timestamps, exit_code,
    stdout/stderr references, failure_reason)."""
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    provenance_fields = (
        "project_id", "experiment_id", "experiment_specification_id", "experiment_specification_version",
        "dataset_version_id", "dataset_version_version", "dataset_fingerprint", "configuration_hash",
        "configuration_snapshot", "seed",
    )
    before = {field: getattr(run, field) for field in provenance_fields}

    final_run = _approve_and_run(run.id, session_factory, execution_config)

    after = {field: getattr(final_run, field) for field in provenance_fields}
    assert after == before
    assert final_run.status == RunStatus.SUCCEEDED  # confirms the lifecycle *did* actually advance meanwhile


# ===========================================================================
# C. Preparation
# ===========================================================================


def test_prepare_run_ready_when_approved(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)
    outcome = prepare_run(run.id, session_factory=session_factory)
    assert outcome.ready is True
    assert outcome.reasons == []
    assert outcome.error is None


def test_prepare_run_blocked_when_not_approved(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    outcome = prepare_run(run.id, session_factory=session_factory)
    assert outcome.ready is False
    assert len(outcome.reasons) == 1
    assert "approval" in outcome.reasons[0].lower()
    assert outcome.error is not None


def test_prepare_run_does_not_mutate_run_status(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    prepare_run(run.id, session_factory=session_factory)
    prepare_run(run.id, session_factory=session_factory)  # calling it twice is safe
    s = session_factory()
    try:
        reloaded = repository.get_run(s, run.id)
    finally:
        s.close()
    assert reloaded.status == RunStatus.CREATED  # unchanged — prepare_run never transitions anything


def test_prepare_run_missing_run_raises(session_factory):
    with pytest.raises(MissingEntityError):
        prepare_run(999999, session_factory=session_factory)


# ===========================================================================
# D. Execution (through the integration entry point)
# ===========================================================================


def test_execute_successful_generic_python_experiment(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    result = _approve_and_run(run.id, session_factory, execution_config)
    assert result.status == RunStatus.SUCCEEDED
    assert result.exit_code == 0


def test_execute_non_zero_exit(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "fail", "--exit-code", "9"]}}
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    result = _approve_and_run(run.id, session_factory, execution_config)
    assert result.status == RunStatus.FAILED
    assert result.exit_code == 9


def test_execute_timeout(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    s = session_factory()
    try:
        configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "sleep", "--sleep-seconds", "5"]}}
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=1,
        config=execution_config, session_factory=session_factory,
    )
    result = _approve_and_run(run.id, session_factory, execution_config)
    assert result.status == RunStatus.TIMEOUT


def test_execute_launch_failure(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    fake_python = r"C:\definitely\not\a\real\python.exe"
    configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "success"], "python_executable": fake_python}}
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    broken_config = execution_config.__class__(
        allowed_module_prefixes=execution_config.allowed_module_prefixes,
        allowed_python_executables=(fake_python,),
        allowed_execution_root=execution_config.allowed_execution_root,
    )
    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=broken_config, session_factory=session_factory,
    )
    result = _approve_and_run(run.id, session_factory, broken_config)
    assert result.status == RunStatus.FAILED
    assert result.exit_code is None
    assert "launch" in result.failure_reason.lower()


# ===========================================================================
# E. Idempotency
# ===========================================================================


def test_execute_run_twice_via_integration_rejected(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    from researchos.execution.errors import InvalidRunStateError

    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)
    with pytest.raises(InvalidRunStateError):
        execute_run(run.id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config, session_factory=session_factory)


def test_prepare_run_twice_is_safe_and_consistent(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    first = prepare_run(run.id, session_factory=session_factory)
    second = prepare_run(run.id, session_factory=session_factory)
    assert first.ready == second.ready == False  # noqa: E712 - explicit for readability


def test_terminal_run_cannot_be_prepared_into_a_false_ready_state(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)
    outcome = prepare_run(run.id, session_factory=session_factory)
    assert outcome.ready is False
    assert "immutable" in outcome.reasons[0].lower() or "terminal" in outcome.reasons[0].lower()


# ===========================================================================
# F. Concurrency (competing execution / preparation attempts)
# ===========================================================================


def test_competing_execution_attempts_only_one_succeeds(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    """Simulates two callers racing to execute the same approved Run —
    the second must be rejected once the first has moved it past
    CREATED, never silently double-executed."""
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)

    from researchos.execution import runs as runs_module

    runs_module.queue_run(run.id, actor="agent:orchestrator", session_factory=session_factory)
    # A second, competing "queue" attempt (as if from a concurrent
    # execute_run call) must be rejected — the CAS in
    # update_run_lifecycle is what actually prevents the race.
    from researchos.execution.errors import InvalidRunStateError

    with pytest.raises(InvalidRunStateError):
        runs_module.queue_run(run.id, actor="agent:other-caller", session_factory=session_factory)


# ===========================================================================
# G. Artifacts / H. Metrics (through the integration entry point)
# ===========================================================================


def test_artifacts_and_metrics_registered_through_integration_entry_point(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "metrics"]}}
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    result = _approve_and_run(run.id, session_factory, execution_config)

    s = session_factory()
    try:
        artifacts = repository.list_artifact_metadata(s, project_id, run_id=result.id)
        metrics = repository.list_metrics(s, project_id, run_id=result.id)
    finally:
        s.close()

    artifact_names = {a.logical_name for a in artifacts}
    assert {"stdout", "stderr", "result_manifest", "metrics_report"} <= artifact_names
    metric_names = {m.name for m in metrics}
    assert {"accuracy", "epoch"} <= metric_names
    assert all(m.run_id == result.id for m in metrics)


# ===========================================================================
# I. Audit trail
# ===========================================================================


def test_audit_trail_covers_full_integration_lifecycle(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    prepare_run(run.id, session_factory=session_factory)  # BLOCKED (not yet approved)
    approval_module.approve_run_execution(run.id, actor="user:pi", session_factory=session_factory)
    prepare_run(run.id, session_factory=session_factory)  # READY
    execute_run(
        run.id, actor="agent:orchestrator", engine=LocalPythonExecutor(), config=execution_config,
        extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, session_factory=session_factory,
    )

    s = session_factory()
    try:
        events = repository.list_audit_events(s, project_id)
    finally:
        s.close()
    event_types = {e.event_type for e in events}
    assert "execution.run_created_from_specification" in event_types
    assert "execution.run_blocked" in event_types
    assert "execution.run_prepared" in event_types
    assert "execution.run_queued" in event_types
    assert "execution.run_started" in event_types
    assert "execution.run_succeeded" in event_types


def test_run_failed_audit_event_recorded(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "fail"]}}
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)

    s = session_factory()
    try:
        events = repository.list_audit_events(s, project_id)
    finally:
        s.close()
    assert any(e.event_type == "execution.run_failed" for e in events)


# ===========================================================================
# J. Security (through the integration entry point)
# ===========================================================================


def test_cross_project_dataset_version_structurally_impossible_at_spec_creation(
    session_factory, project_id, second_project_id, experiment_id, approved_experimental_design_id
):
    """A specification can never legitimately reference a DatasetVersion
    from a different project in the first place — the repository layer
    already refuses this at creation time (see
    `researchos.db.repository.create_experiment_specification`), so a
    Run created from any real specification can never inherit a
    cross-project dataset either."""
    s = session_factory()
    try:
        other_record = repository.register_dataset(
            s, project_id=second_project_id, name="Other DS", version="raw", path_or_uri="s3://other/",
        )
        from researchos.db.models import DatasetLifecycleStatus

        other_version = repository.create_dataset_version(
            s, project_id=second_project_id, dataset_record_id=other_record.id, format="classification",
            lifecycle_status=DatasetLifecycleStatus.APPROVED,
        )
        s.commit()
        other_version_id = other_version.id
    finally:
        s.close()

    s = session_factory()
    try:
        with pytest.raises(NotFoundError):
            repository.create_experiment_specification(
                s, project_id=project_id, experiment_id=experiment_id,
                experimental_design_id=approved_experimental_design_id, dataset_version_id=other_version_id,
                planning_status=PlanningApprovalStatus.APPROVED,
            )
    finally:
        s.close()


def test_malicious_module_in_configuration_execution_block_rejected(
    session_factory, project_id, experiment_id, approved_experimental_design_id, approved_dataset_version_id, execution_config
):
    configuration = {"execution": {"module": "os; rm -rf /", "arguments": []}}
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    with pytest.raises(InvalidExecutionTargetError):
        create_run_from_specification(
            project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
            config=execution_config, session_factory=session_factory,
        )


# ===========================================================================
# K. Scientific semantics
# ===========================================================================


def test_successful_execution_never_creates_scientific_approval(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    s = session_factory()
    try:
        before = {a.id: a.decision.value for a in repository.list_approvals(s, project_id)}
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)

    s = session_factory()
    try:
        after = repository.list_approvals(s, project_id)
        spec = repository.get_experiment_specification(s, linked_experiment_specification_id)
    finally:
        s.close()

    # The ONLY new approval is the execution approval itself; the
    # specification's own planning_status (already APPROVED before this
    # test ran) is untouched by a successful execution.
    new_approvals = [a for a in after if a.id not in before]
    assert len(new_approvals) == 1
    assert new_approvals[0].stage.startswith("EXECUTION_APPROVAL:")
    assert spec.planning_status == PlanningApprovalStatus.APPROVED  # unchanged, not re-decided


def test_metrics_never_auto_modify_contribution_candidate(
    session_factory, project_id, experiment_id, approved_contribution_id, approved_experimental_design_id,
    approved_dataset_version_id, execution_config,
):
    s = session_factory()
    try:
        before = repository.get_contribution_candidate(s, approved_contribution_id)
        before_status = before.planning_status
    finally:
        s.close()

    configuration = {"execution": {"module": "tests.execution._local_target", "arguments": ["--mode", "metrics"]}}
    s = session_factory()
    try:
        spec = repository.create_experiment_specification(
            s, project_id=project_id, experiment_id=experiment_id,
            experimental_design_id=approved_experimental_design_id, dataset_version_id=approved_dataset_version_id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        s.commit()
        spec_id = spec.id
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, spec_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)

    s = session_factory()
    try:
        after = repository.get_contribution_candidate(s, approved_contribution_id)
    finally:
        s.close()
    assert after.planning_status == before_status  # metrics never touch this at all


def test_workflow_current_stage_never_automatically_advanced(
    session_factory, project_id, experiment_id, linked_experiment_specification_id, execution_config
):
    s = session_factory()
    try:
        before_stage = repository.get_project(s, project_id).current_stage
    finally:
        s.close()

    run = create_run_from_specification(
        project_id, linked_experiment_specification_id, requested_by="agent:orchestrator", timeout_seconds=30,
        config=execution_config, session_factory=session_factory,
    )
    _approve_and_run(run.id, session_factory, execution_config)

    s = session_factory()
    try:
        after_stage = repository.get_project(s, project_id).current_stage
    finally:
        s.close()
    assert after_stage == before_stage  # researchos.workflow is never touched by execution


def test_researchos_execution_never_imports_workflow_service():
    """Static check: no module in researchos.execution imports
    researchos.workflow.service (the state-machine authority) — only
    the read-only policy.is_human_actor helper, exactly like every
    other phase's approval module."""
    import ast
    import pathlib

    package_root = pathlib.Path(__file__).resolve().parents[2] / "src" / "researchos" / "execution"
    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "workflow.service" in node.module:
                raise AssertionError(f"{path.name} imports researchos.workflow.service")
