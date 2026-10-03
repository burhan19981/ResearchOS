"""Evidence / literature schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class LiteratureItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    authors: str | None
    year: int | None
    venue: str | None
    doi: str | None
    url: str | None
    source: str | None
    publisher: str | None
    publication_date: date | None
    document_type: str | None
    citation_count: int | None
    evidence_status: str
    record_status: str
    metadata_completeness: float | None
    retrieved_at: datetime | None
    created_at: datetime
