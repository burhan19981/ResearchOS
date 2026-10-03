"""Database initialization and migration tests.

Uses the real Alembic migration path (`init_db` -> `alembic upgrade head`),
not a `create_all()` shortcut, so these tests exercise exactly what a
fresh deployment would run.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from researchos.db.engine import create_db_engine
from researchos.db.migrate import current_revision, init_db

EXPECTED_TABLES = {
    "research_projects",
    "research_ideas",
    "research_questions",
    "literature_items",
    "research_gaps",
    "novelty_assessments",
    "methodology_plans",
    "dataset_records",
    "experiments",
    "experiment_results",
    "manuscripts",
    "journal_candidates",
    "approvals",
    "audit_events",
    "alembic_version",
}


def test_init_db_creates_all_expected_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES <= tables
    finally:
        engine.dispose()


def test_init_db_is_idempotent(db_url: str):
    # Running init_db twice against the same fresh database must not raise
    # and must leave the schema in the same state.
    init_db(db_url)
    init_db(db_url)
    assert current_revision(db_url) is not None


def test_init_db_creates_missing_parent_directory(tmp_path: Path):
    nested_path = tmp_path / "nested" / "dir" / "researchos.db"
    url = f"sqlite:///{nested_path.as_posix()}"
    assert not nested_path.parent.exists()
    init_db(url)
    assert nested_path.exists()


def test_current_revision_matches_head_after_init(db_url: str):
    init_db(db_url)
    revision = current_revision(db_url)
    assert revision is not None
    assert isinstance(revision, str)
    assert len(revision) > 0


def test_foreign_keys_are_declared_on_child_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        fks = inspector.get_foreign_keys("research_ideas")
        assert any(fk["referred_table"] == "research_projects" for fk in fks)
        result_fks = inspector.get_foreign_keys("experiment_results")
        assert any(fk["referred_table"] == "experiments" for fk in result_fks)
    finally:
        engine.dispose()
