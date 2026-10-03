"""Persistent state layer for ResearchOS.

This is the source of truth for research project state: projects, ideas,
questions, literature, gaps, novelty assessments, methodology, datasets,
experiments/results, manuscripts, journal candidates, approvals, and
audit events. See `docs/PHASE3_DATABASE.md` for the full design.

Application code should interact with this layer through:

- `researchos.db.repository` — persistence operations (no raw SQL needed)
- `researchos.db.engine` — engines, sessions, and `session_scope()`
- `researchos.db.migrate` — `init_db()` to bring a database up to date
- `researchos.db.models` — ORM model classes (for type hints / queries)
- `researchos.db.errors` — normalized exceptions

Nothing in this package makes an LLM API call, and nothing in this
package should ever be given real research data during development —
see `docs/PHASE3_DATABASE.md` for the testing approach.
"""

from . import errors, models, repository
from .config import DatabaseConfig, load_database_config
from .engine import (
    create_db_engine,
    get_engine,
    get_sessionmaker,
    reset_default_engine,
    session_scope,
)
from .migrate import init_db
from .models import Base

__all__ = [
    "Base",
    "DatabaseConfig",
    "load_database_config",
    "create_db_engine",
    "get_engine",
    "get_sessionmaker",
    "reset_default_engine",
    "session_scope",
    "init_db",
    "models",
    "repository",
    "errors",
]
