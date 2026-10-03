"""Categories E/F/G: `researchos.analysis.claims`/`reviews` — manual
and LLM-assisted candidate generation, and the anti-hallucination /
LLM-boundary guarantees around them."""

from __future__ import annotations

import pytest

from researchos.analysis.claims import create_scientific_claim, generate_candidate_claim
from researchos.analysis.errors import InvalidAnalysisInputError, InvalidAnalysisResponseError
from researchos.analysis.reviews import create_scientific_review, generate_scientific_review
from researchos.db import repository
from researchos.db.models import ClaimApprovalStatus, ClaimStrength, ScientificReviewStatus
from tests.analysis.fakes import FakeLLMProvider

_DIMENSIONS = {
    "evidence_completeness": "partial",
    "experimental_consistency": "consistent",
    "dataset_consistency": "consistent",
    "metric_appropriateness": "appropriate",
    "baseline_adequacy": "adequate",
    "ablation_coverage": "none",
    "reproducibility": "reproducible",
    "statistical_support": "descriptive only",
    "threats_to_validity": "single run per condition",
    "claim_strength": "moderate",
    "alternative_explanations": "random variation",
    "missing_evidence": "repeated runs",
}


# ===========================================================================
# create_scientific_claim (manual)
# ===========================================================================


def test_create_scientific_claim_manual(session_factory, project_id, analysis_record_id):
    claim = create_scientific_claim(
        project_id, "Run B's F1 may be higher under these conditions.", [analysis_record_id],
        actor="tester", session_factory=session_factory,
    )
    assert claim.approval_status == ClaimApprovalStatus.PENDING_REVIEW
    assert claim.strength == ClaimStrength.NOT_ASSESSABLE

    with session_factory() as session:
        links = repository.list_scientific_claim_analyses(session, project_id, claim_id=claim.id)
    assert {l.analysis_record_id for l in links} == {analysis_record_id}


def test_create_scientific_claim_requires_at_least_one_analysis_record(session_factory, project_id):
    with pytest.raises(InvalidAnalysisInputError):
        create_scientific_claim(project_id, "An unsupported claim.", [], actor="tester", session_factory=session_factory)


# ===========================================================================
# generate_candidate_claim (LLM-assisted)
# ===========================================================================


