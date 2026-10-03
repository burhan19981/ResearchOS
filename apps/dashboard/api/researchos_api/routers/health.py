"""Health endpoint — reports actual backend/database availability, not
merely "the process started" (Dashboard V1 spec section 29)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

import researchos
from researchos.workflow.stages import STAGE_ORDER

from ..dependencies import get_db
from ..schemas.common import ComponentHealth, HealthResponse

router = APIRouter(tags=["health"])


def _check_database(db: Session) -> ComponentHealth:
    try:
        db.execute(text("SELECT 1"))
        return ComponentHealth(name="database", healthy=True)
    except Exception as exc:  # noqa: BLE001 - health check must never raise, only report
        return ComponentHealth(name="database", healthy=False, detail=str(exc))


def _check_workflow() -> ComponentHealth:
    try:
        healthy = len(STAGE_ORDER) == 20
        return ComponentHealth(
            name="workflow", healthy=healthy, detail=None if healthy else f"expected 20 stages, found {len(STAGE_ORDER)}"
        )
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="workflow", healthy=False, detail=str(exc))


def _check_evidence() -> ComponentHealth:
    try:
        import researchos.evidence  # noqa: F401 - import-only check, no network call

        return ComponentHealth(name="evidence", healthy=True)
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="evidence", healthy=False, detail=str(exc))


def _check_execution() -> ComponentHealth:
    try:
        from researchos.execution.local_executor import LocalPythonExecutor  # noqa: F401

        return ComponentHealth(name="execution", healthy=True)
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(name="execution", healthy=False, detail=str(exc))


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)) -> HealthResponse:
    components = [_check_database(db), _check_workflow(), _check_evidence(), _check_execution()]
    return HealthResponse(
        healthy=all(c.healthy for c in components), version=researchos.__version__, components=components
    )
