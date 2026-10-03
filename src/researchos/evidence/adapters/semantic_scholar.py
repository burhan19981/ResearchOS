"""Semantic Scholar (Graph API) adapter.

API docs: https://api.semanticscholar.org/api-docs/graph (public; an
optional API key raises rate limits — configured via
`SEMANTIC_SCHOLAR_API_KEY`, sent as the `x-api-key` header, never
required or embedded in a URL/cache key).

Semantic Scholar's `externalIds` bundle (DOI/ArXiv/PubMed/MAG/...) is a
particularly strong cross-source dedup signal — normalized into
`NormalizedRecord.external_ids` with lowercased key names for
consistency with the OpenAlex adapter's `ids` handling.

Field mapping implemented from Semantic Scholar's well-established,
public Graph API schema — not verified against a live response in this
phase (no real network calls were made or are permitted here);
recommend a smoke-test before production use.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..config import SourceConfig, load_semantic_scholar_config
from ..errors import SourceNotFoundError, SourceResponseError
from ..normalization import compute_metadata_completeness, normalize_doi
from ..types import NormalizedRecord, PageInfo, RecordStatus, SearchFilters, SearchResult
from .base import SourceAdapter

_FIELDS = (
    "title,abstract,year,venue,publicationDate,authors,externalIds,url,"
    "citationCount,publicationTypes,fieldsOfStudy,publicationVenue"
)

_EXTERNAL_ID_KEY_MAP = {
    "DOI": "doi",
    "ArXiv": "arxiv",
    "PubMed": "pubmed",
    "PubMedCentral": "pubmedcentral",
    "MAG": "mag",
    "DBLP": "dblp",
    "CorpusId": "corpusid",
}


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class SemanticScholarAdapter(SourceAdapter):
    def __init__(self, **kwargs: Any) -> None:
        config: SourceConfig = kwargs.pop("config", None) or load_semantic_scholar_config()
        super().__init__(config, **kwargs)

    @property
    def source_name(self) -> str:
        return "semantic_scholar"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._config.api_key} if self._config.api_key else {}

    def search(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        *,
        page: int = 1,
        page_size: int = 25,
        cursor: Optional[str] = None,
    ) -> SearchResult:
        filters = filters or SearchFilters()
        offset = (page - 1) * page_size
        params: dict[str, Any] = {"query": query, "offset": offset, "limit": page_size, "fields": _FIELDS}

        if filters.year_from is not None or filters.year_to is not None:
            low = filters.year_from if filters.year_from is not None else ""
            high = filters.year_to if filters.year_to is not None else ""
            params["year"] = f"{low}-{high}" if (low or high) else None
        if filters.venue:
            params["venue"] = filters.venue

        data = self._get_json(
            f"{self._config.base_url}/paper/search", params=params, headers=self._headers(), operation="search"
        )
        raw_data = data.get("data")
        if not isinstance(raw_data, list):
            raise SourceResponseError("semantic_scholar: search response missing a 'data' list.")

        records = [self.normalize(item) for item in raw_data]
        total = data.get("total")
        has_more = data.get("next") is not None if "next" in data else (
            total is not None and offset + len(records) < total
        )
        page_info = PageInfo(page=page, page_size=page_size, total=total, has_more=bool(has_more))
        return SearchResult(source=self.source_name, records=records, page_info=page_info, query=query, filters=filters)

    def get_by_id(self, source_record_id: str) -> Optional[NormalizedRecord]:
        try:
            data = self._get_json(
                f"{self._config.base_url}/paper/{source_record_id}",
                params={"fields": _FIELDS},
                headers=self._headers(),
                operation="get_by_id",
            )
        except SourceNotFoundError:
            return None
        return self.normalize(data)

    def normalize(self, raw: dict[str, Any]) -> NormalizedRecord:
        title = raw.get("title")
        if not title:
            raise SourceResponseError("semantic_scholar: record has no title; cannot normalize.")

        source_record_id = str(raw.get("paperId") or "")
        authors = [a["name"] for a in raw.get("authors") or [] if a.get("name")]

        publication_venue = raw.get("publicationVenue") or {}
        venue = publication_venue.get("name") or raw.get("venue")
        publisher = publication_venue.get("publisher")

        external_ids_raw = raw.get("externalIds") or {}
        doi = normalize_doi(external_ids_raw.get("DOI"))
        external_ids: dict[str, str] = {}
        for key, value in external_ids_raw.items():
            if not value:
                continue
            mapped_key = _EXTERNAL_ID_KEY_MAP.get(key, key.lower())
            if mapped_key == "doi":
                normalized = normalize_doi(str(value))
                if normalized:
                    external_ids["doi"] = normalized
            else:
                external_ids[mapped_key] = str(value)

        document_types = raw.get("publicationTypes") or []
        document_type = document_types[0] if document_types else None
        keywords = raw.get("fieldsOfStudy") or []

        fields = dict(
            title=title, authors=authors, year=raw.get("year"), venue=venue, doi=doi, url=raw.get("url"),
            abstract=raw.get("abstract"), document_type=document_type,
        )
        completeness = compute_metadata_completeness(fields)

        return NormalizedRecord(
            source=self.source_name,
            source_record_id=source_record_id,
            title=title,
            authors=authors,
            year=raw.get("year"),
            publication_date=_parse_iso_date(raw.get("publicationDate")),
            venue=venue,
            publisher=publisher,
            doi=doi,
            url=raw.get("url"),
            abstract=raw.get("abstract"),
            document_type=document_type,
            citation_count=raw.get("citationCount"),
            keywords=list(keywords),
            external_ids=external_ids,
            raw_metadata=raw,
            record_status=RecordStatus.VERIFIED_SOURCE_RECORD if completeness >= 0.5 else RecordStatus.PARTIAL_METADATA,
            metadata_completeness=completeness,
        )
