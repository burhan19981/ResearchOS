"""Audit log page — strictly read-only; nothing here writes an
`AuditEvent` (Dashboard V1 spec section 19)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.models import ResearchProject

from ..dependencies import get_db, get_project_or_404
from ..schemas.audit import AuditEventResponse
from ..services.mapping import to_audit_event_response

router = APIRouter(prefix="/projects/{project_id}", tags=["audit"])


@router.get("/audit", response_model=list[AuditEventResponse])
def list_audit_events(
    project: ResearchProject = Depends(get_project_or_404), db: Session = Depends(get_db)
) -> list[AuditEventResponse]:
    events = repository.list_audit_events(db, project.id)
    return [to_audit_event_response(e) for e in events]
