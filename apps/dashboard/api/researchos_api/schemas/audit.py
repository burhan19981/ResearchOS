"""Audit log schemas — strictly read-only, never fabricated."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: int
    project_id: int
    event_type: str
    actor: str
    description: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
