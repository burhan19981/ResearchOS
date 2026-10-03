"""Test #12: audit event creation and content.

Every workflow mutation must produce an AuditEvent carrying: project id
(the FK itself), previous stage, new stage, actor, transition type,
reason, timestamp (created_at), and metadata — see
docs/PHASE4_WORKFLOW.md for exactly how each maps onto AuditEvent's
existing Phase 3 columns.
"""

from __future__ import annotations

from researchos import workflow
from researchos.db import repository
from researchos.workflow import WorkflowStage


def test_auto_allowed_transition_produces_a_complete_audit_event(session_factory, project_id):
    from .helpers import advance_via_approval

    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)

    workflow.transition(
        project_id,
        WorkflowStage.STAGE_03_LITERATURE_SEARCH,
        actor="agent:literature-bot",
        reason="beginning the search",
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        transition_events = [e for e in events if e.event_type == "workflow.transition"]
        assert len(transition_events) >= 1
        event = transition_events[-1]

        assert event.project_id == project_id
        assert event.actor == "agent:literature-bot"
        assert event.created_at is not None
        assert event.metadata_["previous_stage"] == WorkflowStage.STAGE_02_INITIAL_VALIDATION.value
        assert event.metadata_["new_stage"] == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value
        assert event.metadata_["transition_type"] == "forward"
        assert event.metadata_["reason"] == "beginning the search"
    finally:
        session.close()


def test_approval_request_and_decision_each_produce_their_own_audit_event(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="ready to commit",
        session_factory=session_factory,
    )
    workflow.approve(outcome.approval.id, actor="user:approver", comment="looks solid", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event_types = [e.event_type for e in events]
        assert "workflow.approval_requested" in event_types
        assert "workflow.approval_approved" in event_types
        assert "workflow.transition" in event_types

        requested = next(e for e in events if e.event_type == "workflow.approval_requested")
        assert requested.actor == "user:pi"
        assert requested.metadata_["approval_id"] == outcome.approval.id
        assert requested.metadata_["reason"] == "ready to commit"

        approved = next(e for e in events if e.event_type == "workflow.approval_approved")
        assert approved.actor == "user:approver"
        assert approved.metadata_["comment"] == "looks solid"
    finally:
        session.close()


def test_rejected_approval_produces_an_audit_event_but_no_transition_event(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x", session_factory=session_factory
    )
    workflow.reject(outcome.approval.id, actor="user:pi", comment="no", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event_types = [e.event_type for e in events]
        assert "workflow.approval_rejected" in event_types
        assert "workflow.transition" not in event_types
    finally:
        session.close()


def test_pause_and_resume_each_produce_an_audit_event(session_factory, project_id):
    workflow.pause_project(project_id, actor="user:pi", reason="budget freeze", session_factory=session_factory)
    workflow.resume_project(project_id, actor="user:pi", reason="budget restored", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event_types = [e.event_type for e in events]
        assert "workflow.project_paused" in event_types
        assert "workflow.project_resumed" in event_types

        paused = next(e for e in events if e.event_type == "workflow.project_paused")
        assert paused.metadata_["reason"] == "budget freeze"
    finally:
        session.close()


def test_backward_transition_audit_event_is_tagged_backward(session_factory, project_id):
    from .helpers import advance_via_approval

    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_03_LITERATURE_SEARCH)

    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_01_IDEA, actor="user:pi", reason="starting over", session_factory=session_factory
    )
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        transition_events = [e for e in events if e.event_type == "workflow.transition"]
        last = transition_events[-1]
        assert last.metadata_["transition_type"] == "backward"
        assert last.metadata_["previous_stage"] == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value
        assert last.metadata_["new_stage"] == WorkflowStage.STAGE_01_IDEA.value
        assert last.metadata_["approval_id"] == outcome.approval.id
    finally:
        session.close()
