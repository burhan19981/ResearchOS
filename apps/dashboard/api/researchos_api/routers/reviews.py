"""Scientific claims + reviews page. Claim strength/approval status
and review status are read verbatim from the existing domain
vocabularies — never collapsed into true/false (Dashboard V1 spec
section 17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.reviews import ScientificClaimResponse
from ..services.mapping import to_scientific_claim_response

router = APIRouter(prefix="/projects/{project_id}", tags=["reviews"])


@router.get("/reviews", response_model=list[ScientificClaimResponse])
def list_claims_and_reviews(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[ScientificClaimResponse]:
    claims = repository.list_scientific_claims(db, project.id)
    return [to_scientific_claim_response(db, c) for c in claims]
