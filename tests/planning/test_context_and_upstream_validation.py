"""Upstream validation (Phase 7 spec section 19, Rules 1-4): distinct
failures for an unknown id, a cross-project id, and a not-yet-approved
upstream artifact — for every context builder in
`researchos.planning.context`.
"""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.models import GapStatus, PlanningApprovalStatus
from researchos.planning import context
from researchos.planning.errors import (
    CrossProjectReferenceError,
    InvalidPlanningReferenceError,
    UnknownPlanningEntityError,
    UpstreamNotApprovedError,
)


# --- research question context: upstream is a ResearchGap ------------------


def test_research_question_context_unknown_gap_raises(session_factory, project_id):
    session = session_factory()
    try:
        with pytest.raises(UnknownPlanningEntityError):
            context.build_research_question_context(session, project_id, 999_999)
    finally:
        session.close()


def test_research_question_context_gap_in_other_project_raises(session_factory, project_id, second_project_id):
    session = session_factory()
    try:
        gap = repository.record_research_gap(session, project_id=second_project_id, statement="Other project's gap.")
        session.commit()
        with pytest.raises(CrossProjectReferenceError):
            context.build_research_question_context(session, project_id, gap.id)
    finally:
        session.close()


def test_research_question_context_unvalidated_gap_raises(session_factory, project_id):
    session = session_factory()
    try:
        gap = repository.record_research_gap(session, project_id=project_id, statement="Still a candidate gap.")
        session.commit()
        assert gap.status == GapStatus.CANDIDATE
        with pytest.raises(UpstreamNotApprovedError):
            context.build_research_question_context(session, project_id, gap.id)
    finally:
        session.close()


def test_research_question_context_validated_gap_succeeds(session_factory, project_id, approved_gap_id):
    session = session_factory()
    try:
        ctx = context.build_research_question_context(session, project_id, approved_gap_id)
        assert ctx.prompt_json["approved_gap"]["gap_id"] == approved_gap_id
        assert len(ctx.allowed_literature_item_ids) == 1
    finally:
        session.close()


# --- contribution context: upstream is a list of ResearchQuestion ----------


def test_contribution_context_empty_list_raises(session_factory, project_id):
    session = session_factory()
    try:
        with pytest.raises(InvalidPlanningReferenceError):
            context.build_contribution_context(session, project_id, [])
    finally:
        session.close()


def test_contribution_context_unknown_question_raises(session_factory, project_id):
    session = session_factory()
    try:
        with pytest.raises(UnknownPlanningEntityError):
            context.build_contribution_context(session, project_id, [999_999])
    finally:
        session.close()


