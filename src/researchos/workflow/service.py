"""The workflow service: the single authority for research-project stage
transitions and approval-gated actions.

Two tiers of function in this module, matching `researchos.db.repository`'s
own layering:

- **Primitives** (`get_current_stage`, `get_allowed_transitions`,
  `can_transition`, `request_approval`, `get_pending_approvals`) take an
  explicit `Session` and never commit — composable within a caller's own
  transaction, exactly like `researchos.db.repository` functions.
- **Orchestrated operations** (`request_transition`, `transition`,
  `pause_project`, `resume_project`, `archive_project`,
  `reject_project`, `approve`, `reject`, `request_changes`) own their
  transaction boundary via `session_scope()` — each public call is one
  atomic unit: if any step fails (including the audit event), nothing
  from that call is persisted.

The LLM never decides any of this: `researchos.workflow.policy` is pure,
deterministic Python, and every mutation here is driven by an explicit
caller-supplied `actor` string and `reason`/`comment` — never inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import Approval, ApprovalDecision, ProjectStatus, ResearchProject
from .errors import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalRequiredError,
    ConcurrentModificationError,
    HumanOnlyActionError,
    InvalidWorkflowStateError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectPausedError,
    ProjectRejectedError,
    WorkflowError,
)
from .policy import (
    ARCHIVE_POLICY,
    PAUSE_POLICY,
    REJECT_POLICY,
    RESUME_POLICY,
    Policy,
    get_policy,
    is_human_actor,
)
from .stages import STAGE_INDEX, STAGE_ORDER, WorkflowStage, earlier_stages, next_stage

StageLike = Union[WorkflowStage, str]

_TRANSITION_KEY_SEPARATOR = "->"
_ARCHIVE_ACTION_KEY = "ARCHIVE_PROJECT"
_REJECT_ACTION_KEY = "REJECT_PROJECT"


@dataclass(frozen=True)
class AllowedTransition:
    target_stage: WorkflowStage
    policy: Policy
    direction: str  # "forward" | "backward"


@dataclass(frozen=True)
class TransitionOutcome:
    """Result of `request_transition()` / `archive_project()` / `reject_project()`.

    Exactly one of `project` / `approval` is populated: `applied=True`
    means the change happened immediately (`project` reflects the new
    state); `applied=False` means a pending `Approval` was created
    instead and nothing has changed yet.
    """

    applied: bool
    project: Optional[ResearchProject]
    approval: Optional[Approval]


# ===========================================================================
# Internal helpers
# ===========================================================================


def _get_project_or_raise(session: Session, project_id: int) -> ResearchProject:
    project = repository.get_project(session, project_id)
    if project is None:
        raise ProjectNotFoundError(f"ResearchProject {project_id} does not exist.")
    return project


def _coerce_stage(value: StageLike) -> WorkflowStage:
    if isinstance(value, WorkflowStage):
        return value
    try:
        return WorkflowStage(value)
    except ValueError as exc:
        raise InvalidWorkflowStateError(f"'{value}' is not a recognized workflow stage.") from exc


def _read_current_stage(project: ResearchProject) -> WorkflowStage:
    """The project's current stage, treating an unset column as STAGE_01_IDEA.

    `current_stage` is NULL for every project until its first workflow
    transition — this function is the one place that implicit default
    is made explicit. Any other, unrecognized string is a corrupted or
    pre-workflow-engine value and raises rather than guessing.
    """
    if project.current_stage is None:
        return STAGE_ORDER[0]
    try:
        return WorkflowStage(project.current_stage)
    except ValueError as exc:
        raise InvalidWorkflowStateError(
            f"Project {project.id} has an unrecognized current_stage value: {project.current_stage!r}."
        ) from exc


def _ensure_transitionable(project: ResearchProject) -> None:
    """Guard used before any *stage* transition (not administrative actions)."""
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectArchivedError(f"Project {project.id} is archived; no further transitions are allowed.")
    if project.status == ProjectStatus.REJECTED:
        raise ProjectRejectedError(f"Project {project.id} is rejected; no further transitions are allowed.")
    if project.status == ProjectStatus.PAUSED:
        raise ProjectPausedError(f"Project {project.id} is paused; call resume_project() first.")


def _ensure_not_terminal(project: ResearchProject) -> None:
    """Guard used before administrative actions (archive/reject/pause)."""
    if project.status == ProjectStatus.ARCHIVED:
        raise ProjectArchivedError(f"Project {project.id} is already archived.")
    if project.status == ProjectStatus.REJECTED:
        raise ProjectRejectedError(f"Project {project.id} is already rejected.")


def _encode_transition_key(from_stage: WorkflowStage, to_stage: WorkflowStage) -> str:
    return f"{from_stage.value}{_TRANSITION_KEY_SEPARATOR}{to_stage.value}"


def _decode_transition_key(key: str) -> Optional[tuple[WorkflowStage, WorkflowStage]]:
    """Decode an `Approval.stage` value back into (from_stage, to_stage).

    Returns None if `key` is an administrative-action key (e.g.
    `"ARCHIVE_PROJECT"`) rather than a stage-transition key.
    """
    if _TRANSITION_KEY_SEPARATOR not in key:
        return None
    from_raw, _, to_raw = key.partition(_TRANSITION_KEY_SEPARATOR)
    return _coerce_stage(from_raw), _coerce_stage(to_raw)


def _apply_stage_transition(
    session: Session,
    project: ResearchProject,
    from_stage: WorkflowStage,
    to_stage: WorkflowStage,
    actor: str,
    reason: Optional[str],
    *,
    approval: Optional[Approval] = None,
) -> ResearchProject:
    """Persist the stage change and its audit event as one unit.

    Update-then-audit ordering matters: if the audit event fails
    validation (e.g. a blank actor), it raises *before* being added to
    the session, and the caller's `session_scope()` rolls back the
    already-flushed stage update too — see
    `docs/PHASE4_WORKFLOW.md`'s atomicity section and
    `tests/workflow/test_atomicity.py`.
    """
    repository.update_project(session, project.id, current_stage=to_stage.value)
    metadata: dict[str, Any] = {
        "previous_stage": from_stage.value,
        "new_stage": to_stage.value,
        "transition_type": "forward" if STAGE_INDEX[to_stage] > STAGE_INDEX[from_stage] else "backward",
        "reason": reason,
    }
    if approval is not None:
        metadata["approval_id"] = approval.id
    repository.append_audit_event(
        session,
        project_id=project.id,
        event_type="workflow.transition",
        actor=actor,
        description=f"Moved from {from_stage.value} to {to_stage.value}" + (f": {reason}" if reason else ""),
        metadata=metadata,
    )
    return project


def _apply_archive(session: Session, project: ResearchProject, actor: str, comment: Optional[str]) -> ResearchProject:
    repository.update_project(session, project.id, status=ProjectStatus.ARCHIVED)
    repository.append_audit_event(
        session,
        project_id=project.id,
        event_type="workflow.project_archived",
        actor=actor,
        description=comment,
        metadata={"comment": comment},
    )
    return project


def _apply_reject(session: Session, project: ResearchProject, actor: str, comment: Optional[str]) -> ResearchProject:
    repository.update_project(session, project.id, status=ProjectStatus.REJECTED)
    repository.append_audit_event(
        session,
        project_id=project.id,
        event_type="workflow.project_rejected",
        actor=actor,
        description=comment,
        metadata={"comment": comment},
    )
    return project


# ===========================================================================
# Primitives (explicit session, no commit)
# ===========================================================================


def get_current_stage(session: Session, project_id: int) -> WorkflowStage:
    project = _get_project_or_raise(session, project_id)
    return _read_current_stage(project)


def get_allowed_transitions(session: Session, project_id: int) -> list[AllowedTransition]:
    """Every structurally valid destination stage right now.

    Includes gated destinations (approval-required or human-only), not
    only ones immediately executable without approval — use
    `can_transition()` to check the latter. Returns an empty list for a
    paused, archived, or rejected project: no stage transition is
    currently valid until it is resumed (or, for archived/rejected,
    never — those are terminal).
    """
    project = _get_project_or_raise(session, project_id)
    if project.status != ProjectStatus.ACTIVE:
        return []
    current = _read_current_stage(project)
    results: list[AllowedTransition] = []
    forward = next_stage(current)
    if forward is not None:
        from .policy import FORWARD_GATE_POLICY

        results.append(AllowedTransition(forward, FORWARD_GATE_POLICY[forward], "forward"))
    for earlier in earlier_stages(current):
        results.append(AllowedTransition(earlier, Policy.APPROVAL_REQUIRED, "backward"))
    return results


def can_transition(session: Session, project_id: int, target_stage: StageLike) -> bool:
    """True iff calling `transition()` right now, with no pending approval,
    would succeed immediately (i.e. the edge is legal AND AUTO_ALLOWED).

    A gated-but-legal destination (approval required or human-only)
    returns False here even though `request_transition()` would
    successfully create a pending approval for it — see
    `get_allowed_transitions()` for the full set of legal destinations.
    """
    try:
        project = _get_project_or_raise(session, project_id)
        _ensure_transitionable(project)
        from_stage = _read_current_stage(project)
        target = _coerce_stage(target_stage)
        policy = get_policy(from_stage, target)
    except WorkflowError:
        return False
    return policy is Policy.AUTO_ALLOWED


def request_approval(
    session: Session,
    project_id: int,
    stage_key: str,
    actor: str,
    reason: Optional[str] = None,
) -> Approval:
    """Create a pending approval request and its audit event.

    Low-level primitive: does not commit, does not itself apply
    anything. `stage_key` is either an encoded `"FROM->TO"` transition
    key (see `_encode_transition_key`) or an administrative-action key
    (`"ARCHIVE_PROJECT"`, `"REJECT_PROJECT"`).
    """
    project = _get_project_or_raise(session, project_id)
    approval = repository.create_approval_request(session, project_id=project.id, stage=stage_key, comment=reason)
    repository.append_audit_event(
        session,
        project_id=project.id,
        event_type="workflow.approval_requested",
        actor=actor,
        description=f"Requested approval for '{stage_key}'" + (f": {reason}" if reason else ""),
        metadata={"approval_id": approval.id, "stage_key": stage_key, "reason": reason},
    )
    return approval


def get_pending_approvals(session: Session, project_id: Optional[int] = None) -> list[Approval]:
    """All approvals still awaiting a decision, optionally scoped to one project."""
    if project_id is not None:
        _get_project_or_raise(session, project_id)
        return [a for a in repository.list_approvals(session, project_id) if a.decision == ApprovalDecision.PENDING]
    stmt = select(Approval).where(Approval.decision == ApprovalDecision.PENDING).order_by(Approval.id)
    return list(session.scalars(stmt))


# ===========================================================================
# Orchestrated operations (own their transaction)
# ===========================================================================


def request_transition(
    project_id: int,
    target_stage: StageLike,
    actor: str,
    reason: Optional[str] = None,
    *,
    expected_current_stage: Optional[StageLike] = None,
    session_factory: Optional[sessionmaker] = None,
) -> TransitionOutcome:
    """Propose a stage transition.

    Applies immediately (and returns `applied=True`) for an
    `AUTO_ALLOWED` edge. For `APPROVAL_REQUIRED`/`HUMAN_ONLY` edges,
    creates a pending `Approval` instead (`applied=False`) — nothing
    changes until a human calls `approve()`. Raises `HumanOnlyActionError`
    immediately if an agent actor attempts to even request a
    `HUMAN_ONLY` transition.
    """
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        _ensure_transitionable(project)
        from_stage = _read_current_stage(project)
        target = _coerce_stage(target_stage)

        if expected_current_stage is not None:
            expected = _coerce_stage(expected_current_stage)
            if expected != from_stage:
                raise ConcurrentModificationError(
                    f"Project {project_id} is at {from_stage.value}, not the expected "
                    f"{expected.value}; reload the project's current stage and retry."
                )

        policy = get_policy(from_stage, target)

        if policy is Policy.HUMAN_ONLY and not is_human_actor(actor):
            raise HumanOnlyActionError(
                f"'{actor}' cannot request a transition to {target.value}: this transition is HUMAN_ONLY."
            )

        if policy is Policy.AUTO_ALLOWED:
            updated = _apply_stage_transition(session, project, from_stage, target, actor, reason)
            return TransitionOutcome(applied=True, project=updated, approval=None)

        stage_key = _encode_transition_key(from_stage, target)
        approval = request_approval(session, project_id, stage_key, actor, reason)
        return TransitionOutcome(applied=False, project=None, approval=approval)


def transition(
    project_id: int,
    target_stage: StageLike,
    actor: str,
    reason: Optional[str] = None,
    *,
    expected_current_stage: Optional[StageLike] = None,
    session_factory: Optional[sessionmaker] = None,
) -> ResearchProject:
    """Authoritatively apply a stage transition right now, or fail.

    Unlike `request_transition()`, this never creates a pending
    approval: for a gated edge it always raises
    `ApprovalRequiredError`/`HumanOnlyActionError`, telling the caller
    to go through `request_transition()` + `approve()` instead. This is
    what makes the workflow engine (not any caller) the sole authority
    for whether a gated change has actually been authorized — approving
    a request is the only way a gated transition is ever applied (see
    `approve()`).
    """
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        _ensure_transitionable(project)
        from_stage = _read_current_stage(project)
        target = _coerce_stage(target_stage)

        if expected_current_stage is not None:
            expected = _coerce_stage(expected_current_stage)
            if expected != from_stage:
                raise ConcurrentModificationError(
                    f"Project {project_id} is at {from_stage.value}, not the expected "
                    f"{expected.value}; reload the project's current stage and retry."
                )

        policy = get_policy(from_stage, target)

        if policy is Policy.HUMAN_ONLY:
            raise HumanOnlyActionError(
                f"{target.value} is a HUMAN_ONLY transition; it can only be applied via "
                "request_transition() followed by a human approve() call, never a direct transition()."
            )
        if policy is Policy.APPROVAL_REQUIRED:
            raise ApprovalRequiredError(
                f"Transitioning to {target.value} requires approval; call request_transition() "
                "to create a pending approval, then approve() it."
            )
        return _apply_stage_transition(session, project, from_stage, target, actor, reason)


def pause_project(
    project_id: int, actor: str, reason: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> ResearchProject:
    """Pause a project (AUTO_ALLOWED — reversible, no approval needed)."""
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        _ensure_not_terminal(project)
        if project.status != ProjectStatus.ACTIVE:
            raise InvalidWorkflowStateError(
                f"Project {project_id} is not active (status={project.status.value}); cannot pause."
            )
        repository.update_project(session, project_id, status=ProjectStatus.PAUSED)
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="workflow.project_paused",
            actor=actor,
            description=reason,
            metadata={"reason": reason},
        )
        return project


def resume_project(
    project_id: int, actor: str, reason: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> ResearchProject:
    """Resume a paused project (AUTO_ALLOWED)."""
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        if project.status != ProjectStatus.PAUSED:
            raise InvalidWorkflowStateError(
                f"Project {project_id} is not paused (status={project.status.value}); cannot resume."
            )
        repository.update_project(session, project_id, status=ProjectStatus.ACTIVE)
        repository.append_audit_event(
            session,
            project_id=project_id,
            event_type="workflow.project_resumed",
            actor=actor,
            description=reason,
            metadata={"reason": reason},
        )
        return project


def archive_project(
    project_id: int, actor: str, reason: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> TransitionOutcome:
    """Request archival of a project (APPROVAL_REQUIRED).

    Always creates a pending approval — archiving is only actually
    applied once a human calls `approve()` on it.
    """
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        _ensure_not_terminal(project)
        approval = request_approval(session, project_id, _ARCHIVE_ACTION_KEY, actor, reason)
        return TransitionOutcome(applied=False, project=None, approval=approval)


def reject_project(
    project_id: int, actor: str, reason: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> TransitionOutcome:
    """Request rejection of a project's overall research direction (APPROVAL_REQUIRED)."""
    with session_scope(session_factory) as session:
        project = _get_project_or_raise(session, project_id)
        _ensure_not_terminal(project)
        approval = request_approval(session, project_id, _REJECT_ACTION_KEY, actor, reason)
        return TransitionOutcome(applied=False, project=None, approval=approval)


