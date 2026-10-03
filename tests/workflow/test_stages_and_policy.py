"""Pure unit tests for the stage graph and policy layer — no database,
no I/O. These are the tests that prove the policy is deterministic.
"""

from __future__ import annotations

import pytest

from researchos.workflow.errors import InvalidTransitionError
from researchos.workflow.policy import (
    ARCHIVE_POLICY,
    PAUSE_POLICY,
    REJECT_POLICY,
    RESUME_POLICY,
    Policy,
    get_policy,
    is_human_actor,
)
from researchos.workflow.stages import (
    STAGE_ORDER,
    WorkflowStage,
    earlier_stages,
    is_backward,
    is_forward_step,
    next_stage,
)


def test_all_20_canonical_stages_are_defined_in_order():
    expected_suffixes = [
        "IDEA",
        "INITIAL_VALIDATION",
        "LITERATURE_SEARCH",
        "LITERATURE_MAPPING",
        "RESEARCH_GAP",
        "NOVELTY_VERIFICATION",
        "METHODOLOGY",
        "DATASET",
        "EXPERIMENTAL_DESIGN",
        "IMPLEMENTATION",
        "EXPERIMENTS",
        "RESULTS_ANALYSIS",
        "SCIENTIFIC_REVIEW",
        "MANUSCRIPT",
        "CITATION_INTEGRITY",
        "JOURNAL_SELECTION",
        "SUBMISSION_PREPARATION",
        "PEER_REVIEW",
        "REVISION",
        "FINAL",
    ]
    assert len(STAGE_ORDER) == 20
    for index, (stage, suffix) in enumerate(zip(STAGE_ORDER, expected_suffixes), start=1):
        assert stage.value == f"STAGE_{index:02d}_{suffix}"


def test_next_stage_advances_one_at_a_time():
    assert next_stage(WorkflowStage.STAGE_01_IDEA) == WorkflowStage.STAGE_02_INITIAL_VALIDATION
    assert next_stage(WorkflowStage.STAGE_19_REVISION) == WorkflowStage.STAGE_20_FINAL


def test_next_stage_of_final_stage_is_none():
    assert next_stage(WorkflowStage.STAGE_20_FINAL) is None


def test_is_forward_step_true_only_for_exactly_one_step():
    assert is_forward_step(WorkflowStage.STAGE_01_IDEA, WorkflowStage.STAGE_02_INITIAL_VALIDATION)
    assert not is_forward_step(WorkflowStage.STAGE_01_IDEA, WorkflowStage.STAGE_03_LITERATURE_SEARCH)
    assert not is_forward_step(WorkflowStage.STAGE_02_INITIAL_VALIDATION, WorkflowStage.STAGE_01_IDEA)


def test_is_backward_true_for_any_earlier_stage():
    assert is_backward(WorkflowStage.STAGE_10_IMPLEMENTATION, WorkflowStage.STAGE_01_IDEA)
    assert is_backward(WorkflowStage.STAGE_10_IMPLEMENTATION, WorkflowStage.STAGE_09_EXPERIMENTAL_DESIGN)
    assert not is_backward(WorkflowStage.STAGE_01_IDEA, WorkflowStage.STAGE_02_INITIAL_VALIDATION)


def test_earlier_stages_returns_all_stages_strictly_before():
    earlier = earlier_stages(WorkflowStage.STAGE_03_LITERATURE_SEARCH)
    assert earlier == [WorkflowStage.STAGE_01_IDEA, WorkflowStage.STAGE_02_INITIAL_VALIDATION]
    assert earlier_stages(WorkflowStage.STAGE_01_IDEA) == []


@pytest.mark.parametrize(
    "to_stage,expected_policy",
    [
        (WorkflowStage.STAGE_02_INITIAL_VALIDATION, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_03_LITERATURE_SEARCH, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_04_LITERATURE_MAPPING, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_05_RESEARCH_GAP, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_06_NOVELTY_VERIFICATION, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_07_METHODOLOGY, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_08_DATASET, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_09_EXPERIMENTAL_DESIGN, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_10_IMPLEMENTATION, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_11_EXPERIMENTS, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_12_RESULTS_ANALYSIS, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_13_SCIENTIFIC_REVIEW, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_14_MANUSCRIPT, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_15_CITATION_INTEGRITY, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_16_JOURNAL_SELECTION, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_17_SUBMISSION_PREPARATION, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_18_PEER_REVIEW, Policy.APPROVAL_REQUIRED),
        (WorkflowStage.STAGE_19_REVISION, Policy.AUTO_ALLOWED),
        (WorkflowStage.STAGE_20_FINAL, Policy.HUMAN_ONLY),
    ],
)
def test_forward_gate_policy_matches_spec_for_every_stage(to_stage, expected_policy):
    from_stage = WorkflowStage(STAGE_ORDER[STAGE_ORDER.index(to_stage) - 1])
    assert get_policy(from_stage, to_stage) is expected_policy


def test_backward_transition_always_requires_approval():
    assert get_policy(WorkflowStage.STAGE_10_IMPLEMENTATION, WorkflowStage.STAGE_01_IDEA) is Policy.APPROVAL_REQUIRED
    assert (
        get_policy(WorkflowStage.STAGE_20_FINAL, WorkflowStage.STAGE_19_REVISION) is Policy.APPROVAL_REQUIRED
    )


def test_same_stage_transition_is_invalid():
    with pytest.raises(InvalidTransitionError):
        get_policy(WorkflowStage.STAGE_05_RESEARCH_GAP, WorkflowStage.STAGE_05_RESEARCH_GAP)


def test_forward_jump_skipping_stages_is_invalid():
    with pytest.raises(InvalidTransitionError):
        get_policy(WorkflowStage.STAGE_01_IDEA, WorkflowStage.STAGE_05_RESEARCH_GAP)


def test_administrative_policies_are_fixed():
    assert PAUSE_POLICY is Policy.AUTO_ALLOWED
    assert RESUME_POLICY is Policy.AUTO_ALLOWED
    assert ARCHIVE_POLICY is Policy.APPROVAL_REQUIRED
    assert REJECT_POLICY is Policy.APPROVAL_REQUIRED


def test_is_human_actor_convention():
    assert is_human_actor("system") is True
    assert is_human_actor("user:alice") is True
    assert is_human_actor("human:bob") is True
    assert is_human_actor("agent:idea-generator") is False
    assert is_human_actor("AGENT:literature-bot") is False  # case-insensitive
    assert is_human_actor("  agent:spacey  ") is False
