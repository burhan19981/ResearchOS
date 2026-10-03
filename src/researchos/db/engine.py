"""Engine, session factory, and transaction-scope helpers.

Repository functions (see `researchos.db.repository`) take an explicit
`Session` argument rather than reaching into global state — this keeps
transaction boundaries under the caller's control and makes rollback
behavior straightforward to test. This module supplies the mechanism
for obtaining that session.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import load_database_config


def _ensure_sqlite_directory(url: str) -> None:
    """Create the parent directory of a `sqlite:///<path>` URL if needed.

    SQLite creates the database *file* itself but not missing parent
    directories. No-op for in-memory SQLite or non-SQLite URLs.
    """
    if not url.startswith("sqlite:///"):
        return
    raw_path = url[len("sqlite:///") :]
    if raw_path in ("", ":memory:"):
        return
    Path(raw_path).resolve().parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Turn on SQLite foreign-key enforcement for every new connection.

    SQLite ships with foreign keys OFF by default for backward
    compatibility; ResearchOS relies on FK constraints for data
    integrity, so this must be set per-connection.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001, ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(url: Optional[str] = None, *, echo: Optional[bool] = None) -> Engine:
    """Create a new SQLAlchemy engine.

    `url` and `echo` default to the environment-derived configuration
    (see `researchos.db.config.load_database_config`) when omitted.
    Callers that need an isolated engine (tests, scripts) can pass an
    explicit `url` instead of touching the process-wide default engine.
    """
    config = load_database_config()
    resolved_url = url or config.url
    resolved_echo = config.echo if echo is None else echo
    _ensure_sqlite_directory(resolved_url)
    engine = create_engine(resolved_url, echo=resolved_echo, future=True)
    if resolved_url.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)
    return engine


_default_engine: Optional[Engine] = None
_default_sessionmaker: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return the process-wide default engine, creating it on first use."""
    global _default_engine
    if _default_engine is None:
        _default_engine = create_db_engine()
    return _default_engine


def get_sessionmaker() -> sessionmaker:
    """Return the process-wide default session factory, creating it on first use."""
    global _default_sessionmaker
    if _default_sessionmaker is None:
        _default_sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _default_sessionmaker


def reset_default_engine() -> None:
    """Dispose of and clear the process-wide default engine/sessionmaker.

    Intended for tests that need a fresh engine bound to a different
    database URL within the same process; application code normally
    never needs to call this.
    """
    global _default_engine, _default_sessionmaker
    if _default_engine is not None:
        _default_engine.dispose()
    _default_engine = None
    _default_sessionmaker = None


@contextmanager
def session_scope(session_factory: Optional[sessionmaker] = None) -> Iterator[Session]:
    """Provide a transactional scope around a series of repository calls.

    Commits once on clean exit; on any exception, rolls back and
    re-raises so no partial write is ever left committed. The session
    is always closed afterward.

    ```python
    with session_scope() as session:
        project = repository.create_project(session, title="...")
        repository.append_audit_event(session, project_id=project.id, ...)
    # committed together, or rolled back together on any error
    ```
    """
    factory = session_factory or get_sessionmaker()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
