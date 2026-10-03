"""Domain errors for the workflow engine.

Kept separate from `researchos.db.errors` deliberately: these describe
workflow-specific rule violations (an illegal transition, a missing
approval, an agent attempting a human-only action, ...), not generic
persistence concerns. `ProjectNotFoundError` mirrors
`researchos.db.errors.NotFoundError` for the one lookup the workflow
layer performs directly; other `researchos.db.errors` (e.g.
`ValidationError` from a blank actor string, `IntegrityConstraintError`
from a rare race on a unique constraint) may still propagate unchanged
from underlying repository calls — they are not workflow-specific
concerns and are not redundantly re-wrapped here.

No error message in this module ever includes a secret — none of the
workflow layer's inputs are secrets in the first place (project ids,
stage names, actor labels, human-authored reasons/comments).
"""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for all normalized workflow-engine errors."""


class ProjectNotFoundError(WorkflowError):
    """No `ResearchProject` exists with the given id."""


class InvalidTransitionError(WorkflowError):
    """The requested stage change is not a legal edge in the transition graph.

    Covers: a no-op (target equals current stage), an illegal forward
    jump (skipping one or more canonical stages), or a target that is
    not a recognized `WorkflowStage` value at all.
    """


class InvalidWorkflowStateError(WorkflowError):
    """The project's persisted state cannot be interpreted as a valid workflow state.

    Covers a `current_stage` value that does not parse as a
    `WorkflowStage`, an administrative action attempted from a status it
    does not apply to (e.g. resuming a project that isn't paused), and
    an approval record whose encoded stage/action key is unrecognized.
    """


class ApprovalRequiredError(WorkflowError):
    """The transition is gated and no prior approval authorizes it.

    Raised by `transition()` for any `APPROVAL_REQUIRED`/`HUMAN_ONLY`
    edge — `transition()` never itself creates a pending approval or
    silently waits; use `request_transition()` to do that, then
    `approve()` it.
    """


class ApprovalNotFoundError(WorkflowError):
    """No `Approval` exists with the given id."""


class ApprovalAlreadyDecidedError(WorkflowError):
    """The approval has already been approved, rejected, or had changes requested."""


class HumanOnlyActionError(WorkflowError):
    """An agent actor attempted an action reserved for human actors.

    Covers both: an agent attempting to even *request* a `HUMAN_ONLY`
    transition, and any actor other than a human attempting to decide
    (`approve`/`reject`/`request_changes`) a pending approval — deciding
    an approval is always a human act, regardless of the gated action's
    policy tier.
    """


class ProjectArchivedError(WorkflowError):
    """The project is archived; no further workflow transitions are allowed."""


class ProjectPausedError(WorkflowError):
    """The project is paused; call `resume_project()` before transitioning."""


class ProjectRejectedError(WorkflowError):
    """The project is rejected; no further workflow transitions are allowed."""


class ConcurrentModificationError(WorkflowError):
    """The project's stage changed since the caller last read it.

    Raised only when the caller opts in by passing
    `expected_current_stage=...` to `transition()` /
    `request_transition()` — a basic optimistic-concurrency check, not
    distributed locking. See `docs/PHASE4_WORKFLOW.md`.
    """
