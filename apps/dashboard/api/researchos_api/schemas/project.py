"""Project identity schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    field: str | None
    status: str
    current_stage: str | None
    created_at: datetime
    updated_at: datetime
