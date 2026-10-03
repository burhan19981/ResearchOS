"""Human approval integration (`researchos.analysis.approval`): the two
preconditions beyond ordinary approval-dispatch mechanics — a review
must be `READY_FOR_HUMAN_REVIEW` before it can be approved, and a claim
must have a `HUMAN_APPROVED` review before it can be approved. An LLM
actor can never decide either."""

from __future__ import annotations

import pytest

from researchos.analysis import approval
from researchos.analysis.errors import ClaimNotSupportedByApprovedReviewError, HumanOnlyActionError, ReviewNotReadyError
from researchos.analysis.reviews import create_scientific_review
from researchos.db import repository
from researchos.db.models import ClaimApprovalStatus, ScientificReviewStatus

_DIMENSIONS = {key: "assessed" for key in (
    "evidence_completeness", "experimental_consistency", "dataset_consistency", "metric_appropriateness",
    "baseline_adequacy", "ablation_coverage", "reproducibility", "statistical_support",
    "threats_to_validity", "claim_strength", "alternative_explanations", "missing_evidence",
)}


def test_approve_scientific_review_requires_ready_status(session_factory, project_id, claim_id):
    draft_review = create_scientific_review(
        project_id, claim_id, _DIMENSIONS, actor="tester",
        status=ScientificReviewStatus.DRAFT, session_factory=session_factory,
    )
    with pytest.raises(ReviewNotReadyError):
        approval.approve_scientific_review(draft_review.id, "human:alice", session_factory=session_factory)


def test_approve_scientific_review_succeeds_when_ready(session_factory, project_id, ready_review_id):
    review = approval.approve_scientific_review(ready_review_id, "human:alice", session_factory=session_factory)
    assert review.status == ScientificReviewStatus.HUMAN_APPROVED


def test_approve_scientific_review_rejects_agent_actor(session_factory, project_id, ready_review_id):
    with pytest.raises(HumanOnlyActionError):
        approval.approve_scientific_review(ready_review_id, "agent:claude", session_factory=session_factory)
    with session_factory() as session:
        review = repository.get_scientific_review(session, ready_review_id)
    assert review.status == ScientificReviewStatus.READY_FOR_HUMAN_REVIEW


def test_reject_scientific_review_does_not_require_ready_status(session_factory, project_id, claim_id):
    draft_review = create_scientific_review(
        project_id, claim_id, _DIMENSIONS, actor="tester",
        status=ScientificReviewStatus.DRAFT, session_factory=session_factory,
    )
    review = approval.reject_scientific_review(draft_review.id, "human:alice", "Not enough evidence.", session_factory=session_factory)
    assert review.status == ScientificReviewStatus.REJECTED


def test_request_changes_scientific_review_maps_to_needs_more_evidence(session_factory, project_id, ready_review_id):
    review = approval.request_changes_scientific_review(
        ready_review_id, "human:alice", "Please add repeated runs.", session_factory=session_factory,
    )
    assert review.status == ScientificReviewStatus.NEEDS_MORE_EVIDENCE


def test_approve_scientific_claim_requires_a_human_approved_review(session_factory, project_id, claim_id, ready_review_id):
    with pytest.raises(ClaimNotSupportedByApprovedReviewError):
        approval.approve_scientific_claim(claim_id, "human:alice", session_factory=session_factory)


def test_approve_scientific_claim_succeeds_after_review_approved(session_factory, project_id, claim_id, ready_review_id):
    approval.approve_scientific_review(ready_review_id, "human:alice", session_factory=session_factory)
    claim = approval.approve_scientific_claim(claim_id, "human:alice", session_factory=session_factory)
    assert claim.approval_status == ClaimApprovalStatus.APPROVED


def test_approve_scientific_claim_rejects_agent_actor(session_factory, project_id, claim_id, ready_review_id):
    approval.approve_scientific_review(ready_review_id, "human:alice", session_factory=session_factory)
    with pytest.raises(HumanOnlyActionError):
        approval.approve_scientific_claim(claim_id, "agent:claude", session_factory=session_factory)
    with session_factory() as session:
        claim = repository.get_scientific_claim(session, claim_id)
    assert claim.approval_status == ClaimApprovalStatus.PENDING_REVIEW


def test_reject_scientific_claim_does_not_require_a_review(session_factory, project_id, claim_id):
    claim = approval.reject_scientific_claim(claim_id, "human:alice", "Not convincing.", session_factory=session_factory)
    assert claim.approval_status == ClaimApprovalStatus.REJECTED


def test_get_pending_analysis_approvals_lists_only_this_layers_prefixes(session_factory, project_id, ready_review_id):
    # `approval_dispatch.decide()` atomically creates-and-decides one
    # `Approval` row in a single call (see planning's own equivalent
    # test) — there is no external window where a row sits `PENDING`,
    # so both before and after a decision this listing is empty; what
    # this test actually guards is that it only ever considers this
    # layer's own two stage prefixes, never raising on an unrelated one.
    with session_factory() as session:
        assert approval.get_pending_analysis_approvals(session, project_id) == []

    approval.request_changes_scientific_review(ready_review_id, "human:alice", session_factory=session_factory)
    with session_factory() as session:
        assert approval.get_pending_analysis_approvals(session, project_id) == []
