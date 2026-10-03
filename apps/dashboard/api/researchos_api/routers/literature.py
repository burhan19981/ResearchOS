"""Evidence / literature page.

`repository.list_literature_items` supports no server-side filter
beyond `project_id` — this router does not invent one (that would be
duplicating/extending the Evidence layer's own repository contract);
optional `q`/`source`/`evidence_status` query parameters instead filter
the already-fetched, already project-scoped list in Python, which is
honest about being a thin client-side convenience, not a new search
engine (Dashboard V1 spec section 10)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.literature import LiteratureItemResponse

router = APIRouter(prefix="/projects/{project_id}", tags=["literature"])


@router.get("/literature", response_model=list[LiteratureItemResponse])
def list_literature(
    project: ResearchProject = Depends(get_project_or_404),
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Case-insensitive substring match against title/authors."),
    source: Optional[str] = Query(None),
    evidence_status: Optional[str] = Query(None),
) -> list[LiteratureItemResponse]:
    items = repository.list_literature_items(db, project.id)
    if q:
        needle = q.lower()
        items = [i for i in items if needle in (i.title or "").lower() or needle in (i.authors or "").lower()]
    if source:
        items = [i for i in items if i.source == source]
    if evidence_status:
        items = [i for i in items if i.evidence_status.value == evidence_status]
    return [LiteratureItemResponse.model_validate(i) for i in items]
