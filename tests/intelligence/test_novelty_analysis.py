"""Novelty candidate analysis service tests."""

from __future__ import annotations

from researchos.db import repository
from researchos.db.models import ComparisonStatus, EvidenceRelationship, EvidenceSubjectType, NoveltyCandidateStatus
from researchos.intelligence.novelty_analysis import analyze_novelty_candidate

from .fakes import FakeLLMProvider


def test_prior_work_similarity_and_difference_are_persisted(session_factory, project_id, literature_item_ids):
    response = {
        "comparisons": [
            {
                "literature_item_id": literature_item_ids[0],
                "similarity": "Both use a widget-based approach.",
                "difference": "The candidate scales to 10x more widgets.",
                "status": "partially_distinct",
                "similarity_evidence_ids": [literature_item_ids[0]],
                "difference_evidence_ids": [],
            }
        ],
        "potentially_novel_elements": "Scaling approach",
        "potentially_existing_elements": "Widget-based method",
        "unresolved_questions": "Unclear if scaling generalizes.",
        "novelty_risk": "medium",
        "confidence": 0.55,
        "candidate_status": "partially_distinct",
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "A widget method that scales 10x", literature_item_ids, actor="agent:novelty-bot",
        provider_name="fake", provider=provider, session_factory=session_factory,
    )
    assert len(outcome.comparison_ids) == 1

    session = session_factory()
    try:
        comparison = repository.list_novelty_comparisons(session, project_id, novelty_assessment_id=outcome.assessment_id)[0]
        assert comparison.similarity == "Both use a widget-based approach."
        assert comparison.difference == "The candidate scales to 10x more widgets."
        assert comparison.status == ComparisonStatus.PARTIALLY_DISTINCT

        assessment = repository.get_novelty_assessment(session, outcome.assessment_id)
        assert assessment.candidate_status == NoveltyCandidateStatus.PARTIALLY_DISTINCT
        assert assessment.novelty_risk == "medium"
        assert assessment.claim == "A widget method that scales 10x"
        assert assessment.provider == "fake"
        assert assessment.prompt_name == "novelty_analysis"
    finally:
        session.close()


def test_similarity_and_difference_evidence_links_recorded_distinctly(session_factory, project_id, literature_item_ids):
    response = {
        "comparisons": [
            {
                "literature_item_id": literature_item_ids[0],
                "status": "similar",
                "similarity_evidence_ids": [literature_item_ids[0]],
                "difference_evidence_ids": [literature_item_ids[1]],
            }
        ],
        "candidate_status": "possibly_already_existing",
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        links = repository.list_evidence_links(
            session, project_id, subject_type=EvidenceSubjectType.NOVELTY_COMPARISON, subject_id=outcome.comparison_ids[0]
        )
        supports = {l.literature_item_id for l in links if l.relationship_type == EvidenceRelationship.SUPPORTS}
        contradicts = {l.literature_item_id for l in links if l.relationship_type == EvidenceRelationship.CONTRADICTS}
        assert supports == {literature_item_ids[0]}
        assert contradicts == {literature_item_ids[1]}
    finally:
        session.close()


def test_insufficient_evidence_status_is_respected(session_factory, project_id, literature_item_ids):
    response = {"comparisons": [], "candidate_status": "insufficient_evidence"}
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, outcome.assessment_id)
        assert assessment.candidate_status == NoveltyCandidateStatus.INSUFFICIENT_EVIDENCE
    finally:
        session.close()


def test_llm_cannot_self_assign_human_approved_status(session_factory, project_id, literature_item_ids):
    """The schema excludes 'human_approved' entirely, but this test
    forces it through anyway (bypassing schema enforcement) to prove the
    defense-in-depth code-level check also rejects it."""
    response = {"comparisons": [], "candidate_status": "human_approved"}
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, outcome.assessment_id)
        assert assessment.candidate_status != NoveltyCandidateStatus.HUMAN_APPROVED
        assert assessment.candidate_status == NoveltyCandidateStatus.INSUFFICIENT_EVIDENCE
    finally:
        session.close()


def test_hallucinated_literature_reference_in_comparison_is_rejected(session_factory, project_id, literature_item_ids):
    response = {
        "comparisons": [{"literature_item_id": 555555, "status": "similar"}],
        "candidate_status": "not_assessed",
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    assert outcome.comparison_ids == []
    assert outcome.rejected_comparison_count == 1


def test_hallucinated_evidence_id_within_otherwise_valid_comparison_rejects_whole_row(
    session_factory, project_id, literature_item_ids
):
    response = {
        "comparisons": [
            {
                "literature_item_id": literature_item_ids[0],
                "status": "similar",
                "similarity_evidence_ids": [literature_item_ids[0], 777777],
            }
        ],
        "candidate_status": "not_assessed",
    }
    provider = FakeLLMProvider(responses=[response])
    outcome = analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    assert outcome.comparison_ids == []
    assert outcome.rejected_comparison_count == 1


def test_novelty_analysis_project_isolation(session_factory, project_id, literature_item_ids):
    from researchos.db.engine import session_scope

    with session_scope(session_factory) as s:
        other = repository.create_project(s, title="Fake Other Project")
        other_id = other.id

    response = {"comparisons": [], "candidate_status": "not_assessed"}
    provider = FakeLLMProvider(responses=[response])
    analyze_novelty_candidate(
        project_id, "Candidate", literature_item_ids, actor="agent:novelty-bot", provider_name="fake",
        provider=provider, session_factory=session_factory,
    )
    session = session_factory()
    try:
        assert len(repository.list_novelty_assessments(session, project_id)) == 1
        assert repository.list_novelty_assessments(session, other_id) == []
    finally:
        session.close()
