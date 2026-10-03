"""Dataset requirements generation service tests (Phase 7 spec section 28)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus
from researchos.planning.dataset_requirements import generate_dataset_requirements
from researchos.planning.errors import UpstreamNotApprovedError
from tests.planning.fakes import FakeLLMProvider


def test_generates_candidate_requirements_with_upstream_snapshot(session_factory, project_id, approved_methodology_id):
    provider = FakeLLMProvider(responses=[{
        "required_characteristics": "At least 500 alloy stress-test samples.",
        "split_strategy": "80/10/10 train/val/test, grouped by sample batch.",
        "leakage_considerations": "No sample from the same batch appears in more than one split.",
        "risks": ["small sample size"],
    }])
    outcome = generate_dataset_requirements(
        project_id, approved_methodology_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        requirements = repository.get_dataset_requirements(session, outcome.dataset_requirements_id)
        assert requirements.planning_status == PlanningApprovalStatus.CANDIDATE
        assert requirements.methodology_plan_id == approved_methodology_id
        assert requirements.methodology_plan_status_at_generation == "approved"
        assert "80/10/10" in requirements.split_strategy
    finally:
        session.close()


def test_never_references_an_actual_dataset_record(session_factory, project_id, approved_methodology_id):
    """DatasetRequirements has no path_or_uri column — this service can
    never point at a real, acquired dataset; that stays DatasetRecord's
    exclusive concern."""
    provider = FakeLLMProvider(responses=[{"required_characteristics": "Needs labeled samples."}])
    outcome = generate_dataset_requirements(
        project_id, approved_methodology_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        requirements = repository.get_dataset_requirements(session, outcome.dataset_requirements_id)
        assert not hasattr(requirements, "path_or_uri")
        assert repository.list_datasets(session, project_id) == []
    finally:
        session.close()


def test_unapproved_methodology_is_refused(session_factory, project_id, approved_contribution_id):
    session = session_factory()
    try:
        plan = repository.create_methodology_version(
            session, project_id=project_id, description="Draft.", contribution_candidate_id=approved_contribution_id,
        )
        session.commit()
        plan_id = plan.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(UpstreamNotApprovedError):
        generate_dataset_requirements(
            project_id, plan_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
    assert provider.calls == []
