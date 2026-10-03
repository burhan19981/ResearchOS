"""Alembic environment script.

Reads the target database URL from `researchos.db.config` (environment
variables / local `.env`) rather than a hard-coded value in
`alembic.ini`, and targets `researchos.db.models.Base.metadata` so
`alembic revision --autogenerate` compares against the real ORM models.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `src/` importable when Alembic is invoked directly (not via `pip install -e .`).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from researchos.db.config import load_database_config  # noqa: E402
from researchos.db.models import Base  # noqa: E402

# this is the Alembic Config object, which provides access to values
# within the .ini file in use.
config = context.config

# Override whatever is in alembic.ini with the real, environment-derived URL.
config.set_main_option("sqlalchemy.url", load_database_config().url)

# Interpret the config file for Python logging, if a logging section is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live DB connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Batch mode lets SQLite (which cannot ALTER most column
            # constraints in place) apply future migrations by
            # rebuilding tables under the hood; a no-op on PostgreSQL.
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
