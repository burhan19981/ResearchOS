"""Overview page schema — project identity + real database counts.

Every count here is a `len(...)` over an actual repository list call
for the selected project. There is no hard-coded or placeholder
number anywhere in this module — a project with no experiments yet
reports `experiments=0`, and the frontend is responsible for the
honest empty-state copy ("No experiments have been created yet."),
never a fabricated example value.
"""

from __future__ import annotations

from pydantic import BaseModel

from .project import ProjectResponse


class OverviewCounts(BaseModel):
    literature_items: int
    research_gaps: int
    novelty_assessments: int
    research_questions: int
    contribution_candidates: int
    experiments: int
    runs: int
    metrics: int
    analysis_records: int
    scientific_claims: int
    scientific_reviews: int
    pending_approvals: int


class OverviewResponse(BaseModel):
    project: ProjectResponse
    current_stage: str
    counts: OverviewCounts
