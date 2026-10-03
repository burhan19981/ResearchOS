"""Provider-agnostic data types for the evidence/literature layer.

`RecordStatus` is imported from `researchos.db.models` (not duplicated)
since it is written directly into `LiteratureItem.record_status` —
persistence is an expected, required dependency of this layer (the
architecture's own diagram ends in "Persistent Research Database").
Only `researchos.llm` is off-limits, per the Phase 5 independence
requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from ..db.models import RecordStatus

__all__ = [
    "RecordStatus",
    "NormalizedRecord",
    "SearchFilters",
    "PageInfo",
    "SearchResult",
    "AdapterHealth",
]


@dataclass(frozen=True)
class NormalizedRecord:
    """A scholarly record normalized from one source's raw response.

    Every field is either exactly what the source supplied (after safe,
    lossless normalization — e.g. DOI casing/prefix stripping) or `None`
    / an empty collection when the source did not supply it. Nothing in
    this layer invents a value for a missing field.
    """

    source: str
    source_record_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    # Populated only when the source supplied a full year-month-day date.
    publication_date: Optional[date] = None
    venue: Optional[str] = None
    publisher: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    document_type: Optional[str] = None
    citation_count: Optional[int] = None
    keywords: list[str] = field(default_factory=list)
    # Other sources' identifiers for the same paper, as mentioned in
    # this source's own metadata (e.g. an OpenAlex record's embedded
    # DOI/PMID/MAG id) — used for cross-source duplicate detection.
    external_ids: dict[str, str] = field(default_factory=dict)
    # The (safely trimmed) raw source payload this record was built from.
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    retrieved_at: datetime = field(default_factory=lambda: datetime.now())
    record_status: RecordStatus = RecordStatus.VERIFIED_SOURCE_RECORD
    metadata_completeness: float = 0.0


@dataclass(frozen=True)
class SearchFilters:
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    author: Optional[str] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    source: Optional[str] = None
    document_type: Optional[str] = None


@dataclass(frozen=True)
class PageInfo:
    """Pagination state for one page of search results.

    Exactly one of (`page`, `cursor`) is meaningful for a given source —
    offset-paginated sources (Crossref, Semantic Scholar, arXiv) use
    `page`; cursor-paginated sources (OpenAlex, optionally) use `cursor`.
    `total` is `None` when the source does not report a total count —
    callers must not assume `has_more is False` just because `total`
    is unknown.
    """

    page: int
    page_size: int
    total: Optional[int]
    has_more: bool
    cursor: Optional[str] = None


@dataclass(frozen=True)
class SearchResult:
    source: str
    records: list[NormalizedRecord]
    page_info: PageInfo
    query: str
    filters: SearchFilters


@dataclass(frozen=True)
class AdapterHealth:
    source: str
    configured: bool
    base_url: str
    detail: Optional[str] = None
