"""Experiments page."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.experiments import ExperimentResponse
from ..services.mapping import to_experiment_response

router = APIRouter(prefix="/projects/{project_id}", tags=["experiments"])


@router.get("/experiments", response_model=list[ExperimentResponse])
def list_experiments(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[ExperimentResponse]:
    experiments = repository.list_experiments(db, project.id)
    return [to_experiment_response(db, e) for e in experiments]


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: int, project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> ExperimentResponse:
    experiment = repository.get_experiment(db, experiment_id)
    if experiment is None or experiment.project_id != project.id:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} does not exist in project {project.id}.")
    return to_experiment_response(db, experiment)
