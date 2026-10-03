"""Human approval integration: Phase 6 spec section 9.

Reuses the Phase 4 `Approval` database model and decision vocabulary
directly (via `researchos.db.repository`'s existing Approval primitives)
and `researchos.workflow.policy.is_human_actor` for the human-only
check — no parallel approval mechanism. `researchos.workflow.service`
itself is not imported or modified: its `approve()`/`reject()` dispatch
only knows about stage-transition and project-administrative keys, and
claims/gaps/novelty-assessments are not workflow-stage transitions, so
this module orchestrates the *same* underlying `Approval` table with
its own small, consistent decision flow instead.

The generic "which entity, which stage-key prefix, which status to set"
dispatch mechanics live in `researchos.db.approval_dispatch` (Phase 7
extracted this out of what was originally a private copy here, so that
`researchos.planning.approval` could reuse it too without a second,
duplicated approval system) — this module supplies only the
entity-specific wiring: which repository getters/updaters to call and
which status values/exception types this layer uses.

Every decision here is atomic (one `session_scope()` per call, applied
by the shared dispatcher): the `Approval` row's decision, the
candidate's own status field, and an `AuditEvent` all commit together or
not at all — the same pattern `researchos.workflow.service` uses for its
own decisions.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..db import approval_dispatch, repository
from ..db.models import (
    Approval,
    ApprovalDecision,
    ClaimApprovalStatus,
    GapStatus,
    NoveltyCandidateStatus,
)
from .errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError

_CLAIM_SPEC = approval_dispatch.EntitySpec(
    label="AnalysisClaim",
    stage_prefix="CLAIM_APPROVAL",
    status_attr="approval_status",
    get=repository.get_analysis_claim,
    update_status=lambda s, i, v: repository.update_analysis_claim(s, i, approval_status=v),
    approved_value=ClaimApprovalStatus.APPROVED,
    rejected_value=ClaimApprovalStatus.REJECTED,
    changes_requested_value=ClaimApprovalStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_GAP_SPEC = approval_dispatch.EntitySpec(
    label="ResearchGap",
    stage_prefix="GAP_APPROVAL",
    status_attr="status",
    get=repository.get_research_gap,
    update_status=lambda s, i, v: repository.update_research_gap(s, i, status=v),
    # VALIDATED is Phase 3's original "a human confirmed this" value —
    # reused here rather than adding a redundant HUMAN_APPROVED member.
    approved_value=GapStatus.VALIDATED,
    rejected_value=GapStatus.REJECTED,
    changes_requested_value=GapStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)
_NOVELTY_SPEC = approval_dispatch.EntitySpec(
    label="NoveltyAssessment",
    stage_prefix="NOVELTY_APPROVAL",
    status_attr="candidate_status",
    get=repository.get_novelty_assessment,
    update_status=lambda s, i, v: repository.update_novelty_assessment(s, i, candidate_status=v),
    approved_value=NoveltyCandidateStatus.HUMAN_APPROVED,
    rejected_value=NoveltyCandidateStatus.REJECTED,
    changes_requested_value=NoveltyCandidateStatus.CHANGES_REQUESTED,
    not_found_error=CandidateNotFoundError,
    already_decided_error=ApprovalAlreadyDecidedError,
    human_only_error=HumanOnlyActionError,
)


def _with_evidence_links(session: Session, entity) -> dict:
    evidence_links = repository.list_evidence_links(session, entity.project_id, subject_id=entity.id)
    return {"evidence_item_ids": sorted({link.literature_item_id for link in evidence_links})}


# ===========================================================================
# AnalysisClaim
# ===========================================================================


def approve_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_CLAIM_SPEC.approved_value,
        event_type="intelligence.claim_approved", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def reject_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_CLAIM_SPEC.rejected_value,
        event_type="intelligence.claim_rejected", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def request_changes_claim(claim_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _CLAIM_SPEC, claim_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_CLAIM_SPEC.changes_requested_value,
        event_type="intelligence.claim_changes_requested", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


# ===========================================================================
# ResearchGap (candidate)
# ===========================================================================


def approve_gap(gap_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _GAP_SPEC, gap_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_GAP_SPEC.approved_value,
        event_type="intelligence.gap_approved", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def reject_gap(gap_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _GAP_SPEC, gap_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_GAP_SPEC.rejected_value,
        event_type="intelligence.gap_rejected", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def request_changes_gap(gap_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _GAP_SPEC, gap_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_GAP_SPEC.changes_requested_value,
        event_type="intelligence.gap_changes_requested", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


# ===========================================================================
# NoveltyAssessment (candidate)
# ===========================================================================


def approve_novelty_assessment(assessment_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _NOVELTY_SPEC, assessment_id, actor, comment,
        decision=ApprovalDecision.APPROVED, new_status=_NOVELTY_SPEC.approved_value,
        event_type="intelligence.novelty_approved", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def reject_novelty_assessment(assessment_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None):
    return approval_dispatch.decide(
        _NOVELTY_SPEC, assessment_id, actor, comment,
        decision=ApprovalDecision.REJECTED, new_status=_NOVELTY_SPEC.rejected_value,
        event_type="intelligence.novelty_rejected", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def request_changes_novelty_assessment(
    assessment_id: int, actor: str, comment: Optional[str] = None, *, session_factory=None
):
    return approval_dispatch.decide(
        _NOVELTY_SPEC, assessment_id, actor, comment,
        decision=ApprovalDecision.CHANGES_REQUESTED, new_status=_NOVELTY_SPEC.changes_requested_value,
        event_type="intelligence.novelty_changes_requested", session_factory=session_factory,
        extra_metadata=_with_evidence_links,
    )


def get_pending_intelligence_approvals(session: Session, project_id: int) -> list[Approval]:
    """All pending approvals in a project whose stage key belongs to this
    layer (`CLAIM_APPROVAL:`/`GAP_APPROVAL:`/`NOVELTY_APPROVAL:`), for a
    reviewer's queue — leaves `researchos.workflow`'s own pending stage
    transitions/admin-action approvals, and `researchos.planning`'s own
    approvals, out of this listing."""
    prefixes = (_CLAIM_SPEC.stage_prefix, _GAP_SPEC.stage_prefix, _NOVELTY_SPEC.stage_prefix)
    return approval_dispatch.pending_for_prefixes(session, project_id, prefixes)