def test_generate_candidate_claim_persists_valid_claims(session_factory, project_id, analysis_record_id):
    provider = FakeLLMProvider(responses=[{
        "observations": ["Run comparison_run's F1 is higher."],
        "missing_evidence": ["Only one run per condition."],
        "threats_to_validity": ["No repeated trials."],
        "alternative_explanations": ["Random seed variation."],
        "candidate_claims": [
            {
                "claim_text": "The comparison run may perform better under these conditions.",
                "claim_type": "performance_comparison",
                "confidence": 0.4,
                "supporting_analysis_record_ids": [analysis_record_id],
            },
        ],
    }])

    outcome = generate_candidate_claim(
        project_id, [analysis_record_id], actor="tester", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.rejected_count == 0
    assert len(outcome.claim_ids) == 1

    with session_factory() as session:
        claim = repository.get_scientific_claim(session, outcome.claim_ids[0])
    assert claim.approval_status == ClaimApprovalStatus.PENDING_REVIEW
    assert claim.provider == "fake"


def test_generate_candidate_claim_rejects_hallucinated_reference(session_factory, project_id, analysis_record_id):
    provider = FakeLLMProvider(responses=[{
        "candidate_claims": [
            {
                "claim_text": "A claim citing an analysis record it was never given.",
                "supporting_analysis_record_ids": [999999],
            },
        ],
    }])

    outcome = generate_candidate_claim(
        project_id, [analysis_record_id], actor="tester", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.claim_ids == []
    assert outcome.rejected_count == 1


def test_generate_candidate_claim_rejects_claim_with_no_supporting_evidence(session_factory, project_id, analysis_record_id):
    provider = FakeLLMProvider(responses=[{
        "candidate_claims": [{"claim_text": "An unsupported assertion.", "supporting_analysis_record_ids": []}],
    }])
    outcome = generate_candidate_claim(
        project_id, [analysis_record_id], actor="tester", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    assert outcome.claim_ids == []
    assert outcome.rejected_count == 1


def test_generate_candidate_claim_never_sets_approved(session_factory, project_id, analysis_record_id):
    provider = FakeLLMProvider(responses=[{
        "candidate_claims": [
            {
                "claim_text": "Trying to sneak in approval.",
                "approval_status": "approved",
                "supporting_analysis_record_ids": [analysis_record_id],
            },
        ],
    }])
    outcome = generate_candidate_claim(
        project_id, [analysis_record_id], actor="tester", provider_name="fake", provider=provider,
        session_factory=session_factory,
    )
    with session_factory() as session:
        claim = repository.get_scientific_claim(session, outcome.claim_ids[0])
    assert claim.approval_status == ClaimApprovalStatus.PENDING_REVIEW


def test_generate_candidate_claim_rejects_malformed_response(session_factory, project_id, analysis_record_id):
    provider = FakeLLMProvider(responses=[{"not_the_expected_key": True}])
    with pytest.raises(InvalidAnalysisResponseError):
        generate_candidate_claim(
            project_id, [analysis_record_id], actor="tester", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
    with session_factory() as session:
        events = repository.list_audit_events(session, project_id)
    assert any(e.event_type == "analysis.claim_generation_failed" for e in events)


# ===========================================================================
# create_scientific_review (manual)
# ===========================================================================


def test_create_scientific_review_manual(session_factory, project_id, claim_id):
    review = create_scientific_review(
        project_id, claim_id, _DIMENSIONS, actor="tester",
        status=ScientificReviewStatus.CANDIDATE, session_factory=session_factory,
    )
    assert review.status == ScientificReviewStatus.CANDIDATE
    assert review.claim_id == claim_id


@pytest.mark.parametrize("forbidden_status", [ScientificReviewStatus.HUMAN_APPROVED, ScientificReviewStatus.REJECTED])
def test_create_scientific_review_rejects_human_only_statuses(session_factory, project_id, claim_id, forbidden_status):
    with pytest.raises(InvalidAnalysisInputError):
        create_scientific_review(
            project_id, claim_id, _DIMENSIONS, actor="tester", status=forbidden_status, session_factory=session_factory,
        )


# ===========================================================================
# generate_scientific_review (LLM-assisted)
# ===========================================================================


def test_generate_scientific_review_persists_valid_review(session_factory, project_id, claim_id):
    provider = FakeLLMProvider(responses=[{
        "dimensions": _DIMENSIONS,
        "status": "ready_for_human_review",
        "recommendation": "A human should review the single-run comparison before accepting this claim.",
    }])
    outcome = generate_scientific_review(
        project_id, claim_id, actor="tester", provider_name="fake", provider=provider, session_factory=session_factory,
    )
    with session_factory() as session:
        review = repository.get_scientific_review(session, outcome.review_id)
    assert review.status == ScientificReviewStatus.READY_FOR_HUMAN_REVIEW
    assert set(review.dimensions.keys()) == set(_DIMENSIONS.keys())


@pytest.mark.parametrize("forbidden_status", ["human_approved", "rejected", "draft"])
def test_generate_scientific_review_rejects_llm_proposed_authoritative_status(session_factory, project_id, claim_id, forbidden_status):
    provider = FakeLLMProvider(responses=[{"dimensions": _DIMENSIONS, "status": forbidden_status}])
    with pytest.raises(InvalidAnalysisResponseError):
        generate_scientific_review(
            project_id, claim_id, actor="tester", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
    with session_factory() as session:
        reviews = repository.list_scientific_reviews(session, project_id, claim_id=claim_id)
    assert reviews == []


def test_generate_scientific_review_rejects_missing_dimension(session_factory, project_id, claim_id):
    incomplete = dict(_DIMENSIONS)
    del incomplete["missing_evidence"]
    provider = FakeLLMProvider(responses=[{"dimensions": incomplete, "status": "candidate"}])
    with pytest.raises(InvalidAnalysisResponseError):
        generate_scientific_review(
            project_id, claim_id, actor="tester", provider_name="fake", provider=provider,
            session_factory=session_factory,
        )
