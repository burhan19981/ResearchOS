"""Normalized exceptions for the persistence layer.

Repository functions raise these instead of letting raw SQLAlchemy/DB
driver exceptions leak to callers, so application code has one small,
stable set of exceptions to handle regardless of the underlying
database engine (SQLite today, PostgreSQL potentially later).
"""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class for all normalized persistence-layer errors."""


class NotFoundError(DatabaseError):
    """Raised when a lookup by id (or other key) finds no matching row.

    Deliberately covers BOTH "no row with this id exists at all" and "a
    row with this id exists but belongs to a different project than the
    one the caller supplied" — the repository layer is intentionally a
    low-level existence/integrity boundary, not the place that
    distinguishes those two cases for the caller (audited and confirmed
    during the Phase 7 post-implementation audit, Finding D). Callers
    that need that distinction go through a higher layer instead:
    `researchos.planning.orchestration.require_in_project()` raises the
    distinctly-typed `UnknownPlanningEntityError` vs.
    `CrossProjectReferenceError`, and every `researchos.planning`
    generation service is required to go through that layer (never a
    bare repository call) for exactly this reason. This boundary is
    deliberate, not an oversight: repository functions stay small,
    uniform, and reusable by any future layer with its own error
    vocabulary, rather than each carrying an opinion about which
    distinction its caller cares about.
    """


class ValidationError(DatabaseError):
    """Raised when a field fails an in-application validation rule.

    Distinct from `IntegrityConstraintError`: this is raised by model
    `@validates` methods *before* anything reaches the database.
    """


class IntegrityConstraintError(DatabaseError):
    """Raised when the database rejects a write for integrity reasons.

    Covers foreign-key violations (e.g. an orphaned `project_id`),
    uniqueness violations, and NOT NULL violations. Wraps
    `sqlalchemy.exc.IntegrityError` with a normalized message.
    """


class ConcurrencyConflictError(DatabaseError):
    """Raised when a caller-supplied expected-current-state does not
    match a row's actual current state (optimistic-concurrency check).

    Distinct from `IntegrityConstraintError`: the database itself would
    accept this write without complaint — this is an application-level
    compare-and-swap failure, used by
    `researchos.db.repository.update_run_lifecycle` so a `Run`'s status
    can never be blindly overwritten out from under a concurrent
    reader/writer.
    """
