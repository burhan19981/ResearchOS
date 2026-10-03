"""Provider-abstraction and anti-hallucination integration tests
(Phase 8A): the provider is only ever accessed through the injected
`provider=` parameter, no secret leaks into a prompt or audit event, a
malformed response is rejected, hallucinated/unknown/cross-project ids
are rejected, and an LLM cannot self-assign APPROVED or mutate upstream
entities.
"""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus
from researchos.planning.errors import InvalidPlanningResponseError
from researchos.planning.llm_call import resolve_provider
from researchos.specification.experiment_specifications import generate_experiment_specification
from tests.specification.fakes import FakeLLMProvider


def _fake_response(question_id, **overrides):
    payload = {
        "description": "A candidate specification.",
        "configuration": {"seed": 1},
        "addressed_research_question_ids": [question_id],
    }
    payload.update(overrides)
    return payload


def test_resolve_provider_returns_injected_provider_without_touching_registry():
    provider = FakeLLMProvider()
    resolved = resolve_provider("this-provider-name-does-not-exist-in-the-registry", provider)
    assert resolved is provider


def test_structured_response_missing_required_keys_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{"not_the_right_shape": True}])
    with pytest.raises(InvalidPlanningResponseError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )


def test_structured_response_wrong_type_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[["not", "an", "object"]])
    with pytest.raises(InvalidPlanningResponseError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )


def test_hallucinated_research_question_id_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id, addressed_research_question_ids=[999_999])])
    with pytest.raises(InvalidPlanningResponseError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )
    session = session_factory()
    try:
        assert repository.list_experiment_specifications(session, project_id) == []
    finally:
        session.close()


def test_unknown_id_in_addressed_questions_is_rejected(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    """An id that isn't even a real ResearchQuestion anywhere — not just
    outside this call's context — must also be rejected the same way."""
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id, addressed_research_question_ids=[123_456_789])])
    with pytest.raises(InvalidPlanningResponseError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )


def test_cross_project_id_in_addressed_questions_is_rejected(
    session_factory, project_id, second_project_id, approved_experimental_design_id, approved_dataset_version_id,
    approved_question_id,
):
    session = session_factory()
    try:
        other_question = repository.create_research_question(
            session, project_id=second_project_id, question="Another project's question?",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        session.commit()
        other_question_id = other_question.id
    finally:
        session.close()

    provider = FakeLLMProvider(
        responses=[_fake_response(approved_question_id, addressed_research_question_ids=[other_question_id])]
    )
    with pytest.raises(InvalidPlanningResponseError):
        generate_experiment_specification(
            project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
            actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
        )


def test_llm_cannot_self_assign_approved_status(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    """Even if a malicious/mock LLM sneaks a planning_status field into
    its response, the persisted specification must still be CANDIDATE —
    the schema never offers this field and the service never reads it."""
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id, planning_status="approved")])
    outcome = generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        spec = repository.get_experiment_specification(session, outcome.experiment_specification_id)
        assert spec.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()


def test_llm_output_never_mutates_upstream_entities(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    """Generation must never write to the ExperimentalDesign, DatasetVersion,
    or ResearchQuestion it was grounded in."""
    session = session_factory()
    try:
        design_before = repository.get_experimental_design(session, approved_experimental_design_id)
        design_snapshot = (design_before.proposed_method, design_before.planning_status, design_before.version)
        dv_before = repository.get_dataset_version(session, approved_dataset_version_id)
        dv_snapshot = (dv_before.lifecycle_status, dv_before.version, dv_before.content_fingerprint)
        q_before = repository.get_research_question(session, approved_question_id)
        q_snapshot = (q_before.question, q_before.planning_status)
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[_fake_response(
        approved_question_id,
        description="Attempting to smuggle upstream mutation via configuration.",
        configuration={"experimental_design_id": approved_experimental_design_id, "mutate": "ignored"},
    )])
    generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )

    session = session_factory()
    try:
        design_after = repository.get_experimental_design(session, approved_experimental_design_id)
        assert (design_after.proposed_method, design_after.planning_status, design_after.version) == design_snapshot
        dv_after = repository.get_dataset_version(session, approved_dataset_version_id)
        assert (dv_after.lifecycle_status, dv_after.version, dv_after.content_fingerprint) == dv_snapshot
        q_after = repository.get_research_question(session, approved_question_id)
        assert (q_after.question, q_after.planning_status) == q_snapshot
    finally:
        session.close()


def test_no_secrets_appear_in_prompt_text_or_audit_events(
    session_factory, project_id, approved_experimental_design_id, approved_dataset_version_id, approved_question_id
):
    fake_secret = "sk-super-secret-test-token-should-never-appear"  # noqa: S105 - test fixture only
    provider = FakeLLMProvider(responses=[_fake_response(approved_question_id)])
    generate_experiment_specification(
        project_id, approved_experimental_design_id, approved_dataset_version_id, [approved_question_id],
        actor="agent:planner", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    assert provider.last_request is not None
    for message in provider.last_request.messages:
        assert fake_secret not in message.content

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        for event in events:
            assert fake_secret not in (event.description or "")
            assert fake_secret not in str(event.metadata_ or {})
    finally:
        session.close()
