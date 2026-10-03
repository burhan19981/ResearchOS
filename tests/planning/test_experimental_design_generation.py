"""Experimental design generation service tests (Phase 7 spec section 29)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus
from researchos.planning.errors import InvalidPlanningResponseError
from researchos.planning.experimental_design import generate_experimental_design
from tests.planning.fakes import FakeLLMProvider


def test_generates_candidate_design_and_links_questions(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{
        "proposed_method": "Compare the new alloy against two baseline alloys under identical stress tests.",
        "baselines": ["standard alloy A", "standard alloy B"],
        "ablation_studies": ["remove heat treatment step"],
        "evaluation_metrics": ["fracture stress (MPa)", "cycles to failure"],
        "comparison_strategy": "paired t-test across matched sample batches",
        "addressed_research_question_ids": [approved_question_id],
    }])
    outcome = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )

    session = session_factory()
    try:
        design = repository.get_experimental_design(session, outcome.experimental_design_id)
        assert design.planning_status == PlanningApprovalStatus.CANDIDATE
        assert design.methodology_plan_id == approved_methodology_id
        assert design.dataset_requirements_id == approved_dataset_requirements_id
        links = repository.list_experimental_design_questions(
            session, project_id, experimental_design_id=design.id
        )
        assert [l.research_question_id for l in links] == [approved_question_id]
    finally:
        session.close()


def test_addressed_question_outside_given_set_is_rejected(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{
        "proposed_method": "A method.",
        "addressed_research_question_ids": [999_999],
    }])
    with pytest.raises(InvalidPlanningResponseError):
        generate_experimental_design(
            project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    session = session_factory()
    try:
        assert repository.list_experimental_designs(session, project_id) == []
    finally:
        session.close()


def test_never_creates_or_touches_an_experiment(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    """Experiment/ExperimentResult remain exclusively the execution-
    tracking entities; this service must never create one."""
    provider = FakeLLMProvider(responses=[{
        "proposed_method": "A method.", "addressed_research_question_ids": [approved_question_id],
    }])
    generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        assert repository.list_experiments(session, project_id) == []
    finally:
        session.close()


# --- Versioning / lineage (audit remediation, Finding C) --------------------


def test_regenerating_via_supersedes_id_creates_a_real_v2_and_preserves_v1(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{
        "proposed_method": "First proposed method.", "addressed_research_question_ids": [approved_question_id],
    }])
    first = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    first_id = first.experimental_design_id

    provider2 = FakeLLMProvider(responses=[{
        "proposed_method": "Revised method, a genuine v2.", "addressed_research_question_ids": [approved_question_id],
    }])
    second = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider2, supersedes_id=first_id,
        session_factory=session_factory,
    )
    second_id = second.experimental_design_id
    assert second_id != first_id

    session = session_factory()
    try:
        v1 = repository.get_experimental_design(session, first_id)
        v2 = repository.get_experimental_design(session, second_id)
        assert v1.version == 1
        assert v1.supersedes_id is None
        assert v1.proposed_method == "First proposed method."  # v1 unchanged
        assert v2.version == 2
        assert v2.supersedes_id == first_id  # traceable to the same lineage
        assert v2.proposed_method == "Revised method, a genuine v2."
    finally:
        session.close()


def test_independent_designs_do_not_share_a_lineage(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    provider_a = FakeLLMProvider(responses=[{
        "proposed_method": "Design A.", "addressed_research_question_ids": [approved_question_id],
    }])
    outcome_a = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider_a, session_factory=session_factory,
    )
    provider_b = FakeLLMProvider(responses=[{
        "proposed_method": "Design B, unrelated.", "addressed_research_question_ids": [approved_question_id],
    }])
    outcome_b = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider_b, session_factory=session_factory,
    )
    session = session_factory()
    try:
        a = repository.get_experimental_design(session, outcome_a.experimental_design_id)
        b = repository.get_experimental_design(session, outcome_b.experimental_design_id)
        assert a.version == 1
        assert b.version == 1
        assert a.supersedes_id is None
        assert b.supersedes_id is None
        assert a.id != b.id
    finally:
        session.close()


def test_superseding_the_same_design_twice_is_rejected(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    """The UniqueConstraint on supersedes_id enforces an unbranching
    lineage: a given prior row can be superseded by at most one row."""
    from researchos.db.errors import IntegrityConstraintError

    provider = FakeLLMProvider(responses=[{
        "proposed_method": "v1.", "addressed_research_question_ids": [approved_question_id],
    }])
    first = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )

    provider2 = FakeLLMProvider(responses=[{
        "proposed_method": "v2 attempt one.", "addressed_research_question_ids": [approved_question_id],
    }])
    generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider2, supersedes_id=first.experimental_design_id,
        session_factory=session_factory,
    )

    provider3 = FakeLLMProvider(responses=[{
        "proposed_method": "v2 attempt two (a fork).", "addressed_research_question_ids": [approved_question_id],
    }])
    try:
        generate_experimental_design(
            project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider3, supersedes_id=first.experimental_design_id,
            session_factory=session_factory,
        )
        assert False, "expected IntegrityConstraintError (branching lineage)"
    except IntegrityConstraintError:
        pass
