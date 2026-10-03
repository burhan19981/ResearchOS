"""Transaction handling and rollback behavior tests."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from researchos.db import repository
from researchos.db.engine import session_scope
from researchos.db.errors import IntegrityConstraintError, NotFoundError
from researchos.db.models import ResearchProject


def test_session_scope_commits_on_success(session_factory: sessionmaker):
    with session_scope(session_factory) as session:
        repository.create_project(session, title="Committed Project")

    with session_factory() as verify_session:
        projects = repository.list_projects(verify_session)
        assert [p.title for p in projects] == ["Committed Project"]


def test_session_scope_rolls_back_on_exception(session_factory: sessionmaker):
    with pytest.raises(RuntimeError):
        with session_scope(session_factory) as session:
            repository.create_project(session, title="Should Not Persist")
            raise RuntimeError("simulated failure mid-transaction")

    with session_factory() as verify_session:
        assert repository.list_projects(verify_session) == []


def test_session_scope_rolls_back_multi_step_transaction_atomically(session_factory: sessionmaker):
    """A later failure must undo earlier writes in the same transaction."""
    with pytest.raises(NotFoundError):
        with session_scope(session_factory) as session:
            project = repository.create_project(session, title="Atomic Project")
            repository.append_audit_event(
                session, project_id=project.id, event_type="created", actor="test"
            )
            # This fails because experiment 999999 does not exist.
            repository.record_experiment_result(
                session, experiment_id=999_999, metric_name="accuracy", metric_value=0.9
            )

    with session_factory() as verify_session:
        assert repository.list_projects(verify_session) == []


def test_integrity_error_triggers_rollback_of_the_offending_statement(session_factory: sessionmaker):
    session = session_factory()
    try:
        project = repository.create_project(session, title="Dup Version Project")
        session.commit()
        repository.create_methodology_version(
            session, project_id=project.id, description="v1", version=1
        )
        session.commit()
        with pytest.raises(IntegrityConstraintError):
            repository.create_methodology_version(
                session, project_id=project.id, description="duplicate v1", version=1
            )
        # Session must still be usable after the repository layer rolled back.
        plans = repository.list_methodology_plans(session, project.id)
        assert len(plans) == 1
    finally:
        session.close()


def test_get_engine_and_sessionmaker_are_lazy_singletons(monkeypatch, tmp_path):
    from researchos.db import engine as engine_module

    engine_module.reset_default_engine()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'singleton.db').as_posix()}")
    monkeypatch.setattr("researchos.db.config.load_dotenv", lambda *a, **k: None)
    try:
        first = engine_module.get_engine()
        second = engine_module.get_engine()
        assert first is second
    finally:
        engine_module.reset_default_engine()
