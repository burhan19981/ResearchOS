"""Shared fixtures for the workflow engine test suite.

Every test gets its own throwaway SQLite file (pytest's `tmp_path`),
migrated via the real Alembic path, exactly like `tests/db/conftest.py`.
No test ever touches the developer's real `data/researchos.db`, no real
API call is made anywhere in this package, and no real research data is
used (all titles/actors are obviously fake).
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
    """A freshly created project, committed so later transactions can see it."""
    s = session_factory()
    try:
        project = repository.create_project(s, title="Fake Workflow Test Project")
        s.commit()
        return project.id
    finally:
        s.close()
