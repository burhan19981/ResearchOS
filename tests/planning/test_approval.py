"""Human approval integration tests (Phase 7 spec sections 17-18)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import ApprovalDecision, GapStatus, NoveltyCandidateStatus, PlanningApprovalStatus
from researchos.intelligence import approval as intelligence_approval
from researchos.intelligence.errors import HumanOnlyActionError as IntelligenceHumanOnlyActionError
from researchos.planning import approval as planning_approval
from researchos.planning.errors import ApprovalAlreadyDecidedError, CandidateNotFoundError, HumanOnlyActionError

# Each package deliberately keeps its own independent exception hierarchy
# (see researchos.db.approval_dispatch's docstring) — NOVELTY_APPROVAL
# still raises researchos.intelligence.errors.HumanOnlyActionError, not
# researchos.planning's own type, so the parametrized "agent blocked"
# tests below accept either.
_HUMAN_ONLY_ERRORS = (HumanOnlyActionError, IntelligenceHumanOnlyActionError)


def _make_question(session_factory, project_id):
    s = session_factory()
    try:
        q = repository.create_research_question(s, project_id=project_id, question="A candidate question?")
        s.commit()
        return q.id
    finally:
        s.close()


def _make_contribution(session_factory, project_id):
    s = session_factory()
    try:
        c = repository.create_contribution_candidate(s, project_id=project_id, title="A candidate", description="D.")
        s.commit()
        return c.id
    finally:
        s.close()


def _make_methodology(session_factory, project_id):
    s = session_factory()
    try:
        m = repository.create_methodology_version(s, project_id=project_id, description="A draft methodology.")
        s.commit()
        return m.id
    finally:
        s.close()


def _make_dataset_requirements(session_factory, project_id):
    s = session_factory()
    try:
        d = repository.create_dataset_requirements(s, project_id=project_id, required_characteristics="X.")
        s.commit()
        return d.id
    finally:
        s.close()


def _make_experimental_design(session_factory, project_id):
    s = session_factory()
    try:
        e = repository.create_experimental_design(s, project_id=project_id, proposed_method="A method.")
        s.commit()
        return e.id
    finally:
        s.close()


def _make_novelty_assessment(session_factory, project_id):
    s = session_factory()
    try:
        n = repository.record_novelty_assessment(s, project_id=project_id, claim="A candidate contribution.")
        s.commit()
        return n.id
    finally:
        s.close()


_ALL_GATE_CASES = [
    (_make_question, planning_approval.approve_research_question, planning_approval.reject_research_question),
    (_make_contribution, planning_approval.approve_contribution, planning_approval.reject_contribution),
    (_make_methodology, planning_approval.approve_methodology_plan, planning_approval.reject_methodology_plan),
    (_make_dataset_requirements, planning_approval.approve_dataset_requirements, planning_approval.reject_dataset_requirements),
    (_make_experimental_design, planning_approval.approve_experimental_design, planning_approval.reject_experimental_design),
    (_make_novelty_assessment, intelligence_approval.approve_novelty_assessment, intelligence_approval.reject_novelty_assessment),
]

# The five genuinely new Phase 7 gates, with their audit event_type and
# entity-getter — used to verify `previous_status`/`new_status` metadata
# correctness across all of them in one parametrized regression test
# (audit remediation, Finding B).
_PLANNING_GATE_AUDIT_CASES = [
    (_make_question, planning_approval.approve_research_question, "planning.research_question_approved",
     repository.get_research_question),
    (_make_contribution, planning_approval.approve_contribution, "planning.contribution_approved",
     repository.get_contribution_candidate),
    (_make_methodology, planning_approval.approve_methodology_plan, "planning.methodology_approved",
     repository.get_methodology_plan),
    (_make_dataset_requirements, planning_approval.approve_dataset_requirements, "planning.dataset_requirements_approved",
     repository.get_dataset_requirements),
    (_make_experimental_design, planning_approval.approve_experimental_design, "planning.experimental_design_approved",
     repository.get_experimental_design),
]


# --- Candidates never pre-approved ------------------------------------------


def test_question_starts_as_candidate_never_pre_approved(session_factory, project_id):
    question_id = _make_question(session_factory, project_id)
    session = session_factory()
    try:
        question = repository.get_research_question(session, question_id)
        assert question.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()


def test_contribution_starts_as_candidate_never_pre_approved(session_factory, project_id):
    contribution_id = _make_contribution(session_factory, project_id)
    session = session_factory()
    try:
        contribution = repository.get_contribution_candidate(session, contribution_id)
        assert contribution.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()


def test_methodology_starts_as_candidate_never_pre_approved(session_factory, project_id):
    plan_id = _make_methodology(session_factory, project_id)
    session = session_factory()
    try:
        plan = repository.get_methodology_plan(session, plan_id)
        assert plan.planning_status == PlanningApprovalStatus.CANDIDATE
    finally:
        session.close()


# --- Agent (LLM) actor blocked on every gate type ---------------------------


@pytest.mark.parametrize("make_fn,approve_fn,reject_fn", _ALL_GATE_CASES)
def test_agent_actor_cannot_approve_any_planning_gate(session_factory, project_id, make_fn, approve_fn, reject_fn):
    entity_id = make_fn(session_factory, project_id)
    with pytest.raises(_HUMAN_ONLY_ERRORS):
        approve_fn(entity_id, actor="agent:auto-approver", session_factory=session_factory)


@pytest.mark.parametrize("make_fn,approve_fn,reject_fn", _ALL_GATE_CASES)
def test_agent_actor_cannot_reject_any_planning_gate(session_factory, project_id, make_fn, approve_fn, reject_fn):
    entity_id = make_fn(session_factory, project_id)
    with pytest.raises(_HUMAN_ONLY_ERRORS):
        reject_fn(entity_id, actor="agent:auto-rejecter", session_factory=session_factory)


def test_agent_cannot_request_changes_either(session_factory, project_id):
    question_id = _make_question(session_factory, project_id)
    with pytest.raises(HumanOnlyActionError):
        planning_approval.request_changes_research_question(
            question_id, actor="agent:x", session_factory=session_factory
        )


# --- Approval recorded correctly + audit event ------------------------------


def test_human_approval_updates_status_and_records_approval_row(session_factory, project_id):
    question_id = _make_question(session_factory, project_id)
    updated = planning_approval.approve_research_question(
        question_id, actor="user:pi", comment="looks solid", session_factory=session_factory
    )
    assert updated.planning_status == PlanningApprovalStatus.APPROVED

    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        assert len(approvals) == 1
        assert approvals[0].decision == ApprovalDecision.APPROVED
        assert approvals[0].stage == f"RESEARCH_QUESTION_APPROVAL:{question_id}"
    finally:
        session.close()


@pytest.mark.parametrize("make_fn,approve_fn,event_type,get_fn", _PLANNING_GATE_AUDIT_CASES)
def test_planning_gate_audit_event_records_correct_previous_status(
    session_factory, project_id, make_fn, approve_fn, event_type, get_fn
):
    """Regression test (audit remediation, Finding B): every Phase 7
    planning gate's audit event must report the entity's real
    `planning_status` before the decision (`"candidate"`), not a
    guessed/incorrect attribute — verified explicitly for all five gate
    types, not just one, since `EntitySpec.status_attr` is now set
    per-spec rather than inferred."""
    entity_id = make_fn(session_factory, project_id)
    approve_fn(entity_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == event_type)
        assert event.metadata_["previous_status"] == "candidate"
        assert event.metadata_["new_status"] == "approved"
        entity = get_fn(session, entity_id)
        assert entity.planning_status == PlanningApprovalStatus.APPROVED
    finally:
        session.close()


def test_approval_generates_a_complete_audit_event(session_factory, project_id):
    contribution_id = _make_contribution(session_factory, project_id)
    planning_approval.approve_contribution(contribution_id, actor="user:pi", comment="approved", session_factory=session_factory)

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "planning.contribution_approved")
        assert event.actor == "user:pi"
        assert event.metadata_["entity_id"] == contribution_id
        assert event.metadata_["previous_status"] == "candidate"
        assert event.metadata_["new_status"] == "approved"
    finally:
        session.close()


# --- Rejection is terminal; changes-requested reopens a fresh round --------


def test_rejected_methodology_remains_rejected_and_cannot_be_reapproved(session_factory, project_id):
    plan_id = _make_methodology(session_factory, project_id)
    rejected = planning_approval.reject_methodology_plan(plan_id, actor="user:pi", session_factory=session_factory)
    assert rejected.planning_status == PlanningApprovalStatus.REJECTED

    with pytest.raises(ApprovalAlreadyDecidedError):
        planning_approval.approve_methodology_plan(plan_id, actor="user:pi", session_factory=session_factory)


def test_changes_requested_allows_a_fresh_approval_round(session_factory, project_id):
    requirements_id = _make_dataset_requirements(session_factory, project_id)
    planning_approval.request_changes_dataset_requirements(
        requirements_id, actor="user:pi", comment="revise", session_factory=session_factory
    )
    updated = planning_approval.approve_dataset_requirements(
        requirements_id, actor="user:pi", comment="now good", session_factory=session_factory
    )
    assert updated.planning_status == PlanningApprovalStatus.APPROVED

    session = session_factory()
    try:
        approvals = repository.list_approvals(session, project_id)
        assert len(approvals) == 2
    finally:
        session.close()


def test_approving_nonexistent_experimental_design_raises_not_found(session_factory, project_id):
    with pytest.raises(CandidateNotFoundError):
        planning_approval.approve_experimental_design(999_999, actor="user:pi", session_factory=session_factory)


# --- Pending listing scoped to this layer's own prefixes --------------------


def test_get_pending_planning_approvals_lists_only_this_layers_approvals(session_factory, project_id):
    question_id = _make_question(session_factory, project_id)
    session = session_factory()
    try:
        assert planning_approval.get_pending_planning_approvals(session, project_id) == []
    finally:
        session.close()

    planning_approval.request_changes_research_question(question_id, actor="user:pi", session_factory=session_factory)
    session = session_factory()
    try:
        pending = planning_approval.get_pending_planning_approvals(session, project_id)
        assert pending == []  # changes-requested is a decided state, not pending
    finally:
        session.close()


# --- ContributionCandidate / NoveltyAssessment independence (critical) -----


def test_contribution_and_novelty_approval_states_are_independent(session_factory, project_id):
    contribution_id = _make_contribution(session_factory, project_id)
    session = session_factory()
    try:
        assessment = repository.record_novelty_assessment(
            session, project_id=project_id, claim="Proposed contribution text.",
            contribution_candidate_id=contribution_id,
        )
        session.commit()
        assessment_id = assessment.id
    finally:
        session.close()

    planning_approval.approve_contribution(contribution_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        assessment = repository.get_novelty_assessment(session, assessment_id)
        assert assessment.candidate_status == NoveltyCandidateStatus.NOT_ASSESSED  # untouched
    finally:
        session.close()

    intelligence_approval.approve_novelty_assessment(assessment_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        contribution = repository.get_contribution_candidate(session, contribution_id)
        assert contribution.planning_status == PlanningApprovalStatus.APPROVED  # untouched by the novelty decision
        assessment = repository.get_novelty_assessment(session, assessment_id)
        assert assessment.candidate_status == NoveltyCandidateStatus.HUMAN_APPROVED
    finally:
        session.close()


def test_one_contribution_can_have_multiple_novelty_assessments(session_factory, project_id):
    contribution_id = _make_contribution(session_factory, project_id)
    session = session_factory()
    try:
        first = repository.record_novelty_assessment(
            session, project_id=project_id, claim="v1", contribution_candidate_id=contribution_id,
        )
        second = repository.record_novelty_assessment(
            session, project_id=project_id, claim="v2 (reassessed against expanded literature)",
            contribution_candidate_id=contribution_id,
        )
        session.commit()
        assert first.id != second.id
        assert first.contribution_candidate_id == second.contribution_candidate_id == contribution_id
    finally:
        session.close()


# --- No cascading invalidation (Phase 7 spec section 16) -------------------


def test_rejecting_approved_upstream_does_not_touch_already_generated_downstream(session_factory, project_id, approved_contribution_id, approved_methodology_id):
    """A methodology generated from an APPROVED contribution keeps
    existing, unmodified, and un-auto-rejected, even after the
    contribution it was based on is later rejected."""
    session = session_factory()
    try:
        plan_before = repository.get_methodology_plan(session, approved_methodology_id)
        assert plan_before.planning_status == PlanningApprovalStatus.APPROVED
        assert plan_before.contribution_candidate_status_at_generation == "approved"
    finally:
        session.close()

    planning_approval.reject_contribution(approved_contribution_id, actor="user:pi", session_factory=session_factory)

    session = session_factory()
    try:
        contribution = repository.get_contribution_candidate(session, approved_contribution_id)
        assert contribution.planning_status == PlanningApprovalStatus.REJECTED

        plan_after = repository.get_methodology_plan(session, approved_methodology_id)
        assert plan_after.id == plan_before.id
        assert plan_after.planning_status == PlanningApprovalStatus.APPROVED  # NOT auto-rejected
        assert plan_after.description == plan_before.description  # NOT auto-deleted/modified
        # The generation-time snapshot is preserved exactly as it was —
        # it is not retroactively updated to reflect the new REJECTED status.
        assert plan_after.contribution_candidate_status_at_generation == "approved"
    finally:
        session.close()
