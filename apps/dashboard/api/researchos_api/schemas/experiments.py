"""Experiment schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    dataset_record_id: int
    version: int
    lifecycle_status: str
    description: str | None
    sample_count: int | None
    content_fingerprint: str | None


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None
    status: str
    code_version: str | None
    dataset_version: str | None
    random_seed: int | None
    hardware: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    run_count: int
    specification_count: int
