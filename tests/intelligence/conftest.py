"""Shared fixtures for the research intelligence layer test suite.

Same pattern as tests/db, tests/workflow, tests/evidence: a fresh
temporary SQLite database per test, migrated via the real Alembic path.
No test in this package makes a real LLM API call — every service
function is called with an explicit `provider=FakeLLMProvider(...)`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "test_researchos.db"
    return f"sqlite:///{db_path.as_posix()}"


@pytest.fixture()
def engine(db_url: str):
    init_db(db_url)
    eng = create_db_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture()
def session(session_factory: sessionmaker) -> Iterator[Session]:
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def project_id(session_factory: sessionmaker) -> int:
    s = session_factory()
    try:
        project = repository.create_project(s, title="Fake Intelligence Test Project")
        s.commit()
        return project.id
    finally:
        s.close()


@pytest.fixture()
def literature_item_ids(session_factory: sessionmaker, project_id: int) -> list[int]:
    """Two fake, obviously-fabricated literature items to build evidence
    packages from."""
    s = session_factory()
    try:
        item1 = repository.add_literature_item(
            s, project_id=project_id, title="Fake Paper One: A Study of Widgets",
            source="openalex", source_record_id="W1", abstract="This fake paper studies widgets.",
            authors="Jane Doe", year=2020, doi="10.1234/fake-one", metadata_completeness=0.9,
        )
        item2 = repository.add_literature_item(
            s, project_id=project_id, title="Fake Paper Two: Widgets Revisited",
            source="crossref", source_record_id="10.1234/fake-two", abstract="This fake paper revisits widgets.",
            authors="John Smith", year=2021, doi="10.1234/fake-two", metadata_completeness=0.8,
        )
        s.commit()
        return [item1.id, item2.id]
    finally:
        s.close()
