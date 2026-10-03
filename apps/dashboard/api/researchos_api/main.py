"""Dashboard V1's FastAPI application entry point.

Run locally with:

    uvicorn researchos_api.main:app --app-dir apps/dashboard/api --reload --port 8000

See docs/PHASE_DASHBOARD_V1.md for full local-development instructions.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .errors import register_exception_handlers
from .routers import (
    analysis,
    approvals,
    audit,
    experiments,
    gaps,
    health,
    literature,
    novelty,
    overview,
    pipeline,
    planning,
    projects,
    reviews,
    runs,
)

logging.basicConfig(level=logging.INFO)

API_PREFIX = "/api/v1"

app = FastAPI(
    title="ResearchOS Dashboard API",
    description="Thin, read-mostly API layer exposing the existing ResearchOS domain services to Dashboard V1.",
    version="0.1.0",
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
)

# Local-development-only CORS: the Vite dev server runs on a different
# origin/port than uvicorn. Dashboard V1 has no auth/session system to
# protect, so this is intentionally permissive for localhost only —
# tightening this for a real deployment is out of this phase's scope
# (see docs/PHASE_DASHBOARD_V1.md's Known Limitations).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_exception_handlers(app)

for router in (
    health.router,
    projects.router,
    overview.router,
    pipeline.router,
    literature.router,
    gaps.router,
    novelty.router,
    planning.router,
    experiments.router,
    runs.router,
    analysis.router,
    reviews.router,
    approvals.router,
    audit.router,
):
    app.include_router(router, prefix=API_PREFIX)
