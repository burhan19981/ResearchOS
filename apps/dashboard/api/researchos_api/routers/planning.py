"""Research planning traceability page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.planning import (
    ContributionCandidateResponse,
    DatasetRequirementsResponse,
    ExperimentalDesignResponse,
    ExperimentSpecificationResponse,
    MethodologyPlanResponse,
    PlanningResponse,
    ResearchQuestionResponse,
)
from ..services.mapping import to_contribution_response

router = APIRouter(prefix="/projects/{project_id}", tags=["planning"])


@router.get("/planning", response_model=PlanningResponse)
def get_planning(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> PlanningResponse:
    pid = project.id
    return PlanningResponse(
        project_id=pid,
        research_questions=[
            ResearchQuestionResponse.model_validate(q) for q in repository.list_research_questions(db, pid)
        ],
        contribution_candidates=[
            to_contribution_response(db, c) for c in repository.list_contribution_candidates(db, pid)
        ],
        methodology_plans=[
            MethodologyPlanResponse.model_validate(m) for m in repository.list_methodology_plans(db, pid)
        ],
        dataset_requirements=[
            DatasetRequirementsResponse.model_validate(d) for d in repository.list_dataset_requirements(db, pid)
        ],
        experimental_designs=[
            ExperimentalDesignResponse.model_validate(e) for e in repository.list_experimental_designs(db, pid)
        ],
        experiment_specifications=[
            ExperimentSpecificationResponse.model_validate(s)
            for s in repository.list_experiment_specifications(db, pid)
        ],
    )
