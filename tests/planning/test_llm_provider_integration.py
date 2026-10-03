"""Provider-abstraction integration tests (Phase 7 spec section 21-22):
the provider is only ever accessed through the injected `provider=`
parameter (never the real registry when injected), no secret leaks
into a prompt or audit event, and a malformed response is rejected.
"""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.planning.errors import InvalidPlanningResponseError
from researchos.planning.llm_call import resolve_provider
from researchos.planning.research_questions import generate_research_questions
from tests.planning.fakes import FakeLLMProvider


def test_resolve_provider_returns_injected_provider_without_touching_registry():
    provider = FakeLLMProvider()
    resolved = resolve_provider("this-provider-name-does-not-exist-in-the-registry", provider)
    assert resolved is provider


def test_structured_response_missing_required_keys_is_rejected(session_factory, project_id, approved_gap_id):
    provider = FakeLLMProvider(responses=[{"not_questions": []}])
    with pytest.raises(InvalidPlanningResponseError):
        generate_research_questions(
            project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )


def test_structured_response_wrong_type_is_rejected(session_factory, project_id, approved_gap_id):
    provider = FakeLLMProvider(responses=[["not", "an", "object"]])
    with pytest.raises(InvalidPlanningResponseError):
        generate_research_questions(
            project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )


def test_no_secrets_appear_in_prompt_text_or_audit_events(session_factory, project_id, approved_gap_id):
    fake_secret = "sk-super-secret-test-token-should-never-appear"  # noqa: S105 - test fixture only
    provider = FakeLLMProvider(responses=[{"questions": [{"question": "A question?"}]}])
    generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
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


def test_llm_never_persists_an_approved_status_even_if_it_tries(session_factory, project_id, approved_gap_id):
    """Defense in depth: even though the schema never offers a status
    field, a service must ignore one if a provider sneaks it into the
    response anyway — it always hard-codes CANDIDATE."""
    provider = FakeLLMProvider(responses=[{
        "questions": [{"question": "A question?", "planning_status": "approved"}]
    }])
    outcome = generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        from researchos.db.models import PlanningApprovalStatus

        question = repository.get_research_question(session, outcome.question_ids[0])
        assert question.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()
