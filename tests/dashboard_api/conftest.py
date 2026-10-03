"""Shared fixtures for the Dashboard V1 API test suite. Same pattern
as tests/db, tests/execution, tests/analysis: a fresh temporary SQLite
database per test, migrated via the real Alembic path — the API layer
is tested against the actual, migrated schema, never a stand-in.

`researchos_api` lives under `apps/dashboard/api/`, outside the
`src/` layout the rest of the project uses, and is not pip-installed —
this conftest adds it to `sys.path` directly rather than requiring a
separate `pip install -e` step, keeping the test suite runnable with
nothing beyond the existing `.venv` plus the `dashboard` extra.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

_API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "dashboard" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from researchos.db import repository
from researchos.db.engine import create_db_engine
from researchos.db.migrate import init_db


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'test_researchos.db').as_posix()}"


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
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    from researchos_api.dependencies import get_db, get_session_factory
    from researchos_api.main import app

    def _override_get_session_factory() -> sessionmaker:
        return session_factory

    def _override_get_db() -> Iterator[Session]:
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    # Both overrides are required: get_db supplies read-only routes'
    # request-scoped Session; get_session_factory is what mutation
    # routes (the Approval Center) pass through to the domain
    # approve/reject/request_changes functions they call — those
    # functions open their OWN session via `session_scope(factory)`,
    # so without this second override they would silently fall
    # through to researchos.db.engine's process-wide default database
    # instead of this test's isolated one.
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = _override_get_session_factory
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def project_id(session_factory: sessionmaker) -> int:
    s = session_factory()
    try:
        project = repository.create_project(s, title="Dashboard Test Project")
        s.commit()
        return project.id
    finally:
        s.close()


@pytest.fixture()
def second_project_id(session_factory: sessionmaker) -> int:
    s = session_factory()
    try:
        project = repository.create_project(s, title="A Different Project")
        s.commit()
        return project.id
    finally:
        s.close()
