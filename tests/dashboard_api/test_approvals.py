"""Approval Center: dispatch across every domain layer, human-only
enforcement, cross-project rejection, and the "no fake frontend
approval" guarantee — every decision must actually persist through the
real domain approval mechanism (Dashboard V1 spec section 18)."""

from __future__ import annotations

from researchos.analysis.approval import approve_scientific_review
from researchos.analysis.claims import create_scientific_claim
from researchos.analysis.records import compare_runs
from researchos.analysis.reviews import create_scientific_review
from researchos.db import repository
from researchos.db.models import (
    ApprovalDecision,
    ClaimApprovalStatus,
    MetricValueType,
    PlanningApprovalStatus,
    ScientificReviewStatus,
)


def test_list_approvals_empty(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/approvals")
    assert response.status_code == 200
    assert response.json() == []


def test_approve_research_question_via_dashboard(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(
            session, project_id=project_id, question="A candidate question?",
            planning_status=PlanningApprovalStatus.CANDIDATE,
        )
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        question_id, approval_id = question.id, approval.id

    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve", "comment": "Looks good."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approval"]["decision"] == "approved"
    assert body["entity_status"] == "approved"

    # Persisted for real through the actual domain mechanism — verify
    # directly against the database, not just the API's own echo.
    with session_factory() as session:
        reloaded = repository.get_research_question(session, question_id)
        assert reloaded.planning_status == PlanningApprovalStatus.APPROVED
        approval_row = repository.get_approval(session, approval_id)
        assert approval_row.decision == ApprovalDecision.APPROVED
        assert approval_row.comment == "Looks good."


def test_approval_list_parses_entity_type_and_id(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=project_id, question="Q?")
        repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        question_id = question.id

    response = client.get(f"/api/v1/projects/{project_id}/approvals")
    body = response.json()
    assert len(body) == 1
    assert body[0]["entity_type"] == "ResearchQuestion"
    assert body[0]["entity_id"] == question_id
    assert body[0]["decision"] == "pending"


def test_reject_and_request_changes_actions(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=project_id, question="Q?")
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        approval_id = approval.id

    response = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "reject"})
    assert response.status_code == 200
    assert response.json()["approval"]["decision"] == "rejected"
    assert response.json()["entity_status"] == "rejected"


def test_act_on_nonexistent_approval_404(client, project_id):
    response = client.post(f"/api/v1/projects/{project_id}/approvals/999999/actions", json={"action": "approve"})
    assert response.status_code == 404


def test_act_on_approval_from_another_project_404(client, session_factory, project_id, second_project_id):
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=second_project_id, question="Q?")
        approval = repository.create_approval_request(session, project_id=second_project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        approval_id = approval.id

    # Acting on it via the WRONG (first) project's URL must 404, never
    # silently act cross-project.
    response = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve"})
    assert response.status_code == 404


def test_approving_already_decided_approval_returns_conflict(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=project_id, question="Q?")
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        approval_id = approval.id

    first = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve"})
    assert first.status_code == 200
    second = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve"})
    assert second.status_code == 409


def test_invalid_action_value_returns_422(client, session_factory, project_id):
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=project_id, question="Q?")
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        approval_id = approval.id

    response = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "self_approve"})
    assert response.status_code == 422


def test_scientific_review_approval_requires_ready_status(client, session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.85, value_type=MetricValueType.FLOAT)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    record = compare_runs(project_id, run1_id, run2_id, "f1", actor="tester", session_factory=session_factory)
    claim = create_scientific_claim(project_id, "A claim.", [record.id], actor="tester", session_factory=session_factory)
    review = create_scientific_review(
        project_id, claim.id, {"evidence_completeness": "partial"}, actor="tester",
        status=ScientificReviewStatus.DRAFT, session_factory=session_factory,
    )

    with session_factory() as session:
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"SCIENTIFIC_REVIEW_APPROVAL:{review.id}")
        session.commit()
        approval_id = approval.id

    # DRAFT, not READY_FOR_HUMAN_REVIEW -> the domain precondition
    # rejects this, surfaced as a structured 400, not a 500 traceback.
    response = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve"})
    assert response.status_code == 400
    assert response.json()["error"] == "ReviewNotReadyError"


