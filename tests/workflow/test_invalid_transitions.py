"""Tests #3 (invalid jumps) and #17 (invalid stage values)."""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.db import repository
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import InvalidTransitionError, InvalidWorkflowStateError


def test_forward_jump_skipping_stages_is_rejected(session_factory, project_id):
    with pytest.raises(InvalidTransitionError):
        workflow.request_transition(
            project_id,
            WorkflowStage.STAGE_10_IMPLEMENTATION,
            actor="user:pi",
            reason="skip ahead",
            session_factory=session_factory,
        )


def test_transition_to_same_stage_is_rejected(session_factory, project_id):
    with pytest.raises(InvalidTransitionError):
        workflow.request_transition(
            project_id,
            WorkflowStage.STAGE_01_IDEA,
            actor="user:pi",
            reason="no-op",
            session_factory=session_factory,
        )


def test_unrecognized_stage_string_is_rejected(session_factory, project_id):
    with pytest.raises(InvalidWorkflowStateError):
        workflow.request_transition(
            project_id,
            "NOT_A_REAL_STAGE",
            actor="user:pi",
            reason="typo",
            session_factory=session_factory,
        )


def test_corrupted_current_stage_value_raises_on_read(session_factory, project_id):
    """A pre-existing/corrupted free-text current_stage value (the column
    itself still allows any string — see docs/PHASE4_WORKFLOW.md) must be
    surfaced clearly, not silently misinterpreted."""
    session = session_factory()
    try:
        repository.update_project(session, project_id, current_stage="LEGACY_UNKNOWN_STAGE")
        session.commit()
    finally:
        session.close()

    session = session_factory()
    try:
        with pytest.raises(InvalidWorkflowStateError):
            workflow.get_current_stage(session, project_id)
    finally:
        session.close()


def test_invalid_transition_does_not_change_project_state(session_factory, project_id):
    try:
        workflow.request_transition(
            project_id, WorkflowStage.STAGE_15_CITATION_INTEGRITY, actor="user:pi", reason="bad jump",
            session_factory=session_factory,
        )
    except InvalidTransitionError:
        pass

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA
        assert workflow.get_pending_approvals(session, project_id) == []
    finally:
        session.close()
