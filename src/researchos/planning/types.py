"""Data types for the research planning layer's context packages and
generation outcomes. Pure dataclasses — no I/O, no database, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlanningContext:
    """A bounded, explicit context assembled from approved upstream
    planning artifacts (and, where applicable, the `LiteratureItem`
    evidence linked to them) for one LLM planning call.

    `prompt_json` is the exact JSON handed to the model — built entirely
    from approved content, never a bare id. `allowed_*_ids` are the sets
    `researchos.planning.validation` checks any model-cited id against;
    an id outside these sets is rejected, never silently trusted.
    `upstream_snapshots` records, for each upstream artifact this
    context was built from, its id/version/status at context-build time
    (Phase 7 spec section 15) — callers persist this verbatim onto the
    generated downstream row(s) so a reviewer can always reconstruct
    exactly what was approved when a plan was generated, even if the
    upstream artifact is later revised or rejected.
    """

    prompt_json: dict[str, Any]
    allowed_literature_item_ids: frozenset[int] = frozenset()
    allowed_research_question_ids: frozenset[int] = frozenset()
    upstream_snapshots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchQuestionGenerationOutcome:
    question_ids: list[int]
    rejected_count: int


@dataclass(frozen=True)
class ContributionGenerationOutcome:
    contribution_ids: list[int]
    rejected_count: int


@dataclass(frozen=True)
class MethodologyGenerationOutcome:
    methodology_plan_id: int


@dataclass(frozen=True)
class DatasetRequirementsGenerationOutcome:
    dataset_requirements_id: int


@dataclass(frozen=True)
class ExperimentalDesignGenerationOutcome:
    experimental_design_id: int
