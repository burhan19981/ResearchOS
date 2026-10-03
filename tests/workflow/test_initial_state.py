"""Test #1: initial project state."""

from __future__ import annotations

from researchos.db.models import ProjectStatus
from researchos.workflow import WorkflowStage, get_allowed_transitions, get_current_stage
from researchos.workflow.policy import Policy


def test_fresh_project_starts_at_stage_01_idea_even_though_column_is_null(session, project_id):
    from researchos.db import repository

    project = repository.get_project(session, project_id)
    assert project.current_stage is None  # nothing has written to it yet
    assert project.status == ProjectStatus.ACTIVE

    assert get_current_stage(session, project_id) == WorkflowStage.STAGE_01_IDEA


def test_initial_allowed_transitions_is_only_the_first_forward_gate(session, project_id):
    allowed = get_allowed_transitions(session, project_id)
    assert len(allowed) == 1
    assert allowed[0].target_stage == WorkflowStage.STAGE_02_INITIAL_VALIDATION
    assert allowed[0].policy is Policy.APPROVAL_REQUIRED
    assert allowed[0].direction == "forward"
