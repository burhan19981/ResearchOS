"""Human approval integration tests (Phase 6 spec section 9)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import ApprovalDecision, ClaimApprovalStatus, ClaimSupportLevel, GapStatus, NoveltyCandidateStatus
from researchos.intelligence import approval
from researchos.intelligence.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError


def _make_claim(session_factory, project_id):
    s = session_factory()
    try:
        analysis = repository.create_literature_analysis(
            s, project_id=project_id, research_topic="topic", actor="agent:x", requested_item_ids=[1],
            included_item_ids=[1], provider="fake", model="fake-model", prompt_name="literature_analysis",
            prompt_version="v1",
        )
        claim = repository.create_analysis_claim(
            s, project_id=project_id, analysis_id=analysis.id, claim_text="A candidate claim.",
            provider="fake", model="fake-model", support_level=ClaimSupportLevel.SUPPORTED,
        )
        s.commit()
        return claim.id
    finally:
        s.close()


def _make_gap(session_factory, project_id):
    s = session_factory()
    try:
        gap = repository.record_research_gap(s, project_id=project_id, statement="A candidate gap.")
        s.commit()
        return gap.id
    finally:
        s.close()


def _make_novelty_assessment(session_factory, project_id):
    s = session_factory()
    try:
        assessment = repository.record_novelty_assessment(s, project_id=project_id, claim="A candidate contribution.")
        s.commit()
        return assessment.id
    finally:
        s.close()


# --- Candidates cannot become approved automatically -----------------------


def test_claim_starts_as_pending_review_never_pre_approved(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    session = session_factory()
    try:
        claim = repository.get_analysis_claim(session, claim_id)
        assert claim.approval_status == ClaimApprovalStatus.PENDING_REVIEW
    finally:
        session.close()


def test_gap_starts_as_candidate_never_pre_validated(session_factory, project_id):
    gap_id = _make_gap(session_factory, project_id)
    session = session_factory()
    try:
        gap = repository.get_research_gap(session, gap_id)
        assert gap.status == GapStatus.CANDIDATE
    finally:
        session.close()


def test_novelty_assessment_starts_as_not_assessed_never_pre_approved(session_factory, project_id):
    assessment_id = _make_novelty_assessment(session_factory, project_id)
    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, assessment_id)
        assert assessment.candidate_status == NoveltyCandidateStatus.NOT_ASSESSED
    finally:
        session.close()


# --- Unauthorized (agent) approval blocked ----------------------------------


@pytest.mark.parametrize(
    "make_fn,approve_fn",
    [
        (_make_claim, approval.approve_claim),
        (_make_gap, approval.approve_gap),
        (_make_novelty_assessment, approval.approve_novelty_assessment),
    ],
)
def test_agent_actor_cannot_approve_any_candidate_type(session_factory, project_id, make_fn, approve_fn):
    entity_id = make_fn(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        approve_fn(entity_id, actor="agent:auto-approver", session_factory=session_factory)


def test_agent_cannot_reject_or_request_changes_either(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        approval.reject_claim(claim_id, actor="agent:x", session_factory=session_factory)
    with pytest.raises(HumanOnlyActionError):
        approval.request_changes_claim(claim_id, actor="agent:x", session_factory=session_factory)


# --- Approval recorded correctly + audit event ------------------------------


def test_human_approval_updates_status_and_records_approval_row(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    updated = approval.approve_claim(claim_id, actor="user:pi", comment="looks solid", session_factory=session_factory)
    assert updated.approval_status == ClaimApprovalStatus.APPROVED

    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        assert len(approvals) == 1
        assert approvals[0].decision == ApprovalDecision.APPROVED
        assert approvals[0].comment == "looks solid"
        assert approvals[0].stage == f"CLAIM_APPROVAL:{claim_id}"
        assert approvals[0].requested_at is not None
        assert approvals[0].decided_at is not None
    finally:
        session.close()


def test_approval_generates_a_complete_audit_event(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    approval.approve_claim(claim_id, actor="user:pi", comment="approved", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "intelligence.claim_approved")
        assert event.actor == "user:pi"
        assert event.metadata_["entity_id"] == claim_id
        assert event.metadata_["previous_status"] == "pending_review"
        assert event.metadata_["new_status"] == "approved"
        assert event.metadata_["comment"] == "approved"
        assert "approval_id" in event.metadata_
    finally:
        session.close()


def test_gap_approval_sets_validated_status(session_factory, project_id):
    gap_id = _make_gap(session_factory, project_id)
    updated = approval.approve_gap(gap_id, actor="user:pi", session_factory=session_factory)
    assert updated.status == GapStatus.VALIDATED


def test_gap_approval_audit_event_records_correct_previous_status(session_factory, project_id):
    gap_id = _make_gap(session_factory, project_id)
    approval.approve_gap(gap_id, actor="user:pi", session_factory=session_factory)
    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "intelligence.gap_approved")
        assert event.metadata_["previous_status"] == "candidate"
        assert event.metadata_["new_status"] == "validated"
    finally:
        session.close()


def test_novelty_approval_sets_human_approved_status(session_factory, project_id):
    assessment_id = _make_novelty_assessment(session_factory, project_id)
    updated = approval.approve_novelty_assessment(assessment_id, actor="user:pi", session_factory=session_factory)
    assert updated.candidate_status == NoveltyCandidateStatus.HUMAN_APPROVED


def test_novelty_approval_audit_event_records_correct_previous_status(session_factory, project_id):
    """Regression test (audit remediation, Finding B): `NoveltyAssessment`
    has two status-like columns — Phase 3's dormant `status`
    (`NoveltyStatus`, always `PENDING`) and Phase 6's actually-changing
    `candidate_status` (`NoveltyCandidateStatus`). Before this fix,
    `researchos.db.approval_dispatch`'s status lookup picked the wrong
    one (`status` before `candidate_status` in a fixed priority list),
    so this audit event's `previous_status` read `"pending"` instead of
    the assessment's real starting `candidate_status`,
    `"not_assessed"`. `EntitySpec.status_attr` now names the correct
    attribute explicitly per entity type instead of guessing."""
    assessment_id = _make_novelty_assessment(session_factory, project_id)
    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, assessment_id)
        assert assessment.status.value == "pending"  # the dormant Phase 3 field — must NOT be what gets reported
        assert assessment.candidate_status == NoveltyCandidateStatus.NOT_ASSESSED
    finally:
        session.close()

    approval.approve_novelty_assessment(assessment_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "intelligence.novelty_approved")
        assert event.metadata_["previous_status"] == "not_assessed"
        assert event.metadata_["new_status"] == "human_approved"
    finally:
        session.close()


# --- Rejected candidate remains rejected ------------------------------------


def test_rejected_claim_remains_rejected_and_cannot_be_reapproved(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    rejected = approval.reject_claim(claim_id, actor="user:pi", comment="not convincing", session_factory=session_factory)
    assert rejected.approval_status == ClaimApprovalStatus.REJECTED

    with pytest.raises(ApprovalAlreadyDecidedError):
        approval.approve_claim(claim_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        claim = repository.get_analysis_claim(session, claim_id)
        assert claim.approval_status == ClaimApprovalStatus.REJECTED  # unchanged
    finally:
        session.close()


def test_gap_rejection_is_terminal(session_factory, project_id):
    gap_id = _make_gap(session_factory, project_id)
    approval.reject_gap(gap_id, actor="user:pi", session_factory=session_factory)
    with pytest.raises(ApprovalAlreadyDecidedError):
        approval.reject_gap(gap_id, actor="user:pi", session_factory=session_factory)


# --- request_changes lifecycle -----------------------------------------------


def test_request_changes_does_not_approve_or_reject(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    updated = approval.request_changes_claim(claim_id, actor="user:pi", comment="add more detail", session_factory=session_factory)
    assert updated.approval_status == ClaimApprovalStatus.CHANGES_REQUESTED


def test_changes_requested_allows_a_fresh_approval_round(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    approval.request_changes_claim(claim_id, actor="user:pi", comment="revise", session_factory=session_factory)
    # Unlike a final approve/reject, changes-requested is not terminal —
    # a subsequent decision should succeed (a new pending round opens).
    updated = approval.approve_claim(claim_id, actor="user:pi", comment="now good", session_factory=session_factory)
    assert updated.approval_status == ClaimApprovalStatus.APPROVED

    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        assert len(approvals) == 2  # the changes-requested round + the fresh approved round
    finally:
        session.close()


# --- Not found ----------------------------------------------------------------


def test_approving_nonexistent_claim_raises_not_found(session_factory, project_id):
    with pytest.raises(CandidateNotFoundError):
        approval.approve_claim(999_999, actor="user:pi", session_factory=session_factory)


def test_get_pending_intelligence_approvals_lists_only_this_layers_approvals(session_factory, project_id):
    claim_id = _make_claim(session_factory, project_id)
    gap_id = _make_gap(session_factory, project_id)
    # Create a pending approval for each by requesting changes is not
    # needed — approving directly is enough to exercise pending listing
    # before any decision: check emptiness first.
    session = session_factory()
    try:
        assert approval.get_pending_intelligence_approvals(session, project_id) == []
    finally:
        session.close()

    # Trigger creation of a pending approval row via request_changes,
    # then re-open a fresh pending round to inspect it mid-flight.
    approval.request_changes_claim(claim_id, actor="user:pi", session_factory=session_factory)
    session = session_factory()
    try:
        pending_before = approval.get_pending_intelligence_approvals(session, project_id)
        assert pending_before == []  # changes-requested is a decided state, not pending
    finally:
        session.close()
