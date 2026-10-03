"""Tests #2 (valid forward transitions) and #11 (AUTO_ALLOWED operations)."""

from __future__ import annotations

from researchos import workflow
from researchos.workflow import WorkflowStage

from .helpers import advance_via_approval


def test_auto_allowed_transition_applies_immediately_for_any_actor(session_factory, project_id):
    # STAGE_01 -> STAGE_02 is APPROVAL_REQUIRED; approve it first to reach STAGE_02.
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)

    # STAGE_02 -> STAGE_03 is AUTO_ALLOWED.
    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_03_LITERATURE_SEARCH,
        actor="agent:literature-bot",
        reason="starting search",
        session_factory=session_factory,
    )
    assert outcome.applied is True
    assert outcome.project.current_stage == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value
    assert outcome.approval is None


def test_direct_transition_call_also_applies_auto_allowed_edges(session_factory, project_id):
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    project = workflow.transition(
        project_id, WorkflowStage.STAGE_03_LITERATURE_SEARCH, actor="system", reason="auto", session_factory=session_factory
    )
    assert project.current_stage == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value


def test_string_stage_values_are_accepted_alongside_the_enum(session_factory, project_id):
    outcome = workflow.request_transition(
        project_id,
        "STAGE_02_INITIAL_VALIDATION",
        actor="user:pi",
        reason="string form",
        session_factory=session_factory,
    )
    assert outcome.applied is False  # gated; just proves the string coerced without error


def test_walking_every_auto_allowed_edge_in_sequence(session_factory, project_id):
    """STAGE_02 -> 03 -> 04 -> 05 are all AUTO_ALLOWED; walk them one at a time."""
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    for target in (
        WorkflowStage.STAGE_03_LITERATURE_SEARCH,
        WorkflowStage.STAGE_04_LITERATURE_MAPPING,
        WorkflowStage.STAGE_05_RESEARCH_GAP,
    ):
        outcome = workflow.request_transition(
            project_id, target, actor="agent:pipeline", reason="advance", session_factory=session_factory
        )
        assert outcome.applied is True
        assert outcome.project.current_stage == target.value

    session = session_factory()
    try:
        assert workflow.get_current_stage(session, project_id) == WorkflowStage.STAGE_05_RESEARCH_GAP
    finally:
        session.close()
