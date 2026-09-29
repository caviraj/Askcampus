"""Admin request and response models.

These are views over rows the student path already wrote. Nothing here is
computed by a model, and nothing here is stored: every field is read out of
`queries`, `query_sources`, `unanswered_queries`, `feedback` or `documents`, so
the admin UI cannot show a number that no row supports.

The one exception is stated where it happens: `count` on `UnansweredGroup` and
`FaqItem` is a count of rows, and `truncated` on the two responses that carry
one says when the count was taken over a partial window.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Mirrors the check constraint on unanswered_queries.status in migration 0001.
UnansweredStatus = Literal["open", "resolved"]

# `normalized_hash` is sha256 hex (`app/services/hashing.py`), and it arrives as
# a path parameter -- so it is constrained here rather than interpolated into a
# query filter as whatever the caller typed.
NormalizedHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class QuerySourceRead(BaseModel):
    """One retrieved chunk, as recorded against the query that cited it."""

    model_config = ConfigDict(extra="ignore")

    rank: int
    score: float | None = None
    document_id: UUID | None = None
    document_title: str | None = None
    page_number: int | None = None
    section_heading: str | None = None


class QueryRead(BaseModel):
    """One question and everything logged with it.

    `document_title` on a source is the copy taken at write time, not a join, so
    a source still names its document after the document is deleted -- which is
    the property migration 0001's CORRECTION B added the column for.

    `answer` is null only for a row written before the answer existed, which
    `log_query` does not do; it is optional rather than required because a
    history read must not 500 on a row it did not write.
    """

    model_config = ConfigDict(extra="ignore")

    id: UUID
    session_id: UUID
    question: str
    category: str | None = None
    answer: str | None = None
    answered: bool
    top_score: float | None = None
    latency_ms: int | None = None
    created_at: datetime | None = None
    sources: list[QuerySourceRead] = Field(default_factory=list)
    # A tri-state, not a bool: null means nobody rated it, which is not the same
    # as "not helpful" and must not be rendered as either.
    helpful: bool | None = None


class QueryListResponse(BaseModel):
    items: list[QueryRead]
    total: int
    limit: int
    offset: int


class UnansweredGroup(BaseModel):
    """Open questions sharing a `normalized_hash`.

    FR-8 groups repeats by the hash so the dashboard can show a count, and §8's
    preview shows the group rather than 40 copies of one question. `question` is
    the most recent wording, since that is the one an admin most recently had to
    turn away.
    """

    normalized_hash: str
    question: str
    category: str | None = None
    count: int
    first_asked_at: datetime | None = None
    last_asked_at: datetime | None = None
    status: UnansweredStatus
    resolved_by_document: UUID | None = None
    resolved_by_document_title: str | None = None


class UnansweredListResponse(BaseModel):
    items: list[UnansweredGroup]
    total: int
    limit: int
    offset: int
    # True when the grouping window was full, so `count` and `total` are lower
    # bounds. Reported rather than hidden: an admin deciding what to write next
    # is entitled to know the number is partial.
    truncated: bool = False


class UnansweredUpdate(BaseModel):
    """Mark a group resolved, or reopen it.

    `resolved_by_document` is the document that answered the question -- FR-9's
    "link to the document that fixed it". It is only meaningful alongside
    `resolved`, and the route clears it when reopening so a resolved link cannot
    survive into an open row.
    """

    status: UnansweredStatus
    resolved_by_document: UUID | None = None


class FaqItem(BaseModel):
    """A frequently asked answered question."""

    normalized_hash: str
    question: str
    count: int
    last_asked_at: datetime | None = None


class FaqGroup(BaseModel):
    """One category's FAQ items, most frequent first.

    `category` is null for questions the classifier could not place. Null is not
    a category -- `app/services/classifier.py` returns None rather than "general"
    on purpose -- so it is a group of its own rather than being folded into one.
    """

    category: str | None = None
    total: int
    items: list[FaqItem]


class FaqListResponse(BaseModel):
    groups: list[FaqGroup]
    truncated: bool = False


class StatCard(BaseModel):
    """A number, and the same number over the seven days before it."""

    value: int
    previous: int


class TopCategoryCard(BaseModel):
    """§8's fourth card.

    Not a `StatCard`: a category name has no meaningful difference from the
    previous period's name, so what is comparable -- the count behind it -- is
    what carries the change, and both names are shown.
    """

    category: str | None = None
    count: int = 0
    previous_category: str | None = None
    previous_count: int = 0


class CategoryCount(BaseModel):
    category: str | None = None
    count: int


class StatsResponse(BaseModel):
    """The summary cards, the category chart and the queue preview.

    `truncated` covers the chart and the preview, which are grouped in Python.
    The three count cards come from `count="exact"` requests, so they are exact
    either way -- which is why the flag is documented as applying to the grouped
    parts rather than to the whole response.
    """

    window_days: int
    truncated: bool = False
    questions: StatCard
    answered: StatCard
    unanswered: StatCard
    top_category: TopCategoryCard
    categories: list[CategoryCount]
    unanswered_preview: list[UnansweredGroup]