def test_contribution_context_question_in_other_project_raises(session_factory, project_id, second_project_id):
    session = session_factory()
    try:
        question = repository.create_research_question(
            session, project_id=second_project_id, question="Other project's question?",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        session.commit()
        with pytest.raises(CrossProjectReferenceError):
            context.build_contribution_context(session, project_id, [question.id])
    finally:
        session.close()


def test_contribution_context_candidate_question_raises(session_factory, project_id):
    session = session_factory()
    try:
        question = repository.create_research_question(session, project_id=project_id, question="Still a candidate?")
        session.commit()
        assert question.planning_status == PlanningApprovalStatus.CANDIDATE
        with pytest.raises(UpstreamNotApprovedError):
            context.build_contribution_context(session, project_id, [question.id])
    finally:
        session.close()


def test_contribution_context_approved_question_succeeds(session_factory, project_id, approved_question_id):
    session = session_factory()
    try:
        ctx = context.build_contribution_context(session, project_id, [approved_question_id])
        assert ctx.allowed_research_question_ids == frozenset([approved_question_id])
    finally:
        session.close()


# --- methodology context: upstream is a ContributionCandidate --------------


def test_methodology_context_unknown_contribution_raises(session_factory, project_id):
    session = session_factory()
    try:
        with pytest.raises(UnknownPlanningEntityError):
            context.build_methodology_context(session, project_id, 999_999)
    finally:
        session.close()


def test_methodology_context_contribution_in_other_project_raises(session_factory, project_id, second_project_id):
    session = session_factory()
    try:
        contribution = repository.create_contribution_candidate(
            session, project_id=second_project_id, title="Other project's contribution", description="...",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        session.commit()
        with pytest.raises(CrossProjectReferenceError):
            context.build_methodology_context(session, project_id, contribution.id)
    finally:
        session.close()


def test_methodology_context_candidate_contribution_raises(session_factory, project_id):
    session = session_factory()
    try:
        contribution = repository.create_contribution_candidate(
            session, project_id=project_id, title="Still a candidate", description="...",
        )
        session.commit()
        with pytest.raises(UpstreamNotApprovedError):
            context.build_methodology_context(session, project_id, contribution.id)
    finally:
        session.close()


def test_methodology_context_question_not_linked_to_contribution_raises(
    session_factory, project_id, approved_contribution_id
):
    session = session_factory()
    try:
        unrelated_question = repository.create_research_question(
            session, project_id=project_id, question="An unrelated question?",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        session.commit()
        with pytest.raises(InvalidPlanningReferenceError):
            context.build_methodology_context(
                session, project_id, approved_contribution_id, [unrelated_question.id]
            )
    finally:
        session.close()


def test_methodology_context_approved_contribution_succeeds(session_factory, project_id, approved_contribution_id):
    session = session_factory()
    try:
        ctx = context.build_methodology_context(session, project_id, approved_contribution_id)
        assert ctx.prompt_json["approved_contribution"]["contribution_candidate_id"] == approved_contribution_id
        assert ctx.upstream_snapshots["contribution_candidate"]["status_at_generation"] == "approved"
    finally:
        session.close()


# --- dataset requirements context: upstream is a MethodologyPlan -----------


def test_dataset_requirements_context_unknown_methodology_raises(session_factory, project_id):
    session = session_factory()
    try:
        with pytest.raises(UnknownPlanningEntityError):
            context.build_dataset_requirements_context(session, project_id, 999_999)
    finally:
        session.close()


def test_dataset_requirements_context_draft_methodology_raises(session_factory, project_id, approved_contribution_id):
    session = session_factory()
    try:
        plan = repository.create_methodology_version(
            session, project_id=project_id, description="Not yet approved.",
            contribution_candidate_id=approved_contribution_id,
        )
        session.commit()
        with pytest.raises(UpstreamNotApprovedError):
            context.build_dataset_requirements_context(session, project_id, plan.id)
    finally:
        session.close()


# --- experimental design context: upstream is Methodology + DatasetReqs ----


def test_experimental_design_context_empty_questions_raises(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id
):
    session = session_factory()
    try:
        with pytest.raises(InvalidPlanningReferenceError):
            context.build_experimental_design_context(
                session, project_id, approved_methodology_id, approved_dataset_requirements_id, []
            )
    finally:
        session.close()


def test_experimental_design_context_mismatched_methodology_raises(
    session_factory, project_id, approved_dataset_requirements_id, approved_question_id
):
    session = session_factory()
    try:
        other_contribution = repository.create_contribution_candidate(
            session, project_id=project_id, title="A different contribution", description="...",
            planning_status=PlanningApprovalStatus.APPROVED,
        )
        other_plan = repository.create_methodology_version(
            session, project_id=project_id, description="A different methodology.",
            planning_status=PlanningApprovalStatus.APPROVED, contribution_candidate_id=other_contribution.id,
        )
        session.commit()
        with pytest.raises(InvalidPlanningReferenceError):
            context.build_experimental_design_context(
                session, project_id, other_plan.id, approved_dataset_requirements_id, [approved_question_id]
            )
    finally:
        session.close()


def test_experimental_design_context_succeeds(
    session_factory, project_id, approved_methodology_id, approved_dataset_requirements_id, approved_question_id
):
    session = session_factory()
    try:
        ctx = context.build_experimental_design_context(
            session, project_id, approved_methodology_id, approved_dataset_requirements_id, [approved_question_id]
        )
        assert ctx.allowed_research_question_ids == frozenset([approved_question_id])
        assert "methodology_plan" in ctx.upstream_snapshots
        assert "dataset_requirements" in ctx.upstream_snapshots
    finally:
        session.close()
