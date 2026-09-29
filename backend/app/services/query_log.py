"""Writing down what was asked, and what the student said about the answer.

One repository for the four history tables, because they are written together and
read together: an admin's query history, the unanswered queue, the FAQ candidates
and the helpfulness counts are all views over the same rows.

The ids and the timestamps come from Postgres. Nothing here invents one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.db import queries


@dataclass(frozen=True)
class LoggedSource:
    """One retrieved chunk, as it is recorded against the query that used it."""

    rank: int
    chunk_id: UUID | None
    score: float | None
    document_id: UUID | None
    document_title: str | None
    page_number: int | None
    section_heading: str | None

    def as_payload(self) -> dict[str, str | None]:
        """The JSON object `log_query` reads out of `p_sources`.

        Every value is a string or a JSON null, because that is all jsonb
        carries: the function casts each one back into a typed column, including
        `nullif(...)` where a null has to survive the round trip as SQL NULL
        rather than as an empty string.
        """
        return {
            "rank": str(self.rank),
            "chunk_id": str(self.chunk_id) if self.chunk_id is not None else None,
            "score": str(self.score) if self.score is not None else None,
            "document_id": str(self.document_id) if self.document_id is not None else None,
            "document_title": self.document_title,
            "page_number": str(self.page_number) if self.page_number is not None else None,
            "section_heading": self.section_heading,
        }


class QueryLogRepository(Protocol):
    """The history tables."""

    async def log_query(
        self,
        *,
        query_id: UUID,
        session_id: UUID,
        question: str,
        normalized_hash: str,
        category: str | None,
        answer: str,
        answered: bool,
        top_score: float | None,
        latency_ms: int,
        sources: list[LoggedSource],
        unanswered: bool,
    ) -> None:
        """Record one question and everything derived from it, atomically."""
        ...

    async def record_feedback(self, *, query_id: UUID, session_id: UUID, helpful: bool) -> bool:
        """Rate a query, if `session_id` is the session that asked it."""
        ...


class SupabaseQueryLogRepository:
    """Both functions live in migration 0007."""

    async def log_query(
        self,
        *,
        query_id: UUID,
        session_id: UUID,
        question: str,
        normalized_hash: str,
        category: str | None,
        answer: str,
        answered: bool,
        top_score: float | None,
        latency_ms: int,
        sources: list[LoggedSource],
        unanswered: bool,
    ) -> None:
        await queries.insert_query_log(
            query_id=query_id,
            session_id=session_id,
            question=question,
            normalized_hash=normalized_hash,
            category=category,
            answer=answer,
            answered=answered,
            top_score=top_score,
            latency_ms=latency_ms,
            sources=[source.as_payload() for source in sources],
            unanswered=unanswered,
        )

    async def record_feedback(self, *, query_id: UUID, session_id: UUID, helpful: bool) -> bool:
        return await queries.insert_feedback(query_id, session_id, helpful=helpful)
