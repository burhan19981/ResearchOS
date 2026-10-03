"""Test #10: HUMAN_ONLY enforcement (STAGE_20_FINAL, and approval decisions in general)."""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import HumanOnlyActionError
from researchos.workflow.stages import STAGE_ORDER

from .helpers import advance_via_approval


def _walk_to_revision(session_factory, project_id):
    for stage in STAGE_ORDER[1 : STAGE_ORDER.index(WorkflowStage.STAGE_19_REVISION) + 1]:
        advance_via_approval(session_factory, project_id, stage)


def test_agent_cannot_even_request_the_human_only_final_transition(session_factory, project_id):
    _walk_to_revision(session_factory, project_id)

    with pytest.raises(HumanOnlyActionError):
        workflow.request_transition(
            project_id,
            WorkflowStage.STAGE_20_FINAL,
            actor="agent:manuscript-bot",
            reason="attempting to finalize autonomously",
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_19_REVISION
        assert workflow.get_pending_approvals(session, project_id) == []
    finally:
        session.close()


def test_human_actor_can_request_the_final_transition_but_it_still_requires_approval(session_factory, project_id):
    _walk_to_revision(session_factory, project_id)

    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_20_FINAL,
        actor="user:pi",
        reason="ready to publish",
        session_factory=session_factory,
    )
    assert outcome.applied is False  # still gated, just not blocked outright


def test_direct_transition_call_never_applies_human_only_edge_even_for_a_human(session_factory, project_id):
    _walk_to_revision(session_factory, project_id)

    with pytest.raises(HumanOnlyActionError):
        workflow.transition(
            project_id, WorkflowStage.STAGE_20_FINAL, actor="user:pi", reason="direct", session_factory=session_factory
        )


def test_agent_cannot_approve_reject_or_request_changes_on_any_approval(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x", session_factory=session_factory
    )
    approval_id = outcome.approval.id

    with pytest.raises(HumanOnlyActionError):
        workflow.approve(approval_id, actor="agent:auto-approver", session_factory=session_factory)
    with pytest.raises(HumanOnlyActionError):
        workflow.reject(approval_id, actor="agent:auto-approver", session_factory=session_factory)
    with pytest.raises(HumanOnlyActionError):
        workflow.request_changes(approval_id, actor="agent:auto-approver", comment="x", session_factory=session_factory)

    # None of those attempts should have decided the approval.
    session = session_factory()
    try:
        pending = workflow.get_pending_approvals(session, project_id)
        assert len(pending) == 1
        assert pending[0].id == approval_id
    finally:
        session.close()


def test_full_human_only_final_approval_flow_succeeds_for_a_human(session_factory, project_id):
    _walk_to_revision(session_factory, project_id)
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_20_FINAL, actor="user:pi", reason="ready to publish",
        session_factory=session_factory,
    )
    decided = workflow.approve(outcome.approval.id, actor="user:editor", comment="approved for publication", session_factory=session_factory)
    assert decided.decision.value == "approved"

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_20_FINAL
    finally:
        session.close()
