"""Retrieval: turn a question into the passages that might answer it.

Hybrid search itself is `hybrid_search` in migration 0002; this module decides
what to search with, in what scope, and which of the results are usable as
evidence.

Two things it does that retrieval alone does not:

**It re-checks that a chunk is still citable.** The ranking and the lookup of the
passages are separate database requests, so a document deactivated between them
would otherwise be cited from a stale ranking -- `AGENTS.md` section 6.12 is a
condition on what is searchable, not a condition on when the search ran. A chunk
whose document fails that check is dropped rather than raising: a missing row is
not an error, it is a document an admin has just taken out of service.

**It can widen the search back out.** A category filter is a guess, whether it
came from a tap or from the classifier, and a wrong guess turns an answerable
question into a fallback. So a filtered search whose best similarity is below the
threshold is retried unfiltered. The unfiltered result is adopted when it clears
the threshold on its own, and also when the filtered scope retrieved nothing --
there it still ends in a fallback, but a fallback that can name an office rather
than one that cannot.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.config import Settings
from app.db import queries
from app.services.embedding import EmbeddingService


@dataclass(frozen=True)
class RetrievedChunk:
    """One passage, with everything a citation needs attached to it.

    `document_updated_at` is the raw column value, a string. It is handed to
    `Citation.last_updated`, which is a `datetime` and parses it -- the row is
    mirrored here as the database gave it, and typed where it is rendered.
    """

    chunk_id: UUID
    document_id: UUID
    score: float
    similarity: float | None
    content: str
    page_number: int | None
    section_heading: str | None
    document_title: str
    department: str | None
    document_updated_at: str | None


@dataclass(frozen=True)
class RetrievalResult:
    """What a search returned, and the worst-case reading of its relevance.

    `best_similarity` is `None` when every hit was keyword-only or nothing was
    retrieved at all -- in both cases there is no cosine evidence, and treating
    that as zero is what makes the fallback decision correct rather than
    optimistic.
    """

    chunks: list[RetrievedChunk]
    best_similarity: float | None


class ChunkRepository(Protocol):
    """The retrieval data access, as one seam."""

    async def search(
        self, *, query_text: str, embedding: list[float], match_count: int, category: str | None
    ) -> list[dict[str, Any]]:
        """Ranked hits, best first: `chunk_id`, `document_id`, `score`, `similarity`."""
        ...

    async def hydrate(self, hits: list[dict[str, Any]]) -> list[RetrievedChunk]:
        """Attach passages and document metadata to hits, dropping any that are gone."""
        ...


class SupabaseChunkRepository:
    """Two flat queries rather than one embedded select.

    An embedded `chunks -> documents(...)` select would fetch both in one round
    trip, but the searchable predicate would then have to be expressed on the
    nested resource. As two queries, `is_active` and `status` stay plain filters
    on the table that owns them.
    """

    async def search(
        self, *, query_text: str, embedding: list[float], match_count: int, category: str | None
    ) -> list[dict[str, Any]]:
        return await queries.run_hybrid_search(
            query_text=query_text,
            embedding=embedding,
            match_count=match_count,
            category=category,
        )

    async def hydrate(self, hits: list[dict[str, Any]]) -> list[RetrievedChunk]:
        if not hits:
            return []

        chunk_rows = await queries.fetch_searchable_chunks(
            _uuids(hit.get("chunk_id") for hit in hits)
        )
        document_rows = await queries.fetch_searchable_documents(
            _uuids(hit.get("document_id") for hit in hits)
        )

        # Keyed by id because row order is not part of the contract. Neither
        # PostgREST nor `in_` promises to return rows in the order they were
        # asked for, and zipping two lists would attach the wrong passage to the
        # wrong score -- a mistake that still reads as a plausible answer.
        chunks = {str(row["id"]): row for row in chunk_rows}
        documents = {str(row["id"]): row for row in document_rows}

        hydrated: list[RetrievedChunk] = []
        for hit in hits:
            chunk_row = chunks.get(str(hit.get("chunk_id")))
            document_row = documents.get(str(hit.get("document_id")))
            if chunk_row is None or document_row is None:
                # Either the chunk went with its deleted document, or the
                # document is no longer active and ready. Both mean the same
                # thing here: there is nothing to cite, so the hit does not exist.
                continue
            hydrated.append(_build(chunk_row, document_row, hit))
        return hydrated


class RetrievalService:
    """Embeds a question, searches, and reports what it found."""

    def __init__(
        self,
        embeddings: EmbeddingService,
        repository: ChunkRepository,
        settings: Settings,
    ) -> None:
        self._embeddings = embeddings
        self._repository = repository
        self._settings = settings

    async def retrieve(self, *, search_text: str, category: str | None) -> RetrievalResult:
        """The passages to answer from, in rank order."""
        embedding = await self._embeddings.embed_query(search_text)

        result = await self._search(search_text=search_text, embedding=embedding, category=category)
        if category is None or self.clears_threshold(result):
            return result

        # The filter is the only reason nothing cleared the threshold, so the
        # same vector is searched again across every category. Reusing the
        # embedding is what makes widening the search cost one query rather than
        # a second model call.
        unfiltered = await self._search(search_text=search_text, embedding=embedding, category=None)
        if self.clears_threshold(unfiltered) or not result.chunks:
            # Cleared it outright, or the filtered scope retrieved nothing at
            # all. An empty result is returned in the second case even though the
            # question ends in a fallback either way: the fallback names the
            # office the best-ranked document belongs to, so an empty result
            # discards the one useful thing the wider search found -- and a
            # classifier that guessed a category with no documents in it is
            # exactly when this happens.
            return unfiltered

        # The filtered scope found something, and it is the scope the student
        # asked for, so it is what the fallback describes.
        return result

    def clears_threshold(self, result: RetrievalResult) -> bool:
        """Whether this result is good enough evidence to try answering from.

        Public because the answering service has to make the same decision, and
        one comparison against `SIMILARITY_THRESHOLD` written in two places is
        one threshold comparison too many.
        """
        best = result.best_similarity
        return best is not None and best >= self._settings.similarity_threshold

    async def _search(
        self, *, search_text: str, embedding: list[float], category: str | None
    ) -> RetrievalResult:
        hits = await self._repository.search(
            query_text=search_text,
            embedding=embedding,
            match_count=self._settings.top_k,
            category=category,
        )
        chunks = await self._repository.hydrate(hits)
        return RetrievalResult(chunks=chunks, best_similarity=_best_similarity(chunks))


def _best_similarity(chunks: list[RetrievedChunk]) -> float | None:
    """The highest cosine similarity among the citable chunks, or None.

    `max` over every chunk rather than the first one's value: migration 0002
    returns NULL similarity for a keyword-only hit, and RRF can place one of
    those above every semantic hit. Reading the top row would then see None and
    fall back on a question the search had in fact matched well.

    Measured over the hydrated chunks rather than the raw hits, so the number the
    threshold is compared against describes exactly the evidence that is
    available to answer from.
    """
    similarities = [chunk.similarity for chunk in chunks if chunk.similarity is not None]
    return max(similarities) if similarities else None


def _build(
    chunk_row: dict[str, Any], document_row: dict[str, Any], hit: dict[str, Any]
) -> RetrievedChunk:
    similarity = hit.get("similarity")
    return RetrievedChunk(
        chunk_id=UUID(str(chunk_row["id"])),
        document_id=UUID(str(chunk_row["document_id"])),
        score=float(hit["score"]),
        similarity=float(similarity) if similarity is not None else None,
        content=str(chunk_row.get("content") or ""),
        page_number=chunk_row.get("page_number"),
        section_heading=chunk_row.get("section_heading") or None,
        document_title=str(document_row.get("title") or ""),
        department=document_row.get("department") or None,
        document_updated_at=document_row.get("updated_at"),
    )


def _uuids(values: Iterable[object]) -> list[UUID]:
    """Parse the ids out of a set of rows, skipping any that are absent.

    Silently skipping is the point: these are the ids of a previous request's
    result, and the useful response to an absent one is to fetch nothing for it
    and let the caller drop the row, not to fail the whole search.
    """
    parsed: list[UUID] = []
    for value in values:
        if value is None:
            continue
        try:
            parsed.append(UUID(str(value)))
        except ValueError:
            continue
    return parsed
