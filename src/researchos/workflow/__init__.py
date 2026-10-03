"""The ResearchOS workflow engine: deterministic, auditable, human-controlled
research-project stage transitions.

The LLM does not control workflow state directly. This package is pure
persistence-and-policy orchestration on top of `researchos.db` — nothing
here calls an LLM provider, runs an experiment, searches literature, or
does anything beyond deciding and recording *whether a state change is
allowed to happen*. See `docs/PHASE4_WORKFLOW.md` for the full design.

Import from this package, not from `researchos.workflow.service` /
`.policy` / `.stages` / `.errors` directly, though those submodules are
also stable public API surfaces.
"""

from .errors import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalRequiredError,
    ConcurrentModificationError,
    HumanOnlyActionError,
    InvalidTransitionError,
    InvalidWorkflowStateError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectPausedError,
    ProjectRejectedError,
    WorkflowError,
)
from .policy import Policy, get_policy, is_human_actor
from .service import (
    AllowedTransition,
    TransitionOutcome,
    approve,
    archive_project,
    can_transition,
    get_allowed_transitions,
    get_current_stage,
    get_pending_approvals,
    pause_project,
    reject,
    reject_project,
    request_approval,
    request_changes,
    request_transition,
    resume_project,
    transition,
)
from .stages import INITIAL_STAGE, STAGE_ORDER, WorkflowStage

__all__ = [
    # stages
    "WorkflowStage",
    "STAGE_ORDER",
    "INITIAL_STAGE",
    # policy
    "Policy",
    "get_policy",
    "is_human_actor",
    # service
    "AllowedTransition",
    "TransitionOutcome",
    "get_current_stage",
    "get_allowed_transitions",
    "can_transition",
    "request_transition",
    "transition",
    "pause_project",
    "resume_project",
    "archive_project",
    "reject_project",
    "request_approval",
    "get_pending_approvals",
    "approve",
    "reject",
    "request_changes",
    # errors
    "WorkflowError",
    "ProjectNotFoundError",
    "InvalidTransitionError",
    "InvalidWorkflowStateError",
    "ApprovalRequiredError",
    "ApprovalNotFoundError",
    "ApprovalAlreadyDecidedError",
    "HumanOnlyActionError",
    "ProjectArchivedError",
    "ProjectPausedError",
    "ProjectRejectedError",
    "ConcurrentModificationError",
]
