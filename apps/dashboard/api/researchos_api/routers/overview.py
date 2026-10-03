"""Overview page — project identity plus real database counts. Every
number is a `len()` over an actual project-scoped repository list
call; there is no hard-coded or placeholder research statistic
anywhere in this module (Dashboard V1 spec section 8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ApprovalDecision, ResearchProject
from researchos.workflow.service import get_current_stage

from ..dependencies import get_db, get_project_or_404
from ..schemas.overview import OverviewCounts, OverviewResponse
from ..services.mapping import to_project_response

router = APIRouter(prefix="/projects/{project_id}", tags=["overview"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> OverviewResponse:
    pid = project.id
    pending_approvals = [a for a in repository.list_approvals(db, pid) if a.decision == ApprovalDecision.PENDING]
    counts = OverviewCounts(
        literature_items=len(repository.list_literature_items(db, pid)),
        research_gaps=len(repository.list_research_gaps(db, pid)),
        novelty_assessments=len(repository.list_novelty_assessments(db, pid)),
        research_questions=len(repository.list_research_questions(db, pid)),
        contribution_candidates=len(repository.list_contribution_candidates(db, pid)),
        experiments=len(repository.list_experiments(db, pid)),
        runs=len(repository.list_runs(db, pid)),
        metrics=len(repository.list_metrics(db, pid)),
        analysis_records=len(repository.list_analysis_records(db, pid)),
        scientific_claims=len(repository.list_scientific_claims(db, pid)),
        scientific_reviews=len(repository.list_scientific_reviews(db, pid)),
        pending_approvals=len(pending_approvals),
    )
    return OverviewResponse(
        project=to_project_response(project), current_stage=get_current_stage(db, pid).value, counts=counts
    )
