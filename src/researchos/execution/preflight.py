"""Preflight validation: everything that must be true before a `Run` is
created, and everything that must be true again immediately before it
is actually queued for execution.

Every failure here is a typed, specific error (see
`researchos.execution.errors`) — never a generic `ValueError` — so a
caller (and a test) can tell exactly which of the Phase 8B-1 spec's 17
preflight requirements failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import (
    DatasetLifecycleStatus,
    DatasetVersion,
    ExecutionBackend,
    Experiment,
    ExperimentSpecification,
    PlanningApprovalStatus,
    ResearchProject,
    Run,
)
from ..planning import orchestration
from ..specification.fingerprint import compute_configuration_hash
from . import approval as approval_module
from . import runs as runs_module
from . import security
from .config import ExecutionConfig
from .contracts import PythonModuleTarget
from .errors import ExecutionNotApprovedError, InvalidExecutionTargetError, MissingEntityError, ProvenanceError


@dataclass(frozen=True)
class PreflightResult:
    """The validated entities `researchos.execution.orchestrator.request_run`
    needs to actually build a `Run` row — returned so the orchestrator
    never has to re-fetch (or worse, re-decide) anything preflight
    already resolved."""

    project: ResearchProject
    experiment: Experiment
    specification: ExperimentSpecification
    dataset_version: DatasetVersion


def preflight_request(
    session: Session,
    *,
    project_id: int,
    experiment_id: int,
    experiment_specification_id: int,
    dataset_version_id: int,
    execution_backend,
    target: PythonModuleTarget,
    timeout_seconds: int,
    config: ExecutionConfig,
) -> PreflightResult:
    """Checks 1-14 and 17 of the Phase 8B-1 preflight checklist —
    everything checkable before a `Run` row exists. Raises on the
    first violation found; never partially proceeds."""
    # 1. project exists
    project = repository.get_project(session, project_id)
    if project is None:
        raise MissingEntityError(f"ResearchProject {project_id} does not exist.")

    # 2 & 17. experiment exists and belongs to this project
    experiment = repository.get_experiment(session, experiment_id)
    orchestration.require_in_project(experiment, experiment_id, "Experiment", project_id)

    # 3, 4, 5, 17. specification exists, same project, APPROVED
    specification = repository.get_experiment_specification(session, experiment_specification_id)
    orchestration.require_in_project(specification, experiment_specification_id, "ExperimentSpecification", project_id)
    orchestration.require_status(
        specification, experiment_specification_id, "ExperimentSpecification",
        status_attr="planning_status", approved_values=(PlanningApprovalStatus.APPROVED,),
    )

    # Provenance-consistency hardening (Phase 8B-3): the caller-supplied
    # experiment_id/dataset_version_id must agree with what the
    # specification itself already recorded, whenever it recorded one —
    # nothing may silently create a Run whose experiment/dataset
    # disagrees with the specification's own upstream links. A
    # specification with no link recorded (both were nullable pre-Phase
    # 8B-3) imposes no constraint here; `researchos.execution.
    # integration.create_run_from_specification` is what requires a
    # link to exist at all.
    if specification.experiment_id is not None and specification.experiment_id != experiment_id:
        raise ProvenanceError(
            f"ExperimentSpecification {experiment_specification_id} is linked to Experiment "
            f"{specification.experiment_id}, not {experiment_id} — refusing to create a Run against a "
            "mismatched experiment identity."
        )
    if specification.dataset_version_id is not None and specification.dataset_version_id != dataset_version_id:
        raise ProvenanceError(
            f"ExperimentSpecification {experiment_specification_id} is grounded in DatasetVersion "
            f"{specification.dataset_version_id}, not {dataset_version_id} — refusing to create a Run against "
            "a dataset version the specification was never validated against."
        )

    # 6, 7, 8, 17. dataset version exists, same project, APPROVED
    # (Phase 8A's terminal accepted lifecycle value — not merely VALID,
    # which only means "passed deterministic validation," not "a human
    # signed off on it for use.")
    dataset_version = repository.get_dataset_version(session, dataset_version_id)
    orchestration.require_in_project(dataset_version, dataset_version_id, "DatasetVersion", project_id)
    orchestration.require_status(
        dataset_version, dataset_version_id, "DatasetVersion",
        status_attr="lifecycle_status", approved_values=(DatasetLifecycleStatus.APPROVED,),
    )

    # 10. execution backend is supported (only LOCAL_PYTHON has a real
    # implementation in this phase — see ExecutionBackend's docstring).
    if execution_backend != ExecutionBackend.LOCAL_PYTHON:
        raise InvalidExecutionTargetError(
            f"Execution backend {execution_backend!r} is not supported in Phase 8B-1; only LOCAL_PYTHON has a "
            "real executor. DOCKER/REMOTE_GPU/SLURM/CLOUD are interface-only extension points."
        )

    # 11. execution target is allowed
    security.validate_execution_target(target, config=config)

    # 12. timeout is valid
    security.validate_timeout(timeout_seconds, config=config)

    # 14. configuration hash matches configuration snapshot — guards
    # against a specification row whose configuration_hash column has
    # drifted from its own configuration column (e.g. a direct,
    # out-of-band DB edit), which would make this Run's own recorded
    # provenance internally inconsistent.
    if specification.configuration is not None:
        recomputed = compute_configuration_hash(specification.configuration)
        if specification.configuration_hash is not None and recomputed != specification.configuration_hash:
            raise ProvenanceError(
                f"ExperimentSpecification {experiment_specification_id}'s stored configuration_hash does not "
                "match its own configuration content — refusing to execute against inconsistent provenance."
            )

    # 9, 13. required provenance: code provenance / environment
    # snapshot are captured unconditionally by the orchestrator (never
    # required to be *present*, since an unavailable git repository is
    # itself a valid, explicitly-recorded fact — see
    # researchos.execution.git_provenance) — nothing to check here
    # beyond what has already been validated above.

    return PreflightResult(
        project=project, experiment=experiment, specification=specification, dataset_version=dataset_version,
    )


def preflight_execute(run: Run, *, session_factory=None) -> None:
    """Checks 15 and 16 — re-checked immediately before a `Run` is
    actually queued, since time may have passed since it was created."""
    # 15. no terminal run is being re-executed accidentally
    runs_module.assert_not_terminal(run)

    # 16. human execution approval exists
    if not approval_module.is_execution_approved(run.id, session_factory=session_factory):
        raise ExecutionNotApprovedError(
            f"Run {run.id} has no APPROVED execution approval (EXECUTION_APPROVAL:{run.id}); "
            "a human must approve execution before it may be queued."
        )
