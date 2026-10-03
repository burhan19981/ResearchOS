"""Migration tests for the Phase 7 revision (18d5e18a097f): upgrade,
downgrade, and re-upgrade round-trip on SQLite, new tables/columns
present, CHECK constraints enforced, FKs declared, uniqueness
constraints declared. Uses the real Alembic path, not a `create_all()`
shortcut.
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
    "contribution_candidates",
    "contribution_candidate_questions",
    "dataset_requirements",
    "experimental_designs",
    "experimental_design_questions",
}


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@contextmanager
def _database_url_env(url: str):
    """migrations/env.py always derives its target URL from
    `researchos.db.config.load_database_config()` (an environment
    variable), ignoring whatever is set on the `Config` object directly
    — the same reason `researchos.db.migrate.init_db()` temporarily sets
    this env var. Any direct `alembic.command.*` call in a test MUST do
    the same, or it silently operates against the real default database
    (`data/researchos.db`) instead of the test's temp file."""
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
        # before that phase's own migration was appended,
        # "a4d80d49ae32" before Phase 8B-2's, "b03b320a103c" before
        # Phase 8B-1's, "984437859de2" before Phase 8A's, and
        # "18d5e18a097f" before Phase 7's own.
        assert current_revision(db_url) == "3447e5ed59d4"
    finally:
        engine.dispose()


def test_upgrade_extends_existing_tables_with_new_columns(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        question_columns = {c["name"] for c in inspector.get_columns("research_questions")}
        assert {"hypothesis", "planning_status"} <= question_columns
        plan_columns = {c["name"] for c in inspector.get_columns("methodology_plans")}
        assert {"planning_status", "methodology_type", "contribution_candidate_id"} <= plan_columns
        novelty_columns = {c["name"] for c in inspector.get_columns("novelty_assessments")}
        assert "contribution_candidate_id" in novelty_columns
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips_cleanly(db_url: str):
    init_db(db_url)
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.downgrade(cfg, "1e460d99a95b")
    engine = create_db_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not (NEW_TABLES & tables)
        question_columns = {c["name"] for c in inspect(engine).get_columns("research_questions")}
        assert "planning_status" not in question_columns
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


def test_planning_status_check_constraint_rejects_invalid_value(db_url: str):
    # SQLAlchemy's Enum(native_enum=False) stores the Python enum
    # MEMBER NAME (e.g. 'ACTIVE', 'OPEN') in the column by default, not
    # `.value` — confirmed directly against the rendered CHECK
    # constraints in migrations/versions/18d5e18a097f_*.py.
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
                    "INSERT INTO research_questions (project_id, question, status, planning_status, created_at) "
                    "VALUES (1, 'Q?', 'OPEN', 'NOT_A_REAL_STATUS', datetime('now'))"
                ))
                conn.commit()
    finally:
        engine.dispose()


def test_evidence_subject_type_check_constraint_admits_new_planning_types(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_links'"
            )).fetchone()
            create_sql = row[0]
            for member in ("RESEARCH_QUESTION", "CONTRIBUTION_CANDIDATE", "METHODOLOGY_PLAN",
                            "DATASET_REQUIREMENTS", "EXPERIMENTAL_DESIGN"):
                assert member in create_sql
    finally:
        engine.dispose()


