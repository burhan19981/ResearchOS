"""Test #2: OpenAlex normalization."""

from __future__ import annotations

import pytest

from researchos.db.models import RecordStatus
from researchos.evidence.adapters.openalex import OpenAlexAdapter
from researchos.evidence.errors import SourceResponseError

ADAPTER = OpenAlexAdapter()

FULL_RECORD = {
    "id": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.7717/peerj.4375",
    "title": "The state of OA: a large-scale analysis",
    "publication_year": 2018,
    "publication_date": "2018-02-13",
    "type": "article",
    "authorships": [
        {"author": {"display_name": "Heather Piwowar"}},
        {"author": {"display_name": "Jason Priem"}},
    ],
    "primary_location": {
        "source": {"display_name": "PeerJ", "host_organization_name": "PeerJ Inc."},
        "landing_page_url": "https://peerj.com/articles/4375",
    },
    "cited_by_count": 500,
    "concepts": [{"display_name": "Open access"}],
    "abstract_inverted_index": {"Open": [0], "access": [1], "is": [2], "growing": [3]},
    "ids": {
        "openalex": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.7717/peerj.4375",
        "pmid": "https://pubmed.ncbi.nlm.nih.gov/29456894",
    },
}


def test_full_record_normalizes_completely():
    record = ADAPTER.normalize(FULL_RECORD)
    assert record.source == "openalex"
    assert record.source_record_id == "W2741809807"
    assert record.title == "The state of OA: a large-scale analysis"
    assert record.authors == ["Heather Piwowar", "Jason Priem"]
    assert record.year == 2018
    assert record.publication_date.isoformat() == "2018-02-13"
    assert record.venue == "PeerJ"
    assert record.publisher == "PeerJ Inc."
    assert record.doi == "10.7717/peerj.4375"  # normalized: no https://doi.org/ prefix, lowercase
    assert record.url == "https://peerj.com/articles/4375"
    assert record.abstract == "Open access is growing"  # reconstructed from inverted index
    assert record.document_type == "article"
    assert record.citation_count == 500
    assert record.keywords == ["Open access"]
    assert record.external_ids == {"doi": "10.7717/peerj.4375", "pmid": "29456894"}
    assert record.record_status == RecordStatus.VERIFIED_SOURCE_RECORD
    assert record.metadata_completeness == 1.0
    assert record.raw_metadata == FULL_RECORD  # nothing destroyed


def test_missing_abstract_inverted_index_yields_none_not_empty_string():
    raw = {**FULL_RECORD, "abstract_inverted_index": None}
    record = ADAPTER.normalize(raw)
    assert record.abstract is None


def test_missing_title_raises_rather_than_fabricating_one():
    raw = {**FULL_RECORD, "title": None}
    with pytest.raises(SourceResponseError):
        ADAPTER.normalize(raw)


def test_partial_record_gets_partial_metadata_status():
    raw = {"id": "https://openalex.org/W1", "title": "Minimal Record"}
    record = ADAPTER.normalize(raw)
    assert record.record_status == RecordStatus.PARTIAL_METADATA
    assert record.doi is None
    assert record.authors == []
    assert 0.0 < record.metadata_completeness < 1.0
