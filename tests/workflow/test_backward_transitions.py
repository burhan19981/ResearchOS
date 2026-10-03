"""Test #4: controlled backward transitions."""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.db import repository
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import ApprovalRequiredError
from researchos.workflow.stages import STAGE_ORDER

from .helpers import advance_via_approval


def _walk_forward_to(session_factory, project_id, target: WorkflowStage):
    """Walk the project forward one edge at a time up to (and including) `target`."""
    for stage in STAGE_ORDER[1 : STAGE_ORDER.index(target) + 1]:
        advance_via_approval(session_factory, project_id, stage)


def test_backward_transition_requires_approval_and_is_recorded_as_backward(session_factory, project_id):
    _walk_forward_to(session_factory, project_id, WorkflowStage.STAGE_05_RESEARCH_GAP)

    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_03_LITERATURE_SEARCH,
        actor="user:pi",
        reason="need more papers before continuing",
        session_factory=session_factory,
    )
    assert outcome.applied is False
    approval = outcome.approval
    assert approval.stage == "STAGE_05_RESEARCH_GAP->STAGE_03_LITERATURE_SEARCH"

    decided = workflow.approve(approval.id, actor="user:pi", comment="agreed", session_factory=session_factory)
    assert decided.decision.value == "approved"

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_03_LITERATURE_SEARCH
        events = repository.list_audit_events(session, project_id)
        backward_events = [e for e in events if e.metadata_ and e.metadata_.get("transition_type") == "backward"]
        assert len(backward_events) == 1
        assert backward_events[0].metadata_["previous_stage"] == WorkflowStage.STAGE_05_RESEARCH_GAP.value
        assert backward_events[0].metadata_["new_stage"] == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value
    finally:
        session.close()


def test_backward_transition_to_any_earlier_stage_is_structurally_allowed(session_factory, project_id):
    _walk_forward_to(session_factory, project_id, WorkflowStage.STAGE_11_EXPERIMENTS)

    # Jump all the way back to STAGE_01 — a big backward move, but still a
    # single, explicit, approved edge (never an arbitrary forward jump).
    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_01_IDEA,
        actor="user:pi",
        reason="fundamental rethink of the idea",
        session_factory=session_factory,
    )
    assert outcome.applied is False
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
    finally:
        session.close()


def test_backward_transition_never_applies_without_approval(session_factory, project_id):
    _walk_forward_to(session_factory, project_id, WorkflowStage.STAGE_05_RESEARCH_GAP)

    with pytest.raises(ApprovalRequiredError):
        workflow.transition(
            project_id,
            WorkflowStage.STAGE_02_INITIAL_VALIDATION,
            actor="user:pi",
            reason="direct backward attempt",
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_05_RESEARCH_GAP
    finally:
        session.close()
