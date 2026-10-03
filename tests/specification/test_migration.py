"""Migration tests for the Phase 8A revision (984437859de2): upgrade,
downgrade, and re-upgrade round-trip on SQLite; new tables/columns
present; CHECK constraints enforced; FKs and uniqueness constraints
declared; populated-database safety. Uses the real Alembic path, not a
`create_all()` shortcut.
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

NEW_TABLES = {
    "dataset_versions",
    "experiment_specifications",
    "baseline_specifications",
    "experiment_specification_contributions",
    "experiment_specification_questions",
}


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@contextmanager
def _database_url_env(url: str):
    """See tests/planning/test_migration.py's identical helper for why
    this is required for any direct `alembic.command.*` call in a test."""
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
        # Head as of Phase 8 (researchos.analysis); was "91a24a97a7d4"
        # before that phase's own migration was appended.
        assert current_revision(db_url) == "3447e5ed59d4"
    finally:
        engine.dispose()


def test_upgrade_does_not_alter_existing_tables_beyond_the_check_constraint(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        # DatasetRecord (Phase 3) must be completely untouched.
        dataset_record_columns = {c["name"] for c in inspector.get_columns("dataset_records")}
        assert dataset_record_columns == {
            "project_id", "name", "version", "path_or_uri", "description", "split_information", "id", "created_at",
        }
        # Experiment/ExperimentResult (Phase 3) must be completely untouched.
        experiment_columns = {c["name"] for c in inspector.get_columns("experiments")}
        assert "dataset_version_id" not in experiment_columns  # no Phase 8A leakage into execution tracking
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips_cleanly(db_url: str):
    init_db(db_url)
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.downgrade(cfg, "18d5e18a097f")
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (NEW_TABLES & tables)
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
    # Head as of Phase 8; was "91a24a97a7d4" before that phase's own
    # migration was appended.
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert NEW_TABLES <= tables
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


def test_dataset_lifecycle_status_check_constraint_rejects_invalid_value(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO dataset_records (project_id, name, version, path_or_uri, created_at) "
                "VALUES (1, 'D', '1', 's3://x/', datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO dataset_versions (project_id, dataset_record_id, version, lifecycle_status, "
                    "created_at, updated_at) VALUES (1, 1, 1, 'NOT_A_REAL_STATUS', datetime('now'), datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_evidence_subject_type_check_constraint_admits_new_specification_types(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_links'"
            )).fetchone()
            create_sql = row[0]
            for member in ("DATASET_VERSION", "EXPERIMENT_SPECIFICATION"):
                assert member in create_sql
    finally:
        engine.dispose()


def test_supersedes_unique_constraints_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        dv_uniques = inspector.get_unique_constraints("dataset_versions")
        assert any(u["column_names"] == ["supersedes_id"] for u in dv_uniques)
        spec_uniques = inspector.get_unique_constraints("experiment_specifications")
        assert any(u["column_names"] == ["supersedes_id"] for u in spec_uniques)
    finally:
        engine.dispose()


def test_foreign_keys_declared_on_new_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        dv_fks = inspector.get_foreign_keys("dataset_versions")
        assert any(fk["referred_table"] == "dataset_records" for fk in dv_fks)
        spec_fks = inspector.get_foreign_keys("experiment_specifications")
        assert any(fk["referred_table"] == "dataset_versions" for fk in spec_fks)
        assert any(fk["referred_table"] == "experimental_designs" for fk in spec_fks)
        assert any(fk["referred_table"] == "methodology_plans" for fk in spec_fks)
    finally:
        engine.dispose()


# ===========================================================================
# Populated-database migration safety
#
# Phase 8A's migration only creates brand-new tables and widens one
# existing CHECK constraint (evidence_links.subject_type) — it never
# adds a NOT NULL column to an already-existing table, so it does not
# have the same class of risk Phase 6/7's migrations needed a
# server_default fix for. These tests verify that directly rather than
# assuming it, and additionally confirm every pre-existing Phase 7 row
# survives the upgrade untouched.
# ===========================================================================


def test_upgrade_succeeds_against_database_with_preexisting_phase7_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "18d5e18a097f")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('Existing Project', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO research_questions (project_id, question, status, planning_status, created_at) "
                "VALUES (1, 'A pre-existing question?', 'OPEN', 'APPROVED', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO contribution_candidates (project_id, title, description, planning_status, version, "
                "created_at, updated_at) VALUES (1, 'A pre-existing contribution', 'D', 'APPROVED', 1, "
                "datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO methodology_plans (project_id, description, status, version, planning_status, "
                "created_at, updated_at) VALUES (1, 'A pre-existing methodology.', 'DRAFT', 1, 'APPROVED', "
                "datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experimental_designs (project_id, planning_status, version, created_at, updated_at) "
                "VALUES (1, 'APPROVED', 1, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO dataset_records (project_id, name, version, path_or_uri, created_at) "
                "VALUES (1, 'A pre-existing dataset', '1', 's3://x/', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    # Head as of Phase 8; was "91a24a97a7d4" before that phase's own
    # migration was appended (none of Phase 8B-1/8B-2/8B-3/8's
    # migrations touch any table this test seeded, so none affects
    # what's asserted here).
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            question = conn.execute(text("SELECT question, planning_status FROM research_questions WHERE id = 1")).fetchone()
            assert question == ("A pre-existing question?", "APPROVED")
            contribution = conn.execute(text("SELECT title, planning_status FROM contribution_candidates WHERE id = 1")).fetchone()
            assert contribution == ("A pre-existing contribution", "APPROVED")
            methodology = conn.execute(text("SELECT description, planning_status FROM methodology_plans WHERE id = 1")).fetchone()
            assert methodology == ("A pre-existing methodology.", "APPROVED")
            design = conn.execute(text("SELECT planning_status FROM experimental_designs WHERE id = 1")).fetchone()
            assert design == ("APPROVED",)
            dataset = conn.execute(text("SELECT name FROM dataset_records WHERE id = 1")).fetchone()
            assert dataset == ("A pre-existing dataset",)

            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_upgrade_then_downgrade_preserves_preexisting_phase7_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "18d5e18a097f")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO dataset_records (project_id, name, version, path_or_uri, created_at) "
                "VALUES (1, 'D', '1', 's3://x/', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "18d5e18a097f")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM dataset_records")).scalar() == 1
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()
    assert current_revision(db_url) == "18d5e18a097f"
