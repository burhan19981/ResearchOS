"""Human approval integration for the dataset & experiment specification
layer (Phase 8A).

Reuses `researchos.db.approval_dispatch` directly — no second generic
approval engine — and `researchos.planning.errors`' `HumanOnlyActionError`/
`ApprovalAlreadyDecidedError`/`CandidateNotFoundError` directly rather
than duplicating them a third time.

Two new gate types: `DATASET_VERSION_APPROVAL:<id>`,
`EXPERIMENT_SPECIFICATION_APPROVAL:<id>`.

`DatasetVersion` has one precondition Phase 6/7's entities don't: it
must be `lifecycle_status VALID` (i.e. it has already been through
`researchos.specification.dataset_versions.validate_dataset_version()`
and passed) before a human can approve it. This is checked here, in a
small pre-flight lookup before delegating to the shared dispatcher —
`approval_dispatch.decide()` itself stays completely generic and
unaware of any entity-specific precondition.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..db import approval_dispatch, repository
from ..db.engine import session_scope
from ..db.models import Approval, ApprovalDecision, DatasetLifecycleStatus, PlanningApprovalStatus
from ..planning.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError
from ..workflow.policy import is_human_actor
from .errors import InvalidLifecycleTransitionError

_DATASET_VERSION_SPEC = approval_dispatch.EntitySpec(
    label="DatasetVersion",
    stage_prefix="DATASET_VERSION_APPROVAL",
    status_attr="lifecycle_status",
    get=repository.get_dataset_version,
    update_status=lambda s, i, v: repository.update_dataset_version(s, i, lifecycle_status=v),
    # APPROVED means only "approved for system use under this project's
    # process" — never "scientifically valid research evidence." INVALID
    # is reused for a human rejection (the same value automated
    # validation failure produces — both mean "not fit for use," just
    # reached differently) rather than inventing a redundant value.
    # request_changes sends a version back to DRAFT rather than a
    # redundant sixth state.
    approved_value=DatasetLifecycleStatus.APPROVED,
    rejected_value=DatasetLifecycleStatus.INVALID,
    changes_requested_value=DatasetLifecycleStatus.DRAFT,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_EXPERIMENT_SPECIFICATION_SPEC = approval_dispatch.EntitySpec(
    label="ExperimentSpecification",
    stage_prefix="EXPERIMENT_SPECIFICATION_APPROVAL",
    status_attr="planning_status",
    get=repository.get_experiment_specification,
    update_status=lambda s, i, v: repository.update_experiment_specification(s, i, planning_status=v),
    approved_value=PlanningApprovalStatus.APPROVED,
    rejected_value=PlanningApprovalStatus.REJECTED,
    changes_requested_value=PlanningApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)


def _decide(spec, entity_id, actor, comment, *, decision, new_status, event_type, session_factory):
    return approval_dispatch.decide(
        spec, entity_id, actor, comment,
        decision=decision, new_status=new_status, event_type=event_type, session_factory=session_factory,
    )


# ===========================================================================
# DatasetVersion
# ===========================================================================


def approve_dataset_version(dataset_version_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    """Approving a `DatasetVersion` requires it to already be
    `lifecycle_status VALID` — a human cannot approve a version that has
    not passed (or has failed) deterministic validation."""
    if not is_human_actor(actor):
        raise HumanOnlyActionError(
            f"'{actor}' cannot decide this approval — the LLM cannot approve its own output; "
            "approval decisions must be made by a human."
        )
    with session_scope(session_factory) as session:
        dataset_version = repository.get_dataset_version(session, dataset_version_id)
        if dataset_version is None:
            raise CandidateNotFoundError(f"DatasetVersion {dataset_version_id} does not exist.")
        if dataset_version.lifecycle_status != DatasetLifecycleStatus.VALID:
            raise InvalidLifecycleTransitionError(
                f"DatasetVersion {dataset_version_id} is {dataset_version.lifecycle_status.value}, not VALID; "
                "it must pass validation before it can be approved."
            )
    return _decide(
        _DATASET_VERSION_SPEC, dataset_version_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_DATASET_VERSION_SPEC.approved_value,
        event_type="specification.dataset_version_approved", session_factory=session_factory,
    )


def reject_dataset_version(dataset_version_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _DATASET_VERSION_SPEC, dataset_version_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_DATASET_VERSION_SPEC.rejected_value,
        event_type="specification.dataset_version_rejected", session_factory=session_factory,
    )


def request_changes_dataset_version(dataset_version_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _DATASET_VERSION_SPEC, dataset_version_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_DATASET_VERSION_SPEC.changes_requested_value,
        event_type="specification.dataset_version_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# ExperimentSpecification
# ===========================================================================


def approve_experiment_specification(experiment_specification_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENT_SPECIFICATION_SPEC, experiment_specification_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_EXPERIMENT_SPECIFICATION_SPEC.approved_value,
        event_type="specification.experiment_specification_approved", session_factory=session_factory,
    )


def reject_experiment_specification(experiment_specification_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENT_SPECIFICATION_SPEC, experiment_specification_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_EXPERIMENT_SPECIFICATION_SPEC.rejected_value,
        event_type="specification.experiment_specification_rejected", session_factory=session_factory,
    )


def request_changes_experiment_specification(experiment_specification_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENT_SPECIFICATION_SPEC, experiment_specification_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_EXPERIMENT_SPECIFICATION_SPEC.changes_requested_value,
        event_type="specification.experiment_specification_changes_requested", session_factory=session_factory,
    )


def get_pending_specification_approvals(session: Session, project_id: int) -> list[Approval]:
    """All pending approvals in a project whose stage key belongs to
    this layer's two gate types."""
    prefixes = (_DATASET_VERSION_SPEC.stage_prefix, _EXPERIMENT_SPECIFICATION_SPEC.stage_prefix)
    return approval_dispatch.pending_for_prefixes(session, project_id, prefixes)
