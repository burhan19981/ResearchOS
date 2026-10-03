"""The ResearchOS evidence/literature layer: retrieval, normalization,
deduplication, and persistence of bibliographic records from external
scholarly sources (OpenAlex, Crossref, Semantic Scholar, arXiv).

**Independent of `researchos.llm`** — nothing in this package imports
it, and nothing here treats an LLM as an authoritative source of
bibliographic facts. LLMs may, in a future phase, *analyze* evidence
already retrieved and persisted here — they never originate it.

```python
from researchos.evidence import search_literature, SearchFilters

outcome = search_literature(
    project_id, "openalex", "graph neural networks",
    filters=SearchFilters(year_from=2020), actor="agent:lit-bot",
)
for item in outcome.persisted_items:
    print(item.title, item.doi, item.record_status)
```

See `docs/PHASE5_EVIDENCE.md` for the full architecture, provenance,
deduplication, and testing design.
"""

from .adapters import SourceAdapter, available_sources, get_adapter
from .errors import (
    EvidenceError,
    SourceConfigurationError,
    SourceNotFoundError,
    SourceRateLimitError,
    SourceResponseError,
    SourceTimeoutError,
    SourceUnavailableError,
    UnsupportedFilterError,
)
from .service import GetByIdOutcome, LiteratureSearchOutcome, get_literature_by_id, search_literature
from .types import AdapterHealth, NormalizedRecord, PageInfo, RecordStatus, SearchFilters, SearchResult

__all__ = [
    # adapters
    "SourceAdapter",
    "get_adapter",
    "available_sources",
    # service
    "search_literature",
    "get_literature_by_id",
    "LiteratureSearchOutcome",
    "GetByIdOutcome",
    # types
    "NormalizedRecord",
    "SearchFilters",
    "PageInfo",
    "SearchResult",
    "AdapterHealth",
    "RecordStatus",
    # errors
    "EvidenceError",
    "SourceConfigurationError",
    "SourceTimeoutError",
    "SourceRateLimitError",
    "SourceUnavailableError",
    "SourceResponseError",
    "SourceNotFoundError",
    "UnsupportedFilterError",
]
