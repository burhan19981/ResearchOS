"""Tests #15 (paused project behavior) and #16 (archived project behavior),
plus resume and the reject_project() administrative action.
"""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.db.models import ProjectStatus
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import (
    InvalidWorkflowStateError,
    ProjectArchivedError,
    ProjectPausedError,
    ProjectRejectedError,
)


def test_pause_project_blocks_transitions_until_resumed(session_factory, project_id):
    project = workflow.pause_project(project_id, actor="user:pi", reason="waiting on funding", session_factory=session_factory)
    assert project.status == ProjectStatus.PAUSED

    with pytest.raises(ProjectPausedError):
        workflow.request_transition(
            project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x",
            session_factory=session_factory,
        )

    resumed = workflow.resume_project(project_id, actor="user:pi", reason="funding secured", session_factory=session_factory)
    assert resumed.status == ProjectStatus.ACTIVE

    # Now transitions work again.
    outcome = workflow.request_transition(
        project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="resumed",
        session_factory=session_factory,
    )
    assert outcome.applied is False  # still gated, but no longer blocked by pause


def test_get_allowed_transitions_is_empty_while_paused(session_factory, project_id):
    workflow.pause_project(project_id, actor="user:pi", reason="pause", session_factory=session_factory)
    session = session_factory()
    try:
        assert workflow.get_allowed_transitions(session, project_id) == []
    finally:
        session.close()


def test_pausing_an_already_paused_project_is_rejected(session_factory, project_id):
    workflow.pause_project(project_id, actor="user:pi", reason="pause", session_factory=session_factory)
    with pytest.raises(InvalidWorkflowStateError):
        workflow.pause_project(project_id, actor="user:pi", reason="pause again", session_factory=session_factory)


def test_resuming_a_non_paused_project_is_rejected(session_factory, project_id):
    with pytest.raises(InvalidWorkflowStateError):
        workflow.resume_project(project_id, actor="user:pi", reason="not paused", session_factory=session_factory)


def test_archive_project_requires_approval_and_then_blocks_all_transitions(session_factory, project_id):
    outcome = workflow.archive_project(project_id, actor="user:pi", reason="shelving this direction", session_factory=session_factory)
    assert outcome.applied is False

    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    with pytest.raises(ProjectArchivedError):
        workflow.request_transition(
            project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x",
            session_factory=session_factory,
        )
    with pytest.raises(ProjectArchivedError):
        workflow.pause_project(project_id, actor="user:pi", reason="x", session_factory=session_factory)


def test_archived_project_get_allowed_transitions_is_empty(session_factory, project_id):
    outcome = workflow.archive_project(project_id, actor="user:pi", reason="x", session_factory=session_factory)
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        assert workflow.get_allowed_transitions(session, project_id) == []
    finally:
        session.close()


def test_reject_project_requires_approval_and_then_blocks_all_transitions(session_factory, project_id):
    outcome = workflow.reject_project(project_id, actor="user:pi", reason="not viable", session_factory=session_factory)
    assert outcome.applied is False
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    with pytest.raises(ProjectRejectedError):
        workflow.request_transition(
            project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION, actor="user:pi", reason="x",
            session_factory=session_factory,
        )


def test_archiving_an_already_archived_project_is_rejected(session_factory, project_id):
    outcome = workflow.archive_project(project_id, actor="user:pi", reason="x", session_factory=session_factory)
    workflow.approve(outcome.approval.id, actor="user:pi", session_factory=session_factory)

    with pytest.raises(ProjectArchivedError):
        workflow.archive_project(project_id, actor="user:pi", reason="again", session_factory=session_factory)
