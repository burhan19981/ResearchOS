"""Contribution candidate generation service tests (Phase 7 spec section 26)."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus
from researchos.planning.contributions import generate_contribution_candidates
from tests.planning.fakes import FakeLLMProvider


def test_generates_candidate_contribution_never_approved(session_factory, project_id, approved_question_id):
    provider = FakeLLMProvider(responses=[{
        "contributions": [
            {"title": "A new alloy", "description": "Proposes a new alloy composition.",
             "contribution_type": "methodological", "cited_research_question_ids": [approved_question_id]},
        ]
    }])
    outcome = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.rejected_count == 0
    assert len(outcome.contribution_ids) == 1

    session = session_factory()
    try:
        contribution = repository.get_contribution_candidate(session, outcome.contribution_ids[0])
        assert contribution.planning_status == PlanningApprovalStatus.CANDIDATE
        links = repository.list_contribution_candidate_questions(
            session, project_id, contribution_candidate_id=contribution.id
        )
        assert [l.research_question_id for l in links] == [approved_question_id]
    finally:
        session.close()


def test_contribution_with_no_cited_question_is_rejected(session_factory, project_id, approved_question_id):
    provider = FakeLLMProvider(responses=[{
        "contributions": [{"title": "Unsupported", "description": "No citations.", "cited_research_question_ids": []}]
    }])
    outcome = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.contribution_ids == []
    assert outcome.rejected_count == 1


def test_hallucinated_question_id_is_rejected(session_factory, project_id, approved_question_id):
    provider = FakeLLMProvider(responses=[{
        "contributions": [{
            "title": "Hallucinated", "description": "Cites a question it was never given.",
            "cited_research_question_ids": [999_999],
        }]
    }])
    outcome = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.contribution_ids == []
    assert outcome.rejected_count == 1


def test_never_claims_novelty_in_persisted_fields(session_factory, project_id, approved_question_id):
    """ContributionCandidate has no novelty-related column at all — this
    service must never write to NoveltyAssessment or any novelty field."""
    provider = FakeLLMProvider(responses=[{
        "contributions": [{"title": "X", "description": "Y", "cited_research_question_ids": [approved_question_id]}]
    }])
    outcome = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        assert repository.list_novelty_assessments(session, project_id) == []
        contribution = repository.get_contribution_candidate(session, outcome.contribution_ids[0])
        assert not hasattr(contribution, "novelty_risk")
    finally:
        session.close()


# --- Versioning / lineage (audit remediation, Finding C) --------------------


def test_regenerating_via_supersedes_id_creates_a_real_v2_and_preserves_v1(
    session_factory, project_id, approved_question_id
):
    provider = FakeLLMProvider(responses=[{
        "contributions": [{"title": "First idea", "description": "Version one.",
                            "cited_research_question_ids": [approved_question_id]}]
    }])
    first = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert len(first.contribution_ids) == 1
    first_id = first.contribution_ids[0]

    provider2 = FakeLLMProvider(responses=[{
        "contributions": [{"title": "Revised idea", "description": "Version two, a genuine revision.",
                            "cited_research_question_ids": [approved_question_id]}]
    }])
    second = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider2,
        supersedes_id=first_id, session_factory=session_factory,
    )
    assert len(second.contribution_ids) == 1
    second_id = second.contribution_ids[0]
    assert second_id != first_id

    session = session_factory()
    try:
        v1 = repository.get_contribution_candidate(session, first_id)
        v2 = repository.get_contribution_candidate(session, second_id)
        assert v1.version == 1
        assert v1.supersedes_id is None
        assert v1.title == "First idea"  # v1 unchanged by the regeneration
        assert v2.version == 2
        assert v2.supersedes_id == first_id  # traceable to the same lineage
        assert v2.title == "Revised idea"
    finally:
        session.close()


def test_independent_contributions_do_not_share_a_lineage(session_factory, project_id, approved_question_id):
    """Two unrelated contributions (no supersedes_id) both start at
    version 1 and remain independent — never silently sharing a
    project-wide counter."""
    provider_a = FakeLLMProvider(responses=[{
        "contributions": [{"title": "Idea A", "description": "First independent idea.",
                            "cited_research_question_ids": [approved_question_id]}]
    }])
    outcome_a = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider_a,
        session_factory=session_factory,
    )
    provider_b = FakeLLMProvider(responses=[{
        "contributions": [{"title": "Idea B", "description": "Second, unrelated idea.",
                            "cited_research_question_ids": [approved_question_id]}]
    }])
    outcome_b = generate_contribution_candidates(
        project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider_b,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        a = repository.get_contribution_candidate(session, outcome_a.contribution_ids[0])
        b = repository.get_contribution_candidate(session, outcome_b.contribution_ids[0])
        assert a.version == 1
        assert b.version == 1
        assert a.supersedes_id is None
        assert b.supersedes_id is None
        assert a.id != b.id
    finally:
        session.close()


def test_supersedes_id_from_another_project_is_rejected(session_factory, project_id, second_project_id, approved_question_id):
    from researchos.planning.errors import CrossProjectReferenceError

    session = session_factory()
    try:
        other_contribution = repository.create_contribution_candidate(
            session, project_id=second_project_id, title="Other project's contribution", description="...",
        )
        session.commit()
        other_id = other_contribution.id
    finally:
        session.close()

    provider = FakeLLMProvider(responses=[{
        "contributions": [{"title": "X", "description": "Y", "cited_research_question_ids": [approved_question_id]}]
    }])
    try:
        generate_contribution_candidates(
            project_id, [approved_question_id], actor="agent:planner", provider_name="fake", provider=provider,
            supersedes_id=other_id, session_factory=session_factory,
        )
        assert False, "expected CrossProjectReferenceError"
    except CrossProjectReferenceError:
        pass
    assert provider.calls == []  # rejected before any LLM call
