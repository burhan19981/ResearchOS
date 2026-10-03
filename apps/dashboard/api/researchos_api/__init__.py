"""Dashboard V1's thin FastAPI layer over the existing ResearchOS
domain services (``researchos.*`` under ``src/``).

This package contains NO business logic of its own — every route
handler either reads through ``researchos.db.repository`` (read-only
GETs) or delegates to an existing ``approve_*``/``reject_*``/
``request_changes_*`` function in one of the domain layers' own
``approval.py`` modules (mutations). See
``docs/PHASE_DASHBOARD_V1.md`` for the full design.
"""

from __future__ import annotations

__version__ = "0.1.0"
