"""Category H: every analysis-layer state change is recorded via the
existing `AuditEvent` mechanism (Phase 8 spec section 24) — no parallel
audit system."""

from __future__ import annotations

from researchos.analysis import approval
from researchos.analysis.claims import create_scientific_claim
from researchos.analysis.records import compare_runs
from researchos.analysis.reviews import create_scientific_review
from researchos.db import repository
from researchos.db.models import ScientificReviewStatus

_DIMENSIONS = {key: "assessed" for key in (
    "evidence_completeness", "experimental_consistency", "dataset_consistency", "metric_appropriateness",
    "baseline_adequacy", "ablation_coverage", "reproducibility", "statistical_support",
    "threats_to_validity", "claim_strength", "alternative_explanations", "missing_evidence",
)}


def _event_types(session_factory, project_id):
    with session_factory() as session:
        return [e.event_type for e in repository.list_audit_events(session, project_id)]


def test_comparison_created_is_audited(session_factory, project_id, two_comparable_run_ids):
    compare_runs(project_id, *two_comparable_run_ids, "f1", actor="tester", session_factory=session_factory)
    assert "analysis.comparison_created" in _event_types(session_factory, project_id)


def test_claim_created_is_audited(session_factory, project_id, analysis_record_id):
    create_scientific_claim(
        project_id, "A candidate claim.", [analysis_record_id], actor="tester", session_factory=session_factory,
    )
    assert "analysis.claim_created" in _event_types(session_factory, project_id)


def test_scientific_review_created_is_audited(session_factory, project_id, claim_id):
    create_scientific_review(
        project_id, claim_id, _DIMENSIONS, actor="tester",
        status=ScientificReviewStatus.DRAFT, session_factory=session_factory,
    )
    assert "analysis.scientific_review_created" in _event_types(session_factory, project_id)


def test_claim_approved_and_review_approved_are_audited(session_factory, project_id, claim_id, ready_review_id):
    approval.approve_scientific_review(ready_review_id, "human:alice", session_factory=session_factory)
    approval.approve_scientific_claim(claim_id, "human:alice", session_factory=session_factory)
    event_types = _event_types(session_factory, project_id)
    assert "analysis.scientific_review_approved" in event_types
    assert "analysis.claim_approved" in event_types


def test_claim_rejected_is_audited(session_factory, project_id, claim_id):
    approval.reject_scientific_claim(claim_id, "human:alice", "No.", session_factory=session_factory)
    assert "analysis.claim_rejected" in _event_types(session_factory, project_id)
