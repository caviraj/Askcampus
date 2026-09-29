"""Chat request and response models.

The response shape is ARCHITECTURE.md section 5.2's, and every citation field is
copied from a database row. Nothing about a citation is produced by the model --
AGENTS.md section 5 forbids a fabricated title, page or date, and the surest way
to honour that is to never ask the model for one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.documents import Category

# The six document categories plus "all", which is the chip that filters nothing.
# Derived from Category rather than retyped so a category added to the documents
# schema cannot go missing from the chip list.
CategoryFilter = Literal[(*get_args(Category), "all")]

# Structural caps, purely to bound how much a single request can allocate. The
# bounds that decide whether a request is acceptable come from Settings and are
# checked in the route, so there is exactly one place that reads config -- and a
# generous ceiling here cannot silently become the real limit.
_MAX_QUESTION_CHARS = 8000
_MAX_TURN_CHARS = 8000
_MAX_HISTORY_TURNS = 20


class HistoryTurn(BaseModel):
    """One earlier message, for resolving what a follow-up question refers to."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=_MAX_TURN_CHARS)


class ChatRequest(BaseModel):
    """A student's question.

    `category` is not in ARCHITECTURE.md section 5.2's body; it is here because
    DESIGN_SYSTEM.md section 8 requires a tapped chip to filter retrieval, which
    the backend cannot do without being told. It is optional and defaults to the
    documented behaviour: classify the question and filter only if confident.
    """

    model_config = ConfigDict(extra="ignore")

    session_id: UUID
    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=_MAX_HISTORY_TURNS)
    category: CategoryFilter | None = None

    @field_validator("question")
    @classmethod
    def _question_must_have_content(cls, value: str) -> str:
        """Strip, so a trailing space cannot produce a second normalized hash.

        A blank question is rejected here rather than reaching retrieval, where it
        would embed to something arbitrary and could match unrelated chunks.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class ModelAnswer(BaseModel):
    """The answering contract from ARCHITECTURE.md section 6.

    Passed to the provider as `response_schema`, so a capable provider constrains
    the model to this shape, and re-validated on the way back -- AGENTS.md section
    6 requires Pydantic validation regardless of which provider is in use.
    """

    model_config = ConfigDict(extra="ignore")

    answerable: bool
    answer: str
    used_sources: list[str]


class Citation(BaseModel):
    """A source slip. Every field comes from `chunks` or `documents`."""

    label: str
    document_title: str
    page: int | None = None
    section: str | None = None
    # The whole retrieved chunk, not an excerpt: DESIGN_SYSTEM.md section 7 shows
    # the expanded slip with "the exact supporting sentence" marked, and a
    # truncated passage can cut off the very sentence to be marked.
    snippet: str
    last_updated: datetime | None = None


class ChatResponse(BaseModel):
    """An answer, or an honest fallback. `answered` is the discriminator.

    `office` is not in ARCHITECTURE.md section 5.2's shape; it is here because
    DESIGN_SYSTEM.md section 9's fallback says "the office below" and section 8
    gives the fallback message an "Ask the office" action. Both need the office
    named, and AGENTS.md section 6.5 forbids the client -- or the model --
    supplying one, so it can only travel in the body. Additive and optional, the
    same posture `category` took in Phase 3.
    """

    query_id: UUID
    answered: bool
    category: Category | None = None
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    office: str | None = None


class FeedbackRequest(BaseModel):
    """A rating for one answer, from the session that asked for it.

    The session id is required because `/chat/feedback` is unauthenticated: it is
    the only thing that can establish that the caller is entitled to rate this
    query.
    """

    model_config = ConfigDict(extra="ignore")

    query_id: UUID
    session_id: UUID
    helpful: bool


class CategoryChip(BaseModel):
    """One chip in the student UI, with the starter questions it reveals."""

    value: CategoryFilter
    label: str
    starter_questions: list[str]


class CategoryListResponse(BaseModel):
    categories: list[CategoryChip]
