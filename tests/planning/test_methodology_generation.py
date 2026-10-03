"""Methodology plan generation service tests (Phase 7 spec section 27)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import MethodologyStatus, PlanningApprovalStatus
from researchos.planning.errors import UpstreamNotApprovedError
from researchos.planning.methodology import generate_methodology_plan
from tests.planning.fakes import FakeLLMProvider


def test_generates_candidate_methodology_with_upstream_snapshot(session_factory, project_id, approved_contribution_id):
    provider = FakeLLMProvider(responses=[{
        "description": "Run a controlled comparison of alloy compositions.",
        "methodology_type": "experimental",
        "components": ["sample preparation", "stress testing"],
        "assumptions": ["ambient temperature is controlled"],
        "risks": ["sample contamination"],
        "reproducibility_requirements": "Record exact alloy ratios.",
    }])
    outcome = generate_methodology_plan(
        project_id, approved_contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        plan = repository.get_methodology_plan(session, outcome.methodology_plan_id)
        assert plan.planning_status == PlanningApprovalStatus.CANDIDATE
        assert plan.status == MethodologyStatus.DRAFT  # untouched lifecycle status
        assert plan.contribution_candidate_id == approved_contribution_id
        assert plan.contribution_candidate_status_at_generation == "approved"
        assert plan.components == ["sample preparation", "stress testing"]
    finally:
        session.close()


def test_unapproved_contribution_is_refused_before_any_llm_call(session_factory, project_id):
    session = session_factory()
    try:
        contribution = repository.create_contribution_candidate(
            session, project_id=project_id, title="Not approved", description="...",
        )
        session.commit()
        contribution_id = contribution.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])  # would raise AssertionError if ever called
    with pytest.raises(UpstreamNotApprovedError):
        generate_methodology_plan(
            project_id, contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
    assert provider.calls == []


def test_blank_description_is_rejected(session_factory, project_id, approved_contribution_id):
    provider = FakeLLMProvider(responses=[{"description": "   "}])
    with pytest.raises(Exception):
        generate_methodology_plan(
            project_id, approved_contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
    session = session_factory()
    try:
        assert repository.list_methodology_plans(session, project_id) == []
    finally:
        session.close()


def test_regeneration_creates_a_new_version_never_overwrites(session_factory, project_id, approved_contribution_id):
    provider = FakeLLMProvider(responses=[
        {"description": "First proposed methodology."},
        {"description": "Second, revised methodology."},
    ])
    first = generate_methodology_plan(
        project_id, approved_contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    second = generate_methodology_plan(
        project_id, approved_contribution_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert first.methodology_plan_id != second.methodology_plan_id

    session = session_factory()
    try:
        first_plan = repository.get_methodology_plan(session, first.methodology_plan_id)
        second_plan = repository.get_methodology_plan(session, second.methodology_plan_id)
        assert first_plan.version == 1
        assert second_plan.version == 2
        assert first_plan.description == "First proposed methodology."  # v1 unchanged
        assert second_plan.description == "Second, revised methodology."
    finally:
        session.close()
