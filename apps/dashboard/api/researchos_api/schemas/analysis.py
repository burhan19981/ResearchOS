"""Analysis record schemas.

`result`/`parameters` are opaque, structured JSON exactly as
`researchos.analysis` computed and persisted them — this layer adds
no interpretation on top. A `NOT_COMPARABLE` record's `result` already
contains `{"comparable": false, "reasons": [...]}`; the frontend must
render those reasons verbatim rather than attempting to reinterpret or
"fix" the comparison (Phase 8 spec section 16 / Dashboard V1 spec
section 16).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalysisInputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_type: str
    input_id: int


class AnalysisRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    method: str
    parameters: dict[str, Any] | None
    result: dict[str, Any]
    status: str
    version: int
    supersedes_id: int | None
    software_versions: dict[str, Any] | None
    created_at: datetime
    inputs: list[AnalysisInputResponse] = []
