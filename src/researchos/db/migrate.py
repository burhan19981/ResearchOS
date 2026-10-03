"""Programmatic Alembic entry point: bring a database up to the latest schema.

The Alembic migration files under `migrations/versions/` are the single
source of truth for the schema — `init_db()` simply invokes
`alembic upgrade head` against the target database URL, so there is no
separate "quick create" schema definition that could drift from the
tracked migrations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from .config import load_database_config
from .engine import _ensure_sqlite_directory

# src/researchos/db/migrate.py -> parents[3] is the repository root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _PROJECT_ROOT / "migrations"


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def init_db(database_url: Optional[str] = None) -> None:
    """Initialize (or upgrade) a database to the latest schema.

    Safe to call repeatedly and on a brand-new, empty database file —
    Alembic tracks applied revisions in its own `alembic_version` table
    and only applies what is missing.

    `migrations/env.py` independently derives its target URL from
    `researchos.db.config.load_database_config()` (so plain `alembic
    upgrade head` on the command line works without going through this
    function at all). To make an explicit `database_url` override here
    actually take effect inside that separately-executed script, it is
    applied via the `DATABASE_URL` environment variable for the
    duration of this call — not only on the `Config` object — and
    restored afterward regardless of outcome.
    """
    url = database_url or load_database_config().url
    _ensure_sqlite_directory(url)
    previous_env_value = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(_alembic_config(url), "head")
    finally:
        if previous_env_value is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_env_value


def current_revision(database_url: Optional[str] = None) -> Optional[str]:
    """Return the current Alembic revision applied to the database, if any."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    url = database_url or load_database_config().url
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()
