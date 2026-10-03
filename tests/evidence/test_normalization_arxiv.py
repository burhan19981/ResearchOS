"""Test #5: arXiv normalization.

`normalize()` takes the flattened dict `_entry_to_dict()` produces from
one `<entry>` — the XML-parsing path itself (`_entry_to_dict`,
`_is_error_entry`) is exercised via `search()`/`get_by_id()` in
`test_search_and_pagination.py` and `test_invalid_and_source_errors.py`.
"""

from __future__ import annotations

import pytest

from researchos.db.models import RecordStatus
from researchos.evidence.adapters.arxiv import ArxivAdapter
from researchos.evidence.errors import SourceResponseError

ADAPTER = ArxivAdapter()

FULL_RECORD = {
    "id": "http://arxiv.org/abs/2101.12345v2",
    "title": "A Great Paper About Things",
    "summary": "This paper studies things in great detail.",
    "published": "2021-01-10T00:00:00Z",
    "updated": "2021-01-15T00:00:00Z",
    "authors": ["Jane Doe", "John Smith"],
    "doi": "10.1234/arxivdoi",
    "journal_ref": "Some Journal 2021",
    "categories": ["cs.LG", "cs.AI"],
    "url": "http://arxiv.org/abs/2101.12345v2",
}


def test_full_record_normalizes_completely():
    record = ADAPTER.normalize(FULL_RECORD)
    assert record.source == "arxiv"
    assert record.source_record_id == "2101.12345v2"  # version preserved on source_record_id
    assert record.external_ids["arxiv"] == "2101.12345"  # version stripped for cross-source matching
    assert record.title == "A Great Paper About Things"
    assert record.authors == ["Jane Doe", "John Smith"]
    assert record.year == 2021
    assert record.publication_date.isoformat() == "2021-01-10"
    assert record.venue == "Some Journal 2021"
    assert record.publisher is None
    assert record.doi == "10.1234/arxivdoi"
    assert record.document_type == "preprint"  # arXiv is definitionally a preprint server
    assert record.citation_count is None  # arXiv's API never supplies this — never fabricated
    assert record.keywords == ["cs.LG", "cs.AI"]
    assert record.record_status == RecordStatus.VERIFIED_SOURCE_RECORD


def test_record_without_doi_has_no_doi_in_external_ids():
    raw = {**FULL_RECORD, "doi": None}
    record = ADAPTER.normalize(raw)
    assert record.doi is None
    assert "doi" not in record.external_ids
    assert record.external_ids["arxiv"] == "2101.12345"


def test_missing_title_raises():
    raw = {**FULL_RECORD, "title": None}
    with pytest.raises(SourceResponseError):
        ADAPTER.normalize(raw)


def test_unparseable_published_date_leaves_year_and_date_none():
    raw = {**FULL_RECORD, "published": "not-a-date"}
    record = ADAPTER.normalize(raw)
    assert record.year is None
    assert record.publication_date is None
