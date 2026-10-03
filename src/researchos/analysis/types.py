"""Data types for the analysis & scientific review layer. Pure
dataclasses — no I/O, no database, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ComparabilityResult:
    """The outcome of `researchos.analysis.comparability.check_comparability`
    — never a guess. `comparable=False` always carries at least one
    structured reason (Phase 8 spec section 12): "the system cannot
    establish comparability" is itself the answer, not a fallback."""

    comparable: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisContext:
    """A bounded, explicit context assembled from explicitly-given
    `AnalysisRecord` ids for one LLM claim-generation call — mirrors
    `researchos.planning.types.PlanningContext`. `prompt_json` is built
    entirely from already-persisted `AnalysisRecord` rows, never a bare
    id; `allowed_analysis_record_ids` is the set
    `researchos.analysis.validation` checks any model-cited
    `supporting_analysis_record_ids` entry against."""

    prompt_json: dict[str, Any]
    allowed_analysis_record_ids: frozenset[int] = frozenset()
    upstream_snapshots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewContext:
    """A bounded, explicit context assembled from one `ScientificClaim`
    and its already-linked `AnalysisRecord` evidence, for one LLM
    scientific-review-generation call."""

    prompt_json: dict[str, Any]
    allowed_analysis_record_ids: frozenset[int] = frozenset()
    upstream_snapshots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimGenerationOutcome:
    claim_ids: list[int]
    rejected_count: int


@dataclass(frozen=True)
class ReviewGenerationOutcome:
    review_id: int
