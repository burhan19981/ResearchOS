"""Structured error responses.

ResearchOS's domain error hierarchies are deliberately NOT unified
across layers (each phase's own package gets its own small
``errors.py``, per this codebase's package-independence convention —
see ``docs/PHASE_DASHBOARD_V1.md``). This module registers one FastAPI
exception handler per layer's own base exception class, each mapping
its known subclasses to an HTTP status code, so every domain error a
route handler lets propagate becomes a structured JSON body —
never a raw Python traceback, and never silently swallowed.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from researchos.analysis.errors import AnalysisError
from researchos.db.errors import DatabaseError
from researchos.execution.errors import ExecutionError
from researchos.intelligence.errors import IntelligenceError
from researchos.planning.errors import PlanningError
from researchos.specification.errors import SpecificationError
from researchos.workflow.errors import WorkflowError

logger = logging.getLogger("researchos_api")

# Exception class names, within a given layer's own hierarchy, that
# mean "the requester asked for something that does not exist" or
# "the requester is not allowed to do this" or "this was already
# decided" rather than an ordinary "the request was invalid" (the
# default for any other subclass of a known base).
_NOT_FOUND_NAMES = {
    "NotFoundError", "UnknownPlanningEntityError", "MissingEntityError", "CandidateNotFoundError",
    "ProjectNotFoundError", "ApprovalNotFoundError",
}
_FORBIDDEN_NAMES = {"CrossProjectReferenceError", "HumanOnlyActionError"}
_CONFLICT_NAMES = {
    "ApprovalAlreadyDecidedError", "ConcurrencyConflictError", "ConcurrentModificationError",
    "DuplicateArtifactError", "DuplicateRunError",
}


def _status_for(exc: Exception) -> int:
    name = type(exc).__name__
    if name in _NOT_FOUND_NAMES:
        return 404
    if name in _FORBIDDEN_NAMES:
        return 403
    if name in _CONFLICT_NAMES:
        return 409
    return 400


def _make_handler(base_name: str):
    def _handler(request: Request, exc: Exception) -> JSONResponse:
        status_code = _status_for(exc)
        logger.warning(
            "%s (%s) on %s %s: %s", type(exc).__name__, base_name, request.method, request.url.path, exc,
        )
        return JSONResponse(status_code=status_code, content={"error": type(exc).__name__, "detail": str(exc)})

    return _handler


def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"error": "InternalServerError", "detail": "An internal error occurred."}
    )


def register_exception_handlers(app: FastAPI) -> None:
    for base_class, name in (
        (DatabaseError, "DatabaseError"),
        (PlanningError, "PlanningError"),
        (WorkflowError, "WorkflowError"),
        (AnalysisError, "AnalysisError"),
        (ExecutionError, "ExecutionError"),
        (SpecificationError, "SpecificationError"),
        (IntelligenceError, "IntelligenceError"),
    ):
        app.add_exception_handler(base_class, _make_handler(name))
    app.add_exception_handler(Exception, unhandled_error_handler)
