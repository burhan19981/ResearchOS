"""Evidence package construction tests."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.intelligence.errors import EvidencePackageError
from researchos.intelligence.evidence_package import build_evidence_package


def test_valid_evidence_package_includes_documented_fields(session, project_id, literature_item_ids):
    package = build_evidence_package(session, project_id, literature_item_ids)
    assert len(package.items) == 2
    assert package.truncated is False
    assert package.excluded_item_ids == []

    item = next(i for i in package.items if i.literature_item_id == literature_item_ids[0])
    assert item.title == "Fake Paper One: A Study of Widgets"
    assert item.authors == ["Jane Doe"]
    assert item.year == 2020
    assert item.doi == "10.1234/fake-one"
    assert item.abstract == "This fake paper studies widgets."
    assert item.source == "openalex"
    assert item.source_record_id == "W1"
    assert item.metadata_completeness == 0.9
    assert item.evidence_status == "unreviewed"


def test_missing_abstract_is_none_not_fabricated(session, project_id):
    item = repository.add_literature_item(session, project_id=project_id, title="No Abstract Paper")
    session.commit()
    package = build_evidence_package(session, project_id, [item.id])
    assert package.items[0].abstract is None


def test_incomplete_metadata_fields_are_none(session, project_id):
    item = repository.add_literature_item(session, project_id=project_id, title="Sparse Paper")
    session.commit()
    package = build_evidence_package(session, project_id, [item.id])
    result = package.items[0]
    assert result.doi is None
    assert result.venue is None
    assert result.citation_count is None
    assert result.authors == []
    assert result.keywords == []


def test_unknown_literature_item_id_raises_rather_than_silently_omitting(session, project_id):
    with pytest.raises(EvidencePackageError):
        build_evidence_package(session, project_id, [999_999])


def test_empty_selection_raises(session, project_id):
    with pytest.raises(EvidencePackageError):
        build_evidence_package(session, project_id, [])


def test_evidence_truncation_is_explicit_and_deterministic(session, project_id):
    ids = []
    for i in range(5):
        item = repository.add_literature_item(
            session, project_id=project_id, title=f"Paper {i}", metadata_completeness=i / 10.0
        )
        ids.append(item.id)
    session.commit()

    package = build_evidence_package(session, project_id, ids, max_items=2)
    assert package.truncated is True
    assert len(package.items) == 2
    assert len(package.excluded_item_ids) == 3
    # Ranking is by metadata_completeness desc, so the two highest-completeness
    # items (the last two created, id order preserved by completeness) survive.
    included_ids = {i.literature_item_id for i in package.items}
    assert included_ids == {ids[3], ids[4]}


def test_truncation_ranking_and_selection_is_deterministic_across_calls(session, project_id):
    ids = []
    for i in range(6):
        item = repository.add_literature_item(session, project_id=project_id, title=f"Paper {i}")
        ids.append(item.id)
    session.commit()

    first = build_evidence_package(session, project_id, ids, max_items=3)
    second = build_evidence_package(session, project_id, ids, max_items=3)
    assert first.included_item_ids == second.included_item_ids
    assert first.excluded_item_ids == second.excluded_item_ids


def test_abstract_truncation_flag_set_when_abstract_exceeds_max_chars(session, project_id):
    long_abstract = "x" * 500
    item = repository.add_literature_item(session, project_id=project_id, title="Long Abstract Paper", abstract=long_abstract)
    session.commit()
    package = build_evidence_package(session, project_id, [item.id], max_abstract_chars=100)
    assert package.items[0].abstract_truncated is True
    assert len(package.items[0].abstract) == 100


def test_evidence_package_project_isolation(session_factory, project_id):
    from researchos.db.engine import session_scope

    with session_scope(session_factory) as s:
        other_project = repository.create_project(s, title="Fake Other Project")
        other_item = repository.add_literature_item(s, project_id=other_project.id, title="Other Project Paper")
        other_id = other_item.id

    with session_scope(session_factory) as s:
        with pytest.raises(EvidencePackageError):
            build_evidence_package(s, project_id, [other_id])
