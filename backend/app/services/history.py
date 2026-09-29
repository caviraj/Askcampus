"""The admin's view of what students asked.

One service for four screens, because they are four readings of the same rows:
the query history, the unanswered queue, the FAQ list and the summary cards all
come out of `queries`, `query_sources`, `unanswered_queries` and `feedback`.

Three of the four need a GROUP BY, and PostgREST has none. Rather than a
migration adding four reporting functions, the rows are fetched over a bounded
window and grouped here -- in pure functions, so the grouping is testable
without a database, which is the same split `app/services/cleaning.py` and
`app/services/chunking.py` use for the ingestion pipeline.

The cost of that choice is stated rather than hidden: a window that comes back
full sets `truncated`, so a partial count is reported as partial. What is *not*
approximated is the four numbers on the cards, which come from `count="exact"`
head requests and are exact at any history size.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app.config import Settings
from app.db import queries

# The four categories the cards and the chart are about, in the order they are
# displayed. A `None` category is appended when it occurs -- the classifier
# returns None rather than "general" on purpose, so unclassified questions are a
# real group and folding them into a category would misreport them.
_CATEGORY_ORDER = [
    "examinations",
    "admissions",
    "departments",
    "events",
    "academic_processes",
    "general",
]


class HistoryRepository(Protocol):
    """Reads over the four history tables, plus the document titles a resolved
    queue entry points at."""

    async def count_queries(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        answered: bool | None = None,
    ) -> int: ...

    async def list_queries(
        self,
        *,
        limit: int,
        offset: int,
        answered: bool | None = None,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def list_query_rows(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        answered: bool | None = None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def fetch_sources(self, query_ids: list[UUID]) -> list[dict[str, Any]]: ...

    async def fetch_feedback(self, query_ids: list[UUID]) -> list[dict[str, Any]]: ...

    async def list_unanswered(
        self, *, status: str | None = None, limit: int
    ) -> list[dict[str, Any]]: ...

    async def update_unanswered_group(
        self, normalized_hash: str, *, status: str, resolved_by_document: UUID | None
    ) -> list[dict[str, Any]]: ...

    async def fetch_document_titles(self, document_ids: list[UUID]) -> list[dict[str, Any]]: ...


class SupabaseHistoryRepository:
    """HistoryRepository backed by the real database."""

    async def count_queries(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        answered: bool | None = None,
    ) -> int:
        return await queries.count_queries(since=since, until=until, answered=answered)

    async def list_queries(
        self,
        *,
        limit: int,
        offset: int,
        answered: bool | None = None,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        return await queries.list_queries(
            limit=limit, offset=offset, answered=answered, category=category
        )

    async def list_query_rows(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        answered: bool | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await queries.list_query_rows(
            since=since, until=until, answered=answered, limit=limit
        )

    async def fetch_sources(self, query_ids: list[UUID]) -> list[dict[str, Any]]:
        return await queries.fetch_sources_for_queries(query_ids)

    async def fetch_feedback(self, query_ids: list[UUID]) -> list[dict[str, Any]]:
        return await queries.fetch_feedback_for_queries(query_ids)

    async def list_unanswered(
        self, *, status: str | None = None, limit: int
    ) -> list[dict[str, Any]]:
        return await queries.list_unanswered(status=status, limit=limit)

    async def update_unanswered_group(
        self, normalized_hash: str, *, status: str, resolved_by_document: UUID | None
    ) -> list[dict[str, Any]]:
        return await queries.update_unanswered_group(
            normalized_hash, status=status, resolved_by_document=resolved_by_document
        )

    async def fetch_document_titles(self, document_ids: list[UUID]) -> list[dict[str, Any]]:
        return await queries.fetch_document_titles(document_ids)


# ---------------------------------------------------------------------------
# Grouping. Pure functions over rows: no database, no clock, no settings.
# ---------------------------------------------------------------------------


def group_unanswered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse one row per occurrence into one row per normalized question.

    `rows` must be newest first, which is how the query orders them: the first
    row seen for a hash carries the most recent wording, and that is the one an
    admin most recently had to turn away.

    A group is `open` while *any* of its occurrences is open. The opposite rule
    would drop a question out of the queue the moment one of forty students had
    it answered, which is the one case where the count matters most.

    Sorted by count, then by most recent occurrence. Count first because the
    queue is a worklist: the question twenty students asked is the one to write
    a document for.
    """
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for row in rows:
        digest = str(row.get("normalized_hash") or "")
        if not digest:
            # Cannot be grouped, and cannot be resolved by hash either -- the
            # PATCH route addresses a group by exactly this value. Skipped
            # rather than bucketed under "".
            continue
        created_at = _timestamp(row.get("created_at"))
        group = groups.get(digest)
        if group is None:
            groups[digest] = {
                "normalized_hash": digest,
                "question": row.get("question") or "",
                "category": row.get("category"),
                "count": 1,
                "first_asked_at": created_at,
                "last_asked_at": created_at,
                "status": _status_of(row),
                "resolved_by_document": _uuid_or_none(row.get("resolved_by_document")),
                "resolved_by_document_title": None,
            }
            continue

        group["count"] += 1
        group["first_asked_at"] = _earliest(group["first_asked_at"], created_at)
        group["last_asked_at"] = _latest(group["last_asked_at"], created_at)
        if _status_of(row) == "open":
            group["status"] = "open"
        # The newest row that names a document wins, so the link is the most
        # recent thing an admin said fixed it.
        if group["resolved_by_document"] is None:
            group["resolved_by_document"] = _uuid_or_none(row.get("resolved_by_document"))

    ordered = sorted(
        groups.values(),
        key=lambda group: (group["count"], _sort_key(group["last_asked_at"])),
        reverse=True,
    )
    return ordered


