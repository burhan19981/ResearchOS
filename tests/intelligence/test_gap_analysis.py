"""Gap candidate generation service tests."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import EvidenceRelationship, EvidenceSubjectType, GapStatus
from researchos.intelligence.gap_analysis import generate_gap_candidates

from .fakes import FakeLLMProvider


def test_valid_gap_candidate_is_persisted_as_candidate_never_confirmed(session_factory, project_id, literature_item_ids):
    response = {
        "gaps": [
            {
                "gap_statement": "No prior work addresses widget robustness at scale.",
                "gap_type": "scalability",
                "affected_research_area": "widget engineering",
                "supporting_literature_ids": [literature_item_ids[0]],
                "contradicting_literature_ids": [],
                "evidence_summary": "Both papers focus on small-scale widgets.",
                "confidence": 0.6,
                "prior_work_summary": "Prior work studies small widgets.",
                "insufficiency_summary": "No large-scale evaluation exists.",
                "missing_evidence_summary": "No benchmark at scale.",
                "candidate_research_question": "How robust are widgets at scale?",
            }
        ]
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert len(outcome.gap_ids) == 1

    session = session_factory()
    try:
        gap = repository.get_research_gap(session, outcome.gap_ids[0])
        assert gap.status == GapStatus.CANDIDATE  # never auto-confirmed
        assert gap.gap_type == "scalability"
        assert gap.provider == "fake"
        assert gap.prompt_name == "gap_analysis"
        assert gap.prompt_version == "v1"
    finally:
        session.close()


def test_gap_with_multiple_supporting_papers_links_all_of_them(session_factory, project_id, literature_item_ids):
    response = {
        "gaps": [
            {
                "gap_statement": "Gap supported by both papers.",
                "supporting_literature_ids": list(literature_item_ids),
                "contradicting_literature_ids": [],
            }
        ]
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_evidence_links(
            session, project_id, subject_type=EvidenceSubjectType.GAP_CANDIDATE, subject_id=outcome.gap_ids[0]
        )
        supports = [l for l in links if l.relationship_type == EvidenceRelationship.SUPPORTS]
        assert {l.literature_item_id for l in supports} == set(literature_item_ids)
    finally:
        session.close()


def test_gap_with_contradicting_evidence_records_contradicts_links(session_factory, project_id, literature_item_ids):
    response = {
        "gaps": [
            {
                "gap_statement": "A contested gap.",
                "supporting_literature_ids": [literature_item_ids[0]],
                "contradicting_literature_ids": [literature_item_ids[1]],
            }
        ]
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_evidence_links(
            session, project_id, subject_type=EvidenceSubjectType.GAP_CANDIDATE, subject_id=outcome.gap_ids[0]
        )
        contradicts = [l for l in links if l.relationship_type == EvidenceRelationship.CONTRADICTS]
        assert [l.literature_item_id for l in contradicts] == [literature_item_ids[1]]
    finally:
        session.close()


def test_gap_with_no_supporting_evidence_is_rejected_as_insufficient(session_factory, project_id, literature_item_ids):
    response = {"gaps": [{"gap_statement": "An unsupported assertion.", "supporting_literature_ids": []}]}
    provider = FakeLLMProvider(responses=[response])
    outcome = generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.gap_ids == []
    assert outcome.rejected_candidate_count == 1


def test_gap_citing_hallucinated_literature_id_is_rejected(session_factory, project_id, literature_item_ids):
    response = {"gaps": [{"gap_statement": "Cites a fake paper.", "supporting_literature_ids": [424242]}]}
    provider = FakeLLMProvider(responses=[response])
    outcome = generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.gap_ids == []
    assert outcome.rejected_candidate_count == 1


def test_gap_analysis_project_isolation(session_factory, project_id, literature_item_ids):
    from researchos.db.engine import session_scope

    with session_scope(session_factory) as s:
        other = repository.create_project(s, title="Fake Other Project")
        other_id = other.id

    response = {"gaps": [{"gap_statement": "Gap.", "supporting_literature_ids": [literature_item_ids[0]]}]}
    provider = FakeLLMProvider(responses=[response])
    generate_gap_candidates(
        project_id, "widgets", literature_item_ids, actor="agent:gap-bot", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        assert len(repository.list_research_gaps(session, project_id)) == 1
        assert repository.list_research_gaps(session, other_id) == []
    finally:
        session.close()
