"""Novelty page. See schemas/novelty.py for why `candidate_status` is
the field the frontend must treat as authoritative-ish (still
non-final until HUMAN_APPROVED), never the legacy `status`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.novelty import NoveltyAssessmentResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["novelty"])


@router.get("/novelty", response_model=list[NoveltyAssessmentResponse])
def list_novelty(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[NoveltyAssessmentResponse]:
    assessments = repository.list_novelty_assessments(db, project.id)
    return [NoveltyAssessmentResponse.model_validate(a) for a in assessments]
