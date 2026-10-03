"""Human approval integration for the research planning layer (Phase 7
spec section 17).

Reuses the Phase 4 `Approval`/`AuditEvent`/`ApprovalDecision` tables and
`researchos.workflow.policy.is_human_actor` directly through the shared
`researchos.db.approval_dispatch` mechanics (the same generic dispatcher
`researchos.intelligence.approval` uses, extracted in this phase — see
that module's docstring). No parallel approval system exists;
`researchos.workflow.service` is neither imported nor modified.

Five new gate types live here: `RESEARCH_QUESTION_APPROVAL:<id>`,
`CONTRIBUTION_APPROVAL:<id>`, `METHODOLOGY_APPROVAL:<id>`,
`DATASET_REQUIREMENTS_APPROVAL:<id>`, `EXPERIMENTAL_DESIGN_APPROVAL:<id>`.
`NOVELTY_APPROVAL:<id>` is deliberately NOT redefined here — it remains
exclusively `researchos.intelligence.approval`'s, unchanged, since a
`NoveltyAssessment` (evidence-based novelty judgment) is a distinct
decision from a `ContributionCandidate`'s own `CONTRIBUTION_APPROVAL`
("we accept this as the direction we're pursuing") — see
docs/PHASE7_RESEARCH_PLANNING.md.

As with Phase 6: every decision function requires a human actor and
raises immediately for an agent actor; the LLM can never approve its
own output.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..db import approval_dispatch, repository
from ..db.models import Approval, ApprovalDecision, PlanningApprovalStatus
from .errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError

_QUESTION_SPEC = approval_dispatch.EntitySpec(
    label="ResearchQuestion",
    stage_prefix="RESEARCH_QUESTION_APPROVAL",
    status_attr="planning_status",
    get=repository.get_research_question,
    update_status=lambda s, i, v: repository.update_research_question(s, i, planning_status=v),
    approved_value=PlanningApprovalStatus.APPROVED,
    rejected_value=PlanningApprovalStatus.REJECTED,
    changes_requested_value=PlanningApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_CONTRIBUTION_SPEC = approval_dispatch.EntitySpec(
    label="ContributionCandidate",
    stage_prefix="CONTRIBUTION_APPROVAL",
    status_attr="planning_status",
    get=repository.get_contribution_candidate,
    update_status=lambda s, i, v: repository.update_contribution_candidate(s, i, planning_status=v),
    approved_value=PlanningApprovalStatus.APPROVED,
    rejected_value=PlanningApprovalStatus.REJECTED,
    changes_requested_value=PlanningApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_METHODOLOGY_SPEC = approval_dispatch.EntitySpec(
    label="MethodologyPlan",
    stage_prefix="METHODOLOGY_APPROVAL",
    status_attr="planning_status",
    get=repository.get_methodology_plan,
    update_status=lambda s, i, v: repository.update_methodology_plan(s, i, planning_status=v),
    approved_value=PlanningApprovalStatus.APPROVED,
    rejected_value=PlanningApprovalStatus.REJECTED,
    changes_requested_value=PlanningApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_DATASET_REQUIREMENTS_SPEC = approval_dispatch.EntitySpec(
    label="DatasetRequirements",
    stage_prefix="DATASET_REQUIREMENTS_APPROVAL",
    status_attr="planning_status",
    get=repository.get_dataset_requirements,
    update_status=lambda s, i, v: repository.update_dataset_requirements(s, i, planning_status=v),
    approved_value=PlanningApprovalStatus.APPROVED,
    rejected_value=PlanningApprovalStatus.REJECTED,
    changes_requested_value=PlanningApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_EXPERIMENTAL_DESIGN_SPEC = approval_dispatch.EntitySpec(
    label="ExperimentalDesign",
    stage_prefix="EXPERIMENTAL_DESIGN_APPROVAL",
    status_attr="planning_status",
    get=repository.get_experimental_design,
    update_status=lambda s, i, v: repository.update_experimental_design(s, i, planning_status=v),
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
# ResearchQuestion
# ===========================================================================


def approve_research_question(question_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _QUESTION_SPEC, question_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_QUESTION_SPEC.approved_value,
        event_type="planning.research_question_approved", session_factory=session_factory,
    )


def reject_research_question(question_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _QUESTION_SPEC, question_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_QUESTION_SPEC.rejected_value,
        event_type="planning.research_question_rejected", session_factory=session_factory,
    )


def request_changes_research_question(question_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _QUESTION_SPEC, question_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_QUESTION_SPEC.changes_requested_value,
        event_type="planning.research_question_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# ContributionCandidate
# ===========================================================================


def approve_contribution(contribution_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _CONTRIBUTION_SPEC, contribution_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_CONTRIBUTION_SPEC.approved_value,
        event_type="planning.contribution_approved", session_factory=session_factory,
    )


def reject_contribution(contribution_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _CONTRIBUTION_SPEC, contribution_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_CONTRIBUTION_SPEC.rejected_value,
        event_type="planning.contribution_rejected", session_factory=session_factory,
    )


def request_changes_contribution(contribution_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _CONTRIBUTION_SPEC, contribution_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_CONTRIBUTION_SPEC.changes_requested_value,
        event_type="planning.contribution_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# MethodologyPlan
# ===========================================================================


def approve_methodology_plan(plan_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _METHODOLOGY_SPEC, plan_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_METHODOLOGY_SPEC.approved_value,
        event_type="planning.methodology_approved", session_factory=session_factory,
    )


def reject_methodology_plan(plan_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _METHODOLOGY_SPEC, plan_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_METHODOLOGY_SPEC.rejected_value,
        event_type="planning.methodology_rejected", session_factory=session_factory,
    )


def request_changes_methodology_plan(plan_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _METHODOLOGY_SPEC, plan_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_METHODOLOGY_SPEC.changes_requested_value,
        event_type="planning.methodology_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# DatasetRequirements
# ===========================================================================


def approve_dataset_requirements(requirements_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _DATASET_REQUIREMENTS_SPEC, requirements_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_DATASET_REQUIREMENTS_SPEC.approved_value,
        event_type="planning.dataset_requirements_approved", session_factory=session_factory,
    )


def reject_dataset_requirements(requirements_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _DATASET_REQUIREMENTS_SPEC, requirements_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_DATASET_REQUIREMENTS_SPEC.rejected_value,
        event_type="planning.dataset_requirements_rejected", session_factory=session_factory,
    )


def request_changes_dataset_requirements(requirements_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _DATASET_REQUIREMENTS_SPEC, requirements_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_DATASET_REQUIREMENTS_SPEC.changes_requested_value,
        event_type="planning.dataset_requirements_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# ExperimentalDesign
# ===========================================================================


def approve_experimental_design(design_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENTAL_DESIGN_SPEC, design_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_EXPERIMENTAL_DESIGN_SPEC.approved_value,
        event_type="planning.experimental_design_approved", session_factory=session_factory,
    )


def reject_experimental_design(design_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENTAL_DESIGN_SPEC, design_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_EXPERIMENTAL_DESIGN_SPEC.rejected_value,
        event_type="planning.experimental_design_rejected", session_factory=session_factory,
    )


def request_changes_experimental_design(design_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return _decide(
        _EXPERIMENTAL_DESIGN_SPEC, design_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_EXPERIMENTAL_DESIGN_SPEC.changes_requested_value,
        event_type="planning.experimental_design_changes_requested", session_factory=session_factory,
    )


def get_pending_planning_approvals(session: Session, project_id: int) -> list[Approval]:
    """All pending approvals in a project whose stage key belongs to this
    layer's five new gate types. Does NOT include `NOVELTY_APPROVAL:`
    (still exclusively `researchos.intelligence.approval`'s) or any
    `researchos.workflow` stage-transition/admin-action approval."""
    prefixes = (
        _QUESTION_SPEC.stage_prefix,
        _CONTRIBUTION_SPEC.stage_prefix,
        _METHODOLOGY_SPEC.stage_prefix,
        _DATASET_REQUIREMENTS_SPEC.stage_prefix,
        _EXPERIMENTAL_DESIGN_SPEC.stage_prefix,
    )
    return approval_dispatch.pending_for_prefixes(session, project_id, prefixes)
