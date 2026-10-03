"""Evidence/literature, gaps, and novelty pages — including project
isolation (a record in project B must never appear when querying
project A)."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import EvidenceRelationship, EvidenceSubjectType, GapStatus, NoveltyCandidateStatus


def test_literature_empty_state(client, project_id):
    response = client.get(f"/api/v1/projects/{project_id}/literature")
    assert response.status_code == 200
    assert response.json() == []


def test_literature_project_isolation(client, session_factory, project_id, second_project_id):
    with session_factory() as session:
        repository.add_literature_item(session, project_id=project_id, title="Project A paper", source="openalex", source_record_id="W1")
        repository.add_literature_item(session, project_id=second_project_id, title="Project B paper", source="openalex", source_record_id="W2")
        session.commit()

    response_a = client.get(f"/api/v1/projects/{project_id}/literature")
    titles_a = {i["title"] for i in response_a.json()}
    assert titles_a == {"Project A paper"}

    response_b = client.get(f"/api/v1/projects/{second_project_id}/literature")
    titles_b = {i["title"] for i in response_b.json()}
    assert titles_b == {"Project B paper"}


def test_literature_search_filter(client, session_factory, project_id):
    with session_factory() as session:
        repository.add_literature_item(session, project_id=project_id, title="Widget durability study", source="openalex", source_record_id="W1")
        repository.add_literature_item(session, project_id=project_id, title="Gadget efficiency review", source="crossref", source_record_id="W2")
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/literature", params={"q": "widget"})
    titles = {i["title"] for i in response.json()}
    assert titles == {"Widget durability study"}


def test_gaps_include_evidence_count(client, session_factory, project_id):
    with session_factory() as session:
        item = repository.add_literature_item(session, project_id=project_id, title="A paper", source="openalex", source_record_id="W1")
        gap = repository.record_research_gap(session, project_id=project_id, statement="A gap.", status=GapStatus.CANDIDATE)
        repository.create_evidence_link(
            session, project_id=project_id, literature_item_id=item.id,
            subject_type=EvidenceSubjectType.GAP_CANDIDATE, subject_id=gap.id,
            relationship_type=EvidenceRelationship.SUPPORTS,
        )
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/gaps")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["evidence_count"] == 1
    assert body[0]["status"] == "candidate"


def test_novelty_reports_candidate_status_not_just_legacy_status(client, session_factory, project_id):
    with session_factory() as session:
        repository.record_novelty_assessment(
            session, project_id=project_id, claim="A candidate claim.",
            candidate_status=NoveltyCandidateStatus.INSUFFICIENT_EVIDENCE,
        )
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/novelty")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["candidate_status"] == "insufficient_evidence"
    # Never silently present the legacy field as if it were the
    # authoritative signal — it is still returned, but candidate_status
    # is the field this test (and the frontend) treats as real.
    assert "status" in body[0]
