"""The Approval Center's dispatch table.

`researchos.db.repository.list_approvals`/`researchos.workflow.
service.get_pending_approvals` already return every `Approval` row
for a project, across every layer, in one call — this module's only
job is to look at one `Approval.stage` string (format
`"<PREFIX>:<entity_id>"`, or a workflow transition key
`"<FROM_STAGE>-><TO_STAGE>"`, or `"ARCHIVE_PROJECT"`/`"REJECT_PROJECT"`)
and dispatch an approve/reject/request-changes action to the ONE
existing domain function that actually owns that decision. It contains
no approval policy of its own — every precondition (human-only actor,
`READY_FOR_HUMAN_REVIEW` before a review can be approved, a
`HUMAN_APPROVED` review before a claim can be approved, ...) is
enforced by the domain function being called, not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.execution import approval as execution_approval
from researchos.intelligence import approval as intelligence_approval
from researchos.analysis import approval as analysis_approval
from researchos.planning import approval as planning_approval
from researchos.specification import approval as specification_approval
from researchos.workflow import service as workflow_service

WORKFLOW_TRANSITION_SEPARATOR = "->"
WORKFLOW_ACTION_KEYS = {"ARCHIVE_PROJECT", "REJECT_PROJECT"}


@dataclass(frozen=True)
class ApprovalHandler:
    entity_type: str
    approve: Callable[..., object]
    reject: Callable[..., object]
    request_changes: Callable[..., object]
    get_entity_status: Callable[[Session, int], str]


def _status_getter(get_entity: Callable[[Session, int], object], status_attr: str) -> Callable[[Session, int], str]:
    def _get(session: Session, entity_id: int) -> str:
        entity = get_entity(session, entity_id)
        if entity is None:
            return "unknown"
        value = getattr(entity, status_attr)
        return value.value if hasattr(value, "value") else str(value)

    return _get


_HANDLERS: dict[str, ApprovalHandler] = {
    "CLAIM_APPROVAL": ApprovalHandler(
        entity_type="AnalysisClaim",
        approve=intelligence_approval.approve_claim,
        reject=intelligence_approval.reject_claim,
        request_changes=intelligence_approval.request_changes_claim,
        get_entity_status=_status_getter(repository.get_analysis_claim, "approval_status"),
    ),
    "GAP_APPROVAL": ApprovalHandler(
        entity_type="ResearchGap",
        approve=intelligence_approval.approve_gap,
        reject=intelligence_approval.reject_gap,
        request_changes=intelligence_approval.request_changes_gap,
        get_entity_status=_status_getter(repository.get_research_gap, "status"),
    ),
    "NOVELTY_APPROVAL": ApprovalHandler(
        entity_type="NoveltyAssessment",
        approve=intelligence_approval.approve_novelty_assessment,
        reject=intelligence_approval.reject_novelty_assessment,
        request_changes=intelligence_approval.request_changes_novelty_assessment,
        get_entity_status=_status_getter(repository.get_novelty_assessment, "candidate_status"),
    ),
    "RESEARCH_QUESTION_APPROVAL": ApprovalHandler(
        entity_type="ResearchQuestion",
        approve=planning_approval.approve_research_question,
        reject=planning_approval.reject_research_question,
        request_changes=planning_approval.request_changes_research_question,
        get_entity_status=_status_getter(repository.get_research_question, "planning_status"),
    ),
    "CONTRIBUTION_APPROVAL": ApprovalHandler(
        entity_type="ContributionCandidate",
        approve=planning_approval.approve_contribution,
        reject=planning_approval.reject_contribution,
        request_changes=planning_approval.request_changes_contribution,
        get_entity_status=_status_getter(repository.get_contribution_candidate, "planning_status"),
    ),
    "METHODOLOGY_APPROVAL": ApprovalHandler(
        entity_type="MethodologyPlan",
        approve=planning_approval.approve_methodology_plan,
        reject=planning_approval.reject_methodology_plan,
        request_changes=planning_approval.request_changes_methodology_plan,
        get_entity_status=_status_getter(repository.get_methodology_plan, "planning_status"),
    ),
    "DATASET_REQUIREMENTS_APPROVAL": ApprovalHandler(
        entity_type="DatasetRequirements",
        approve=planning_approval.approve_dataset_requirements,
        reject=planning_approval.reject_dataset_requirements,
        request_changes=planning_approval.request_changes_dataset_requirements,
        get_entity_status=_status_getter(repository.get_dataset_requirements, "planning_status"),
    ),
    "EXPERIMENTAL_DESIGN_APPROVAL": ApprovalHandler(
        entity_type="ExperimentalDesign",
        approve=planning_approval.approve_experimental_design,
        reject=planning_approval.reject_experimental_design,
        request_changes=planning_approval.request_changes_experimental_design,
        get_entity_status=_status_getter(repository.get_experimental_design, "planning_status"),
    ),
    "DATASET_VERSION_APPROVAL": ApprovalHandler(
        entity_type="DatasetVersion",
        approve=specification_approval.approve_dataset_version,
        reject=specification_approval.reject_dataset_version,
        request_changes=specification_approval.request_changes_dataset_version,
        get_entity_status=_status_getter(repository.get_dataset_version, "lifecycle_status"),
    ),
    "EXPERIMENT_SPECIFICATION_APPROVAL": ApprovalHandler(
        entity_type="ExperimentSpecification",
        approve=specification_approval.approve_experiment_specification,
        reject=specification_approval.reject_experiment_specification,
        request_changes=specification_approval.request_changes_experiment_specification,
        get_entity_status=_status_getter(repository.get_experiment_specification, "planning_status"),
    ),
    "EXECUTION_APPROVAL": ApprovalHandler(
        entity_type="Run",
        approve=execution_approval.approve_run_execution,
        reject=execution_approval.reject_run_execution,
        request_changes=execution_approval.request_changes_run_execution,
        # Execution approval never itself transitions the Run (see
        # execution/approval.py's own docstring) — the Run's own
        # status is genuinely unchanged by this decision, and
        # reporting it as-is is the accurate "resulting state".
        get_entity_status=_status_getter(repository.get_run, "status"),
    ),
    "SCIENTIFIC_REVIEW_APPROVAL": ApprovalHandler(
        entity_type="ScientificReview",
        approve=analysis_approval.approve_scientific_review,
        reject=analysis_approval.reject_scientific_review,
        request_changes=analysis_approval.request_changes_scientific_review,
        get_entity_status=_status_getter(repository.get_scientific_review, "status"),
    ),
    "SCIENTIFIC_CLAIM_APPROVAL": ApprovalHandler(
        entity_type="ScientificClaim",
        approve=analysis_approval.approve_scientific_claim,
        reject=analysis_approval.reject_scientific_claim,
        request_changes=analysis_approval.request_changes_scientific_claim,
        get_entity_status=_status_getter(repository.get_scientific_claim, "approval_status"),
    ),
}


def parse_stage(stage: str) -> tuple[str, Optional[int]]:
    """Returns `(entity_type, entity_id)` for display purposes — never
    raises on an unrecognized shape, since the Approval Log must still
    render every row even if a future layer adds a stage shape this
    module does not yet know about."""
    if WORKFLOW_TRANSITION_SEPARATOR in stage:
        return "WorkflowTransition", None
    if stage in WORKFLOW_ACTION_KEYS:
        return "WorkflowAction", None
    prefix, sep, rest = stage.partition(":")
    if not sep:
        return "Unknown", None
    handler = _HANDLERS.get(prefix)
    entity_type = handler.entity_type if handler is not None else prefix
    try:
        return entity_type, int(rest)
    except ValueError:
        return entity_type, None


def act_on_approval(
    session: Session, project_id: int, approval_id: int, action: str, actor: str, comment: Optional[str],
    *, session_factory: Optional[sessionmaker] = None,
) -> tuple[object, str]:
    """Dispatches `action` (`"approve"`/`"reject"`/`"request_changes"`)
    for one `Approval` row to the exactly one domain function that
    owns that decision. Returns `(updated_approval, entity_status)`.

    Raises `ValueError` for a stage shape this dispatcher does not
    recognize (surfaced by the route handler as 400) — every other
    error (not-found, already-decided, human-only, review-not-ready,
    claim-not-supported-by-review, ...) propagates unchanged from the
    domain function itself, so the API's structured-error mapping in
    `errors.py` handles it exactly like it handles that same error
    raised anywhere else in ResearchOS.
    """
    approval = repository.get_approval(session, approval_id)
    if approval is None or approval.project_id != project_id:
        raise LookupError(f"Approval {approval_id} does not exist in project {project_id}.")
    stage = approval.stage

    if WORKFLOW_TRANSITION_SEPARATOR in stage or stage in WORKFLOW_ACTION_KEYS:
        action_fn = {"approve": workflow_service.approve, "reject": workflow_service.reject,
                     "request_changes": workflow_service.request_changes}[action]
        updated_approval = action_fn(approval_id, actor, comment, session_factory=session_factory)
        return updated_approval, updated_approval.decision.value

    prefix, sep, rest = stage.partition(":")
    if not sep:
        raise ValueError(f"Approval {approval_id} has an unrecognized stage shape: {stage!r}.")
    handler = _HANDLERS.get(prefix)
    if handler is None:
        raise ValueError(f"Approval {approval_id} has an unrecognized stage prefix: {prefix!r}.")
    entity_id = int(rest)
    action_fn = {"approve": handler.approve, "reject": handler.reject, "request_changes": handler.request_changes}[action]
    action_fn(entity_id, actor, comment, session_factory=session_factory)
    # The mutation above committed through its own session (each
    # domain approval function manages its own `session_scope`) — this
    # request-scoped `session` already has `approval` (and possibly
    # the entity) cached in its identity map from the lookup above, and
    # with `expire_on_commit=False` a plain re-`get()` would silently
    # return that stale, pre-decision snapshot. Rolling back this
    # session's own (write-free) transaction forces the next read to
    # start a fresh transaction that sees the just-committed change.
    session.rollback()
    updated_approval = repository.get_approval(session, approval_id)
    entity_status = handler.get_entity_status(session, entity_id)
    return updated_approval, entity_status
