"""ExperimentSpecification generation service tests (Phase 8A)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.errors import IntegrityConstraintError
from researchos.db.models import DatasetLifecycleStatus, PlanningApprovalStatus
from researchos.planning.errors import (
    CrossProjectReferenceError,
    InvalidPlanningResponseError,
    UpstreamNotApprovedError,
)
from researchos.specification.experiment_specifications import generate_experiment_specification
from researchos.specification.fingerprint import compute_configuration_hash
from tests.specification.fakes import FakeLLMProvider


def _fake_response(question_id, **overrides):
    payload = {
        "description": "Fine-tune and evaluate the proposed alloy against two baselines.",
        "configuration": {"seed": 42, "hardware_profile": "single-gpu"},
        "baselines": [{"name": "standard-alloy-A", "rationale": "industry standard"}],
        "addressed_research_question_ids": [question_id],
    }
    payload.update(overrides)
    return payload


def test_generates_candidate_specification_never_approved(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id)])
    outcome = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        spec = repository.get_experiment_specification(session, outcome.experiment_specification_id)
        assert spec.planning_status == PlanningApprovalStatus.CANDIDATE
        assert spec.experimental_design_id == approved_experimental_design_id
        assert spec.dataset_version_id == approved_dataset_version_id
        assert spec.configuration == {"seed": 42, "hardware_profile": "single-gpu"}
        assert spec.configuration_hash == compute_configuration_hash(spec.configuration)
        links = repository.list_experiment_specification_questions(
            session, project_id, experiment_specification_id=spec.id
        )
        assert [l.research_question_id for l in links] == [approved_question_id]
        baselines = repository.list_baseline_specifications(session, project_id, experiment_specification_id=spec.id)
        assert len(baselines) == 1
        assert baselines[0].name == "standard-alloy-A"
    finally:
        session.close()


# --- Versioning / supersedes -------------------------------------------------


def test_regenerating_via_supersedes_id_creates_a_real_v2_and_preserves_v1(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    first = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id, description="v1 description")]),
        session_factory=session_factory,
    )
    second = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id, description="v2 description")]),
        supersedes_id=first.experiment_specification_id, session_factory=session_factory,
    )
    session = session_factory()
    try:
        v1 = repository.get_experiment_specification(session, first.experiment_specification_id)
        v2 = repository.get_experiment_specification(session, second.experiment_specification_id)
        assert v1.version == 1
        assert v1.description == "v1 description"
        assert v2.version == 2
        assert v2.supersedes_id == first.experiment_specification_id
        assert v2.description == "v2 description"
    finally:
        session.close()


def test_independent_specifications_do_not_share_a_lineage(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    a = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]), session_factory=session_factory,
    )
    b = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]), session_factory=session_factory,
    )
    session = session_factory()
    try:
        sa = repository.get_experiment_specification(session, a.experiment_specification_id)
        sb = repository.get_experiment_specification(session, b.experiment_specification_id)
        assert sa.version == 1
        assert sb.version == 1
        assert sa.supersedes_id is None
        assert sb.supersedes_id is None
    finally:
        session.close()


def test_duplicate_version_via_double_supersede_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    first = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]), session_factory=session_factory,
    )
    generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]),
        supersedes_id=first.experiment_specification_id, session_factory=session_factory,
    )
    with pytest.raises(IntegrityConstraintError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake",
            provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]),
            supersedes_id=first.experiment_specification_id, session_factory=session_factory,
        )


def test_supersedes_id_from_another_project_is_rejected(
    session_factory, project_id, second_project_id, approved_experimental_design_id, approved_dataset_version_id,
    approved_question_id,
):
    session = session_factory()
    try:
        other_spec = repository.create_experiment_specification(session, project_id=second_project_id)
        session.commit()
        other_id = other_spec.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id)])
    with pytest.raises(CrossProjectReferenceError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, supersedes_id=other_id,
            session_factory=session_factory,
        )
    assert provider.calls == []  # rejected before any LLM call


# --- Approved-upstream enforcement -------------------------------------------


def test_unapproved_experimental_design_is_refused_before_any_llm_call(
    session_factory, project_id, approved_methodology_id, approved_dataset_version_id, approved_question_id
):
    session = session_factory()
    try:
        draft_design = repository.create_experimental_design(
            session, project_id=project_id, proposed_method="Not yet approved.",
            methodology_plan_id=approved_methodology_id,
        )
        session.commit()
        design_id = draft_design.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(UpstreamNotApprovedError):
        generate_experiment_specification(
            project_id, design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    assert provider.calls == []


def test_unapproved_dataset_version_is_refused_before_any_llm_call(
    session_factory, project_id, approved_experimental_design_id, dataset_record_id, approved_question_id
):
    session = session_factory()
    try:
        draft_version = repository.create_dataset_version(
            session, project_id=project_id, dataset_record_id=dataset_record_id,
        )
        session.commit()
        version_id = draft_version.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(UpstreamNotApprovedError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    assert provider.calls == []


def test_contribution_candidate_id_from_another_project_is_rejected(
    session_factory, project_id, second_project_id, approved_experimental_design_id, approved_dataset_version_id,
    approved_question_id,
):
    session = session_factory()
    try:
        other_contribution = repository.create_contribution_candidate(
            session, project_id=second_project_id, title="Other project's contribution", description="...",
        )
        session.commit()
        other_contribution_id = other_contribution.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(CrossProjectReferenceError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider,
            contribution_candidate_ids=[other_contribution_id], session_factory=session_factory,
        )
    assert provider.calls == []  # rejected before any LLM call


def test_missing_experimental_design_is_rejected(session_factory, project_id, approved_dataset_version_id, approved_question_id):
    provider = FakeLLMProvider(responses=[])
    with pytest.raises(Exception):
        generate_experiment_specification(
            project_id, 999_999, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    assert provider.calls == []


def test_wrong_project_dataset_version_is_rejected(
    session_factory, project_id, second_project_id, approved_experimental_design_id, approved_question_id
):
    session = session_factory()
    try:
        other_record = repository.register_dataset(
            session, project_id=second_project_id, name="Other project dataset", version="raw",
            path_or_uri="s3://other/",
        )
        other_version = repository.create_dataset_version(
            session, project_id=second_project_id, dataset_record_id=other_record.id,
        )
        repository.update_dataset_version(session, other_version.id, lifecycle_status=DatasetLifecycleStatus.APPROVED)
        session.commit()
        other_version_id = other_version.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(CrossProjectReferenceError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, other_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    assert provider.calls == []


def test_rejected_experimental_design_is_refused(
    session_factory, project_id, approved_methodology_id, approved_dataset_version_id, approved_question_id
):
    from researchos.planning import approval as planning_approval

    session = session_factory()
    try:
        design = repository.create_experimental_design(
            session, project_id=project_id, proposed_method="Will be rejected.",
            methodology_plan_id=approved_methodology_id,
        )
        session.commit()
        design_id = design.id
    finally:
        session.close()

    planning_approval.reject_experimental_design(design_id, actor="user:pi", session_factory=session_factory)

    provider = FakeLLMProvider(responses=[])
    with pytest.raises(UpstreamNotApprovedError):
        generate_experiment_specification(
            project_id, design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    assert provider.calls == []


# --- Provenance snapshot -------------------------------------------------


def test_provenance_snapshot_persisted(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id)])
    outcome = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        spec = repository.get_experiment_specification(session, outcome.experiment_specification_id)
        assert spec.experimental_design_version == 1
        assert spec.experimental_design_status_at_generation == "approved"
        assert spec.dataset_version_version == 1
        assert spec.dataset_version_status_at_generation == "approved"
        assert spec.methodology_plan_version == 1
        assert spec.methodology_plan_status_at_generation == "approved"
        assert spec.provider == "fake"
        assert spec.model == "fake-model-1"
        assert spec.prompt_name == "experiment_specification_generation"
        assert spec.prompt_version == "v1"
    finally:
        session.close()


# --- Configuration validation / hashing --------------------------------------


def test_configuration_hash_is_deterministic_regardless_of_key_order(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id, configuration={"b": 2, "a": 1})])
    outcome = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        spec = repository.get_experiment_specification(session, outcome.experiment_specification_id)
        expected = compute_configuration_hash({"a": 1, "b": 2})
        assert spec.configuration_hash == expected
    finally:
        session.close()


def test_malformed_configuration_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id, configuration="not-an-object")])
    with pytest.raises(Exception):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    session = session_factory()
    try:
        assert repository.list_experiment_specifications(session, project_id) == []
    finally:
        session.close()


def test_configuration_with_secret_like_key_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[
        _fake_response(approved_question_id, configuration={"api_key": "sk-fake-should-be-rejected"})
    ])
    with pytest.raises(Exception):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    session = session_factory()
    try:
        assert repository.list_experiment_specifications(session, project_id) == []
    finally:
        session.close()


# --- Associations --------------------------------------------------------


def test_contribution_associations(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id,
    approved_contribution_id,
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id)])
    outcome = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider,
        contribution_candidate_ids=[approved_contribution_id], session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_experiment_specification_contributions(
            session, project_id, experiment_specification_id=outcome.experiment_specification_id
        )
        assert [l.contribution_candidate_id for l in links] == [approved_contribution_id]
    finally:
        session.close()


def test_multiple_specifications_can_address_the_same_question(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    """RQ1 -> Spec1, RQ1 -> Spec2."""
    a = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]), session_factory=session_factory,
    )
    b = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake",
        provider=FakeLLMProvider(responses=[_fake_response(approved_question_id)]), session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_experiment_specification_questions(session, project_id, research_question_id=approved_question_id)
        spec_ids = {l.experiment_specification_id for l in links}
        assert spec_ids == {a.experiment_specification_id, b.experiment_specification_id}
    finally:
        session.close()
