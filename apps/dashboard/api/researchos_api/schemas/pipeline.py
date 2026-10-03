"""Research pipeline (workflow stage) visualization schemas.

A pure read-projection of `researchos.workflow`'s real, existing state
machine — this package never re-implements stage ordering or
transition policy; it only reports what
`researchos.workflow.service`/`researchos.workflow.stages` already
compute.
"""

from __future__ import annotations

from pydantic import BaseModel


class PipelineStage(BaseModel):
    stage: str
    order: int
    is_current: bool
    is_completed: bool
    """True for every stage strictly before the current one in
    canonical order — a visualization convenience, not a new status
    concept: ResearchOS itself has no per-stage "completed" flag,
    only a single `current_stage` pointer, and this field is computed
    purely from `STAGE_ORDER`'s position relative to that pointer."""


class AllowedTransition(BaseModel):
    target_stage: str
    policy: str
    direction: str


class PipelineResponse(BaseModel):
    project_id: int
    project_status: str
    current_stage: str
    stages: list[PipelineStage]
    allowed_transitions: list[AllowedTransition]
