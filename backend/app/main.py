"""FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import admin, health
from app.api.errors import api_error_handler, validation_error_handler
from app.config import Settings, get_settings
from app.db.client import close_db_client, init_db_client
from app.logging_config import configure_logging
from app.services.auth import TokenVerifier

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    A factory so tests can build an isolated app with injected settings, while
    the module-level `app` below keeps `uvicorn app.main:app` working.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_db_client(settings)
        # Best-effort: warms the JWKS cache but never fails startup, so the app
        # boots with no network.
        await app.state.token_verifier.warm_cache()
        try:
            yield
        finally:
            await close_db_client()

    app = FastAPI(title="CampusAsk API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(settings)

    # allow_credentials stays False: the access token travels in an
    # Authorization header, not a cookie, so credentialed CORS would buy nothing
    # while requiring exact origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_exception_handler(StarletteHTTPException, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health.router)
    app.include_router(admin.router)

    logger.info(
        "CampusAsk API %s starting in %s mode; CORS origins: %s",
        __version__,
        settings.environment,
        ", ".join(settings.cors_origins) or "(none)",
    )
    return app


app = create_app()
