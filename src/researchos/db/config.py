"""Database configuration loading.

The database URL is read from the `DATABASE_URL` environment variable
(optionally populated from a local `.env` file — never committed), so
switching from SQLite to PostgreSQL later is a configuration change, not
a code change. See `docs/PHASE3_DATABASE.md` for migration considerations.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# src/researchos/db/config.py -> parents[3] is the repository root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"

# Default SQLite database file: outside `src/`, alongside the other
# runtime/data directories established in Phase 1. Never committed —
# see `.gitignore`.
DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "researchos.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"


def load_dotenv_if_present() -> None:
    """Load variables from a local `.env` file, if one exists.

    Never overrides a variable already set in the real process
    environment, and never raises if the file is absent.
    """
    load_dotenv(dotenv_path=_ENV_FILE, override=False)


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    echo: bool


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_database_config() -> DatabaseConfig:
    """Load database configuration from the environment.

    `DATABASE_URL` may be any SQLAlchemy-supported URL (SQLite for
    local development/tests today; a `postgresql+psycopg://...` URL in
    a future phase). No credentials are ever hard-coded here.
    """
    load_dotenv_if_present()
    url = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    echo = _get_bool_env("RESEARCHOS_DB_ECHO", False)
    return DatabaseConfig(url=url, echo=echo)
