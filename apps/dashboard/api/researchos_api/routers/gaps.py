"""Research gaps page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.gaps import ResearchGapResponse
from ..services.mapping import to_gap_response

router = APIRouter(prefix="/projects/{project_id}", tags=["gaps"])


@router.get("/gaps", response_model=list[ResearchGapResponse])
def list_gaps(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[ResearchGapResponse]:
    gaps = repository.list_research_gaps(db, project.id)
    return [to_gap_response(db, g) for g in gaps]
