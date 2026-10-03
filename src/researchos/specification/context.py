"""Planning context assembly for `ExperimentSpecification` generation.

Reuses `researchos.planning.orchestration` directly (existence/project/
approval-eligibility checks) and `researchos.planning.types.PlanningContext`
directly (already fully generic) rather than reimplementing either a
third time — Phase 8A is a direct continuation of the Phase 7 planning
chain, not an independent sibling package.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..db import repository
from ..db.models import DatasetLifecycleStatus
from ..planning import orchestration
from ..planning.errors import InvalidPlanningReferenceError, UnknownPlanningEntityError
from ..planning.types import PlanningContext


def _project_or_raise(session: Session, project_id: int):
    project = repository.get_project(session, project_id)
    if project is None:
        raise UnknownPlanningEntityError(f"ResearchProject {project_id} does not exist.")
    return project


def build_experiment_specification_context(
    session: Session,
    project_id: int,
    experimental_design_id: int,
    dataset_version_id: int,
    research_question_ids: list[int],
) -> PlanningContext:
    """Rules 1-4 for experiment-specification generation:
    `experimental_design_id` and `dataset_version_id` are both explicit,
    must exist in this project, and must both be approved
    (`planning_status APPROVED` for the design; `lifecycle_status
    APPROVED` for the dataset version — reusing `orchestration.
    require_status` directly with DatasetVersion's own vocabulary, since
    `require_approved`'s convenience wrapper is scoped to
    `PlanningApprovalStatus` only). `research_question_ids` is explicit
    and non-empty.

    The design's own `methodology_plan_id`, if set, is included in the
    context and its snapshot for traceability, but is not itself
    re-validated as APPROVED here — that was already enforced when the
    design itself was generated in Phase 7; Phase 8A does not re-walk
    and re-check an entire upstream chain on every new generation.
    """
    _project_or_raise(session, project_id)
    if not research_question_ids:
        raise InvalidPlanningReferenceError("At least one research_question_id must be provided.")

    design = repository.get_experimental_design(session, experimental_design_id)
    orchestration.require_in_project(design, experimental_design_id, "ExperimentalDesign", project_id)
    orchestration.require_approved(design, experimental_design_id, "ExperimentalDesign")

    dataset_version = repository.get_dataset_version(session, dataset_version_id)
    orchestration.require_in_project(dataset_version, dataset_version_id, "DatasetVersion", project_id)
    orchestration.require_status(
        dataset_version, dataset_version_id, "DatasetVersion",
        status_attr="lifecycle_status", approved_values=(DatasetLifecycleStatus.APPROVED,),
    )

    methodology_plan = None
    if design.methodology_plan_id is not None:
        methodology_plan = repository.get_methodology_plan(session, design.methodology_plan_id)

    questions_json = []
    for question_id in research_question_ids:
        question = repository.get_research_question(session, question_id)
        orchestration.require_in_project(question, question_id, "ResearchQuestion", project_id)
        questions_json.append({"research_question_id": question.id, "question": question.question})

    prompt_json = {
        "approved_experimental_design": {
            "experimental_design_id": design.id,
            "proposed_method": design.proposed_method,
            "baselines": design.baselines,
            "ablation_studies": design.ablation_studies,
            "evaluation_metrics": design.evaluation_metrics,
            "comparison_strategy": design.comparison_strategy,
        },
        "approved_dataset_version": {
            "dataset_version_id": dataset_version.id,
            "format": dataset_version.format,
            "sample_count": dataset_version.sample_count,
            "split_definition": dataset_version.split_definition,
        },
        "methodology": (
            {"methodology_plan_id": methodology_plan.id, "description": methodology_plan.description}
            if methodology_plan is not None
            else None
        ),
        "research_questions": questions_json,
    }

    upstream_snapshots: dict = {
        "experimental_design": orchestration.snapshot(design),
        "dataset_version": orchestration.snapshot(dataset_version, status_attr="lifecycle_status"),
    }
    if methodology_plan is not None:
        upstream_snapshots["methodology_plan"] = orchestration.snapshot(methodology_plan)

    return PlanningContext(
        prompt_json=prompt_json,
        allowed_research_question_ids=frozenset(research_question_ids),
        upstream_snapshots=upstream_snapshots,
    )
