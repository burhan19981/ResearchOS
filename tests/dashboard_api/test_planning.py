"""Planning traceability page: Research Gap -> Question -> Contribution
-> Methodology -> Dataset Requirements -> Experimental Design ->
Experiment Specification."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import PlanningApprovalStatus


def test_planning_empty_state(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/planning")
    assert response.status_code == 200
    body = response.json()
    assert body["research_questions"] == []
    assert body["contribution_candidates"] == []


def test_planning_shows_full_chain_with_citations(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(
            session, project_id=project_id, question="How can widgets be more durable?",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        contribution = repository.create_contribution_candidate(
            session, project_id=project_id, title="A durable alloy", description="A new alloy.",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        repository.link_contribution_candidate_question(
            session, project_id=project_id, contribution_candidate_id=contribution.id, research_question_id=question.id,
        )
        plan = repository.create_methodology_version(
            session, project_id=project_id, description="A controlled study.",
            planning_status=PlanningApprovalStatus.APPROVED, contribution_candidate_id=contribution.id,
        )
        session.commit()
        question_id, contribution_id, plan_id = question.id, contribution.id, plan.id

    response = client.get(f"/api/v1/projects/{project_id}/planning")
    body = response.json()
    assert len(body["research_questions"]) == 1
    assert body["research_questions"][0]["id"] == question_id
    assert len(body["contribution_candidates"]) == 1
    assert body["contribution_candidates"][0]["cited_research_question_ids"] == [question_id]
    assert len(body["methodology_plans"]) == 1
    assert body["methodology_plans"][0]["contribution_candidate_id"] == contribution_id
