"""OpenAlex adapter.

API docs: https://docs.openalex.org (public, no API key required; a
`mailto` contact param is OpenAlex's documented "polite pool" courtesy
identifier for higher rate limits — configured via
`OPENALEX_CONTACT_EMAIL`, never required).

Field mapping was implemented from OpenAlex's well-established, public
Works API schema. No real network call was made or is permitted in this
phase (see docs/PHASE5_EVIDENCE.md) — this should be smoke-tested
against the live API before production use, the same way Phase 2
verified installed-SDK shapes before trusting them.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..config import SourceConfig, load_openalex_config
from ..errors import SourceNotFoundError, SourceResponseError
from ..normalization import compute_metadata_completeness, normalize_doi, reconstruct_openalex_abstract
from ..types import NormalizedRecord, PageInfo, RecordStatus, SearchFilters, SearchResult
from .base import SourceAdapter


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class OpenAlexAdapter(SourceAdapter):
    def __init__(self, **kwargs: Any) -> None:
        config: SourceConfig = kwargs.pop("config", None) or load_openalex_config()
        super().__init__(config, **kwargs)

    @property
    def source_name(self) -> str:
        return "openalex"

    def _mailto_params(self) -> dict[str, Any]:
        return {"mailto": self._config.contact_email} if self._config.contact_email else {}

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
        params: dict[str, Any] = {"search": query, "page": page, "per_page": min(page_size, 200)}
        params.update(self._mailto_params())

        filter_parts: list[str] = []
        if filters.year_from is not None:
            filter_parts.append(f"from_publication_date:{filters.year_from}-01-01")
        if filters.year_to is not None:
            filter_parts.append(f"to_publication_date:{filters.year_to}-12-31")
        if filters.author:
            filter_parts.append(f"authorships.author.display_name.search:{filters.author}")
        if filters.venue:
            filter_parts.append(f"primary_location.source.display_name.search:{filters.venue}")
        if filters.doi:
            filter_parts.append(f"doi:{normalize_doi(filters.doi) or filters.doi}")
        if filters.document_type:
            filter_parts.append(f"type:{filters.document_type}")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)

        data = self._get_json(f"{self._config.base_url}/works", params=params, operation="search")
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise SourceResponseError("openalex: search response missing a 'results' list.")

        records = [self.normalize(item) for item in raw_results]
        meta = data.get("meta") or {}
        total = meta.get("count")
        has_more = total is not None and page * page_size < total
        page_info = PageInfo(page=page, page_size=page_size, total=total, has_more=bool(has_more))
        return SearchResult(source=self.source_name, records=records, page_info=page_info, query=query, filters=filters)

    def get_by_id(self, source_record_id: str) -> Optional[NormalizedRecord]:
        try:
            data = self._get_json(
                f"{self._config.base_url}/works/{source_record_id}",
                params=self._mailto_params(),
                operation="get_by_id",
            )
        except SourceNotFoundError:
            return None
        return self.normalize(data)

    def normalize(self, raw: dict[str, Any]) -> NormalizedRecord:
        title = raw.get("title") or raw.get("display_name")
        if not title:
            raise SourceResponseError("openalex: record has no title; cannot normalize.")

        openalex_id = raw.get("id") or ""
        source_record_id = openalex_id.rsplit("/", 1)[-1] if openalex_id else str(raw.get("source_record_id", ""))

        authors = [
            authorship["author"]["display_name"]
            for authorship in raw.get("authorships") or []
            if authorship.get("author", {}).get("display_name")
        ]

        primary_location = raw.get("primary_location") or {}
        source_info = primary_location.get("source") or {}
        host_venue = raw.get("host_venue") or {}
        venue = source_info.get("display_name") or host_venue.get("display_name")
        publisher = source_info.get("host_organization_name") or host_venue.get("publisher")
        url = primary_location.get("landing_page_url") or (f"https://openalex.org/{source_record_id}" if source_record_id else None)

        doi = normalize_doi(raw.get("doi"))
        abstract = reconstruct_openalex_abstract(raw.get("abstract_inverted_index"))
        keywords = [c["display_name"] for c in raw.get("concepts") or [] if c.get("display_name")]

        external_ids: dict[str, str] = {}
        for key, value in (raw.get("ids") or {}).items():
            if key == "openalex" or not value:
                continue
            if key == "doi":
                normalized = normalize_doi(value)
                if normalized:
                    external_ids["doi"] = normalized
            else:
                external_ids[key] = str(value).rsplit("/", 1)[-1]

        fields = dict(
            title=title, authors=authors, year=raw.get("publication_year"), venue=venue, doi=doi, url=url,
            abstract=abstract, document_type=raw.get("type"),
        )
        completeness = compute_metadata_completeness(fields)

        return NormalizedRecord(
            source=self.source_name,
            source_record_id=source_record_id,
            title=title,
            authors=authors,
            year=raw.get("publication_year"),
            publication_date=_parse_iso_date(raw.get("publication_date")),
            venue=venue,
            publisher=publisher,
            doi=doi,
            url=url,
            abstract=abstract,
            document_type=raw.get("type"),
            citation_count=raw.get("cited_by_count"),
            keywords=keywords,
            external_ids=external_ids,
            raw_metadata=raw,
            record_status=RecordStatus.VERIFIED_SOURCE_RECORD if completeness >= 0.5 else RecordStatus.PARTIAL_METADATA,
            metadata_completeness=completeness,
        )
