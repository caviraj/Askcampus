"""Batch embedding, with a content-addressed cache and bounded retries.

The cache is the free-tier mitigation PRD section 10 asks for: re-uploading or
reprocessing a document re-embeds nothing, because a chunk's vector depends only
on its text and the model.

Two properties are load-bearing:

**Output order always matches input order.** Vectors are reassembled by walking
the input hash list, never by iterating the cache or the provider's response. A
silent reordering would attach the wrong vector to the wrong chunk, and the
result would look plausible -- retrieval would just be subtly worse with nothing
to point at.

**Only transient failures are retried.** A retired model returns 404 on every
attempt; retrying it turns a fast, clear failure into a slow one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from app.config import Settings
from app.db import queries
from app.providers.embeddings import EmbeddingProvider
from app.providers.errors import ProviderError
from app.services.hashing import sha256_hex

logger = logging.getLogger(__name__)


class EmbeddingCache(Protocol):
    """Vector cache keyed by the hash of the text that produced it."""

    async def get_many(
        self, content_hashes: list[str], *, model: str, dimensions: int
    ) -> dict[str, list[float]]: ...

    async def put_many(
        self, entries: dict[str, list[float]], *, model: str, dimensions: int
    ) -> None: ...


class SupabaseEmbeddingCache:
    """The `embedding_cache` table, created by migration 0005."""

    async def get_many(
        self, content_hashes: list[str], *, model: str, dimensions: int
    ) -> dict[str, list[float]]:
        if not content_hashes:
            return {}
        return await queries.fetch_cached_embeddings(
            content_hashes, model=model, dimensions=dimensions
        )

    async def put_many(
        self, entries: dict[str, list[float]], *, model: str, dimensions: int
    ) -> None:
        await queries.store_cached_embeddings(entries, model=model, dimensions=dimensions)


class EmbeddingService:
    """Turns text into vectors, spending as few provider calls as possible."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        settings: Settings,
        cache: EmbeddingCache,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._cache = cache

    @property
    def dimensions(self) -> int:
        """Vector width, taken from the provider that will produce the vectors."""
        return self._provider.dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts`, returning one vector per input, in input order."""
        if not texts:
            return []

        hashes = [sha256_hex(text) for text in texts]

        # Identical text is common -- a repeated table header, a boilerplate
        # clause, the same fee line on two pages. Embedding it twice would spend a
        # second call on a vector already in hand, so each distinct hash is
        # embedded once and reused for every position that carries it.
        unique: dict[str, str] = {}
        for key, text in zip(hashes, texts, strict=True):
            unique.setdefault(key, text)

        resolved = await self._load(list(unique))
        missing = [key for key in unique if key not in resolved]

        batch_size = self._settings.embed_batch_size
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            vectors = await self._embed_with_retry([unique[key] for key in batch])
            if len(vectors) != len(batch):
                # Defensive rather than redundant: the Gemini provider checks this
                # too, but the service depends on the Protocol, and a replacement
                # provider that folded a batch into one vector would otherwise
                # poison every chunk silently.
                raise ProviderError(
                    f"Asked for {len(batch)} embeddings and received {len(vectors)}.",
                    transient=False,
                )
            produced = dict(zip(batch, vectors, strict=True))
            resolved.update(produced)
            # Written through batch by batch rather than once at the end: if batch
            # 7 fails, batches 1-6 stay cached and the retry pays only for the
            # batches that did not finish.
            await self._store(produced)

        return [resolved[key] for key in hashes]

    async def _load(self, content_hashes: list[str]) -> dict[str, list[float]]:
        if not content_hashes or not self._settings.embedding_cache_enabled:
            return {}
        return await self._cache.get_many(
            content_hashes,
            model=self._settings.embedding_model,
            dimensions=self.dimensions,
        )

    async def _store(self, entries: dict[str, list[float]]) -> None:
        if not entries or not self._settings.embedding_cache_enabled:
            return
        try:
            await self._cache.put_many(
                entries,
                model=self._settings.embedding_model,
                dimensions=self.dimensions,
            )
        except Exception as exc:  # noqa: BLE001 - the cache is an optimisation
            # Deliberately swallowed. The vectors in hand are valid and the document
            # can still become searchable; failing the whole ingestion because a
            # cache write failed would trade a working pipeline for a faster one.
            # Logged at warning so the condition is visible rather than silent.
            logger.warning(
                "Could not write %d vectors to the embedding cache: %s", len(entries), exc
            )

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Embed one batch, retrying only failures that could plausibly pass."""
        attempt = 0
        while True:
            try:
                return await self._provider.embed(texts)
            except ProviderError as exc:
                if not exc.transient or attempt >= self._settings.embedding_max_retries:
                    raise
                # Exponential backoff: a 429 is usually a rate limit, and
                # retrying immediately is the one response guaranteed to make it
                # worse.
                delay = self._settings.retry_backoff_seconds * (2**attempt)
                attempt += 1
                # The batch size and the error, never the text itself: AGENTS.md
                # section 7 forbids logging document content.
                logger.warning(
                    "Embedding a batch of %d failed, retrying in %.1fs (%d of %d retries used): %s",
                    len(texts),
                    delay,
                    attempt,
                    self._settings.embedding_max_retries,
                    exc,
                )
                await asyncio.sleep(delay)
