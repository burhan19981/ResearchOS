"""Test #14: project isolation."""

from __future__ import annotations

from researchos import workflow
from researchos.db import repository
from researchos.workflow import WorkflowStage

from .helpers import advance_via_approval


def test_two_projects_progress_independently(session_factory, project_id):
    session = session_factory()
    try:
        other = repository.create_project(session, title="Fake Independent Project")
        session.commit()
        other_id = other.id
    finally:
        session.close()

    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    # `other_id` is untouched.

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_02_INITIAL_VALIDATION
        assert workflow.get_current_stage(session, other_id) == WorkflowStage.STAGE_01_IDEA
    finally:
        session.close()


def test_pending_approvals_do_not_leak_across_projects(session_factory, project_id):
    session = session_factory()
    try:
        other = repository.create_project(session, title="Fake Second Project")
        session.commit()
        other_id = other.id
    finally:
        session.close()

    outcome_a = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="a", session_factory=session_factory
    )
    outcome_b = workflow.request_transition(
        other_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="b", session_factory=session_factory
    )
    assert outcome_a.approval.id != outcome_b.approval.id

    session = session_factory()
    try:
        pending_a = workflow.get_pending_approvals(session, project_id)
        pending_b = workflow.get_pending_approvals(session, other_id)
        assert [a.id for a in pending_a] == [outcome_a.approval.id]
        assert [a.id for a in pending_b] == [outcome_b.approval.id]
    finally:
        session.close()


def test_audit_events_are_scoped_per_project(session_factory, project_id):
    session = session_factory()
    try:
        other = repository.create_project(session, title="Fake Third Project")
        session.commit()
        other_id = other.id
    finally:
        session.close()

    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)

    session = session_factory()
    try:
        events_a = repository.list_audit_events(session, project_id)
        events_b = repository.list_audit_events(session, other_id)
        assert len(events_a) > 0
        assert len(events_b) == 0
    finally:
        session.close()
