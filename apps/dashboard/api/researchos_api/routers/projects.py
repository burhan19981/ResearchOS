"""Project listing and identity — the project selector's data source."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.project import ProjectResponse
from ..services.mapping import to_project_response

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectResponse]:
    projects = repository.list_projects(db)
    return [to_project_response(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project: ResearchProject = Depends(get_project_or_404)) -> ProjectResponse:
    return to_project_response(project)
