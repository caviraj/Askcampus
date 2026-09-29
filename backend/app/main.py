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
from app.api import admin, chat, documents, health
from app.api.errors import (
    api_error_handler,
    provider_error_handler,
    validation_error_handler,
)
from app.config import Settings, get_settings
from app.db.client import close_db_client, init_db_client
from app.db.queries import (
    CHUNK_EMBEDDING_DIMENSIONS,
    reap_orphaned_processing_documents,
)
from app.logging_config import configure_logging
from app.providers.errors import ProviderError
from app.providers.gemini import GeminiProvider
from app.services.auth import TokenVerifier
from app.services.ratelimit import SlidingWindowRateLimiter

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
        _check_embedding_width(settings)
        await init_db_client(settings)
        await _reap_orphaned_documents()
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
    # Built once rather than per request: constructing a genai client builds an
    # HTTP connection pool, and doing that on every upload would throw it away
    # each time. No network call happens here.
    app.state.embedding_provider = GeminiProvider(settings)
    # One instance serves both protocols, but the two names say which one a call
    # site means -- an embedding failure and a generation failure are handled
    # differently, so the difference is worth spelling out where it is read.
    app.state.llm_provider = app.state.embedding_provider
    # Per app rather than module-level, so every test gets counters of its own.
    app.state.rate_limiter = SlidingWindowRateLimiter(limit=settings.chat_rate_limit_per_minute)

    # allow_credentials stays False: the access token travels in an
    # Authorization header, not a cookie, so credentialed CORS would buy nothing
    # while requiring exact origins.
    #
    # expose_headers is not optional. `Retry-After` is not a CORS-safelisted
    # response header, so without this the browser hides it from the 429 handler
    # on /chat: the request still fails correctly, and the countdown silently
    # falls back to a hardcoded default forever. Nothing else would report it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After"],
    )

    app.add_exception_handler(StarletteHTTPException, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # The provider SDK is the one dependency that can be up or down independently
    # of this process, and /chat is the first route that awaits it inline rather
    # than inside a background task -- where the failure would otherwise reach the
    # student as an unhandled 500.
    app.add_exception_handler(ProviderError, provider_error_handler)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(documents.router)
    app.include_router(chat.router)

    logger.info(
        "CampusAsk API %s starting in %s mode; CORS origins: %s",
        __version__,
        settings.environment,
        ", ".join(settings.cors_origins) or "(none)",
    )
    return app


def _check_embedding_width(settings: Settings) -> None:
    """Refuse to start if the configured vector width is not the column's.

    A mismatch would not surface until the first upload, as a pgvector cast error
    that never mentions dimensions -- and by then it arrives inside a background
    task, where it is recorded as a document failure rather than as the
    configuration mistake it is.
    """
    if settings.embedding_dimensions != CHUNK_EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS is {settings.embedding_dimensions} but the chunks "
            f"table stores vector({CHUNK_EMBEDDING_DIMENSIONS}). Set it to "
            f"{CHUNK_EMBEDDING_DIMENSIONS}, or add a migration that resizes the column."
        )


async def _reap_orphaned_documents() -> None:
    """Mark documents left mid-processing by a process that died.

    Ingestion runs as a background task, so it does not survive a kill -9 or a
    hard restart: the row stays `processing` with nothing working on it, and the
    admin sees a spinner that never resolves. At startup nothing in this process
    is processing, so there are no false positives.

    Best-effort, like the JWKS warm-up: an unreachable database at boot should not
    stop the app from starting, and the log says plainly what was missed.
    """
    try:
        count = await reap_orphaned_processing_documents()
    except Exception:  # noqa: BLE001 - startup must not fail on this
        logger.warning(
            "Could not check for interrupted document processing at startup.", exc_info=True
        )
        return

    if count:
        logger.warning(
            "Marked %d document(s) as failed: they were left mid-processing by a "
            "previous run and need reprocessing.",
            count,
        )


app = create_app()
