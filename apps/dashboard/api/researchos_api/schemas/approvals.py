"""Approval Center schemas.

`ApprovalActionRequest` intentionally carries no actor/identity field
at all — the server always records the dashboard's own fixed,
non-agent actor string (`dependencies.DASHBOARD_ACTOR`); a frontend
field such as `is_human=true` would be worthless as authorization
(anyone could set it), so no such field exists in this contract. See
docs/PHASE_DASHBOARD_V1.md's Approval Flow section.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    stage: str
    entity_type: str
    entity_id: int | None
    decision: str
    comment: str | None
    requested_at: datetime
    decided_at: datetime | None


class ApprovalActionRequest(BaseModel):
    action: Literal["approve", "reject", "request_changes"]
    comment: str | None = None


class ApprovalActionResponse(BaseModel):
    approval: ApprovalResponse
    entity_status: str
    """The decided-upon entity's own resulting status field (e.g. a
    `ScientificReview.status` or `ResearchQuestion.planning_status`
    value), read back immediately after the domain approval function
    committed — proof the decision was actually persisted through the
    real approval mechanism, not merely accepted by this endpoint."""
