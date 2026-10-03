"""CRUD tests for ResearchProject, plus timestamp behavior."""

from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session

from researchos.db import repository
from researchos.db.errors import NotFoundError
from researchos.db.models import ProjectStatus


def test_create_and_get_project(session: Session):
    project = repository.create_project(
        session, title="Fake Research Project", description="A test project", field="test-domain"
    )
    assert project.id is not None
    fetched = repository.get_project(session, project.id)
    assert fetched is not None
    assert fetched.title == "Fake Research Project"
    assert fetched.status == ProjectStatus.ACTIVE


def test_get_project_returns_none_for_missing_id(session: Session):
    assert repository.get_project(session, 999_999) is None


def test_list_projects_returns_all_then_filters_by_status(session: Session):
    repository.create_project(session, title="Active One", status=ProjectStatus.ACTIVE)
    repository.create_project(session, title="Archived One", status=ProjectStatus.ARCHIVED)

    all_projects = repository.list_projects(session)
    assert {p.title for p in all_projects} == {"Active One", "Archived One"}

    archived = repository.list_projects(session, status=ProjectStatus.ARCHIVED)
    assert [p.title for p in archived] == ["Archived One"]


def test_update_project_changes_fields_and_updated_at(session: Session):
    project = repository.create_project(session, title="Original Title")
    original_updated_at = project.updated_at
    time.sleep(0.01)

    updated = repository.update_project(session, project.id, title="New Title", status=ProjectStatus.PAUSED)
    assert updated.title == "New Title"
    assert updated.status == ProjectStatus.PAUSED
    assert updated.updated_at > original_updated_at
    assert updated.created_at == project.created_at  # created_at must not change


def test_update_project_raises_not_found_for_missing_id(session: Session):
    with pytest.raises(NotFoundError):
        repository.update_project(session, 999_999, title="Doesn't matter")


def test_created_at_and_updated_at_are_set_on_creation(session: Session):
    project = repository.create_project(session, title="Timestamp Project")
    assert project.created_at is not None
    assert project.updated_at is not None
    assert project.created_at.tzinfo is not None  # stored timezone-aware
