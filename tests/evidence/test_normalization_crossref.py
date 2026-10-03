"""Test #3: Crossref normalization."""

from __future__ import annotations

import pytest

from researchos.db.models import RecordStatus
from researchos.evidence.adapters.crossref import CrossrefAdapter
from researchos.evidence.errors import SourceResponseError

ADAPTER = CrossrefAdapter()

FULL_RECORD = {
    "DOI": "10.1234/EXAMPLE",
    "title": ["Some Crossref Title"],
    "author": [{"given": "Jane", "family": "Doe"}, {"family": "Smith"}],
    "published": {"date-parts": [[2020, 5, 3]]},
    "container-title": ["Journal of Examples"],
    "publisher": "Example Press",
    "URL": "https://doi.org/10.1234/example",
    "type": "journal-article",
    "is-referenced-by-count": 42,
    "abstract": "<jats:p>Some abstract text.</jats:p>",
    "subject": ["Computer Science"],
}


def test_full_record_normalizes_completely():
    record = ADAPTER.normalize(FULL_RECORD)
    assert record.source == "crossref"
    assert record.source_record_id == "10.1234/example"  # DOI normalized (lowercased)
    assert record.doi == "10.1234/example"
    assert record.title == "Some Crossref Title"
    assert record.authors == ["Jane Doe", "Smith"]
    assert record.year == 2020
    assert record.publication_date.isoformat() == "2020-05-03"
    assert record.venue == "Journal of Examples"
    assert record.publisher == "Example Press"
    assert record.abstract == "Some abstract text."  # JATS tags stripped
    assert record.document_type == "journal-article"
    assert record.citation_count == 42
    assert record.keywords == ["Computer Science"]
    assert record.record_status == RecordStatus.VERIFIED_SOURCE_RECORD
    assert record.raw_metadata == FULL_RECORD


def test_year_only_date_leaves_publication_date_none():
    raw = {**FULL_RECORD, "published": {"date-parts": [[2020]]}}
    record = ADAPTER.normalize(raw)
    assert record.year == 2020
    assert record.publication_date is None  # never fabricate a day-of-month


def test_missing_abstract_is_common_and_yields_none():
    raw = {k: v for k, v in FULL_RECORD.items() if k != "abstract"}
    record = ADAPTER.normalize(raw)
    assert record.abstract is None


def test_missing_title_raises():
    raw = {**FULL_RECORD, "title": []}
    with pytest.raises(SourceResponseError):
        ADAPTER.normalize(raw)


def test_no_structured_cross_source_ids_for_crossref():
    record = ADAPTER.normalize(FULL_RECORD)
    assert record.external_ids == {}
