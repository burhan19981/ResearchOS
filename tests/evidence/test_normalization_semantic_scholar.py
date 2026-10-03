"""Test #4: Semantic Scholar normalization."""

from __future__ import annotations

import pytest

from researchos.db.models import RecordStatus
from researchos.evidence.adapters.semantic_scholar import SemanticScholarAdapter
from researchos.evidence.errors import SourceResponseError

ADAPTER = SemanticScholarAdapter()

FULL_RECORD = {
    "paperId": "649def34f8be52c8b66281af98ae884c09aef38",
    "title": "Construction of the Literature Graph in Semantic Scholar",
    "abstract": "We describe a deployed scalable system for extraction...",
    "year": 2018,
    "venue": "NAACL",
    "publicationDate": "2018-06-01",
    "authors": [{"authorId": "1", "name": "Waleed Ammar"}, {"authorId": "2", "name": "Dirk Groeneveld"}],
    "externalIds": {"DOI": "10.18653/V1/N18-3011", "ArXiv": "1805.02262", "MAG": "12345"},
    "url": "https://www.semanticscholar.org/paper/649def34",
    "citationCount": 300,
    "publicationTypes": ["JournalArticle"],
    "fieldsOfStudy": ["Computer Science"],
    "publicationVenue": {"name": "NAACL", "publisher": "ACL"},
}


def test_full_record_normalizes_completely():
    record = ADAPTER.normalize(FULL_RECORD)
    assert record.source == "semantic_scholar"
    assert record.source_record_id == "649def34f8be52c8b66281af98ae884c09aef38"
    assert record.title == "Construction of the Literature Graph in Semantic Scholar"
    assert record.authors == ["Waleed Ammar", "Dirk Groeneveld"]
    assert record.year == 2018
    assert record.publication_date.isoformat() == "2018-06-01"
    assert record.venue == "NAACL"
    assert record.publisher == "ACL"
    assert record.doi == "10.18653/v1/n18-3011"  # normalized (lowercased)
    assert record.document_type == "JournalArticle"
    assert record.citation_count == 300
    assert record.keywords == ["Computer Science"]
    assert record.external_ids == {"doi": "10.18653/v1/n18-3011", "arxiv": "1805.02262", "mag": "12345"}
    assert record.record_status == RecordStatus.VERIFIED_SOURCE_RECORD
    assert record.raw_metadata == FULL_RECORD


def test_falls_back_to_plain_venue_when_publication_venue_absent():
    raw = {**FULL_RECORD, "publicationVenue": None, "venue": "Some Conference"}
    record = ADAPTER.normalize(raw)
    assert record.venue == "Some Conference"
    assert record.publisher is None


def test_missing_title_raises():
    raw = {**FULL_RECORD, "title": None}
    with pytest.raises(SourceResponseError):
        ADAPTER.normalize(raw)


def test_no_external_ids_yields_empty_dict_not_none():
    raw = {**FULL_RECORD, "externalIds": {}}
    record = ADAPTER.normalize(raw)
    assert record.external_ids == {}
    assert record.doi is None
