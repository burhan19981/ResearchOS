"""Planning context package assembly (Phase 7 spec section 24).

Turns explicitly-supplied, already-approved upstream artifact ids into
the bounded, explicit `PlanningContext` each generation service sends
to an LLM — never the raw ORM row, never arbitrary internal fields.
Every builder here enforces `researchos.planning.orchestration`'s
existence/project/approval rules before assembling anything, so a
generation service can never accidentally ground itself on a
nonexistent, cross-project, or unapproved upstream artifact.

Deliberately NOT a reuse of `researchos.intelligence.evidence_package`:
that module is hard-typed to project one thing (`LiteratureItem` rows)
into a prompt; this layer's context is assembled from multiple upstream
table types (`ResearchGap`, `ResearchQuestion`, `ContributionCandidate`,
`MethodologyPlan`, `DatasetRequirements`), which does not fit that
module's shape.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import EvidenceSubjectType, GapStatus
from . import orchestration
from .errors import InvalidPlanningReferenceError, UnknownPlanningEntityError
from .types import PlanningContext


def _project_or_raise(session: Session, project_id: int) -> Any:
    project = repository.get_project(session, project_id)
    if project is None:
        raise UnknownPlanningEntityError(f"ResearchProject {project_id} does not exist.")
    return project


def _literature_evidence_for(
    session: Session, project_id: int, subject_type: EvidenceSubjectType, subject_id: int
) -> list[dict[str, Any]]:
    links = repository.list_evidence_links(session, project_id, subject_type=subject_type, subject_id=subject_id)
    items: list[dict[str, Any]] = []
    for link in links:
        item = repository.get_literature_item(session, link.literature_item_id)
        if item is None:
            continue
        items.append(
            {
                "literature_item_id": item.id,
                "title": item.title,
                "abstract": (item.abstract[:1000] if item.abstract else None),
                "relationship": link.relationship_type.value,
            }
        )
    return items


def build_research_question_context(session: Session, project_id: int, research_gap_id: int) -> PlanningContext:
    """Rules 1-4 for research question generation: `research_gap_id` is
    explicit, must exist in this project, and must be
    `GapStatus.VALIDATED` (Phase 6's own "a human confirmed this" value,
    reused rather than duplicated)."""
    _project_or_raise(session, project_id)
    gap = repository.get_research_gap(session, research_gap_id)
    orchestration.require_in_project(gap, research_gap_id, "ResearchGap", project_id)
    orchestration.require_status(
        gap, research_gap_id, "ResearchGap", status_attr="status", approved_values=(GapStatus.VALIDATED,)
    )

    evidence = _literature_evidence_for(session, project_id, EvidenceSubjectType.GAP_CANDIDATE, gap.id)
    allowed_literature_ids = frozenset(e["literature_item_id"] for e in evidence)

    prompt_json = {
        "approved_gap": {
            "gap_id": gap.id,
            "statement": gap.statement,
            "gap_type": gap.gap_type,
            "affected_research_area": gap.affected_research_area,
            "evidence_summary": gap.evidence_summary,
            "prior_work_summary": gap.prior_work_summary,
            "insufficiency_summary": gap.insufficiency_summary,
            "missing_evidence_summary": gap.missing_evidence_summary,
            "candidate_research_question": gap.candidate_research_question,
        },
        "evidence": evidence,
    }
    return PlanningContext(
        prompt_json=prompt_json,
        allowed_literature_item_ids=allowed_literature_ids,
        upstream_snapshots={"research_gap": {"id": gap.id, "status_at_generation": gap.status.value}},
    )


def build_contribution_context(session: Session, project_id: int, research_question_ids: list[int]) -> PlanningContext:
    """Rules 1-4 for contribution generation: `research_question_ids` is
    explicit and non-empty; every question must exist in this project
    and be `planning_status APPROVED`."""
    _project_or_raise(session, project_id)
    if not research_question_ids:
        raise InvalidPlanningReferenceError("At least one research_question_id must be provided.")

    questions_json = []
    upstream_questions: dict[str, Any] = {}
    for question_id in research_question_ids:
        question = repository.get_research_question(session, question_id)
        orchestration.require_in_project(question, question_id, "ResearchQuestion", project_id)
        orchestration.require_approved(question, question_id, "ResearchQuestion")
        questions_json.append(
            {
                "research_question_id": question.id,
                "question": question.question,
                "hypothesis": question.hypothesis,
                "type": question.type,
            }
        )
        upstream_questions[str(question.id)] = orchestration.snapshot(question, include_version=False)

    return PlanningContext(
        prompt_json={"approved_research_questions": questions_json},
        allowed_research_question_ids=frozenset(research_question_ids),
        upstream_snapshots={"research_questions": upstream_questions},
    )


def build_methodology_context(
    session: Session,
    project_id: int,
    contribution_candidate_id: int,
    research_question_ids: Optional[list[int]] = None,
) -> PlanningContext:
    """Rules 1-4 for methodology generation: `contribution_candidate_id`
    is explicit, must exist in this project, and must be `planning_status
    APPROVED`. If `research_question_ids` is given, every id must
    actually be linked to that contribution (via
    `contribution_candidate_questions`) — a caller cannot ground a
    methodology on a question the contribution never claimed to
    address."""
    _project_or_raise(session, project_id)
    contribution = repository.get_contribution_candidate(session, contribution_candidate_id)
    orchestration.require_in_project(contribution, contribution_candidate_id, "ContributionCandidate", project_id)
    orchestration.require_approved(contribution, contribution_candidate_id, "ContributionCandidate")

    linked_question_ids = {
        link.research_question_id
        for link in repository.list_contribution_candidate_questions(
            session, project_id, contribution_candidate_id=contribution.id
        )
    }
    questions_json = []
    if research_question_ids:
        unknown = set(research_question_ids) - linked_question_ids
        if unknown:
            raise InvalidPlanningReferenceError(
                f"research_question_id(s) {sorted(unknown)} are not linked to "
                f"ContributionCandidate {contribution_candidate_id}."
            )
        for question_id in research_question_ids:
            question = repository.get_research_question(session, question_id)
            questions_json.append(
                {"research_question_id": question.id, "question": question.question, "hypothesis": question.hypothesis}
            )

    prompt_json = {
        "approved_contribution": {
            "contribution_candidate_id": contribution.id,
            "title": contribution.title,
            "description": contribution.description,
            "contribution_type": contribution.contribution_type,
        },
        "research_questions": questions_json,
    }
    return PlanningContext(
        prompt_json=prompt_json,
        upstream_snapshots={"contribution_candidate": orchestration.snapshot(contribution)},
    )


def build_dataset_requirements_context(session: Session, project_id: int, methodology_plan_id: int) -> PlanningContext:
    """Rules 1-4 for dataset requirements generation:
    `methodology_plan_id` is explicit, must exist in this project, and
    must be `planning_status APPROVED`."""
    _project_or_raise(session, project_id)
    plan = repository.get_methodology_plan(session, methodology_plan_id)
    orchestration.require_in_project(plan, methodology_plan_id, "MethodologyPlan", project_id)
    orchestration.require_approved(plan, methodology_plan_id, "MethodologyPlan")

    prompt_json = {
        "approved_methodology": {
            "methodology_plan_id": plan.id,
            "description": plan.description,
            "methodology_type": plan.methodology_type,
            "components": plan.components,
            "assumptions": plan.assumptions,
        }
    }
    return PlanningContext(
        prompt_json=prompt_json,
        upstream_snapshots={"methodology_plan": orchestration.snapshot(plan)},
    )


def build_experimental_design_context(
    session: Session,
    project_id: int,
    methodology_plan_id: int,
    dataset_requirements_id: int,
    research_question_ids: list[int],
) -> PlanningContext:
    """Rules 1-4 for experimental design generation: `methodology_plan_id`
    and `dataset_requirements_id` are both explicit, must exist in this
    project, and must both be `planning_status APPROVED`;
    `research_question_ids` is explicit and non-empty. Also checks that
    `dataset_requirements_id` was actually generated from
    `methodology_plan_id` (when that provenance is recorded), rather
    than silently pairing a design with a mismatched dataset spec."""
    _project_or_raise(session, project_id)
    if not research_question_ids:
        raise InvalidPlanningReferenceError("At least one research_question_id must be provided.")

    plan = repository.get_methodology_plan(session, methodology_plan_id)
    orchestration.require_in_project(plan, methodology_plan_id, "MethodologyPlan", project_id)
    orchestration.require_approved(plan, methodology_plan_id, "MethodologyPlan")

    requirements = repository.get_dataset_requirements(session, dataset_requirements_id)
    orchestration.require_in_project(requirements, dataset_requirements_id, "DatasetRequirements", project_id)
    orchestration.require_approved(requirements, dataset_requirements_id, "DatasetRequirements")
    if requirements.methodology_plan_id is not None and requirements.methodology_plan_id != methodology_plan_id:
        raise InvalidPlanningReferenceError(
            f"DatasetRequirements {dataset_requirements_id} was generated from MethodologyPlan "
            f"{requirements.methodology_plan_id}, not {methodology_plan_id}."
        )

    questions_json = []
    for question_id in research_question_ids:
        question = repository.get_research_question(session, question_id)
        orchestration.require_in_project(question, question_id, "ResearchQuestion", project_id)
        questions_json.append({"research_question_id": question.id, "question": question.question})

    prompt_json = {
        "approved_methodology": {
            "methodology_plan_id": plan.id,
            "description": plan.description,
            "methodology_type": plan.methodology_type,
        },
        "approved_dataset_requirements": {
            "dataset_requirements_id": requirements.id,
            "required_characteristics": requirements.required_characteristics,
            "split_strategy": requirements.split_strategy,
        },
        "research_questions": questions_json,
    }
    return PlanningContext(
        prompt_json=prompt_json,
        allowed_research_question_ids=frozenset(research_question_ids),
        upstream_snapshots={
            "methodology_plan": orchestration.snapshot(plan),
            "dataset_requirements": orchestration.snapshot(requirements, include_version=False),
        },
    )