def group_faqs(rows: list[dict[str, Any]], *, max_per_category: int) -> list[dict[str, Any]]:
    """Answered questions, counted per normalized wording, grouped by category.

    Only answered rows are passed in, so "frequent" means frequently answered --
    which is what makes a question an FAQ rather than a gap. `last_asked_at` is
    the most recent occurrence, so a stale entry can be told from a live one.
    """
    per_category: dict[str | None, dict[str, dict[str, Any]]] = {}

    for row in rows:
        digest = str(row.get("normalized_hash") or "")
        if not digest:
            continue
        category = row.get("category")
        bucket = per_category.setdefault(category, {})
        entry = bucket.get(digest)
        created_at = _timestamp(row.get("created_at"))
        if entry is None:
            bucket[digest] = {
                "normalized_hash": digest,
                "question": row.get("question") or "",
                "count": 1,
                "last_asked_at": created_at,
            }
            continue
        entry["count"] += 1
        entry["last_asked_at"] = _latest(entry["last_asked_at"], created_at)

    groups: list[dict[str, Any]] = []
    for category, bucket in per_category.items():
        items = sorted(
            bucket.values(),
            key=lambda item: (item["count"], _sort_key(item["last_asked_at"])),
            reverse=True,
        )[:max_per_category]
        groups.append(
            {
                "category": category,
                "total": sum(item["count"] for item in bucket.values()),
                "items": items,
            }
        )

    # Most-asked category first, so the FAQ screen opens on the busiest one.
    groups.sort(key=lambda group: group["total"], reverse=True)
    return groups


