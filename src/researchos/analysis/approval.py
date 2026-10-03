"""Human approval integration for the analysis & scientific review layer
(Phase 8 spec section 14).

Reuses the Phase 4 `Approval`/`AuditEvent`/`ApprovalDecision` tables and
`researchos.workflow.policy.is_human_actor` through the shared
`researchos.db.approval_dispatch` mechanics — the same generic
dispatcher `researchos.intelligence.approval`/`researchos.planning.
approval` use. No parallel approval system exists here either.

Two new gate types: `SCIENTIFIC_REVIEW_APPROVAL:<id>` and
`SCIENTIFIC_CLAIM_APPROVAL:<id>`. Each carries an extra precondition
beyond what `approval_dispatch.decide` checks on its own (Phase 8 spec
section 14):

- A `ScientificReview` may only be approved once its own `status` is
  `READY_FOR_HUMAN_REVIEW` — approving a review that is still `DRAFT`/
  `CANDIDATE`/`NEEDS_MORE_EVIDENCE` would make a human decision on an
  assessment that never declared itself complete.
- A `ScientificClaim` may only be approved once at least one of its
  linked `ScientificReview`s is itself `HUMAN_APPROVED` — a claim's own
  approval always rests on an evidence assessment a human has already
  signed off on; there is no path to `ClaimApprovalStatus.APPROVED`
  that skips review entirely.

As with every prior phase: every decision function requires a human
actor and raises immediately for an agent actor — the LLM can never
approve its own output.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from ..db import approval_dispatch, repository
from ..db.engine import session_scope
from ..db.models import Approval, ApprovalDecision, ClaimApprovalStatus, ScientificReviewStatus
from .errors import (
    ApprovalAlreadyDecidedError,
    CandidateNotFoundError,
    ClaimNotSupportedByApprovedReviewError,
    HumanOnlyActionError,
    ReviewNotReadyError,
)

_REVIEW_SPEC = approval_dispatch.EntitySpec(
    label="ScientificReview",
    stage_prefix="SCIENTIFIC_REVIEW_APPROVAL",
    status_attr="status",
    get=repository.get_scientific_review,
    update_status=lambda s, i, v: repository.update_scientific_review(s, i, status=v),
    approved_value=ScientificReviewStatus.HUMAN_APPROVED,
    rejected_value=ScientificReviewStatus.REJECTED,
    # "Changes requested" naturally maps onto this lifecycle's own
    # NEEDS_MORE_EVIDENCE state rather than inventing a third
    # near-identical concept.
    changes_requested_value=ScientificReviewStatus.NEEDS_MORE_EVIDENCE,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_CLAIM_SPEC = approval_dispatch.EntitySpec(
    label="ScientificClaim",
    stage_prefix="SCIENTIFIC_CLAIM_APPROVAL",
    status_attr="approval_status",
    get=repository.get_scientific_claim,
    update_status=lambda s, i, v: repository.update_scientific_claim(s, i, approval_status=v),
    approved_value=ClaimApprovalStatus.APPROVED,
    rejected_value=ClaimApprovalStatus.REJECTED,
    changes_requested_value=ClaimApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)


def _decide(spec, entity_id, actor, comment, *, decision, new_status, event_type, session_factory):
    return approval_dispatch.decide(
        spec, entity_id, actor, comment,
        decision=decision, new_status=new_status, event_type=event_type, session_factory=session_factory,
    )


# ===========================================================================
# ScientificReview
# ===========================================================================


def approve_scientific_review(review_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    """Requires `status == READY_FOR_HUMAN_REVIEW` — raises
    `ReviewNotReadyError` otherwise, before any `Approval`/`AuditEvent`
    row is touched."""
    with session_scope(session_factory) as session:
        review = repository.get_scientific_review(session, review_id)
        if review is None:
            raise CandidateNotFoundError(f"ScientificReview {review_id} does not exist.")
        if review.status != ScientificReviewStatus.READY_FOR_HUMAN_REVIEW:
            raise ReviewNotReadyError(
                f"ScientificReview {review_id} is {review.status.value!r}, not 'ready_for_human_review' — "
                "it cannot be approved yet."
            )

    return _decide(
        _REVIEW_SPEC, review_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_REVIEW_SPEC.approved_value,
        event_type="analysis.scientific_review_approved", session_factory=session_factory,
    )


def reject_scientific_review(review_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    return _decide(
        _REVIEW_SPEC, review_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_REVIEW_SPEC.rejected_value,
        event_type="analysis.scientific_review_rejected", session_factory=session_factory,
    )


def request_changes_scientific_review(review_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    return _decide(
        _REVIEW_SPEC, review_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_REVIEW_SPEC.changes_requested_value,
        event_type="analysis.scientific_review_changes_requested", session_factory=session_factory,
    )


# ===========================================================================
# ScientificClaim
# ===========================================================================


def approve_scientific_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    """Requires at least one linked `ScientificReview` to already be
    `HUMAN_APPROVED` — raises `ClaimNotSupportedByApprovedReviewError`
    otherwise, before any `Approval`/`AuditEvent` row is touched."""
    with session_scope(session_factory) as session:
        claim = repository.get_scientific_claim(session, claim_id)
        if claim is None:
            raise CandidateNotFoundError(f"ScientificClaim {claim_id} does not exist.")
        reviews = repository.list_scientific_reviews(session, claim.project_id, claim_id=claim_id)
        if not any(r.status == ScientificReviewStatus.HUMAN_APPROVED for r in reviews):
            raise ClaimNotSupportedByApprovedReviewError(
                f"ScientificClaim {claim_id} has no HUMAN_APPROVED ScientificReview — approve a review of the "
                "supporting evidence first."
            )

    return _decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_CLAIM_SPEC.approved_value,
        event_type="analysis.claim_approved", session_factory=session_factory,
    )


def reject_scientific_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    return _decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_CLAIM_SPEC.rejected_value,
        event_type="analysis.claim_rejected", session_factory=session_factory,
    )


def request_changes_scientific_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory: Optional[sessionmaker] = None):
    return _decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_CLAIM_SPEC.changes_requested_value,
        event_type="analysis.claim_changes_requested", session_factory=session_factory,
    )


def get_pending_analysis_approvals(session: Session, project_id: int) -> list[Approval]:
    """All pending approvals in a project whose stage key belongs to
    this layer's two gate types."""
    prefixes = (_REVIEW_SPEC.stage_prefix, _CLAIM_SPEC.stage_prefix)
    return approval_dispatch.pending_for_prefixes(session, project_id, prefixes)
