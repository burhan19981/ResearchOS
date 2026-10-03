"""Research planning traceability schemas.

`PlanningResponse` visualizes the existing chain Research Gap ->
Research Question -> Contribution -> Methodology -> Dataset
Requirements -> Experimental Design -> Experiment Specification — it
does not compute or infer any new relationship; every list here is a
project-scoped read of an already-persisted table.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResearchQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    question: str
    type: str | None
    status: str
    planning_status: str


class ContributionCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str
    contribution_type: str | None
    planning_status: str
    version: int
    cited_research_question_ids: list[int] = []


class MethodologyPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    description: str
    status: str
    planning_status: str
    methodology_type: str | None
    version: int
    contribution_candidate_id: int | None


class DatasetRequirementsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    required_characteristics: str | None
    planning_status: str
    methodology_plan_id: int | None


class ExperimentalDesignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    proposed_method: str | None
    comparison_strategy: str | None
    planning_status: str
    version: int
    methodology_plan_id: int | None
    dataset_requirements_id: int | None


class ExperimentSpecificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    experiment_id: int | None
    experimental_design_id: int | None
    methodology_plan_id: int | None
    dataset_version_id: int | None
    description: str | None
    planning_status: str
    version: int
    configuration_hash: str | None


class PlanningResponse(BaseModel):
    project_id: int
    research_questions: list[ResearchQuestionResponse]
    contribution_candidates: list[ContributionCandidateResponse]
    methodology_plans: list[MethodologyPlanResponse]
    dataset_requirements: list[DatasetRequirementsResponse]
    experimental_designs: list[ExperimentalDesignResponse]
    experiment_specifications: list[ExperimentSpecificationResponse]