# ===========================================================================
# Approval decisions (own their transaction; always require a human actor)
# ===========================================================================


def _load_pending_approval_or_raise(session: Session, approval_id: int) -> Approval:
    approval = repository.get_approval(session, approval_id)
    if approval is None:
        raise ApprovalNotFoundError(f"Approval {approval_id} does not exist.")
    if approval.decision != ApprovalDecision.PENDING:
        raise ApprovalAlreadyDecidedError(f"Approval {approval_id} was already decided ({approval.decision.value}).")
    return approval


def approve(
    approval_id: int,
    actor: str,
    comment: Optional[str] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
) -> Approval:
    """Approve a pending request and atomically apply the underlying action.

    Deciding an approval is always a human act, regardless of the
    gated action's policy tier — raises `HumanOnlyActionError` for an
    agent actor.
    """
    with session_scope(session_factory) as session:
        if not is_human_actor(actor):
            raise HumanOnlyActionError(f"'{actor}' cannot approve requests; approval decisions must be made by a human.")
        approval = _load_pending_approval_or_raise(session, approval_id)
        project = _get_project_or_raise(session, approval.project_id)

        repository.record_approval_decision(
            session, approval_id, decision=ApprovalDecision.APPROVED, comment=comment
        )
        repository.append_audit_event(
            session,
            project_id=project.id,
            event_type="workflow.approval_approved",
            actor=actor,
            description=f"Approved request #{approval_id} ({approval.stage})" + (f": {comment}" if comment else ""),
            metadata={"approval_id": approval_id, "comment": comment},
        )

        decoded = _decode_transition_key(approval.stage)
        if decoded is not None:
            from_stage, to_stage = decoded
            _apply_stage_transition(session, project, from_stage, to_stage, actor, comment, approval=approval)
        elif approval.stage == _ARCHIVE_ACTION_KEY:
            _apply_archive(session, project, actor, comment)
        elif approval.stage == _REJECT_ACTION_KEY:
            _apply_reject(session, project, actor, comment)
        else:
            raise InvalidWorkflowStateError(
                f"Approval {approval_id} has an unrecognized stage/action key {approval.stage!r}."
            )

        return repository.get_approval(session, approval_id)


