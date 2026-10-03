"""Crossref adapter.

API docs: https://api.crossref.org/swagger-ui/index.html (public, no API
key; a `mailto` contact param is Crossref's documented "polite pool"
courtesy identifier for higher rate limits — configured via
`CROSSREF_CONTACT_EMAIL`, never required). Crossref's primary
identifier for a work *is* its DOI — there is no separate internal id,
so `source_record_id` is always the normalized DOI here.

Known limitation: Crossref rarely returns an `abstract` field for most
records (a long-standing, well-known gap in Crossref's own data, not
this adapter) — expect `abstract=None` far more often than with
OpenAlex or Semantic Scholar. Crossref also has no structured
cross-source identifier bundle (unlike OpenAlex's `ids`), so
`external_ids` is typically empty for Crossref-sourced records.

Field mapping implemented from Crossref's well-established, public REST
API schema — not verified against a live response in this phase (no
real network calls were made or are permitted here); recommend a
smoke-test before production use.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..config import SourceConfig, load_crossref_config
from ..errors import SourceNotFoundError, SourceResponseError
from ..normalization import compute_metadata_completeness, normalize_doi, strip_simple_xml_tags
from ..types import NormalizedRecord, PageInfo, RecordStatus, SearchFilters, SearchResult
from .base import SourceAdapter


def _extract_date(item: dict[str, Any]) -> tuple[Optional[int], Optional[date]]:
    for field_name in ("published", "published-print", "published-online", "issued"):
        parts_container = item.get(field_name)
        if not parts_container:
            continue
        date_parts = (parts_container.get("date-parts") or [[]])[0]
        if not date_parts:
            continue
        year = date_parts[0]
        if len(date_parts) >= 3:
            try:
                return year, date(date_parts[0], date_parts[1], date_parts[2])
            except ValueError:
                return year, None
        return year, None
    return None, None


def _author_display_name(author: dict[str, Any]) -> Optional[str]:
    given = author.get("given")
    family = author.get("family")
    if given and family:
        return f"{given} {family}"
    return family or given or author.get("name")


class CrossrefAdapter(SourceAdapter):
    def __init__(self, **kwargs: Any) -> None:
        config: SourceConfig = kwargs.pop("config", None) or load_crossref_config()
        super().__init__(config, **kwargs)

    @property
    def source_name(self) -> str:
        return "crossref"

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
        offset = (page - 1) * page_size
        params: dict[str, Any] = {"query": query, "rows": page_size, "offset": offset}
        params.update(self._mailto_params())

        if filters.author:
            params["query.author"] = filters.author
        if filters.venue:
            params["query.container-title"] = filters.venue

        filter_parts: list[str] = []
        if filters.year_from is not None:
            filter_parts.append(f"from-pub-date:{filters.year_from}-01-01")
        if filters.year_to is not None:
            filter_parts.append(f"until-pub-date:{filters.year_to}-12-31")
        if filters.document_type:
            filter_parts.append(f"type:{filters.document_type}")
        if filters.doi:
            # Best-effort: Crossref's /works search does not officially
            # document DOI as a `filter` key; kept for parity with other
            # adapters and harmless if the source ignores/rejects it.
            filter_parts.append(f"doi:{normalize_doi(filters.doi) or filters.doi}")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)

        data = self._get_json(f"{self._config.base_url}/works", params=params, operation="search")
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
            raise SourceResponseError("crossref: search response missing 'message.items'.")

        records = [self.normalize(item) for item in message["items"]]
        total = message.get("total-results")
        has_more = total is not None and offset + len(records) < total
        page_info = PageInfo(page=page, page_size=page_size, total=total, has_more=bool(has_more))
        return SearchResult(source=self.source_name, records=records, page_info=page_info, query=query, filters=filters)

    def get_by_id(self, source_record_id: str) -> Optional[NormalizedRecord]:
        doi = normalize_doi(source_record_id) or source_record_id
        try:
            data = self._get_json(
                f"{self._config.base_url}/works/{doi}", params=self._mailto_params(), operation="get_by_id"
            )
        except SourceNotFoundError:
            return None
        message = data.get("message")
        if not isinstance(message, dict):
            raise SourceResponseError("crossref: get_by_id response missing 'message'.")
        return self.normalize(message)

    def normalize(self, raw: dict[str, Any]) -> NormalizedRecord:
        titles = raw.get("title") or []
        title = titles[0] if titles else None
        if not title:
            raise SourceResponseError("crossref: record has no title; cannot normalize.")

        doi = normalize_doi(raw.get("DOI"))
        source_record_id = doi or str(raw.get("DOI") or "")

        authors = [name for name in (_author_display_name(a) for a in raw.get("author") or []) if name]
        year, publication_date = _extract_date(raw)
        venue = (raw.get("container-title") or [None])[0]
        abstract = strip_simple_xml_tags(raw.get("abstract"))
        keywords = raw.get("subject") or []

        fields = dict(
            title=title, authors=authors, year=year, venue=venue, doi=doi, url=raw.get("URL"),
            abstract=abstract, document_type=raw.get("type"),
        )
        completeness = compute_metadata_completeness(fields)

        return NormalizedRecord(
            source=self.source_name,
            source_record_id=source_record_id,
            title=title,
            authors=authors,
            year=year,
            publication_date=publication_date,
            venue=venue,
            publisher=raw.get("publisher"),
            doi=doi,
            url=raw.get("URL"),
            abstract=abstract,
            document_type=raw.get("type"),
            citation_count=raw.get("is-referenced-by-count"),
            keywords=list(keywords),
            external_ids={},
            raw_metadata=raw,
            record_status=RecordStatus.VERIFIED_SOURCE_RECORD if completeness >= 0.5 else RecordStatus.PARTIAL_METADATA,
            metadata_completeness=completeness,
        )
