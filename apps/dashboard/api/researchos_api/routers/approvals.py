"""Approval Center.

`GET /approvals` lists every `Approval` row for the project (every
layer, via `researchos.db.repository.list_approvals` — the single
global function that already answers "all approvals across every
layer," see `services/approvals.py`'s module docstring).

`POST /approvals/{approval_id}/actions` is the only mutating endpoint
in this router (indeed, in the entire dashboard API besides it) — it
dispatches to the exactly one existing domain approve/reject/
request-changes function for that approval's stage, via
`services.approvals.act_on_approval`. It never implements approval
policy itself: every precondition (human-only actor, a review must be
`READY_FOR_HUMAN_REVIEW`, a claim needs a `HUMAN_APPROVED` review,
...) is enforced by the domain function, which either mutates and
commits or raises — this endpoint has no fallback path that persists
a decision the domain layer rejected (Dashboard V1 spec section 18).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import DASHBOARD_ACTOR, get_db, get_project_or_404, get_session_factory
from ..schemas.approvals import ApprovalActionRequest, ApprovalActionResponse, ApprovalResponse
from ..services.approvals import act_on_approval, parse_stage

router = APIRouter(prefix="/projects/{project_id}", tags=["approvals"])


def _to_approval_response(approval) -> ApprovalResponse:
    entity_type, entity_id = parse_stage(approval.stage)
    return ApprovalResponse(
        id=approval.id,
        project_id=approval.project_id,
        stage=approval.stage,
        entity_type=entity_type,
        entity_id=entity_id,
        decision=approval.decision.value,
        comment=approval.comment,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
    )


@router.get("/approvals", response_model=list[ApprovalResponse])
def list_approvals(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[ApprovalResponse]:
    approvals = repository.list_approvals(db, project.id)
    return [_to_approval_response(a) for a in approvals]


@router.post("/approvals/{approval_id}/actions", response_model=ApprovalActionResponse)
def act_on_approval_route(
    approval_id: int,
    body: ApprovalActionRequest,
    project: ResearchProject = Depends(get_project_or_404),
    db: Session = Depends(get_db),
    session_factory: sessionmaker = Depends(get_session_factory),
) -> ApprovalActionResponse:
    try:
        updated_approval, entity_status = act_on_approval(
            db, project.id, approval_id, body.action, DASHBOARD_ACTOR, body.comment,
            session_factory=session_factory,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApprovalActionResponse(approval=_to_approval_response(updated_approval), entity_status=entity_status)
