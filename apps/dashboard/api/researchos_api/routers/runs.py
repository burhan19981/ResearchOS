"""Runs page. Statuses are read verbatim from the existing `RunStatus`
lifecycle — this router invents no new execution status (Dashboard V1
spec section 14)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.runs import RunResponse
from ..services.mapping import to_run_response

router = APIRouter(prefix="/projects/{project_id}", tags=["runs"])


@router.get("/runs", response_model=list[RunResponse])
def list_runs(
    project: ResearchProject = Depends(get_project_or_404),
    db: Session = Depends(get_db),
    experiment_id: Optional[int] = Query(None),
) -> list[RunResponse]:
    runs = repository.list_runs(db, project.id, experiment_id=experiment_id)
    return [to_run_response(db, r, include_children=False) for r in runs]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: int, project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> RunResponse:
    run = repository.get_run(db, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} does not exist in project {project.id}.")
    return to_run_response(db, run, include_children=True)
