"""Human execution approval for Phase 8B-1.

Reuses the exact same `Approval`/`AuditEvent` tables and
`researchos.workflow.policy.is_human_actor` every other phase's
approval mechanism is built on — `repository.create_approval_request`/
`record_approval_decision`/`get_approval_by_stage` are the very
primitives `researchos.db.approval_dispatch.decide()` itself calls, so
this is not a second approval framework, only a second *caller* of the
first one's underlying primitives, following the exact same
lazily-create-the-pending-row-on-first-decision pattern
`approval_dispatch._get_or_create_pending_approval` already
established (no `Approval` row exists for a `Run` until someone first
tries to decide it).

It deliberately does NOT go through
`researchos.db.approval_dispatch.EntitySpec`/`decide()` the way
`researchos.intelligence.approval`/`researchos.planning.approval`/
`researchos.specification.approval` all do, because that convenience
wrapper's design assumes the approval decision directly overwrites the
entity's own status column (`status_attr`) with one of three symmetric
values. A `Run`'s `status` is a *lifecycle* (`CREATED` -> `QUEUED` ->
`RUNNING` -> ...), not an approval-decision vocabulary — there is no
`RunStatus.APPROVED`, because "approved" doesn't replace a `Run`'s
lifecycle position, it only unlocks the `CREATED -> QUEUED` edge (see
`researchos.execution.orchestrator.execute_run`). Reusing the wrapper
here would mean inventing a `RunStatus` value that means "approved but
still hasn't executed," which collides with `CREATED`'s own meaning.
So this module calls the shared repository primitives directly instead
— still one `Approval` table, still one audit trail, still the same
`is_human_actor` human-only rule, just without a status value to
mirror the decision onto.

Gate identity: `EXECUTION_APPROVAL:<run_id>` — chosen over
`EXECUTION_APPROVAL:<execution_request_id>` because Phase 8B-1 has no
separate `ExecutionRequest` entity (see `Run`'s own docstring in
`researchos.db.models` for why); the `Run` row itself, created in
`RunStatus.CREATED`, *is* the execution request this gate authorizes.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.models import Approval, ApprovalDecision
from ..planning.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError
from ..workflow.policy import is_human_actor

EXECUTION_APPROVAL_STAGE_PREFIX = "EXECUTION_APPROVAL"


def stage_key(run_id: int) -> str:
    return f"{EXECUTION_APPROVAL_STAGE_PREFIX}:{run_id}"


def _get_or_create_pending(session: Session, run, key: str) -> Approval:
    existing = repository.get_approval_by_stage(session, run.project_id, key)
    if existing is None:
        return repository.create_approval_request(session, project_id=run.project_id, stage=key)
    if existing.decision == ApprovalDecision.PENDING:
        return existing
    if existing.decision == ApprovalDecision.CHANGES_REQUESTED:
        # A changes-requested round is not terminal — open a fresh
        # pending round, exactly as approval_dispatch does.
        return repository.create_approval_request(session, project_id=run.project_id, stage=key)
    raise ApprovalAlreadyDecidedError(f"Execution approval for Run {run.id} was already decided ({existing.decision.value}).")


def _decide(
    run_id: int, actor: str, comment: Optional[str], *, decision: ApprovalDecision, event_type: str,
    session_factory: Optional[sessionmaker],
) -> Approval:
    if not is_human_actor(actor):
        raise HumanOnlyActionError(
            f"'{actor}' cannot decide this approval — the LLM cannot approve its own execution request; "
            "execution approval must be made by a human."
        )
    with session_scope(session_factory) as session:
        run = repository.get_run(session, run_id)
        if run is None:
            raise CandidateNotFoundError(f"Run {run_id} does not exist.")
        key = stage_key(run_id)
        approval = _get_or_create_pending(session, run, key)
        updated = repository.record_approval_decision(session, approval.id, decision=decision, comment=comment)
        repository.append_audit_event(
            session, project_id=run.project_id, actor=actor, event_type=event_type,
            description=f"{decision.value} execution approval for Run #{run_id}" + (f": {comment}" if comment else ""),
            metadata={"run_id": run_id, "approval_id": approval.id, "decision": decision.value, "comment": comment},
        )
        return updated


def approve_run_execution(
    run_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> Approval:
    """Record human approval to execute `run_id`. Does NOT itself start
    execution or transition the `Run`'s lifecycle — see
    `researchos.execution.orchestrator.execute_run`, which checks this
    decision before calling `researchos.execution.runs.queue_run`."""
    return _decide(
        run_id, actor, comment, decision=ApprovalDecision.APPROVED,
        event_type="execution.execution_approved", session_factory=session_factory,
    )


def reject_run_execution(
    run_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> Approval:
    return _decide(
        run_id, actor, comment, decision=ApprovalDecision.REJECTED,
        event_type="execution.execution_rejected", session_factory=session_factory,
    )


def request_changes_run_execution(
    run_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None
) -> Approval:
    return _decide(
        run_id, actor, comment, decision=ApprovalDecision.CHANGES_REQUESTED,
        event_type="execution.execution_changes_requested", session_factory=session_factory,
    )


def is_execution_approved(run_id: int, *, session_factory: Optional[sessionmaker] = None) -> bool:
    """Whether `run_id` currently has a decided, `APPROVED` execution
    approval — the single check `researchos.execution.orchestrator.
    execute_run` gates on before it will queue a `Run`. Returns `False`
    (never raises for "not yet decided") when no approval has been
    requested/decided at all — the natural pre-approval state of a
    freshly-created `Run`."""
    with session_scope(session_factory) as session:
        run = repository.get_run(session, run_id)
        if run is None:
            raise CandidateNotFoundError(f"Run {run_id} does not exist.")
        approval = repository.get_approval_by_stage(session, run.project_id, stage_key(run_id))
        return approval is not None and approval.decision == ApprovalDecision.APPROVED


def get_pending_execution_approvals(session: Session, project_id: int) -> list[Approval]:
    return [
        a for a in repository.list_approvals(session, project_id)
        if a.decision == ApprovalDecision.PENDING and a.stage.startswith(f"{EXECUTION_APPROVAL_STAGE_PREFIX}:")
    ]