def count_by_category(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Question counts per category, in the order the chips are displayed.

    A category with no questions is omitted rather than shown as zero: the chart
    is drawn from this list, and a fixed row of empty bars claims the corpus
    covers a category it does not.
    """
    counts: dict[str | None, int] = {}
    for row in rows:
        category = row.get("category")
        counts[category] = counts.get(category, 0) + 1

    ordered: list[dict[str, Any]] = [
        {"category": category, "count": counts[category]}
        for category in _CATEGORY_ORDER
        if category in counts
    ]
    # Anything the schema does not know about, then the unclassified bucket,
    # so neither can be silently dropped from a chart that claims to summarise
    # everything.
    unknown = sorted(
        category for category in counts if category not in _CATEGORY_ORDER and category is not None
    )
    ordered.extend({"category": category, "count": counts[category]} for category in unknown)
    if None in counts:
        ordered.append({"category": None, "count": counts[None]})
    return ordered


def top_category(rows: list[dict[str, Any]]) -> tuple[str | None, int]:
    """The busiest category, or `(None, 0)` when there is nothing to count.

    Ties go to the earlier entry in `count_by_category`, which is the display
    order -- so the answer is stable between two requests rather than depending
    on dictionary iteration. `max` alone would take whichever came first in the
    list, which is the same thing only because this list is ordered; the tie is
    therefore decided by the ordering rather than by `max`, and it is worth
    saying out loud that a chart and a card reading the same rows can disagree
    only if this stops being true.
    """
    entries = count_by_category(rows)
    if not entries:
        return None, 0
    best = entries[0]
    for entry in entries[1:]:
        # Strictly greater, so a tie keeps the earlier (display-order) entry.
        if entry["count"] > best["count"]:
            best = entry
    return best["category"], best["count"]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """The reporting window and the one before it, both half-open."""

    since: datetime
    until: datetime
    previous_since: datetime


class AdminHistoryService:
    """The five admin reads, over a `HistoryRepository`."""

    def __init__(self, repository: HistoryRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def list_queries(
        self,
        *,
        limit: int,
        offset: int,
        answered: bool | None = None,
        category: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """A page of history, with each question's citations and rating attached.

        The page is fetched first and the citations and ratings second, both by
        id, so the number of round trips is three whatever the page size --
        rather than one per row.
        """
        rows, total = await self._repository.list_queries(
            limit=limit, offset=offset, answered=answered, category=category
        )
        if not rows:
            return [], total

        query_ids = [UUID(str(row["id"])) for row in rows]
        sources = await self._repository.fetch_sources(query_ids)
        feedback = await self._repository.fetch_feedback(query_ids)

        by_query: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            by_query.setdefault(str(source.get("query_id")), []).append(source)
        ratings = {str(row.get("query_id")): row.get("helpful") for row in feedback}

        for row in rows:
            key = str(row.get("id"))
            row["sources"] = by_query.get(key, [])
            rating = ratings.get(key)
            row["helpful"] = bool(rating) if rating is not None else None

        return rows, total

    async def list_unanswered(
        self, *, limit: int, offset: int, status: str | None = "open"
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """A page of the grouped queue, plus whether the grouping window filled.

        `total` is the number of *groups* in the window, not the number of rows:
        the queue's unit is a question, and a count of occurrences is already
        carried per group.
        """
        cap = self._settings.admin_aggregate_row_limit
        rows = await self._repository.list_unanswered(status=status, limit=cap)
        truncated = len(rows) >= cap

        groups = group_unanswered(rows)
        await self._attach_document_titles(groups)
        return groups[offset : offset + limit], len(groups), truncated

    async def resolve_unanswered(
        self,
        normalized_hash: str,
        *,
        status: str,
        resolved_by_document: UUID | None,
    ) -> dict[str, Any] | None:
        """Set one group's status, returning it as the queue would show it.

        Returns None when the hash matches nothing, which the route turns into a
        404. The document is checked to exist first: `resolved_by_document` is a
        foreign key, and letting an unknown id reach the insert would surface a
        constraint violation as a 500 rather than as a 404 the admin can act on.
        """
        if resolved_by_document is not None:
            found = await self._repository.fetch_document_titles([resolved_by_document])
            if not found:
                raise UnknownDocumentError(str(resolved_by_document))

        # Reopening clears the link. A row that is `open` and points at the
        # document that resolved it is a contradiction the queue would render.
        linked = resolved_by_document if status == "resolved" else None
        rows = await self._repository.update_unanswered_group(
            normalized_hash, status=status, resolved_by_document=linked
        )
        if not rows:
            return None

        # Re-sorted newest-first: the update returns the rows in whatever order
        # the database chose, and the grouping reads the newest wording from the
        # first row it sees for each hash.
        newest_first = sorted(rows, key=lambda row: _sort_key(row.get("created_at")), reverse=True)
        groups = group_unanswered(newest_first)
        if not groups:
            return None
        await self._attach_document_titles(groups)
        return groups[0]

    async def faqs(self) -> tuple[list[dict[str, Any]], bool]:
        """FAQ groups over answered questions, most recent first in the window."""
        cap = self._settings.admin_aggregate_row_limit
        rows = await self._repository.list_query_rows(answered=True, limit=cap)
        truncated = len(rows) >= cap
        groups = group_faqs(rows, max_per_category=self._settings.faq_max_items_per_category)
        return groups, truncated

    async def stats(self, *, preview_limit: int) -> dict[str, Any]:
        """§8's four cards, the category chart and the queue preview.

        The three counts are exact head requests; the chart and the top category
        are grouped from a bounded window and the response says when it filled.
        `unanswered` is derived as `questions - answered` rather than asked for
        separately, so the three cards can never disagree with each other.
        """
        window = self._window()
        repository = self._repository

        questions = await repository.count_queries(since=window.since, until=window.until)
        previous_questions = await repository.count_queries(
            since=window.previous_since, until=window.since
        )
        answered = await repository.count_queries(
            since=window.since, until=window.until, answered=True
        )
        previous_answered = await repository.count_queries(
            since=window.previous_since, until=window.since, answered=True
        )

        cap = self._settings.admin_aggregate_row_limit
        # One fetch spanning both windows, split here: the previous period's top
        # category costs no extra round trip this way.
        rows = await repository.list_query_rows(since=window.previous_since, limit=cap)
        truncated = len(rows) >= cap
        current = [row for row in rows if _at_or_after(row.get("created_at"), window.since)]
        previous = [row for row in rows if not _at_or_after(row.get("created_at"), window.since)]

        category, count = top_category(current)
        previous_category, previous_count = top_category(previous)

        preview_rows = await repository.list_unanswered(status="open", limit=cap)
        truncated = truncated or len(preview_rows) >= cap
        preview = group_unanswered(preview_rows)[:preview_limit]
        await self._attach_document_titles(preview)

        return {
            "window_days": self._settings.stats_window_days,
            "truncated": truncated,
            "questions": {"value": questions, "previous": previous_questions},
            "answered": {"value": answered, "previous": previous_answered},
            "unanswered": {
                "value": questions - answered,
                "previous": previous_questions - previous_answered,
            },
            "top_category": {
                "category": category,
                "count": count,
                "previous_category": previous_category,
                "previous_count": previous_count,
            },
            "categories": count_by_category(current),
            "unanswered_preview": preview,
        }

    def _window(self) -> Window:
        """The reporting window, ending now.

        Computed from the clock rather than passed in, so every call inside one
        request sees the same boundaries -- and half-open, so a row created
        exactly on the boundary is counted once rather than twice.
        """
        now = datetime.now(UTC)
        span = timedelta(days=self._settings.stats_window_days)
        return Window(since=now - span, until=now, previous_since=now - 2 * span)

    async def _attach_document_titles(self, groups: list[dict[str, Any]]) -> None:
        """Name the document that resolved each group, in one lookup."""
        ids = [
            group["resolved_by_document"]
            for group in groups
            if group.get("resolved_by_document") is not None
        ]
        if not ids:
            return
        titles = {
            str(row.get("id")): row.get("title")
            for row in await self._repository.fetch_document_titles(ids)
        }
        for group in groups:
            document_id = group.get("resolved_by_document")
            if document_id is not None:
                group["resolved_by_document_title"] = titles.get(str(document_id))


class UnknownDocumentError(Exception):
    """`resolved_by_document` named a document that does not exist."""

    def __init__(self, document_id: str) -> None:
        super().__init__(f"No document {document_id}")
        self.document_id = document_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _timestamp(value: Any) -> datetime | None:
    """Read a timestamp that may arrive as a string.

    PostgREST sends timestamptz as ISO 8601 text, and the fake repositories used
    in tests hand over real datetimes. Both are accepted so the grouping does not
    depend on which side of the boundary it is running on.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _at_or_after(value: Any, boundary: datetime) -> bool:
    stamp = _timestamp(value)
    return stamp is not None and stamp >= boundary


def _sort_key(value: datetime | None) -> float:
    """A datetime as a sortable number. None sorts oldest, never newest."""
    return value.timestamp() if value is not None else float("-inf")


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _latest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _status_of(row: dict[str, Any]) -> str:
    return "resolved" if row.get("status") == "resolved" else "open"


def _uuid_or_none(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None