def test_scientific_claim_approval_requires_approved_review(client, session_factory, project_id):
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.85, value_type=MetricValueType.FLOAT)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    record = compare_runs(project_id, run1_id, run2_id, "f1", actor="tester", session_factory=session_factory)
    claim = create_scientific_claim(project_id, "A claim.", [record.id], actor="tester", session_factory=session_factory)

    with session_factory() as session:
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"SCIENTIFIC_CLAIM_APPROVAL:{claim.id}")
        session.commit()
        approval_id = approval.id

    response = client.post(f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions", json={"action": "approve"})
    assert response.status_code == 400
    assert response.json()["error"] == "ClaimNotSupportedByApprovedReviewError"

    with session_factory() as session:
        claim_row = repository.get_scientific_claim(session, claim.id)
        assert claim_row.approval_status == ClaimApprovalStatus.PENDING_REVIEW


def test_client_supplied_actor_field_is_ignored_not_trusted(client, session_factory, project_id):
    """`ApprovalActionRequest` has no actor/identity field at all — a
    client trying to smuggle one in (e.g. attempting to impersonate a
    human, or an `is_human=true`-style field) must have zero effect;
    the server always records its own fixed, non-agent actor string."""
    with session_factory() as session:
        question = repository.create_research_question(session, project_id=project_id, question="Q?")
        approval = repository.create_approval_request(session, project_id=project_id, stage=f"RESEARCH_QUESTION_APPROVAL:{question.id}")
        session.commit()
        approval_id = approval.id

    response = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approval_id}/actions",
        json={"action": "approve", "actor": "agent:not_a_human", "is_human": True},
    )
    assert response.status_code == 200  # extra unknown fields are silently ignored, not an error
    with session_factory() as session:
        events = repository.list_audit_events(session, project_id)
        approval_events = [e for e in events if "approved" in e.event_type]
        assert approval_events
        assert approval_events[0].actor == "user:dashboard"


def test_full_scientific_claim_approval_chain_via_dashboard(client, session_factory, project_id):
    """The complete evidence chain end-to-end through the dashboard's
    own approval endpoint: review approval, THEN claim approval — the
    two-step precondition genuinely enforced, not bypassed."""
    with session_factory() as session:
        experiment = repository.register_experiment(session, project_id=project_id, name="Exp A")
        r1 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r1.id, name="f1", value=0.8, value_type=MetricValueType.FLOAT)
        r2 = repository.create_run(session, project_id=project_id, experiment_id=experiment.id, timeout_seconds=60)
        repository.create_metric(session, project_id=project_id, run_id=r2.id, name="f1", value=0.85, value_type=MetricValueType.FLOAT)
        session.commit()
        run1_id, run2_id = r1.id, r2.id

    record = compare_runs(project_id, run1_id, run2_id, "f1", actor="tester", session_factory=session_factory)
    claim = create_scientific_claim(project_id, "A claim.", [record.id], actor="tester", session_factory=session_factory)
    review = create_scientific_review(
        project_id, claim.id, {"evidence_completeness": "partial"}, actor="tester",
        status=ScientificReviewStatus.READY_FOR_HUMAN_REVIEW, session_factory=session_factory,
    )

    with session_factory() as session:
        review_approval = repository.create_approval_request(session, project_id=project_id, stage=f"SCIENTIFIC_REVIEW_APPROVAL:{review.id}")
        claim_approval = repository.create_approval_request(session, project_id=project_id, stage=f"SCIENTIFIC_CLAIM_APPROVAL:{claim.id}")
        session.commit()
        review_approval_id, claim_approval_id = review_approval.id, claim_approval.id

    review_response = client.post(f"/api/v1/projects/{project_id}/approvals/{review_approval_id}/actions", json={"action": "approve"})
    assert review_response.status_code == 200
    assert review_response.json()["entity_status"] == "human_approved"

    claim_response = client.post(f"/api/v1/projects/{project_id}/approvals/{claim_approval_id}/actions", json={"action": "approve"})
    assert claim_response.status_code == 200
    assert claim_response.json()["entity_status"] == "approved"

    with session_factory() as session:
        assert repository.get_scientific_claim(session, claim.id).approval_status == ClaimApprovalStatus.APPROVED
