"""Research gap schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ResearchGapResponse(BaseModel):
    id: int
    project_id: int
    statement: str
    status: str
    gap_type: str | None
    affected_research_area: str | None
    evidence_summary: str | None
    confidence: float | None
    research_question_id: int | None
    evidence_count: int
    created_at: datetime
    updated_at: datetime
