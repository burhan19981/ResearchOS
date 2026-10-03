"""Test #12: provenance preservation through the service/persistence layer.

Uses a minimal fake `SourceAdapter` (not a fake HTTP transport) since
these tests are about what the *service* does with already-normalized
records, not about parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from researchos.db import repository
from researchos.db.models import RecordStatus
from researchos.evidence.service import search_literature
from researchos.evidence.types import NormalizedRecord, PageInfo, SearchFilters, SearchResult


class FakeAdapter:
    source_name = "fake_source"

    def __init__(self, records: list[NormalizedRecord]):
        self._records = records

    def search(self, query, filters=None, *, page=1, page_size=25, cursor=None):
        return SearchResult(
            source=self.source_name,
            records=self._records,
            page_info=PageInfo(page=page, page_size=page_size, total=len(self._records), has_more=False),
            query=query,
            filters=filters or SearchFilters(),
        )

    def get_by_id(self, source_record_id):
        return next((r for r in self._records if r.source_record_id == source_record_id), None)

    def normalize(self, raw):
        raise NotImplementedError

    def health(self):
        raise NotImplementedError


def _record(**overrides) -> NormalizedRecord:
    defaults = dict(
        source="fake_source",
        source_record_id="rec-1",
        title="A Provenance Test Paper",
        authors=["Jane Doe"],
        year=2022,
        doi="10.9/provenance",
        url="https://example.org/paper",
        raw_metadata={"original": "payload", "nested": {"a": 1}},
        retrieved_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return NormalizedRecord(**defaults)


def test_persisted_record_preserves_source_and_source_record_id(session_factory, project_id):
    record = _record()
    outcome = search_literature(
        project_id, "fake_source", "query", actor="agent:lit-bot", adapter=FakeAdapter([record]),
        session_factory=session_factory,
    )
    item = outcome.persisted_items[0]
    assert item.source == "fake_source"
    assert item.source_record_id == "rec-1"


def test_persisted_record_preserves_retrieval_timestamp(session_factory, project_id):
    record = _record()
    outcome = search_literature(
        project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([record]),
        session_factory=session_factory,
    )
    item = outcome.persisted_items[0]
    assert item.retrieved_at == record.retrieved_at


def test_persisted_record_preserves_original_url(session_factory, project_id):
    record = _record(url="https://example.org/original-landing-page")
    outcome = search_literature(
        project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([record]),
        session_factory=session_factory,
    )
    assert outcome.persisted_items[0].url == "https://example.org/original-landing-page"


def test_persisted_record_preserves_full_raw_metadata(session_factory, project_id):
    record = _record(raw_metadata={"anything": "the source sent", "list": [1, 2, 3]})
    outcome = search_literature(
        project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([record]),
        session_factory=session_factory,
    )
    assert outcome.persisted_items[0].raw_metadata == {"anything": "the source sent", "list": [1, 2, 3]}


def test_two_sources_describing_the_same_paper_both_survive(session_factory, project_id):
    """If multiple sources describe the same paper, preserve provenance
    from both rather than silently replacing one with the other."""
    first = _record(source="openalex", source_record_id="W1", doi="10.9/same-paper")
    outcome_a = search_literature(
        project_id, "openalex", "q", actor="agent:lit-bot", adapter=FakeAdapter([first]),
        session_factory=session_factory,
    )

    second = _record(source="crossref", source_record_id="10.9/same-paper", doi="10.9/same-paper", title="Same Paper, Different Source")
    outcome_b = search_literature(
        project_id, "crossref", "q", actor="agent:lit-bot", adapter=FakeAdapter([second]),
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        items = repository.list_literature_items(session, project_id)
        assert len(items) == 2  # both rows exist — neither was overwritten or deleted
        sources = {item.source for item in items}
        assert sources == {"openalex", "crossref"}
    finally:
        session.close()

    # The second (later) one is flagged as a duplicate candidate of the first.
    duplicate_item = outcome_b.persisted_items[0]
    assert duplicate_item.record_status == RecordStatus.DUPLICATE_CANDIDATE
    assert duplicate_item.duplicate_of_id == outcome_a.persisted_items[0].id
    assert len(outcome_b.matches) == 1
    assert outcome_b.matches[0].confidence == 1.0


def test_refetching_the_same_source_record_updates_in_place_not_duplicated(session_factory, project_id):
    v1 = _record(citation_count=10)
    search_literature(project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([v1]), session_factory=session_factory)

    v2 = _record(citation_count=25)  # same source + source_record_id, updated citation count
    search_literature(project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([v2]), session_factory=session_factory)

    session = session_factory()
    try:
        items = repository.list_literature_items(session, project_id)
        assert len(items) == 1  # updated in place, not duplicated
        assert items[0].citation_count == 25
    finally:
        session.close()
