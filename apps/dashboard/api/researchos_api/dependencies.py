"""FastAPI dependency providers.

Wires FastAPI's request lifecycle onto ``researchos.db.engine``'s
already-existing session factory — this module creates no second
database and no second engine. ``get_project_or_404`` is the one
project-isolation checkpoint every project-scoped route depends on: a
project id that does not exist in the database never reaches a route
handler's body.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from researchos.db import repository
from researchos.db.engine import get_sessionmaker
from researchos.db.models import ResearchProject

# The actor string every dashboard-initiated approval decision is
# recorded under. Hardcoded server-side and never taken from the
# frontend or the request body: Dashboard V1 has no real identity/auth
# system, and trusting a client-supplied actor value would let the
# client forge who approved what (`workflow.policy.is_human_actor`
# treats any string not starting with "agent:" as human — this value
# is deliberately always the human path).
DASHBOARD_ACTOR = "user:dashboard"


def get_session_factory() -> sessionmaker:
    """The `sessionmaker` every request's DB access is built from.

    A dependency (not a bare module-level call) specifically so tests
    can override it to point at an isolated test database — every
    mutation route passes this same factory through to the domain
    approval function it calls (`services.approvals.act_on_approval`),
    so a test that overrides only `get_db` but not this one would
    silently let approval mutations fall through to
    `researchos.db.engine`'s process-wide default `DATABASE_URL`
    database instead of the test's own. See `tests/dashboard_api/
    conftest.py`'s `client` fixture, which overrides both together.
    """
    return get_sessionmaker()


def get_db(factory: sessionmaker = Depends(get_session_factory)) -> Iterator[Session]:
    """One request-scoped SQLAlchemy `Session`, closed at the end of
    every request. Read-only routes never call `.commit()` on it —
    mutation routes instead delegate to a domain service function,
    each of which manages its own transaction via
    `researchos.db.engine.session_scope`."""
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_project_or_404(project_id: int, db: Session = Depends(get_db)) -> ResearchProject:
    """The project-isolation checkpoint: every `{project_id}`-scoped
    route depends on this instead of trusting the path parameter
    directly. A nonexistent project id is rejected here, uniformly,
    before any route-specific logic runs."""
    project = repository.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} does not exist.")
    return project
