"""Analysis page. A `NOT_COMPARABLE` record's `result.reasons` is
returned verbatim — this router never attempts to reinterpret or
silently fix a comparability finding (Dashboard V1 spec section 16)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.analysis import AnalysisRecordResponse
from ..services.mapping import to_analysis_record_response

router = APIRouter(prefix="/projects/{project_id}", tags=["analysis"])


@router.get("/analysis", response_model=list[AnalysisRecordResponse])
def list_analysis_records(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[AnalysisRecordResponse]:
    records = repository.list_analysis_records(db, project.id)
    return [to_analysis_record_response(r) for r in records]