def reject(
    approval_id: int,
    actor: str,
    comment: Optional[str] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
) -> Approval:
    """Reject a pending request. The underlying change never happens; the
    project remains exactly as it was."""
    with session_scope(session_factory) as session:
        if not is_human_actor(actor):
            raise HumanOnlyActionError(f"'{actor}' cannot reject requests; approval decisions must be made by a human.")
        approval = _load_pending_approval_or_raise(session, approval_id)
        repository.record_approval_decision(
            session, approval_id, decision=ApprovalDecision.REJECTED, comment=comment
        )
        repository.append_audit_event(
            session,
            project_id=approval.project_id,
            event_type="workflow.approval_rejected",
            actor=actor,
            description=f"Rejected request #{approval_id} ({approval.stage})" + (f": {comment}" if comment else ""),
            metadata={"approval_id": approval_id, "comment": comment},
        )
        return repository.get_approval(session, approval_id)


def request_changes(
    approval_id: int,
    actor: str,
    comment: Optional[str] = None,
    *,
    session_factory: Optional[sessionmaker] = None,
) -> Approval:
    """Send a pending request back for changes, without approving or
    rejecting it outright. The underlying change never happens."""
    with session_scope(session_factory) as session:
        if not is_human_actor(actor):
            raise HumanOnlyActionError(
                f"'{actor}' cannot request changes on requests; approval decisions must be made by a human."
            )
        approval = _load_pending_approval_or_raise(session, approval_id)
        repository.record_approval_decision(
            session, approval_id, decision=ApprovalDecision.CHANGES_REQUESTED, comment=comment
        )
        repository.append_audit_event(
            session,
            project_id=approval.project_id,
            event_type="workflow.approval_changes_requested",
            actor=actor,
            description=f"Requested changes on #{approval_id} ({approval.stage})"
            + (f": {comment}" if comment else ""),
            metadata={"approval_id": approval_id, "comment": comment},
        )
        return repository.get_approval(session, approval_id)
