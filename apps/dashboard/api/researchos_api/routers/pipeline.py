"""Research pipeline visualization — a read-only projection of
`researchos.workflow`'s real state machine. This router computes no
stage ordering or transition policy of its own; it only reads
`workflow.stages.STAGE_ORDER`/`workflow.service.get_current_stage`/
`get_allowed_transitions` (Dashboard V1 spec section 9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db.models import ResearchProject
from researchos.workflow.service import get_allowed_transitions, get_current_stage
from researchos.workflow.stages import STAGE_INDEX, STAGE_ORDER

from ..dependencies import get_db, get_project_or_404
from ..schemas.pipeline import AllowedTransition, PipelineResponse, PipelineStage

router = APIRouter(prefix="/projects/{project_id}", tags=["pipeline"])


@router.get("/pipeline", response_model=PipelineResponse)
def get_pipeline(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> PipelineResponse:
    current_stage = get_current_stage(db, project.id)
    current_index = STAGE_INDEX[current_stage]

    stages = [
        PipelineStage(
            stage=stage.value,
            order=index,
            is_current=(stage == current_stage),
            is_completed=(index < current_index),
        )
        for index, stage in enumerate(STAGE_ORDER)
    ]
    transitions = [
        AllowedTransition(target_stage=t.target_stage.value, policy=t.policy.value, direction=t.direction)
        for t in get_allowed_transitions(db, project.id)
    ]
    return PipelineResponse(
        project_id=project.id,
        project_status=project.status.value,
        current_stage=current_stage.value,
        stages=stages,
        allowed_transitions=transitions,
    )
