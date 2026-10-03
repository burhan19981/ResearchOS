"""Research question generation service tests (Phase 7 spec section 25)."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus
from researchos.llm.errors import LLMError
from researchos.planning.research_questions import generate_research_questions
from tests.planning.fakes import FakeLLMProvider


def test_generates_candidate_questions_never_approved(session_factory, project_id, approved_gap_id, literature_item_ids):
    provider = FakeLLMProvider(responses=[{
        "questions": [
            {"question": "How can widget durability be improved?", "hypothesis": "Alloy X improves durability.",
             "type": "empirical", "cited_literature_item_ids": [literature_item_ids[0]]},
        ]
    }])
    outcome = generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.rejected_count == 0
    assert len(outcome.question_ids) == 1

    session = session_factory()
    try:
        question = repository.get_research_question(session, outcome.question_ids[0])
        assert question.planning_status == PlanningApprovalStatus.CANDIDATE
        assert question.hypothesis == "Alloy X improves durability."
    finally:
        session.close()


def test_hallucinated_literature_id_is_rejected(session_factory, project_id, approved_gap_id, literature_item_ids):
    provider = FakeLLMProvider(responses=[{
        "questions": [
            {"question": "A question citing evidence it was never given.", "cited_literature_item_ids": [999_999]},
        ]
    }])
    outcome = generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.question_ids == []
    assert outcome.rejected_count == 1


def test_blank_question_text_is_rejected(session_factory, project_id, approved_gap_id):
    provider = FakeLLMProvider(responses=[{"questions": [{"question": "   "}]}])
    outcome = generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.question_ids == []
    assert outcome.rejected_count == 1


def test_llm_error_propagates_and_is_audited(session_factory, project_id, approved_gap_id):
    provider = FakeLLMProvider(responses=[LLMError("simulated provider failure")])
    try:
        generate_research_questions(
            project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
        assert False, "expected LLMError to propagate"
    except LLMError:
        pass

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        assert any(e.event_type == "planning.research_question_generation_failed" for e in events)
    finally:
        session.close()


def test_max_questions_is_respected(session_factory, project_id, approved_gap_id):
    provider = FakeLLMProvider(responses=[{
        "questions": [{"question": f"Question {i}?"} for i in range(5)]
    }])
    outcome = generate_research_questions(
        project_id, approved_gap_id, actor="agent:planner", provider_name="fake", provider=provider,
        max_questions=2, session_factory=session_factory,
    )
    assert len(outcome.question_ids) == 2
