"""Test #13: atomic rollback when audit persistence fails.

`AuditEvent.actor` is validated non-blank by the model itself
(`researchos.db.models.AuditEvent._validate_actor`). Passing a blank
actor lets us force the *audit* write to fail, after the *stage*
update has already been flushed within the same transaction, proving
`session_scope()` rolls back both together rather than leaving a
half-applied change.
"""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.db.errors import ValidationError
from researchos.workflow import WorkflowStage


def test_blank_actor_fails_audit_write_and_rolls_back_the_already_flushed_stage_update(session_factory, project_id):
    # STAGE_01 -> STAGE_02 is APPROVAL_REQUIRED, so get to STAGE_02 via a
    # normal, valid approval first, then isolate the failure to exactly
    # the audit-event step of a subsequent AUTO_ALLOWED transition.
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="setup",
        session_factory=session_factory,
    )
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    # Now attempt an AUTO_ALLOWED transition with a blank actor: update_project()
    # flushes fine, then append_audit_event() raises ValidationError.
    with pytest.raises(ValidationError):
        workflow.transition(
            project_id,
            WorkflowStage.STAGE_03_LITERATURE_SEARCH,
            actor="   ",
            reason="this should never be applied",
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        # The stage must still be STAGE_02 — the update_project() flush
        # that ran before the failing audit event must have been rolled
        # back along with it, not left committed.
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_02_INITIAL_VALIDATION
    finally:
        session.close()


def test_blank_actor_fails_approval_request_audit_and_rolls_back_the_approval_row(session_factory, project_id):
    with pytest.raises(ValidationError):
        workflow.request_transition(
            project_id,
            WorkflowStage.STAGE_02_INITIAL_VALIDATION,
            actor="",
            reason="blank actor",
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        # No Approval row should have survived: request_approval() creates
        # the Approval row and the audit event in the same transaction;
        # the audit event's validation failure must roll back the Approval
        # insert too.
        assert workflow.get_pending_approvals(session, project_id) == []
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
    finally:
        session.close()
