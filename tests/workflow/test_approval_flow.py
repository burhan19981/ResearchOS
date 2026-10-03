"""Tests #5-#9: approval-required transitions, missing-approval rejection,
successful approval, rejected approval, and request-changes.
"""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.db.models import ApprovalDecision
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import ApprovalAlreadyDecidedError, ApprovalNotFoundError, ApprovalRequiredError


def test_approval_required_transition_creates_pending_approval_not_a_stage_change(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_02_INITIAL_VALIDATION,
        actor="user:pi",
        reason="ready to commit to this idea",
        session_factory=session_factory,
    )
    assert outcome.applied is False
    assert outcome.approval.decision == ApprovalDecision.PENDING
    assert outcome.approval.stage == "STAGE_01_IDEA->STAGE_02_INITIAL_VALIDATION"

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
        pending = workflow.get_pending_approvals(session, project_id)
        assert len(pending) == 1
        assert pending[0].id == outcome.approval.id
    finally:
        session.close()


def test_transition_without_approval_is_rejected(session_factory, project_id):
    with pytest.raises(ApprovalRequiredError):
        workflow.transition(
            project_id,
            WorkflowStage.STAGE_02_INITIAL_VALIDATION,
            actor="user:pi",
            reason="trying to skip the approval step",
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
    finally:
        session.close()


def test_successful_approval_applies_the_transition(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="agent:idea-scout", reason="propose",
        session_factory=session_factory,
    )
    decided = workflow.approve(
        outcome.approval.id, actor="user:pi", comment="agreed, let's proceed", session_factory=session_factory
    )
    assert decided.decision == ApprovalDecision.APPROVED
    assert decided.decided_at is not None
    assert decided.comment == "agreed, let's proceed"

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_02_INITIAL_VALIDATION
        assert workflow.get_pending_approvals(session, project_id) == []
    finally:
        session.close()


def test_rejected_approval_does_not_change_project_stage(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="agent:idea-scout", reason="propose",
        session_factory=session_factory,
    )
    decided = workflow.reject(outcome.approval.id, actor="user:pi", comment="not convincing", session_factory=session_factory)
    assert decided.decision == ApprovalDecision.REJECTED
    assert decided.decided_at is not None

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
        assert workflow.get_pending_approvals(session, project_id) == []
    finally:
        session.close()


def test_request_changes_leaves_approval_pending_state_but_recorded_and_project_unchanged(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="agent:idea-scout", reason="propose",
        session_factory=session_factory,
    )
    decided = workflow.request_changes(
        outcome.approval.id, actor="user:pi", comment="please add more detail on feasibility", session_factory=session_factory
    )
    assert decided.decision == ApprovalDecision.CHANGES_REQUESTED
    assert decided.decided_at is not None

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
        # CHANGES_REQUESTED is a decided state, not pending.
        assert workflow.get_pending_approvals(session, project_id) == []
    finally:
        session.close()


def test_approving_an_already_decided_approval_is_rejected(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x", session_factory=session_factory
    )
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)
    with pytest.raises(ApprovalAlreadyDecidedError):
        workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)
    with pytest.raises(ApprovalAlreadyDecidedError):
        workflow.reject(outcome.approval.id, actor="user:pi", session_factory=session_factory)


def test_deciding_a_nonexistent_approval_raises_not_found(session_factory):
    with pytest.raises(ApprovalNotFoundError):
        workflow.approve(999_999, actor="user:pi", session_factory=session_factory)


def test_get_pending_approvals_without_project_id_lists_across_projects(session_factory, project_id):
    from researchos.db import repository

    session = session_factory()
    try:
        other_project = repository.create_project(session, title="Fake Other Project")
        session.commit()
        other_id = other_project.id
    finally:
        session.close()

    workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="a", session_factory=session_factory
    )
    workflow.request_transition(
        other_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="b", session_factory=session_factory
    )

    session = session_factory()
    try:
        all_pending = workflow.get_pending_approvals(session)
        assert len(all_pending) == 2
        assert {a.project_id for a in all_pending} == {project_id, other_id}
    finally:
        session.close()
