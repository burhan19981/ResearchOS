"""Reproducibility: provider/model/prompt_name/prompt_version/timestamp
persisted for every generation type (Phase 7 spec section 23), plus the
generation-time upstream snapshot (Phase 7 spec section 15)."""

from __future__ import annotations

from researchos.db import repository
from researchos.planning.contributions import generate_contribution_candidates
from researchos.planning.dataset_requirements import generate_dataset_requirements
from researchos.planning.experimental_design import generate_experimental_design
from researchos.planning.methodology import generate_methodology_plan
from tests.planning.fakes import FakeLLMProvider


def test_contribution_persists_full_provenance(session_factory, project_id, approved_question_id):
    provider = FakeLLMProvider(responses=[{
        "contributions": [{"title": "T", "description": "D", "cited_research_question_ids": [approved_question_id]}]
    }])
    outcome = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        contribution = repository.get_contribution_candidate(session, outcome.contribution_ids[0])
        assert contribution.provider == "fake"
        assert contribution.model == "fake-model-1"
        assert contribution.prompt_name == "contribution_generation"
        assert contribution.prompt_version == "v1"
        assert contribution.created_at is not None
    finally:
        session.close()


def test_methodology_persists_full_provenance_and_upstream_snapshot(session_factory, project_id, approved_contribution_id):
    provider = FakeLLMProvider(responses=[{"description": "A methodology."}])
    outcome = generate_methodology_plan(
        project_id, approved_contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        plan = repository.get_methodology_plan(session, outcome.methodology_plan_id)
        assert plan.provider == "fake"
        assert plan.model == "fake-model-1"
        assert plan.prompt_name == "methodology_generation"
        assert plan.prompt_version == "v1"
        assert plan.contribution_candidate_id == approved_contribution_id
        assert plan.contribution_candidate_version == 1
        assert plan.contribution_candidate_status_at_generation == "approved"
    finally:
        session.close()


def test_dataset_requirements_persists_upstream_snapshot(session_factory, project_id, approved_methodology_id):
    provider = FakeLLMProvider(responses=[{"required_characteristics": "X."}])
    outcome = generate_dataset_requirements(
        project_id, approved_methodology_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        requirements = repository.get_dataset_requirements(session, outcome.dataset_requirements_id)
        assert requirements.methodology_plan_id == approved_methodology_id
        assert requirements.methodology_plan_version == 1
        assert requirements.methodology_plan_status_at_generation == "approved"
        assert requirements.prompt_name == "dataset_requirements_generation"
    finally:
        session.close()


def test_experimental_design_persists_both_upstream_snapshots(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{
        "proposed_method": "A method.", "addressed_research_question_ids": [approved_question_id],
    }])
    outcome = generate_experimental_design(
        project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        design = repository.get_experimental_design(session, outcome.experimental_design_id)
        assert design.methodology_plan_id == approved_methodology_id
        assert design.methodology_plan_version == 1
        assert design.methodology_plan_status_at_generation == "approved"
        assert design.dataset_requirements_id == approved_dataset_requirements_id
        assert design.dataset_requirements_status_at_generation == "approved"
        assert design.prompt_name == "experimental_design_generation"
        assert design.prompt_version == "v1"
    finally:
        session.close()
