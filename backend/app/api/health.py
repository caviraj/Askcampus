"""Liveness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.config import Settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Report that the process is up.

    Deliberately does not touch Supabase: a database readiness probe here would
    make the service report down whenever the database is unreachable, which is
    a different signal from "this process is alive".
    """
    settings: Settings = request.app.state.settings
    return HealthResponse(version=__version__, environment=settings.environment)
