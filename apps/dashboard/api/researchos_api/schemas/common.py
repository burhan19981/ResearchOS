"""Shared response types."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    detail: str


class ComponentHealth(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    healthy: bool
    version: str
    components: list[ComponentHealth]
