"""DatasetVersion service and repository tests (Phase 8A)."""

from __future__ import annotations

import pytest

from researchos.db import repository
from researchos.db.errors import IntegrityConstraintError, NotFoundError
from researchos.db.models import DatasetLifecycleStatus
from researchos.planning.errors import CrossProjectReferenceError, UnknownPlanningEntityError
from researchos.specification.dataset_versions import create_dataset_version, validate_dataset_version
from researchos.specification.errors import InvalidLifecycleTransitionError
from researchos.specification.fingerprint import compute_dataset_fingerprints


def test_create_dataset_version_starts_as_draft(session_factory, project_id, dataset_record_id):
    outcome = create_dataset_version(
        project_id, dataset_record_id, actor="agent:registrar", format="classification",
        sample_count=500, split_definition={"train": 0.8, "test": 0.2}, source_uri="s3://bucket/v1/",
        session_factory=session_factory,
    )
    session = session_factory()
    try:
        dataset_version = repository.get_dataset_version(session, outcome.dataset_version_id)
        assert dataset_version.lifecycle_status == DatasetLifecycleStatus.DRAFT
        assert dataset_version.version == 1
        assert dataset_version.content_fingerprint is not None
        assert dataset_version.metadata_fingerprint is not None
    finally:
        session.close()


def test_dataset_version_retrieval_and_project_isolation(session_factory, project_id, second_project_id, dataset_record_id):
    outcome = create_dataset_version(
        project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory,
    )
    session = session_factory()
    try:
        found = repository.get_dataset_version(session, outcome.dataset_version_id)
        assert found is not None
        assert found.project_id == project_id
        assert found.project_id != second_project_id
    finally:
        session.close()


def test_regeneration_creates_a_new_version_never_overwrites(session_factory, project_id, dataset_record_id):
    first = create_dataset_version(
        project_id, dataset_record_id, actor="agent:registrar", description="v1", session_factory=session_factory,
    )
    session = session_factory()
    try:
        v1_id = first.dataset_version_id
        second = repository.create_dataset_version(
            session, project_id=project_id, dataset_record_id=dataset_record_id, supersedes_id=v1_id,
            description="v2, revised",
        )
        session.commit()
        v1 = repository.get_dataset_version(session, v1_id)
        v2 = repository.get_dataset_version(session, second.id)
        assert v1.version == 1
        assert v1.description == "v1"  # unchanged by the regeneration
        assert v2.version == 2
        assert v2.supersedes_id == v1_id
    finally:
        session.close()


def test_independent_versions_do_not_share_a_lineage(session_factory, project_id, dataset_record_id):
    a = create_dataset_version(project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory)
    b = create_dataset_version(project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory)
    session = session_factory()
    try:
        va = repository.get_dataset_version(session, a.dataset_version_id)
        vb = repository.get_dataset_version(session, b.dataset_version_id)
        assert va.version == 1
        assert vb.version == 1
        assert va.supersedes_id is None
        assert vb.supersedes_id is None
    finally:
        session.close()


def test_superseding_the_same_version_twice_is_rejected(session_factory, project_id, dataset_record_id):
    first = create_dataset_version(project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory)
    session = session_factory()
    try:
        repository.create_dataset_version(
            session, project_id=project_id, dataset_record_id=dataset_record_id, supersedes_id=first.dataset_version_id,
        )
        session.commit()
        with pytest.raises(IntegrityConstraintError):
            repository.create_dataset_version(
                session, project_id=project_id, dataset_record_id=dataset_record_id,
                supersedes_id=first.dataset_version_id,
            )
    finally:
        session.close()


def test_parent_version_must_belong_to_same_dataset_record(session_factory, project_id, dataset_record_id):
    session = session_factory()
    try:
        other_record = repository.register_dataset(
            session, project_id=project_id, name="A different dataset", version="raw",
            path_or_uri="s3://bucket/other/",
        )
        first = repository.create_dataset_version(session, project_id=project_id, dataset_record_id=dataset_record_id)
        session.commit()
        with pytest.raises(NotFoundError):
            repository.create_dataset_version(
                session, project_id=project_id, dataset_record_id=other_record.id, supersedes_id=first.id,
            )
    finally:
        session.close()


def test_parent_version_cross_project_rejected(session_factory, project_id, second_project_id, dataset_record_id):
    first = create_dataset_version(project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory)
    session = session_factory()
    try:
        other_record = repository.register_dataset(
            session, project_id=second_project_id, name="Other project's dataset", version="raw",
            path_or_uri="s3://bucket/other-project/",
        )
        session.commit()
        with pytest.raises(NotFoundError):
            repository.create_dataset_version(
                session, project_id=second_project_id, dataset_record_id=other_record.id,
                supersedes_id=first.dataset_version_id,
            )
    finally:
        session.close()


def test_dataset_record_cross_project_rejected(session_factory, second_project_id, dataset_record_id):
    with pytest.raises(NotFoundError):
        repository.create_dataset_version(
            session_factory(), project_id=second_project_id, dataset_record_id=dataset_record_id,
        )


