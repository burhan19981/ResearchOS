"""Run / artifact / metric / environment schemas.

Statuses are read verbatim from the existing `RunStatus` lifecycle —
this layer invents no new execution status and never labels a run
"best" or "winner" (that judgment belongs exclusively to the Analysis
layer's own, explicitly non-authoritative comparison machinery; see
schemas/analysis.py).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EnvironmentSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    os_name: str | None
    os_version: str | None
    architecture: str | None
    python_version: str | None
    pytorch_version: str | None
    cuda_version: str | None
    gpu_name: str | None
    cpu_model: str | None
    cpu_count: int | None
    total_memory_bytes: int | None
    researchos_version: str | None


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    logical_name: str
    artifact_type: str
    reference: str
    size_bytes: int | None
    content_hash: str | None
    mime_type: str | None
    source: str | None
    description: str | None
    created_at: datetime


class MetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    name: str
    value: float
    value_type: str
    unit: str | None
    split: str | None
    aggregation: str | None
    source: str | None
    created_at: datetime


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    experiment_id: int
    experiment_specification_id: int | None
    dataset_version_id: int | None
    status: str
    execution_backend: str
    configuration_hash: str | None
    dataset_fingerprint: str | None
    code_repository: str | None
    code_commit: str | None
    code_branch: str | None
    working_tree_clean: bool | None
    seed: int | None
    timeout_seconds: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    exit_code: int | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    environment: EnvironmentSnapshotResponse | None = None
    artifacts: list[ArtifactResponse] = []
    metrics: list[MetricResponse] = []
