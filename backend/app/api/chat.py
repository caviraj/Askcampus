"""Student chat routes: ask a question, rate the answer, list the chips.

None of these require a token. `AGENTS.md` section 12 puts student login out of
scope for v1, so a student is a random session id and nothing else -- which is
also why `/chat/feedback` takes the session id in its body: it is the only thing
that can establish that the caller is entitled to rate a given query.

The work that costs a network round trip sits *after* validation and rate
limiting, so a malformed or over-limit request is refused before anything is
spent on it.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.errors import ApiError
from app.config import Settings
from app.schemas.chat import (
    CategoryListResponse,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
)
from app.services.answering import AnsweringService
from app.services.classifier import category_chips
from app.services.embedding import EmbeddingService, SupabaseEmbeddingCache
from app.services.query_log import QueryLogRepository, SupabaseQueryLogRepository
from app.services.ratelimit import SlidingWindowRateLimiter
from app.services.retrieval import ChunkRepository, RetrievalService, SupabaseChunkRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

# DESIGN_SYSTEM.md section 9, verbatim.
RATE_LIMITED_MESSAGE = "Too many questions in a short time. Wait a minute and ask again."


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_chunk_repository() -> ChunkRepository:
    """Overridden in tests with an in-memory implementation."""
    return SupabaseChunkRepository()


def get_query_log_repository() -> QueryLogRepository:
    """Overridden in tests with an in-memory implementation."""
    return SupabaseQueryLogRepository()


def get_embedding_service(request: Request) -> EmbeddingService:
    settings: Settings = request.app.state.settings
    return EmbeddingService(
        # Built once at app creation. Constructing a genai client builds an HTTP
        # connection pool, and doing that per question would discard it each time.
        provider=request.app.state.embedding_provider,
        settings=settings,
        cache=SupabaseEmbeddingCache(),
    )


def get_retrieval_service(
    request: Request,
    repository: Annotated[ChunkRepository, Depends(get_chunk_repository)],
    embeddings: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> RetrievalService:
    settings: Settings = request.app.state.settings
    return RetrievalService(embeddings, repository, settings)


def get_answering_service(
    request: Request,
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
    query_log: Annotated[QueryLogRepository, Depends(get_query_log_repository)],
) -> AnsweringService:
    return AnsweringService(
        retrieval=retrieval,
        llm=request.app.state.llm_provider,
        query_log=query_log,
    )


AnsweringDep = Annotated[AnsweringService, Depends(get_answering_service)]
QueryLogDep = Annotated[QueryLogRepository, Depends(get_query_log_repository)]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse, summary="Ask a question")
async def ask_question(
    payload: ChatRequest, request: Request, answering: AnsweringDep
) -> ChatResponse:
    """Answer from the college documents, or say plainly that it cannot."""
    settings: Settings = request.app.state.settings
    _check_lengths(payload, settings)
    _check_rate_limit(request, payload.session_id, settings)

    outcome = await answering.answer(
        session_id=payload.session_id,
        question=payload.question,
        history=payload.history,
        requested_category=payload.category,
    )
    return ChatResponse(
        query_id=outcome.query_id,
        answered=outcome.answered,
        category=outcome.category,
        answer=outcome.answer,
        citations=outcome.citations,
        office=outcome.office,
    )


@router.post("/chat/feedback", status_code=204, summary="Rate an answer")
async def rate_answer(payload: FeedbackRequest, query_log: QueryLogDep) -> Response:
    """Record helpful or not helpful for one query.

    A query belonging to another session is reported as not found rather than as
    forbidden. The two are deliberately indistinguishable: a 403 would confirm
    that the query id exists, and confirming anything at all is what an
    unauthenticated route must not do.
    """
    recorded = await query_log.record_feedback(
        query_id=payload.query_id,
        session_id=payload.session_id,
        helpful=payload.helpful,
    )
    if not recorded:
        raise ApiError(404, "That question is not available to rate.", "not_found")
    return Response(status_code=204)


@router.get("/categories", response_model=CategoryListResponse, summary="Category chips")
async def list_categories() -> CategoryListResponse:
    """The chips the student UI shows, each with its starter questions."""
    return CategoryListResponse(categories=category_chips())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_lengths(payload: ChatRequest, settings: Settings) -> None:
    """The configured bounds.

    Checked here rather than in the schema so that exactly one place reads
    settings. The schema's own limits are far larger and exist only to bound how
    much a single request can allocate, so a schema constant can never quietly
    become the real limit.
    """
    if len(payload.question) > settings.chat_question_max_chars:
        raise ApiError(
            422,
            f"Questions are limited to {settings.chat_question_max_chars} characters. "
            "Shorten it and send it again.",
            "validation_error",
        )
    if len(payload.history) > settings.chat_history_max_turns:
        raise ApiError(
            422,
            f"Send at most {settings.chat_history_max_turns} earlier messages.",
            "validation_error",
        )
    for turn in payload.history:
        if len(turn.content) > settings.chat_history_max_chars:
            raise ApiError(
                422,
                f"An earlier message is longer than {settings.chat_history_max_chars} "
                "characters. Shorten it and send it again.",
                "validation_error",
            )


def _check_rate_limit(request: Request, session_id: UUID, settings: Settings) -> None:
    """Refuse the question if the caller or the session has had too many.

    Both keys are counted, not just one: the IP bound is what stops a script, and
    the session bound is what stops a single tab from spending the whole allowance
    for everyone behind the same address.

    `request.client.host` is the direct peer. Behind a reverse proxy that is the
    proxy itself, and every student then shares one counter -- the deployment
    ARCHITECTURE.md section 11 describes is a single instance with nothing in
    front of it, and the limitation is recorded as an assumption rather than
    papered over here.
    """
    if not settings.chat_rate_limit_enabled:
        return

    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    host = request.client.host if request.client else "unknown"
    for key in (f"ip:{host}", f"session:{session_id}"):
        allowed, retry_after = limiter.hit(key)
        if not allowed:
            raise ApiError(
                429,
                RATE_LIMITED_MESSAGE,
                "rate_limited",
                headers={"Retry-After": str(retry_after)},
            )
