"""Data types for the research intelligence layer's evidence packages and
parsed LLM responses. Pure dataclasses — no I/O, no database, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# The 13 literature-analysis dimensions from the Phase 6 spec. A missing
# dimension value must be the literal string "unknown" — never omitted,
# never guessed from the model's outside knowledge.
ANALYSIS_DIMENSIONS: tuple[str, ...] = (
    "research_topic",
    "problem_addressed",
    "task",
    "dataset",
    "methodology",
    "model_architecture",
    "evaluation_metrics",
    "reported_limitations",
    "stated_future_work",
    "contribution_type",
    "domain_application",
    "key_findings",
    "evidence_limitations",
)

UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidencePackageItem:
    """Exactly the fields the Phase 6 spec allows into an evidence
    package — a deliberately narrow projection of `LiteratureItem`, never
    the raw ORM row or its full `raw_metadata`."""

    literature_item_id: int
    source: Optional[str]
    source_record_id: Optional[str]
    title: str
    authors: list[str]
    year: Optional[int]
    publication_date: Optional[str]
    venue: Optional[str]
    doi: Optional[str]
    abstract: Optional[str]
    citation_count: Optional[int]
    keywords: list[str]
    metadata_completeness: Optional[float]
    evidence_status: str
    retrieved_at: Optional[str]
    url: Optional[str]
    abstract_truncated: bool = False

    def to_prompt_dict(self) -> dict[str, Any]:
        """The exact JSON shape sent to the LLM for this item."""
        return {
            "literature_item_id": self.literature_item_id,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "publication_date": self.publication_date,
            "venue": self.venue,
            "doi": self.doi,
            "abstract": self.abstract,
            "abstract_truncated": self.abstract_truncated,
            "citation_count": self.citation_count,
            "keywords": self.keywords,
            "provenance": {
                "source": self.source,
                "source_record_id": self.source_record_id,
                "retrieved_at": self.retrieved_at,
                "url": self.url,
            },
            "metadata_completeness": self.metadata_completeness,
            "evidence_status": self.evidence_status,
        }


@dataclass(frozen=True)
class EvidencePackage:
    """A bounded, deterministic selection of evidence for one LLM call.

    `requested_item_ids` is what the caller asked for; `items` is what
    actually made it in after deterministic ranking/truncation.
    `truncated` and `excluded_item_ids` make the omission explicit —
    never silent, per the Phase 6 spec's cost/context-control section.
    """

    requested_item_ids: list[int]
    items: list[EvidencePackageItem]
    truncated: bool
    excluded_item_ids: list[int]
    max_items: int
    max_abstract_chars: int

    @property
    def included_item_ids(self) -> list[int]:
        return [item.literature_item_id for item in self.items]

    def to_prompt_json_ready(self) -> dict[str, Any]:
        return {
            "evidence": [item.to_prompt_dict() for item in self.items],
            "truncated": self.truncated,
            "excluded_item_count": len(self.excluded_item_ids),
        }


@dataclass(frozen=True)
class ParsedClaim:
    claim_text: str
    claim_type: Optional[str]
    support_level: str
    evidence_item_ids: list[int]
    confidence: Optional[float]
    uncertainty: Optional[str]


@dataclass(frozen=True)
class LiteratureAnalysisOutcome:
    analysis_id: int
    result: dict[str, Any]
    claim_ids: list[int]
    rejected_claim_count: int
    truncated: bool


@dataclass(frozen=True)
class GapCandidateOutcome:
    gap_ids: list[int]
    rejected_candidate_count: int


@dataclass(frozen=True)
class NoveltyAnalysisOutcome:
    assessment_id: int
    comparison_ids: list[int]
    rejected_comparison_count: int
