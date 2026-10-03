"""Novelty assessment schemas.

`candidate_status` (`NoveltyCandidateStatus`) is the non-authoritative
vocabulary the dashboard must display — CANDIDATE / PENDING_REVIEW /
INSUFFICIENT_EVIDENCE / HUMAN_APPROVED, never a bare "confirmed" claim
the underlying domain does not itself assert. The legacy `status`
field (`NoveltyStatus`) is included for completeness but the frontend
must not present it as the authoritative signal — see
docs/PHASE_DASHBOARD_V1.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NoveltyAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    claim: str
    status: str
    candidate_status: str
    confidence: float | None
    novelty_risk: str | None
    unresolved_questions: str | None
    research_question_id: int | None
    contribution_candidate_id: int | None
