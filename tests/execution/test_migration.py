"""Migration tests for the Phase 8B-1 revision (b03b320a103c), the
Phase 8B-2 revision (a4d80d49ae32), and the Phase 8B-3 revision
(91a24a97a7d4) on top of them: upgrade, downgrade, round-trip on
SQLite; new tables/columns present; CHECK constraints enforced; FKs
declared; populated-database safety for all three phases. Uses the
real Alembic path, not a `create_all()` shortcut.

The `current_revision(db_url) == ...` assertions in this file have now
been updated three times — from `"b03b320a103c"` to `"a4d80d49ae32"`
(Phase 8B-2's own migration), then to `"91a24a97a7d4"` (Phase 8B-3's),
and now to `"3447e5ed59d4"` (Phase 8's `researchos.analysis` migration,
on top of this layer) — each time only the literal head revision
string changed; the schema facts each test actually checks (the
`runs`/`environment_snapshots`/`artifact_metadata`/`metrics` tables
exist, FKs are declared, etc.) remain true at the new head.
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

NEW_TABLES = {"runs", "environment_snapshots", "artifact_metadata"}


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
        # Head as of Phase 8; was "91a24a97a7d4" before that phase's
        # migration was appended (see module docstring).
        assert current_revision(db_url) == "3447e5ed59d4"
    finally:
        engine.dispose()


def test_upgrade_does_not_alter_existing_phase8a_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        dataset_version_columns = {c["name"] for c in inspector.get_columns("dataset_versions")}
        assert "run_id" not in dataset_version_columns  # no Phase 8B-1 leakage into Phase 8A tables
        spec_columns = {c["name"] for c in inspector.get_columns("experiment_specifications")}
        assert "run_id" not in spec_columns
        experiment_columns = {c["name"] for c in inspector.get_columns("experiments")}
        assert "run_id" not in experiment_columns  # Experiment (Phase 3) is genuinely untouched
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips_cleanly(db_url: str):
    init_db(db_url)
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.downgrade(cfg, "984437859de2")
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (NEW_TABLES & tables)
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
    # Head as of Phase 8; was "91a24a97a7d4" before that phase's
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


def test_run_status_check_constraint_rejects_invalid_value(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiments (project_id, name, status, created_at) "
                "VALUES (1, 'E', 'PLANNED', datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                    "created_at, updated_at) VALUES (1, 1, 'NOT_A_REAL_STATUS', 'LOCAL_PYTHON', 30, "
                    "datetime('now'), datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_environment_snapshot_hash_unique_constraint_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        uniques = inspector.get_unique_constraints("environment_snapshots")
        assert any(u["column_names"] == ["environment_hash"] for u in uniques)
    finally:
        engine.dispose()


def test_foreign_keys_declared_on_runs(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        fks = inspector.get_foreign_keys("runs")
        referred = {fk["referred_table"] for fk in fks}
        assert referred == {"experiments", "experiment_specifications", "dataset_versions", "environment_snapshots", "research_projects"}
        experiment_fk = next(fk for fk in fks if fk["referred_table"] == "experiments")
        assert experiment_fk["options"].get("ondelete") == "CASCADE"
    finally:
        engine.dispose()


def test_environment_snapshots_table_has_no_project_id_column(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("environment_snapshots")}
        assert "project_id" not in columns
    finally:
        engine.dispose()


# ===========================================================================
# Populated-database migration safety
# ===========================================================================


def test_upgrade_succeeds_against_database_with_preexisting_phase8a_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "984437859de2")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('Existing Project', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO dataset_records (project_id, name, version, path_or_uri, created_at) "
                "VALUES (1, 'A pre-existing dataset', '1', 's3://x/', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO dataset_versions (project_id, dataset_record_id, version, lifecycle_status, "
                "created_at, updated_at) VALUES (1, 1, 1, 'APPROVED', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiment_specifications (project_id, version, planning_status, created_at, updated_at) "
                "VALUES (1, 1, 'APPROVED', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiments (project_id, name, status, created_at) "
                "VALUES (1, 'A pre-existing experiment', 'PLANNED', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    # Head as of Phase 8; was "91a24a97a7d4" before that phase's
    # migration was appended.
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            dataset = conn.execute(text("SELECT lifecycle_status FROM dataset_versions WHERE id = 1")).fetchone()
            assert dataset == ("APPROVED",)
            spec = conn.execute(text("SELECT planning_status FROM experiment_specifications WHERE id = 1")).fetchone()
            assert spec == ("APPROVED",)
            experiment = conn.execute(text("SELECT name FROM experiments WHERE id = 1")).fetchone()
            assert experiment == ("A pre-existing experiment",)

            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_upgrade_then_downgrade_preserves_preexisting_phase8a_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "984437859de2")

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
        command.downgrade(cfg, "984437859de2")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM dataset_records")).scalar() == 1
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()
    assert current_revision(db_url) == "984437859de2"


# ===========================================================================
# Phase 8B-2 (a4d80d49ae32): metrics table, artifact_metadata extensions,
# environment_snapshots extensions.
# ===========================================================================


def test_upgrade_creates_metrics_table(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        assert "metrics" in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_artifact_metadata_has_new_phase8b2_columns(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("artifact_metadata")}
        assert {"logical_name", "source", "description"} <= columns
    finally:
        engine.dispose()


def test_artifact_metadata_logical_name_unique_per_run(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        uniques = inspector.get_unique_constraints("artifact_metadata")
        assert any(set(u["column_names"]) == {"run_id", "logical_name"} for u in uniques)
    finally:
        engine.dispose()


def test_duplicate_logical_name_for_same_run_rejected(db_url: str):
    init_db(db_url)
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
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'CREATED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO artifact_metadata (project_id, run_id, logical_name, artifact_type, reference, created_at) "
                "VALUES (1, 1, 'stdout', 'STDOUT', '/tmp/a.log', datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO artifact_metadata (project_id, run_id, logical_name, artifact_type, reference, created_at) "
                    "VALUES (1, 1, 'stdout', 'STDERR', '/tmp/b.log', datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_artifact_type_check_constraint_admits_new_members(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='artifact_metadata'"
            )).fetchone()
            create_sql = row[0]
            for member in ("METRIC_REPORT", "RESULT_MANIFEST"):
                assert member in create_sql
            assert "'RESULT'" not in create_sql  # renamed, not kept alongside RESULT_MANIFEST
    finally:
        engine.dispose()


def test_metric_value_type_check_constraint_rejects_invalid_value(db_url: str):
    init_db(db_url)
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
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'CREATED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO metrics (project_id, run_id, name, value, value_type, created_at) "
                    "VALUES (1, 1, 'accuracy', 0.9, 'NOT_A_REAL_TYPE', datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_environment_snapshots_has_new_phase8b2_columns(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("environment_snapshots")}
        assert {"cpu_model", "cpu_count", "total_memory_bytes", "researchos_version"} <= columns
    finally:
        engine.dispose()


def test_metrics_foreign_keys_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        fks = inspect(engine).get_foreign_keys("metrics")
        referred = {fk["referred_table"] for fk in fks}
        assert referred == {"research_projects", "runs", "artifact_metadata"}
    finally:
        engine.dispose()


def test_no_uniqueness_constraint_on_metric_name_per_run(db_url: str):
    """The same metric name must be insertable multiple times for one
    Run (different splits/evaluations) — Phase 8B-2 spec section 24."""
    init_db(db_url)
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
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'CREATED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO metrics (project_id, run_id, name, value, value_type, split, created_at) "
                "VALUES (1, 1, 'accuracy', 0.9, 'FLOAT', 'train', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO metrics (project_id, run_id, name, value, value_type, split, created_at) "
                "VALUES (1, 1, 'accuracy', 0.95, 'FLOAT', 'test', datetime('now'))"
            ))  # must not raise — same name, same run, different split
            conn.commit()
            count = conn.execute(text("SELECT COUNT(*) FROM metrics WHERE name = 'accuracy'")).scalar()
            assert count == 2
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Populated-Phase-8B-1-database safety: the logical_name backfill.
# ---------------------------------------------------------------------------


def test_phase8a_rows_survive_8b2_migration_unchanged(db_url: str):
    """Phase 8A's own tables (`dataset_versions`, `experiment_specifications`)
    are never touched by the 8B-2 migration — verified directly against
    a database seeded at the Phase 8A head, upgraded all the way to the
    new Phase 8B-2 head."""
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "984437859de2")

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
            conn.execute(text(
                "INSERT INTO dataset_versions (project_id, dataset_record_id, version, lifecycle_status, "
                "content_fingerprint, created_at, updated_at) "
                "VALUES (1, 1, 1, 'APPROVED', 'deadbeef', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiment_specifications (project_id, version, planning_status, configuration_hash, "
                "created_at, updated_at) VALUES (1, 1, 'APPROVED', 'cafebabe', datetime('now'), datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            dataset_version = conn.execute(text(
                "SELECT lifecycle_status, content_fingerprint FROM dataset_versions WHERE id = 1"
            )).fetchone()
            assert dataset_version == ("APPROVED", "deadbeef")
            spec = conn.execute(text(
                "SELECT planning_status, configuration_hash FROM experiment_specifications WHERE id = 1"
            )).fetchone()
            assert spec == ("APPROVED", "cafebabe")
    finally:
        engine.dispose()
    # Head as of Phase 8; was "91a24a97a7d4" before that phase's
    # migration was appended.
    assert current_revision(db_url) == "3447e5ed59d4"


def test_upgrade_backfills_logical_name_for_preexisting_phase8b1_artifacts(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "b03b320a103c")

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
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'SUCCEEDED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            # Two pre-existing artifact rows for the SAME run — exactly
            # the shape Phase 8B-1's own orchestrator would have produced.
            conn.execute(text(
                "INSERT INTO artifact_metadata (project_id, run_id, artifact_type, reference, size_bytes, created_at) "
                "VALUES (1, 1, 'STDOUT', '/tmp/stdout.log', 10, datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO artifact_metadata (project_id, run_id, artifact_type, reference, size_bytes, created_at) "
                "VALUES (1, 1, 'STDERR', '/tmp/stderr.log', 0, datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise — no unique-constraint collision on backfill

    # Head as of Phase 8; was "91a24a97a7d4" before that phase's
    # migration was appended.
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT artifact_type, logical_name, reference FROM artifact_metadata ORDER BY id"
            )).fetchall()
            assert rows == [
                ("STDOUT", "stdout", "/tmp/stdout.log"),
                ("STDERR", "stderr", "/tmp/stderr.log"),
            ]
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_downgrade_from_phase8b2_preserves_phase8b1_artifact_rows(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "b03b320a103c")

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
            conn.execute(text(
                "INSERT INTO runs (project_id, experiment_id, status, execution_backend, timeout_seconds, "
                "created_at, updated_at) VALUES (1, 1, 'SUCCEEDED', 'LOCAL_PYTHON', 30, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO artifact_metadata (project_id, run_id, artifact_type, reference, created_at) "
                "VALUES (1, 1, 'STDOUT', '/tmp/stdout.log', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "b03b320a103c")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            columns = {c["name"] for c in inspect(engine).get_columns("artifact_metadata")}
            assert "logical_name" not in columns
            row = conn.execute(text("SELECT artifact_type, reference FROM artifact_metadata")).fetchone()
            assert row == ("STDOUT", "/tmp/stdout.log")
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()
    assert current_revision(db_url) == "b03b320a103c"


# ===========================================================================
# Phase 8B-3 (91a24a97a7d4): experiment_specifications.experiment_id
# ===========================================================================


def test_upgrade_adds_experiment_id_column(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("experiment_specifications")}
        assert "experiment_id" in columns
    finally:
        engine.dispose()


def test_experiment_id_foreign_key_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        fks = inspect(engine).get_foreign_keys("experiment_specifications")
        experiment_fk = next(fk for fk in fks if fk["referred_table"] == "experiments")
        assert experiment_fk["constrained_columns"] == ["experiment_id"]
        assert experiment_fk["options"].get("ondelete") == "SET NULL"
    finally:
        engine.dispose()


def test_upgrade_against_populated_phase8a_database_leaves_experiment_id_null(db_url: str):
    """A pre-existing Phase 8A specification has no way to have ever
    recorded an experiment link — the new column must be nullable and
    backfilled to NULL (never fabricated) for such rows."""
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "a4d80d49ae32")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO experiment_specifications (project_id, version, planning_status, created_at, updated_at) "
                "VALUES (1, 1, 'APPROVED', datetime('now'), datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    # Head as of Phase 8; was "91a24a97a7d4" before that phase's
    # migration was appended.
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT experiment_id, planning_status FROM experiment_specifications WHERE id = 1")).fetchone()
            assert row == (None, "APPROVED")
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_downgrade_from_phase8b3_drops_experiment_id_preserves_data(db_url: str):
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "head")

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
            conn.execute(text(
                "INSERT INTO experiment_specifications (project_id, experiment_id, version, planning_status, created_at, updated_at) "
                "VALUES (1, 1, 1, 'APPROVED', datetime('now'), datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.downgrade(cfg, "a4d80d49ae32")

    engine = create_db_engine(db_url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("experiment_specifications")}
        assert "experiment_id" not in columns
        with engine.connect() as conn:
            row = conn.execute(text("SELECT planning_status FROM experiment_specifications WHERE id = 1")).fetchone()
            assert row == ("APPROVED",)
            stray = conn.execute(text("SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'")).fetchall()
            assert stray == []
    finally:
        engine.dispose()
    assert current_revision(db_url) == "a4d80d49ae32"
