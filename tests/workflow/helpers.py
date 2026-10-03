"""Shared test helpers (not fixtures) for the workflow test suite."""

from __future__ import annotations

from researchos import workflow


def advance_via_approval(session_factory, project_id, target_stage, *, actor="user:pi", reason="test reason"):
    """Move the project to `target_stage`, approving it first if the edge is gated.

    Handles both AUTO_ALLOWED edges (applied immediately by
    `request_transition`) and APPROVAL_REQUIRED/HUMAN_ONLY edges
    (approved here by a human actor) so callers can walk the pipeline
    forward one call per stage without caring which tier each edge is.

    Returns the current WorkflowStage after the move (re-read via
    `get_current_stage` in a fresh session, since the objects returned
    by `request_transition`/`approve` belong to already-closed sessions).
    """
    outcome = workflow.request_transition(
        project_id, target_stage, actor=actor, reason=reason, session_factory=session_factory
    )
    if not outcome.applied:
        assert outcome.approval is not None
        workflow.approve(outcome.approval.id, actor="user:approver", comment="ok", session_factory=session_factory)

    session = session_factory()
    try:
        return workflow.get_current_stage(session, project_id)
    finally:
        session.close()
