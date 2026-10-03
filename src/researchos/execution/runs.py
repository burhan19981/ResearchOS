"""`Run` lifecycle transitions: the deterministic transition table,
terminal-state immutability, and the audit trail for every state
change.

Every function here calls `researchos.db.repository.update_run_lifecycle`
with an explicit `expected_status` — never a blind write — so a
transition either atomically succeeds against the state the caller
observed, or raises. This module is what decides WHICH transitions are
allowed (the table below); the repository function alone only enforces
THAT the caller's expectation matched reality.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from ..db import repository
from ..db.engine import session_scope
from ..db.errors import ConcurrencyConflictError, NotFoundError
from ..db.models import Run, RunStatus
from .errors import InvalidRunStateError

TERMINAL_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT})

# The complete, deterministic transition table (Phase 8B-1 spec section
# 5) — every edge not listed here is refused, including any edge out of
# a terminal state. `QUEUED -> FAILED` was added in Phase 8B-2: once
# actual workspace preparation sits between QUEUED and RUNNING (see
# researchos.execution.orchestrator.execute_run), a preparation failure
# (e.g. cannot create the run's workspace directories) must still be
# able to reach a terminal state rather than leaving the Run stranded
# in QUEUED forever — this is the narrowest possible edge that
# satisfies "no Run stuck in a non-terminal state after a controlled
# failure" (Phase 8B-2 spec section 19) without reopening the
# deliberately-not-added pre-RUNNING *cancellation* question (section 21).
_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.QUEUED}),
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.TIMEOUT: frozenset(),
}


def _transition(
    session_factory: Optional[sessionmaker],
    run_id: int,
    *,
    from_status: RunStatus,
    to_status: RunStatus,
    actor: str,
    event_type: str,
    audit_metadata: Optional[dict[str, Any]] = None,
    **fields: Any,
) -> Run:
    if to_status not in _ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        raise InvalidRunStateError(
            f"Run {run_id} cannot transition {from_status.value} -> {to_status.value}: not an allowed edge "
            f"(from {from_status.value}, only {sorted(s.value for s in _ALLOWED_TRANSITIONS.get(from_status, ()))} "
            "are allowed)."
        )
    with session_scope(session_factory) as session:
        try:
            run = repository.update_run_lifecycle(
                session, run_id, expected_status=from_status, new_status=to_status, **fields
            )
        except ConcurrencyConflictError as exc:
            raise InvalidRunStateError(str(exc)) from exc
        except NotFoundError:
            raise
        project_id = run.project_id
        metadata = {"run_id": run_id, "from_status": from_status.value, "to_status": to_status.value}
        if audit_metadata:
            metadata.update(audit_metadata)
        repository.append_audit_event(
            session, project_id=project_id, event_type=event_type, actor=actor,
            description=f"Run #{run_id}: {from_status.value} -> {to_status.value}", metadata=metadata,
        )
        run_id_out = run.id
    with session_scope(session_factory) as session:
        return repository.get_run(session, run_id_out)


def queue_run(run_id: int, *, actor: str, session_factory: Optional[sessionmaker] = None) -> Run:
    """`CREATED -> QUEUED`. Callers must have already confirmed
    execution approval — see `researchos.execution.orchestrator`, which
    is the only place this should be called from in practice; this
    function itself enforces only the lifecycle edge, not the approval
    precondition (single-responsibility, matching
    `researchos.db.repository`'s own layering)."""
    return _transition(
        session_factory, run_id, from_status=RunStatus.CREATED, to_status=RunStatus.QUEUED,
        actor=actor, event_type="execution.run_queued",
    )


def start_run(run_id: int, *, actor: str, started_at, session_factory: Optional[sessionmaker] = None) -> Run:
    """`QUEUED -> RUNNING`."""
    return _transition(
        session_factory, run_id, from_status=RunStatus.QUEUED, to_status=RunStatus.RUNNING,
        actor=actor, event_type="execution.run_started", started_at=started_at,
    )


def mark_preparation_failed(
    run_id: int, *, actor: str, failure_reason: str, finished_at, session_factory: Optional[sessionmaker] = None
) -> Run:
    """`QUEUED -> FAILED`. Used only when something between "approved
    and queued" and "the process actually started running" fails —
    e.g. the run's on-disk workspace could not be created — so the
    process itself never even launched (`exit_code`/stdout/stderr
    references are all `None`, since none exist)."""
    return _transition(
        session_factory, run_id, from_status=RunStatus.QUEUED, to_status=RunStatus.FAILED,
        actor=actor, event_type="execution.run_preparation_failed",
        finished_at=finished_at, duration_seconds=0.0, exit_code=None,
        stdout_reference=None, stderr_reference=None, failure_reason=failure_reason,
    )


def complete_run(
    run_id: int,
    *,
    actor: str,
    status: RunStatus,
    finished_at,
    duration_seconds: float,
    exit_code: Optional[int],
    stdout_reference: Optional[str],
    stderr_reference: Optional[str],
    failure_reason: Optional[str],
    session_factory: Optional[sessionmaker] = None,
) -> Run:
    """`RUNNING -> {SUCCEEDED, FAILED, CANCELLED, TIMEOUT}`. `status`
    must be one of those four terminal values — the transition table
    rejects anything else. A failed/timed-out/cancelled Run is
    persisted with exactly the same rigor as a succeeded one: it is a
    valid, permanent scientific record, never deleted or downgraded to
    a generic error."""
    event_type = {
        RunStatus.SUCCEEDED: "execution.run_succeeded",
        RunStatus.FAILED: "execution.run_failed",
        RunStatus.CANCELLED: "execution.run_cancelled",
        RunStatus.TIMEOUT: "execution.run_timed_out",
    }.get(status)
    if event_type is None:
        raise InvalidRunStateError(f"complete_run() cannot be called with non-terminal status {status!r}.")
    return _transition(
        session_factory, run_id, from_status=RunStatus.RUNNING, to_status=status,
        actor=actor, event_type=event_type,
        finished_at=finished_at, duration_seconds=duration_seconds, exit_code=exit_code,
        stdout_reference=stdout_reference, stderr_reference=stderr_reference, failure_reason=failure_reason,
    )


# --------------------------------------------------------------------------
# Terminal-run immutability
# --------------------------------------------------------------------------
#
# researchos.db.repository intentionally keeps update_run_lifecycle (and
# every other repository setter) as a low-level primitive with no
# entity-specific immutability opinion of its own — exactly the same
# architectural boundary Phase 8A documented for
# DatasetVersion/ExperimentSpecification (see that phase's audit
# Finding on this). The protection below is the service-level
# discipline that boundary relies on: every real application path for
# "change a Run" goes through this module, and nothing here ever calls
# repository.update_run_lifecycle (or update_run_lifecycle's own
# **fields passthrough) against a Run already in a terminal state,
# because _transition()'s edge table has no outgoing edges from any
# terminal status at all. A caller that bypasses this module and calls
# the repository function directly is not stopped by a database
# trigger — this is a documented boundary, not an unbreakable one; see
# docs/PHASE8B1_EXECUTION_FOUNDATION.md's Run Immutability section.


def assert_not_terminal(run: Run) -> None:
    """Raise `InvalidRunStateError` if `run` is already in a terminal
    state — the guard every mutation-adjacent entry point (queueing,
    starting, completing, or re-requesting) must call before acting on
    an existing `Run` row, so an accidental re-execution of an
    already-decided `Run` is refused rather than silently overwriting
    its scientific record (Phase 8B-1 spec section 24, Idempotency)."""
    if run.status in TERMINAL_STATUSES:
        raise InvalidRunStateError(
            f"Run {run.id} is already terminal ({run.status.value}); it is immutable. "
            "Create a new Run instead of re-executing this one."
        )
