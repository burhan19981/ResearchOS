"""Tests #19 (project isolation), #20 (audit events), #21 (no-secret-leakage)."""

from __future__ import annotations

from datetime import datetime

import pytest

from researchos.db import repository
from researchos.db.engine import session_scope
from researchos.db.errors import NotFoundError
from researchos.evidence.errors import SourceUnavailableError
from researchos.evidence.service import get_literature_by_id, search_literature
from researchos.evidence.types import NormalizedRecord, PageInfo, SearchFilters, SearchResult


class FakeAdapter:
    source_name = "fake_source"

    def __init__(self, records=None, search_error=None, get_by_id_error=None):
        self._records = records or []
        self._search_error = search_error
        self._get_by_id_error = get_by_id_error

    def search(self, query, filters=None, *, page=1, page_size=25, cursor=None):
        if self._search_error:
            raise self._search_error
        return SearchResult(
            source=self.source_name, records=self._records,
            page_info=PageInfo(page=page, page_size=page_size, total=len(self._records), has_more=False),
            query=query, filters=filters or SearchFilters(),
        )

    def get_by_id(self, source_record_id):
        if self._get_by_id_error:
            raise self._get_by_id_error
        return next((r for r in self._records if r.source_record_id == source_record_id), None)

    def normalize(self, raw):
        raise NotImplementedError

    def health(self):
        raise NotImplementedError


def _record(**overrides) -> NormalizedRecord:
    defaults = dict(source="fake_source", source_record_id="rec-1", title="A Paper", retrieved_at=datetime.now())
    defaults.update(overrides)
    return NormalizedRecord(**defaults)


# --- Project isolation (#19) ------------------------------------------


def test_search_results_are_scoped_to_the_requesting_project(session_factory):
    with session_scope(session_factory) as s:
        project_a = repository.create_project(s, title="Fake Project A")
        project_b = repository.create_project(s, title="Fake Project B")
        a_id, b_id = project_a.id, project_b.id

    search_literature(
        a_id, "fake_source", "q", actor="agent:bot", adapter=FakeAdapter([_record()]), session_factory=session_factory
    )

    session = session_factory()
    try:
        assert len(repository.list_literature_items(session, a_id)) == 1
        assert len(repository.list_literature_items(session, b_id)) == 0
    finally:
        session.close()


def test_audit_events_are_scoped_to_the_requesting_project(session_factory):
    with session_scope(session_factory) as s:
        project_a = repository.create_project(s, title="Fake Project A")
        project_b = repository.create_project(s, title="Fake Project B")
        a_id, b_id = project_a.id, project_b.id

    search_literature(
        a_id, "fake_source", "q", actor="agent:bot", adapter=FakeAdapter([_record()]), session_factory=session_factory
    )

    session = session_factory()
    try:
        assert len(repository.list_audit_events(session, a_id)) > 0
        assert len(repository.list_audit_events(session, b_id)) == 0
    finally:
        session.close()


def test_search_against_nonexistent_project_raises_not_found(session_factory):
    with pytest.raises(NotFoundError):
        search_literature(
            999_999, "fake_source", "q", actor="agent:bot", adapter=FakeAdapter([_record()]),
            session_factory=session_factory,
        )


# --- Audit events (#20) --------------------------------------------------


def test_successful_search_writes_a_complete_audit_event(session_factory, project_id):
    search_literature(
        project_id, "fake_source", "neural nets", actor="agent:lit-bot",
        filters=SearchFilters(year_from=2020, author="Jane Doe"), adapter=FakeAdapter([_record()]),
        session_factory=session_factory,
    )

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "evidence.search")
        assert event.actor == "agent:lit-bot"
        assert event.metadata_["source"] == "fake_source"
        assert event.metadata_["query"] == "neural nets"
        assert event.metadata_["filters"] == {"year_from": 2020, "author": "Jane Doe"}
        assert event.metadata_["result_count"] == 1
        assert event.metadata_["persisted_count"] == 1
        assert event.metadata_["page"] == 1
        assert event.metadata_["has_more"] is False
    finally:
        session.close()


def test_failed_search_still_writes_an_audit_event_with_the_error(session_factory, project_id):
    error = SourceUnavailableError("fake_source: simulated outage")
    with pytest.raises(SourceUnavailableError):
        search_literature(
            project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([], search_error=error),
            session_factory=session_factory,
        )

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "evidence.search")
        assert "simulated outage" in event.metadata_["error"]
    finally:
        session.close()


def test_get_by_id_not_found_writes_audit_event_and_returns_none_record(session_factory, project_id):
    outcome = get_literature_by_id(
        project_id, "fake_source", "missing-id", actor="agent:lit-bot", adapter=FakeAdapter([]),
        session_factory=session_factory,
    )
    assert outcome.record is None
    assert outcome.item is None

    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "evidence.get_by_id")
        assert event.metadata_["found"] is False
    finally:
        session.close()


def test_unpersisted_search_writes_audit_event_with_zero_persisted(session_factory, project_id):
    search_literature(
        project_id, "fake_source", "q", actor="agent:lit-bot", persist=False, adapter=FakeAdapter([_record()]),
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        assert repository.list_literature_items(session, project_id) == []
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "evidence.search")
        assert event.metadata_["persisted_count"] == 0
    finally:
        session.close()


# --- No secret leakage (#21) -----------------------------------------------


def test_audit_event_metadata_never_contains_api_key_or_contact_email(session_factory, project_id):
    search_literature(
        project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([_record()]),
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        for event in events:
            blob = str(event.metadata_) + str(event.description)
            assert "api_key" not in blob.lower()
            assert "mailto" not in blob.lower()
            assert "x-api-key" not in blob.lower()
    finally:
        session.close()


def test_error_audit_event_does_not_leak_a_secret_embedded_in_the_error_message(session_factory, project_id):
    error = SourceUnavailableError("fake_source: could not reach https://api.example.test (no secrets here)")
    with pytest.raises(SourceUnavailableError):
        search_literature(
            project_id, "fake_source", "q", actor="agent:lit-bot", adapter=FakeAdapter([], search_error=error),
            session_factory=session_factory,
        )
    session = session_factory()
    try:
        events = repository.list_audit_events(session, project_id)
        event = next(e for e in events if e.event_type == "evidence.search")
        assert "secret-key" not in str(event.metadata_)
    finally:
        session.close()
