"""Scientific claim / review schemas.

`strength`/`approval_status`/`status` are read verbatim from the
existing `ClaimStrength`/`ClaimApprovalStatus`/`ScientificReviewStatus`
vocabularies — never collapsed into a blunt true/false, and never
presented as `APPROVED`/`HUMAN_APPROVED` unless the underlying row
genuinely already is (Phase 8 spec section 17).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ScientificReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    claim_id: int
    status: str
    dimensions: dict[str, Any] | None
    recommendation: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ScientificClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    claim_text: str
    claim_type: str | None
    strength: str
    approval_status: str
    confidence: float | None
    version: int
    created_at: datetime
    updated_at: datetime
    supporting_analysis_record_ids: list[int] = []
    reviews: list[ScientificReviewResponse] = []
