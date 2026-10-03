"""Test #11: duplicate detection."""

from __future__ import annotations

from datetime import datetime

from researchos.db import repository
from researchos.db.models import EvidenceStatus, MatchType
from researchos.evidence.dedup import find_duplicate
from researchos.evidence.types import NormalizedRecord


def _make_record(**overrides) -> NormalizedRecord:
    defaults = dict(
        source="crossref",
        source_record_id="10.1/candidate",
        title="Deep Learning for Everyone",
        authors=["Jane Doe"],
        year=2021,
        doi=None,
        external_ids={},
        retrieved_at=datetime.now(),
    )
    defaults.update(overrides)
    return NormalizedRecord(**defaults)


def test_doi_match_is_highest_confidence(session, project_id):
    existing = repository.add_literature_item(
        session, project_id=project_id, title="Existing Paper", source="openalex", source_record_id="W1",
        doi="10.1234/shared",
    )
    session.commit()

    candidate = _make_record(doi="10.1234/shared", title="A Completely Different Title")
    decision = find_duplicate(session, project_id, candidate)

    assert decision.is_duplicate
    assert decision.duplicate_of_id == existing.id
    assert decision.match_type == MatchType.DOI
    assert decision.confidence == 1.0
    assert "10.1234/shared" in decision.notes


def test_strong_external_identifier_match_across_sources(session, project_id):
    existing = repository.add_literature_item(
        session, project_id=project_id, title="Existing Arxiv Paper", source="arxiv", source_record_id="2101.00001v1",
        external_ids={"arxiv": "2101.00001"},
    )
    session.commit()

    # A Semantic Scholar record that mentions the same arXiv id in its externalIds.
    candidate = _make_record(
        source="semantic_scholar", source_record_id="abc123", title="Totally Different Title Text",
        external_ids={"arxiv": "2101.00001"},
    )
    decision = find_duplicate(session, project_id, candidate)

    assert decision.is_duplicate
    assert decision.duplicate_of_id == existing.id
    assert decision.match_type == MatchType.SOURCE_ID
    assert decision.confidence == 0.95


def test_weak_title_author_year_match_is_recorded_as_candidate_not_merged(session, project_id):
    existing = repository.add_literature_item(
        session, project_id=project_id, title="Deep Learning, for Everyone!", authors="Jane Doe", year=2021,
        source="crossref", source_record_id="10.1/existing",
    )
    session.commit()

    candidate = _make_record(title="deep learning for everyone", authors=["Jane Doe"], year=2021)
    decision = find_duplicate(session, project_id, candidate)

    assert decision.is_duplicate
    assert decision.duplicate_of_id == existing.id
    assert decision.match_type == MatchType.TITLE_AUTHOR_YEAR
    assert decision.confidence == 0.6  # weak — never treated as certain


def test_different_author_or_year_does_not_match_on_title_alone(session, project_id):
    repository.add_literature_item(
        session, project_id=project_id, title="Deep Learning for Everyone", authors="Jane Doe", year=2021,
        source="crossref", source_record_id="10.1/existing",
    )
    session.commit()

    different_author = _make_record(title="Deep Learning for Everyone", authors=["John Smith"], year=2021)
    assert not find_duplicate(session, project_id, different_author).is_duplicate

    different_year = _make_record(title="Deep Learning for Everyone", authors=["Jane Doe"], year=1999)
    assert not find_duplicate(session, project_id, different_year).is_duplicate


def test_no_match_returns_non_duplicate_decision(session, project_id):
    decision = find_duplicate(session, project_id, _make_record())
    assert not decision.is_duplicate
    assert decision.duplicate_of_id is None
    assert decision.match_type is None
    assert decision.confidence is None


def test_titles_merely_similar_are_not_treated_as_duplicates_without_author_year_match(session, project_id):
    """Do not merge records merely because titles are approximately
    similar unless the match confidence is explicitly recorded — here,
    similar titles with no matching author+year must not match at all."""
    repository.add_literature_item(
        session, project_id=project_id, title="Deep Learning for Everyone", year=2021, authors="Jane Doe",
        source="crossref", source_record_id="10.1/existing",
    )
    session.commit()

    candidate = _make_record(title="Deep Learning for Everyone: An Introduction", authors=["Someone Else"], year=2021)
    assert not find_duplicate(session, project_id, candidate).is_duplicate


def test_duplicate_scoped_to_project_not_global(session, session_factory):
    from researchos.db.engine import session_scope

    with session_scope(session_factory) as s:
        project_a = repository.create_project(s, title="Fake Project A")
        project_b = repository.create_project(s, title="Fake Project B")
        repository.add_literature_item(
            s, project_id=project_a.id, title="Shared Title Paper", doi="10.1/shared", source="openalex",
            source_record_id="W1",
        )
        project_a_id, project_b_id = project_a.id, project_b.id

    with session_scope(session_factory) as s:
        candidate = _make_record(doi="10.1/shared")
        decision = find_duplicate(s, project_b_id, candidate)
        assert not decision.is_duplicate  # project B has no items at all
