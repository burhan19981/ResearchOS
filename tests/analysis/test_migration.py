"""Migration tests for the Phase 8 revision (3447e5ed59d4): upgrade,
downgrade, round-trip on SQLite; new tables/columns present; CHECK
constraints enforced; FKs declared; populated-database safety (seeding
pre-existing Phase 8B-3 rows before upgrading). Uses the real Alembic
path, not a `create_all()` shortcut — same pattern as
tests/execution/test_migration.py.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from researchos.db.engine import create_db_engine
from researchos.db.migrate import _ALEMBIC_INI, _MIGRATIONS_DIR, current_revision, init_db

NEW_TABLES = {"analysis_records", "analysis_inputs", "scientific_claims", "scientific_claim_analyses", "scientific_reviews"}
PREVIOUS_HEAD = "91a24a97a7d4"
NEW_HEAD = "3447e5ed59d4"


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@contextmanager
def _database_url_env(url: str):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_upgrade_creates_all_new_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert NEW_TABLES <= tables
        assert current_revision(db_url) == NEW_HEAD
    finally:
        engine.dispose()


def test_upgrade_does_not_alter_existing_execution_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        run_columns = {c["name"] for c in inspector.get_columns("runs")}
        assert "analysis_record_id" not in run_columns  # Run (Phase 8B-1) is genuinely untouched
        metric_columns = {c["name"] for c in inspector.get_columns("metrics")}
        assert "analysis_record_id" not in metric_columns
    finally:
        engine.dispose()


def test_no_temporary_alembic_tables_remain_after_upgrade(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips_cleanly(db_url: str):
    init_db(db_url)
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.downgrade(cfg, PREVIOUS_HEAD)
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (NEW_TABLES & tables)
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
    assert current_revision(db_url) == NEW_HEAD
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert NEW_TABLES <= tables
    finally:
        engine.dispose()


def test_analysis_record_status_check_constraint_rejects_invalid_value(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO analysis_records (project_id, method, result, status, version, created_at) "
                    "VALUES (1, 'pairwise_comparison', '{}', 'NOT_A_REAL_STATUS', 1, datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_scientific_review_status_check_constraint_rejects_invalid_value(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO scientific_claims (project_id, claim_text, strength, approval_status, version, "
                "created_at, updated_at) VALUES (1, 'A claim.', 'NOT_ASSESSABLE', 'PENDING_REVIEW', 1, "
                "datetime('now'), datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO scientific_reviews (project_id, claim_id, status, version, created_at, updated_at) "
                    "VALUES (1, 1, 'NOT_A_REAL_STATUS', 1, datetime('now'), datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_analysis_record_supersedes_unique_constraint_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        uniques = inspector.get_unique_constraints("analysis_records")
        assert any(u["column_names"] == ["supersedes_id"] for u in uniques)
    finally:
        engine.dispose()


def test_analysis_input_identity_unique_constraint_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        uniques = inspector.get_unique_constraints("analysis_inputs")
        assert any(set(u["column_names"]) == {"analysis_record_id", "input_type", "input_id"} for u in uniques)
    finally:
        engine.dispose()


def test_foreign_keys_declared_on_analysis_records(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        fks = inspector.get_foreign_keys("analysis_records")
        referred = {fk["referred_table"] for fk in fks}
        assert referred == {"research_projects", "analysis_records"}
    finally:
        engine.dispose()


def test_evidence_links_check_constraint_widened_to_admit_new_subject_types(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_links'"
            )).fetchone()
            create_sql = row[0]
            assert "SCIENTIFIC_CLAIM" in create_sql
            assert "ANALYSIS_RECORD" in create_sql
    finally:
        engine.dispose()


def test_evidence_links_check_constraint_rejects_unknown_subject_type(db_url: str):
    from sqlalchemy.orm import sessionmaker
    from researchos.db import repository

    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        with session_factory() as session:
            project = repository.create_project(session, title="P")
            repository.add_literature_item(
                session, project_id=project.id, title="A paper", source="openalex", source_record_id="W1",
            )
            session.commit()

        with engine.connect() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO evidence_links (project_id, literature_item_id, subject_type, subject_id, "
                    "relationship_type, created_at) VALUES (1, 1, 'NOT_A_REAL_SUBJECT_TYPE', 1, 'SUPPORTS', datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


# ===========================================================================
# Populated-database migration safety
# ===========================================================================


def test_upgrade_succeeds_against_database_with_preexisting_phase8b3_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, PREVIOUS_HEAD)

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('Existing Project', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiments (project_id, name, status, created_at) "
                "VALUES (1, 'A pre-existing experiment', 'PLANNED', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'SUCCEEDED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO metrics (project_id, run_id, name, value, value_type, created_at) "
                "VALUES (1, 1, 'f1', 0.8, 'FLOAT', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    assert current_revision(db_url) == NEW_HEAD
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            run = conn.execute(text("SELECT status FROM runs WHERE id = 1")).fetchone()
            assert run == ("SUCCEEDED",)
            metric = conn.execute(text("SELECT name, value FROM metrics WHERE id = 1")).fetchone()
            assert metric == ("f1", 0.8)

            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_upgrade_then_downgrade_preserves_preexisting_phase8b3_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, PREVIOUS_HEAD)

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiments (project_id, name, status, created_at) VALUES (1, 'E', 'PLANNED', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, PREVIOUS_HEAD)

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM experiments")).scalar() == 1
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
        tables = set(inspect(engine).get_table_names())
        assert not (NEW_TABLES & tables)
    finally:
        engine.dispose()
    assert current_revision(db_url) == PREVIOUS_HEAD


def test_downgrade_reverts_evidence_links_check_constraint(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, PREVIOUS_HEAD)

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_links'"
            )).fetchone()
            create_sql = row[0]
            assert "SCIENTIFIC_CLAIM" not in create_sql
            assert "ANALYSIS_RECORD" not in create_sql
    finally:
        engine.dispose()
