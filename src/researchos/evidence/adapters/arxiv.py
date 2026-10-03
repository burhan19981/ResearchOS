"""arXiv adapter.

API docs: https://info.arxiv.org/help/api/user-manual.html (public, no
API key or contact identifier required or supported). Returns an Atom
XML feed, parsed here with the standard library's `xml.etree.ElementTree`
— no new dependency.

Known arXiv API quirk handled explicitly: an unknown id in `get_by_id()`
does **not** come back as an HTTP 404 — arXiv returns a normal 200 OK
feed containing a single `<entry>` whose `<id>` is under
`http://arxiv.org/api/errors#...`. This adapter detects that specific
shape and returns `None`, exactly as it would for a real 404 from
another source.

Field mapping implemented from arXiv's well-established, public Atom
API schema — not verified against a live response in this phase (no
real network calls were made or are permitted here); recommend a
smoke-test before production use.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any, Optional

from ..config import SourceConfig, load_arxiv_config
from ..errors import SourceResponseError, UnsupportedFilterError
from ..normalization import compute_metadata_completeness, normalize_doi
from ..types import NormalizedRecord, PageInfo, RecordStatus, SearchFilters, SearchResult
from .base import SourceAdapter

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_VERSION_SUFFIX = re.compile(r"v\d+$")


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _find_text(element: ET.Element, path: str) -> Optional[str]:
    found = element.find(path, _NS)
    return _clean_text(found.text) if found is not None else None


class ArxivAdapter(SourceAdapter):
    def __init__(self, **kwargs: Any) -> None:
        config: SourceConfig = kwargs.pop("config", None) or load_arxiv_config()
        super().__init__(config, **kwargs)

    @property
    def source_name(self) -> str:
        return "arxiv"

    def _build_search_query(self, query: str, filters: SearchFilters) -> str:
        parts = [f"all:{query}"]
        if filters.author:
            parts.append(f"AND au:{filters.author}")
        if filters.year_from is not None or filters.year_to is not None:
            low = f"{filters.year_from}0101000000" if filters.year_from is not None else "00000101000000"
            high = f"{filters.year_to}1231235959" if filters.year_to is not None else "99991231235959"
            parts.append(f"AND submittedDate:[{low} TO {high}]")
        if filters.venue:
            raise UnsupportedFilterError("arxiv: does not support filtering by venue (preprints have no venue).")
        if filters.doi:
            raise UnsupportedFilterError("arxiv: does not support filtering by DOI in search queries.")
        if filters.document_type:
            raise UnsupportedFilterError("arxiv: every record is a preprint; document_type filtering is not meaningful.")
        return " ".join(parts)

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
        start = (page - 1) * page_size
        search_query = self._build_search_query(query, filters)
        params = {"search_query": search_query, "start": start, "max_results": page_size}

        text = self._get_text(self._config.base_url, params=params, operation="search")
        root = self._parse_feed(text)

        entries = root.findall("atom:entry", _NS)
        records = [self.normalize(self._entry_to_dict(entry)) for entry in entries if not self._is_error_entry(entry)]

        total_text = _find_text(root, "opensearch:totalResults")
        total = int(total_text) if total_text and total_text.isdigit() else None
        has_more = total is not None and start + len(records) < total
        page_info = PageInfo(page=page, page_size=page_size, total=total, has_more=bool(has_more))
        return SearchResult(source=self.source_name, records=records, page_info=page_info, query=query, filters=filters)

    def get_by_id(self, source_record_id: str) -> Optional[NormalizedRecord]:
        text = self._get_text(self._config.base_url, params={"id_list": source_record_id}, operation="get_by_id")
        root = self._parse_feed(text)
        entries = root.findall("atom:entry", _NS)
        if not entries or self._is_error_entry(entries[0]):
            return None
        return self.normalize(self._entry_to_dict(entries[0]))

    def _parse_feed(self, text: str) -> ET.Element:
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise SourceResponseError("arxiv: response was not valid XML.") from exc

    def _is_error_entry(self, entry: ET.Element) -> bool:
        entry_id = _find_text(entry, "atom:id") or ""
        return "arxiv.org/api/errors" in entry_id

    def _entry_to_dict(self, entry: ET.Element) -> dict[str, Any]:
        """Flatten one <entry> into a plain dict — this *is* the adapter's
        'raw' representation, preserved in full as `raw_metadata`."""
        links = entry.findall("atom:link", _NS)
        alternate_url = next((l.get("href") for l in links if l.get("rel") == "alternate"), None)
        categories = [c.get("term") for c in entry.findall("atom:category", _NS) if c.get("term")]
        return {
            "id": _find_text(entry, "atom:id"),
            "title": _find_text(entry, "atom:title"),
            "summary": _find_text(entry, "atom:summary"),
            "published": _find_text(entry, "atom:published"),
            "updated": _find_text(entry, "atom:updated"),
            "authors": [_clean_text(a.text) for a in entry.findall("atom:author/atom:name", _NS) if a.text],
            "doi": _find_text(entry, "arxiv:doi"),
            "journal_ref": _find_text(entry, "arxiv:journal_ref"),
            "categories": categories,
            "url": alternate_url,
        }

    def normalize(self, raw: dict[str, Any]) -> NormalizedRecord:
        title = raw.get("title")
        if not title:
            raise SourceResponseError("arxiv: record has no title; cannot normalize.")

        entry_id = raw.get("id") or ""
        source_record_id = entry_id.rsplit("/", 1)[-1] if entry_id else ""
        base_arxiv_id = _VERSION_SUFFIX.sub("", source_record_id) if source_record_id else None

        published = raw.get("published")
        publication_date = None
        year = None
        if published:
            try:
                parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
                publication_date = date(parsed.year, parsed.month, parsed.day)
                year = parsed.year
            except ValueError:
                pass

        doi = normalize_doi(raw.get("doi"))
        authors = list(raw.get("authors") or [])
        keywords = list(raw.get("categories") or [])
        url = raw.get("url") or (entry_id or None)

        fields = dict(
            title=title, authors=authors, year=year, venue=raw.get("journal_ref"), doi=doi, url=url,
            abstract=raw.get("summary"), document_type="preprint",
        )
        completeness = compute_metadata_completeness(fields)

        external_ids: dict[str, str] = {}
        if base_arxiv_id:
            external_ids["arxiv"] = base_arxiv_id
        if doi:
            external_ids["doi"] = doi

        return NormalizedRecord(
            source=self.source_name,
            source_record_id=source_record_id,
            title=title,
            authors=authors,
            year=year,
            publication_date=publication_date,
            venue=raw.get("journal_ref"),
            publisher=None,
            doi=doi,
            url=url,
            abstract=raw.get("summary"),
            document_type="preprint",
            citation_count=None,  # arXiv's API does not provide citation counts
            keywords=keywords,
            external_ids=external_ids,
            raw_metadata=raw,
            record_status=RecordStatus.VERIFIED_SOURCE_RECORD if completeness >= 0.5 else RecordStatus.PARTIAL_METADATA,
            metadata_completeness=completeness,
        )
