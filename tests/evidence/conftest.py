"""Shared fixtures for the evidence-layer test suite.

Two guarantees every test in this package gets automatically:

1. **No real network call is possible.** `urllib.request.urlopen` is
   monkeypatched to raise immediately — if any code path under test
   ever tries a real request (a bug, not by design), the test fails
   loudly instead of silently hitting the network.
2. **A fresh temporary SQLite database**, migrated via the real
   Alembic path, exactly like `tests/db/` and `tests/workflow/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db


@pytest.fixture(autouse=True)
def block_real_network_calls(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "A real network call was attempted (urllib.request.urlopen) — "
            "evidence-layer tests must use FakeTransport / mocked adapters only."
        )

    monkeypatch.setattr("urllib.request.urlopen", _forbidden)


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
        project = repository.create_project(s, title="Fake Evidence Test Project")
        s.commit()
        return project.id
    finally:
        s.close()


@pytest.fixture()
def no_cache():
    """A cache config that never persists anything, for tests that need
    to control exactly how many `FakeTransport` calls happen."""
    from researchos.evidence.cache import NullCache

    return NullCache()