# --- Fingerprinting ----------------------------------------------------------


def test_content_fingerprint_is_deterministic():
    a = compute_dataset_fingerprints(
        content_descriptor={"source_uri": "s3://x/", "format": "classification", "sample_count": 100,
                             "split_definition": {"train": 0.8, "test": 0.2}, "class_definition": ["a", "b"]},
        metadata_descriptor={"description": "d"},
    )
    b = compute_dataset_fingerprints(
        content_descriptor={"format": "classification", "sample_count": 100, "source_uri": "s3://x/",
                             "class_definition": ["a", "b"], "split_definition": {"test": 0.2, "train": 0.8}},
        metadata_descriptor={"description": "d"},
    )
    assert a.content_fingerprint == b.content_fingerprint  # key ordering must not matter


def test_content_fingerprint_changes_with_content():
    a = compute_dataset_fingerprints(
        content_descriptor={"sample_count": 100}, metadata_descriptor={},
    )
    b = compute_dataset_fingerprints(
        content_descriptor={"sample_count": 200}, metadata_descriptor={},
    )
    assert a.content_fingerprint != b.content_fingerprint


def test_metadata_fingerprint_independent_of_content_fingerprint():
    a = compute_dataset_fingerprints(content_descriptor={"sample_count": 100}, metadata_descriptor={"description": "x"})
    b = compute_dataset_fingerprints(content_descriptor={"sample_count": 100}, metadata_descriptor={"description": "y"})
    assert a.content_fingerprint == b.content_fingerprint
    assert a.metadata_fingerprint != b.metadata_fingerprint


def test_created_dataset_version_fingerprint_is_reproducible(session_factory, project_id, dataset_record_id):
    kwargs = dict(
        project_id=project_id, dataset_record_id=dataset_record_id, actor="agent:registrar",
        format="classification", sample_count=100, split_definition={"train": 0.8, "test": 0.2},
        class_definition=["a", "b"], source_uri="s3://x/",
    )
    first = create_dataset_version(session_factory=session_factory, **kwargs)
    second = create_dataset_version(session_factory=session_factory, **kwargs)
    session = session_factory()
    try:
        v1 = repository.get_dataset_version(session, first.dataset_version_id)
        v2 = repository.get_dataset_version(session, second.dataset_version_id)
        assert v1.content_fingerprint == v2.content_fingerprint
        assert v1.metadata_fingerprint == v2.metadata_fingerprint
    finally:
        session.close()


# --- Lifecycle -----------------------------------------------------------


def test_validate_valid_dataset_transitions_to_valid(session_factory, project_id, dataset_record_id):
    outcome = create_dataset_version(
        project_id, dataset_record_id, actor="agent:registrar", format="generic", sample_count=100,
        split_definition={"train": 0.8, "test": 0.2}, source_uri="s3://x/", session_factory=session_factory,
    )
    result = validate_dataset_version(project_id, outcome.dataset_version_id, actor="agent:registrar", session_factory=session_factory)
    assert result.is_valid
    session = session_factory()
    try:
        dataset_version = repository.get_dataset_version(session, outcome.dataset_version_id)
        assert dataset_version.lifecycle_status == DatasetLifecycleStatus.VALID
        assert dataset_version.validation_result["is_valid"] is True
    finally:
        session.close()


def test_validate_invalid_dataset_transitions_to_invalid(session_factory, project_id, dataset_record_id):
    outcome = create_dataset_version(
        project_id, dataset_record_id, actor="agent:registrar", format="classification",
        class_definition=[], session_factory=session_factory,  # empty class_definition -> invalid
    )
    result = validate_dataset_version(project_id, outcome.dataset_version_id, actor="agent:registrar", session_factory=session_factory)
    assert not result.is_valid
    assert result.errors
    session = session_factory()
    try:
        dataset_version = repository.get_dataset_version(session, outcome.dataset_version_id)
        assert dataset_version.lifecycle_status == DatasetLifecycleStatus.INVALID
    finally:
        session.close()


def test_validate_cross_project_dataset_version_rejected(session_factory, project_id, second_project_id, dataset_record_id):
    outcome = create_dataset_version(project_id, dataset_record_id, actor="agent:registrar", session_factory=session_factory)
    with pytest.raises(CrossProjectReferenceError):
        validate_dataset_version(second_project_id, outcome.dataset_version_id, actor="agent:registrar", session_factory=session_factory)


def test_validate_unknown_dataset_version_rejected(session_factory, project_id):
    with pytest.raises(UnknownPlanningEntityError):
        validate_dataset_version(project_id, 999_999, actor="agent:registrar", session_factory=session_factory)


def test_approved_dataset_version_cannot_be_revalidated(session_factory, approved_dataset_version_id, project_id):
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_dataset_version(project_id, approved_dataset_version_id, actor="agent:registrar", session_factory=session_factory)
