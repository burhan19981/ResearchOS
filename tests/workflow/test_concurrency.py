"""Test #18: basic protection against conflicting updates.

This is a deliberately simple optimistic-concurrency check (compare the
caller's `expected_current_stage` against the freshly-read value inside
the same transaction), not distributed locking — see
`docs/PHASE4_WORKFLOW.md`. Simulated here as two "callers" acting on the
same project without a real second thread/process, which is sufficient
to prove the guard fires when a caller's assumption about the current
stage has gone stale.
"""

from __future__ import annotations

import pytest

from researchos import workflow
from researchos.workflow import WorkflowStage
from researchos.workflow.errors import ConcurrentModificationError

from .helpers import advance_via_approval


def test_second_caller_with_stale_expected_stage_is_rejected(session_factory, project_id):
    # Both "callers" read the stage as STAGE_01_IDEA.
    caller_a_expected = WorkflowStage.STAGE_01_IDEA
    caller_b_expected = WorkflowStage.STAGE_01_IDEA

    # Caller A acts first and succeeds (STAGE_01 -> STAGE_02 is gated, but
    # the expected-stage check happens before that and passes).
    outcome = workflow.request_transition(
        project_id,
        WorkflowStage.STAGE_02_INITIAL_VALIDATION,
        actor="user:pi-a",
        reason="caller A",
        expected_current_stage=caller_a_expected,
        session_factory=session_factory,
    )
    assert outcome.applied is False
    workflow.approve(outcome.approval.id, actor="user:pi-a", session_factory=session_factory)

    # Caller B still believes the project is at STAGE_01_IDEA (stale read)
    # and now tries to act on that assumption.
    with pytest.raises(ConcurrentModificationError):
        workflow.request_transition(
            project_id,
            WorkflowStage.STAGE_02_INITIAL_VALIDATION,
            actor="user:pi-b",
            reason="caller B, unaware A already moved things",
            expected_current_stage=caller_b_expected,
            session_factory=session_factory,
        )


def test_transition_also_honors_expected_current_stage(session_factory, project_id):
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)

    with pytest.raises(ConcurrentModificationError):
        workflow.transition(
            project_id,
            WorkflowStage.STAGE_03_LITERATURE_SEARCH,
            actor="user:pi",
            reason="stale assumption",
            expected_current_stage=WorkflowStage.STAGE_01_IDEA,
            session_factory=session_factory,
        )


def test_correct_expected_stage_succeeds(session_factory, project_id):
    # STAGE_02 is gated, so exercise the matching-expectation success path
    # on a subsequent AUTO_ALLOWED edge instead.
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    updated = workflow.transition(
        project_id,
        WorkflowStage.STAGE_03_LITERATURE_SEARCH,
        actor="user:pi",
        reason="matches",
        expected_current_stage=WorkflowStage.STAGE_02_INITIAL_VALIDATION,
        session_factory=session_factory,
    )
    assert updated.current_stage == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value


def test_no_concurrency_check_when_expected_stage_omitted(session_factory, project_id):
    """Omitting expected_current_stage opts out of the check entirely —
    existing callers that don't care about this are unaffected."""
    advance_via_approval(session_factory, project_id, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    updated = workflow.transition(
        project_id, WorkflowStage.STAGE_03_LITERATURE_SEARCH, actor="user:pi", reason="no check",
        session_factory=session_factory,
    )
    assert updated.current_stage == WorkflowStage.STAGE_03_LITERATURE_SEARCH.value
