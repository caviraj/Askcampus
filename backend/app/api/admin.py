"""Admin routes.

require_admin is attached at the router level so that a route added here is
protected by construction rather than by remembering to add the dependency.
test_admin_route_protection.py asserts this holds for every /admin path.

Four of these five are reads over rows the student path already wrote. The fifth,
`PATCH /admin/unanswered/{hash}`, is the only admin write outside the document
manager, and it changes nothing a student can see: resolving a question is an
admin saying "this is handled", not an answer appearing anywhere.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.auth_deps import require_admin
from app.api.errors import ApiError
from app.config import Settings
from app.schemas.admin import (
    CategoryCount,
    FaqGroup,
    FaqItem,
    FaqListResponse,
    NormalizedHash,
    QueryListResponse,
    QueryRead,
    StatCard,
    StatsResponse,
    TopCategoryCard,
    UnansweredGroup,
    UnansweredListResponse,
    UnansweredUpdate,
)
from app.schemas.auth import AdminUser
from app.schemas.documents import Category
from app.services.history import (
    AdminHistoryService,
    HistoryRepository,
    SupabaseHistoryRepository,
    UnknownDocumentError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_history_repository() -> HistoryRepository:
    """Overridden in tests with an in-memory implementation."""
    return SupabaseHistoryRepository()


def get_history_service(
    request: Request,
    repository: Annotated[HistoryRepository, Depends(get_history_repository)],
) -> AdminHistoryService:
    settings: Settings = request.app.state.settings
    return AdminHistoryService(repository, settings)


HistoryServiceDep = Annotated[AdminHistoryService, Depends(get_history_service)]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/me", response_model=AdminUser, summary="Who am I")
async def read_current_admin(
    admin: Annotated[AdminUser, Depends(require_admin)],
) -> AdminUser:
    """Return the signed-in admin.

    Doubles as the endpoint the admin UI uses to confirm a session is valid.
    """
    return admin


@router.get("/queries", response_model=QueryListResponse, summary="Query history")
async def list_queries(
    request: Request,
    history: HistoryServiceDep,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    answered: Annotated[bool | None, Query()] = None,
    category: Annotated[Category | None, Query()] = None,
) -> QueryListResponse:
    """Every question asked, newest first, with the sources it cited.

    `answered` filters both ways and defaults to neither: an admin looking at
    history usually wants to see the falls mixed in with the answers, because
    that is the sequence a student experienced.
    """
    settings: Settings = request.app.state.settings
    effective_limit = min(limit or settings.admin_list_default_limit, settings.admin_list_max_limit)

    rows, total = await history.list_queries(
        limit=effective_limit, offset=offset, answered=answered, category=category
    )
    # model_validate on the whole row, not field by field: QueryRead ignores the
    # columns it does not declare and validates `sources` into its own model, so
    # the mapping cannot drift from the schema.
    return QueryListResponse(
        items=[QueryRead.model_validate(row) for row in rows],
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/unanswered", response_model=UnansweredListResponse, summary="Unanswered queue")
async def list_unanswered(
    request: Request,
    history: HistoryServiceDep,
    status: Annotated[Literal["open", "resolved", "all"], Query()] = "open",
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UnansweredListResponse:
    """Questions the documents could not answer, grouped by normalized hash.

    Grouped rather than listed one per occurrence, because FR-8's count is the
    point: forty students asking the same thing is one document to write, and
    forty rows would read as forty problems. `all` is spelled out rather than
    expressed as a null status, so "no filter" is a thing the caller asked for
    rather than a parameter they forgot.
    """
    settings: Settings = request.app.state.settings
    effective_limit = min(limit or settings.admin_list_default_limit, settings.admin_list_max_limit)

    groups, total, truncated = await history.list_unanswered(
        limit=effective_limit,
        offset=offset,
        status=None if status == "all" else status,
    )
    return UnansweredListResponse(
        items=[UnansweredGroup.model_validate(group) for group in groups],
        total=total,
        limit=effective_limit,
        offset=offset,
        truncated=truncated,
    )


@router.patch(
    "/unanswered/{normalized_hash}",
    response_model=UnansweredGroup,
    summary="Resolve or reopen a question",
)
async def update_unanswered(
    normalized_hash: NormalizedHash,
    payload: UnansweredUpdate,
    history: HistoryServiceDep,
) -> UnansweredGroup:
    """Mark a question resolved, optionally naming the document that answered it.

    Every occurrence of the question moves together, which is what the grouped
    view promises: resolving a row and having it reappear because a second
    student asked the same thing last week would be a lie about the queue.
    """
    try:
        group = await history.resolve_unanswered(
            normalized_hash,
            status=payload.status,
            resolved_by_document=payload.resolved_by_document,
        )
    except UnknownDocumentError as exc:
        raise ApiError(404, "No such document.", "document_not_found") from exc

    if group is None:
        raise ApiError(404, "No such question in the queue.", "unanswered_not_found")
    return UnansweredGroup.model_validate(group)


@router.get("/faqs", response_model=FaqListResponse, summary="Frequent answered questions")
async def list_faqs(history: HistoryServiceDep) -> FaqListResponse:
    """Answered questions counted by wording, grouped by category.

    Only answered questions: a question that appears here is one the documents
    already cover, which is what makes this a page of things students ask often
    rather than a second copy of the unanswered queue. Each item carries the
    query the student typed, so it doubles as a list of phrasings the retrieval
    already matches.
    """
    groups, truncated = await history.faqs()
    return FaqListResponse(
        groups=[
            FaqGroup(
                category=group["category"],
                total=group["total"],
                items=[FaqItem.model_validate(item) for item in group["items"]],
            )
            for group in groups
        ],
        truncated=truncated,
    )


@router.get("/stats", response_model=StatsResponse, summary="Summary cards")
async def read_stats(
    request: Request,
    history: HistoryServiceDep,
    preview_limit: Annotated[int | None, Query(ge=1, le=20)] = None,
) -> StatsResponse:
    """The four dashboard cards, the category chart and the queue preview.

    The counts are exact. The chart and the top category are grouped from a
    bounded window of rows and `truncated` says when that window filled -- a
    number that is sometimes a lower bound is still useful, but only if it is
    labelled as one.
    """
    settings: Settings = request.app.state.settings
    data: dict[str, Any] = await history.stats(
        preview_limit=preview_limit or settings.stats_preview_limit
    )

    return StatsResponse(
        window_days=data["window_days"],
        truncated=data["truncated"],
        questions=StatCard.model_validate(data["questions"]),
        answered=StatCard.model_validate(data["answered"]),
        unanswered=StatCard.model_validate(data["unanswered"]),
        top_category=TopCategoryCard.model_validate(data["top_category"]),
        categories=[CategoryCount.model_validate(entry) for entry in data["categories"]],
        unanswered_preview=[
            UnansweredGroup.model_validate(group) for group in data["unanswered_preview"]
        ],
    )
