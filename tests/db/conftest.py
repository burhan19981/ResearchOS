"""Shared fixtures for the database layer test suite.

Every test gets its own throwaway SQLite file under pytest's `tmp_path`,
brought up to the latest schema via the real Alembic migration (not a
`create_all()` shortcut), so the migration itself is exercised by every
test run. No test ever touches the developer's real
`data/researchos.db`, and no real research data is used anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

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