def test_association_table_unique_constraints_declared(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        cc_uniques = inspector.get_unique_constraints("contribution_candidate_questions")
        assert any(set(u["column_names"]) == {"contribution_candidate_id", "research_question_id"} for u in cc_uniques)
        ed_uniques = inspector.get_unique_constraints("experimental_design_questions")
        assert any(set(u["column_names"]) == {"experimental_design_id", "research_question_id"} for u in ed_uniques)
    finally:
        engine.dispose()


def test_foreign_keys_declared_on_new_tables(db_url: str):
    init_db(db_url)
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        methodology_fks = inspector.get_foreign_keys("methodology_plans")
        assert any(fk["referred_table"] == "contribution_candidates" for fk in methodology_fks)
        design_fks = inspector.get_foreign_keys("experimental_designs")
        assert any(fk["referred_table"] == "methodology_plans" for fk in design_fks)
        assert any(fk["referred_table"] == "dataset_requirements" for fk in design_fks)
    finally:
        engine.dispose()


# ===========================================================================
# Populated-database migration safety (audit remediation: Finding A)
#
# Every test above builds a database from empty via the full migration
# chain in one run, so the affected tables never have pre-existing rows
# at the moment each migration touches them — which is exactly why the
# original NOT-NULL-without-server_default gap in both
# 18d5e18a097f_research_planning_layer.py (research_questions.
# planning_status, methodology_plans.planning_status) and
# 1e460d99a95b_research_intelligence_layer.py (novelty_assessments.
# candidate_status) went undetected. These tests instead reach an
# EARLIER revision first, insert real rows via raw SQL (simulating a
# genuinely-used pre-existing database), and only then upgrade further —
# reproducing the exact scenario the audit found broken.
# ===========================================================================


def test_phase7_upgrade_succeeds_against_database_with_preexisting_phase6_rows(db_url: str):
    """Database A (audit remediation spec): migrate to Phase 6 head,
    insert a ResearchQuestion / MethodologyPlan / NoveltyAssessment row,
    then upgrade to Phase 7 head. Must succeed, preserve every row, and
    backfill each new status column with its correct default value —
    never merely "some value that happens to satisfy the constraint"."""
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "1e460d99a95b")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('Existing Project', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO research_questions (project_id, question, status, created_at) "
                "VALUES (1, 'A pre-existing question?', 'OPEN', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO methodology_plans (project_id, description, status, version, created_at, updated_at) "
                "VALUES (1, 'A pre-existing methodology.', 'DRAFT', 1, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO novelty_assessments (project_id, claim, status, candidate_status, assessed_at) "
                "VALUES (1, 'A pre-existing claim.', 'PENDING', 'NOT_ASSESSED', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")  # must not raise

    # Head as of Phase 8; was "91a24a97a7d4" before that phase's own
    # migration was appended (none of these phases' migrations touch
    # any table this test seeded, so none affects what's asserted here).
    assert current_revision(db_url) == "3447e5ed59d4"
    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            question = conn.execute(text(
                "SELECT question, planning_status FROM research_questions WHERE id = 1"
            )).fetchone()
            assert question == ("A pre-existing question?", "CANDIDATE")

            plan = conn.execute(text(
                "SELECT description, planning_status FROM methodology_plans WHERE id = 1"
            )).fetchone()
            assert plan == ("A pre-existing methodology.", "CANDIDATE")

            assessment = conn.execute(text(
                "SELECT claim, candidate_status FROM novelty_assessments WHERE id = 1"
            )).fetchone()
            assert assessment == ("A pre-existing claim.", "NOT_ASSESSED")

            # No lingering server_default on any of the three columns —
            # the final schema must be identical to the empty-database case.
            for table in ("research_questions", "methodology_plans", "novelty_assessments"):
                create_sql = conn.execute(text(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"
                ), {"t": table}).fetchone()[0]
                assert "DEFAULT" not in create_sql.upper()

            stray = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'"
            )).fetchall()
            assert stray == []
    finally:
        engine.dispose()


def test_phase7_upgrade_then_downgrade_preserves_preexisting_rows(db_url: str):
    """The same populated database, additionally verifying downgrade
    (Phase 7 -> Phase 6, and the full chain to base) leaves every
    pre-existing row intact throughout."""
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "1e460d99a95b")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO research_questions (project_id, question, status, created_at) "
                "VALUES (1, 'Q?', 'OPEN', datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO methodology_plans (project_id, description, status, version, created_at, updated_at) "
                "VALUES (1, 'M.', 'DRAFT', 1, datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO novelty_assessments (project_id, claim, status, candidate_status, assessed_at) "
                "VALUES (1, 'C.', 'PENDING', 'NOT_ASSESSED', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "1e460d99a95b")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM research_questions")).scalar() == 1
            assert conn.execute(text("SELECT COUNT(*) FROM methodology_plans")).scalar() == 1
            assert conn.execute(text("SELECT COUNT(*) FROM novelty_assessments")).scalar() == 1
            stray = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp%'"
            )).fetchall()
            assert stray == []
    finally:
        engine.dispose()
    assert current_revision(db_url) == "1e460d99a95b"

    with _database_url_env(db_url):
        command.downgrade(cfg, "base")  # exercises 1e460d99a95b's own downgrade too — must not raise

    # "base" means no migrations applied at all — the tables themselves
    # are gone at this point (this is the initial schema's own
    # downgrade(), not something Phase 7 controls), so there is nothing
    # left to assert about row counts; reaching here without an
    # exception is the assertion.
    assert current_revision(db_url) is None


def test_phase6_upgrade_succeeds_against_database_with_preexisting_novelty_assessment_row(db_url: str):
    """The inherited Phase 6 gap in isolation: a database that already
    has a `novelty_assessments` row from BEFORE 1e460d99a95b ever ran
    (i.e. seeded at the prior revision, a8116c2a3b87) must still upgrade
    through 1e460d99a95b cleanly."""
    cfg = _alembic_config(db_url)
    with _database_url_env(db_url):
        command.upgrade(cfg, "a8116c2a3b87")

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO research_projects (title, status, created_at, updated_at) "
                "VALUES ('P', 'ACTIVE', datetime('now'), datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO novelty_assessments (project_id, claim, status, assessed_at) "
                "VALUES (1, 'A pre-Phase-6 claim.', 'PENDING', datetime('now'))"
            ))
            conn.commit()
    finally:
        engine.dispose()

    with _database_url_env(db_url):
        command.upgrade(cfg, "1e460d99a95b")  # must not raise

    engine = create_db_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT claim, candidate_status FROM novelty_assessments WHERE id = 1"
            )).fetchone()
            assert row == ("A pre-Phase-6 claim.", "NOT_ASSESSED")
    finally:
        engine.dispose()
