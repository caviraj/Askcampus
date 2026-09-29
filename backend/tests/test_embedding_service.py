"""Embedding service: batching, the cache, retries, and output order.

Everything here runs against `FakeEmbeddingProvider`, so no test touches the
network and the vectors are derived from the text -- which is what lets a test
assert that position 3 came back with the vector for the text that was at
position 3, rather than merely that three vectors came back.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.errors import ProviderError
from app.services.embedding import EmbeddingService
from app.services.hashing import sha256_hex
from tests.fakes import FakeEmbeddingProvider, InMemoryEmbeddingCache, fake_vector


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def cache() -> InMemoryEmbeddingCache:
    return InMemoryEmbeddingCache()


@pytest.fixture
def service(
    settings: Settings,
    provider: FakeEmbeddingProvider,
    cache: InMemoryEmbeddingCache,
) -> EmbeddingService:
    return EmbeddingService(provider, settings, cache)


def _texts(count: int) -> list[str]:
    return [f"Fee clause number {index} applies to semester {index}." for index in range(count)]


async def test_no_input_makes_no_call(
    service: EmbeddingService, provider: FakeEmbeddingProvider
) -> None:
    assert await service.embed_texts([]) == []
    assert provider.batch_sizes == []


async def test_one_vector_comes_back_per_text(
    service: EmbeddingService, provider: FakeEmbeddingProvider
) -> None:
    texts = _texts(3)
    vectors = await service.embed_texts(texts)
    assert len(vectors) == 3
    assert provider.batch_sizes == [3]


async def test_vectors_are_in_input_order(
    service: EmbeddingService, provider: FakeEmbeddingProvider
) -> None:
    """The property that matters most: a reordering would attach the wrong vector
    to the wrong chunk, and retrieval would just be subtly worse with nothing to
    point at."""
    texts = _texts(20)
    vectors = await service.embed_texts(texts)
    assert vectors == [fake_vector(text) for text in texts]


async def test_texts_are_split_into_batches(
    settings: Settings, provider: FakeEmbeddingProvider, cache: InMemoryEmbeddingCache
) -> None:
    """ARCHITECTURE.md section 8 specifies batches of 50. The last batch is short
    rather than padded, which is what the provider expects."""
    service = EmbeddingService(
        provider, settings.model_copy(update={"embed_batch_size": 50}), cache
    )
    vectors = await service.embed_texts(_texts(120))
    assert provider.batch_sizes == [50, 50, 20]
    assert len(vectors) == 120


async def test_a_batch_boundary_does_not_disturb_the_order(
    settings: Settings, provider: FakeEmbeddingProvider, cache: InMemoryEmbeddingCache
) -> None:
    service = EmbeddingService(provider, settings.model_copy(update={"embed_batch_size": 7}), cache)
    texts = _texts(20)
    assert await service.embed_texts(texts) == [fake_vector(text) for text in texts]


async def test_identical_text_is_embedded_once(
    service: EmbeddingService, provider: FakeEmbeddingProvider
) -> None:
    """A repeated table header or boilerplate clause is common, and paying a
    second provider call for a vector already in hand is waste on a free tier."""
    vectors = await service.embed_texts(["Fees are due in June."] * 3)
    assert len(vectors) == 3
    assert vectors[0] == vectors[1] == vectors[2]
    assert provider.batch_sizes == [1]


async def test_a_cache_hit_skips_the_provider_entirely(
    settings: Settings,
    provider: FakeEmbeddingProvider,
    cache: InMemoryEmbeddingCache,
) -> None:
    """The whole point of the cache: a reprocess of unchanged text costs nothing."""
    service = EmbeddingService(provider, settings, cache)
    texts = _texts(5)
    await service.embed_texts(texts)
    calls_after_first = len(provider.batch_sizes)

    vectors = await service.embed_texts(texts)
    assert len(provider.batch_sizes) == calls_after_first
    assert vectors == [fake_vector(text) for text in texts]


async def test_cache_entries_are_keyed_by_the_text_hash(
    service: EmbeddingService, cache: InMemoryEmbeddingCache
) -> None:
    """Keyed by content, not position: the same text at a different index must
    still hit, and different text must not."""
    await service.embed_texts(["Fees are due in June."])
    assert sha256_hex("Fees are due in June.") in cache.entries
    assert sha256_hex("Hostel forms open in May.") not in cache.entries


async def test_a_partial_hit_embeds_only_the_misses(
    settings: Settings,
    provider: FakeEmbeddingProvider,
    cache: InMemoryEmbeddingCache,
) -> None:
    service = EmbeddingService(provider, settings, cache)
    texts = _texts(6)
    await service.embed_texts(texts[:3])

    vectors = await service.embed_texts(texts)
    # Only the three new texts were sent, and the order is still the input order.
    assert provider.texts[3:] == texts[3:]
    assert vectors == [fake_vector(text) for text in texts]


async def test_a_partial_hit_still_uses_the_cached_vectors(
    settings: Settings,
    provider: FakeEmbeddingProvider,
    cache: InMemoryEmbeddingCache,
) -> None:
    service = EmbeddingService(provider, settings, cache)
    texts = _texts(4)
    await service.embed_texts(texts[:2])
    cache.entries[sha256_hex(texts[0])] = [0.5] * 768

    vectors = await service.embed_texts(texts)
    assert vectors[0] == [0.5] * 768
    assert vectors[1] == fake_vector(texts[1])


async def test_the_cache_is_written_through_per_batch(
    settings: Settings,
    provider: FakeEmbeddingProvider,
    cache: InMemoryEmbeddingCache,
) -> None:
    """Written batch by batch, so a failure on batch 7 leaves batches 1-6 cached
    and the retry pays only for what did not finish."""
    service = EmbeddingService(
        provider, settings.model_copy(update={"embed_batch_size": 10}), cache
    )
    await service.embed_texts(_texts(25))
    assert cache.writes == 3
    assert len(cache.entries) == 25


async def test_a_transient_failure_is_retried_and_succeeds(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    provider = FakeEmbeddingProvider(transient_failures=2)
    service = EmbeddingService(
        provider, settings.model_copy(update={"retry_backoff_seconds": 0.0}), cache
    )
    vectors = await service.embed_texts(_texts(3))
    assert vectors == [fake_vector(text) for text in _texts(3)]
    assert len(provider.batch_sizes) == 3


async def test_a_transient_failure_gives_up_after_the_retry_budget(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    """Bounded, not infinite: a provider that is down stays down."""
    provider = FakeEmbeddingProvider(transient_failures=99)
    service = EmbeddingService(
        provider,
        settings.model_copy(update={"retry_backoff_seconds": 0.0, "embedding_max_retries": 3}),
        cache,
    )
    with pytest.raises(ProviderError):
        await service.embed_texts(_texts(1))
    # The first attempt plus three retries.
    assert len(provider.batch_sizes) == 4


async def test_a_permanent_failure_is_not_retried(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    """A retired model returns 404 on every attempt. Retrying it turns a fast,
    clear failure into a slow one -- the loop finding 1 would otherwise produce."""
    provider = FakeEmbeddingProvider(
        error=ProviderError("models/text-embedding-004 is not found", transient=False)
    )
    service = EmbeddingService(
        provider, settings.model_copy(update={"retry_backoff_seconds": 0.0}), cache
    )
    with pytest.raises(ProviderError, match="not found"):
        await service.embed_texts(_texts(1))
    assert len(provider.batch_sizes) == 1


async def test_a_provider_that_returns_too_few_vectors_is_rejected(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    """The finding-3 guard. If a batch of 50 folded into one vector, every chunk
    after the first would silently receive the wrong embedding."""

    class FoldingProvider(FakeEmbeddingProvider):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.batch_sizes.append(len(texts))
            return [fake_vector(" ".join(texts))]

    service = EmbeddingService(FoldingProvider(), settings, cache)
    with pytest.raises(ProviderError, match="received 1"):
        await service.embed_texts(_texts(3))


async def test_a_cache_write_failure_does_not_fail_the_document(
    settings: Settings, provider: FakeEmbeddingProvider
) -> None:
    """The cache is an optimisation. Failing ingestion because a cache write
    failed would trade a working pipeline for a faster one."""

    class BrokenCache(InMemoryEmbeddingCache):
        async def put_many(
            self, entries: dict[str, list[float]], *, model: str, dimensions: int
        ) -> None:
            raise RuntimeError("the cache table is unavailable")

    vectors = await EmbeddingService(provider, settings, BrokenCache()).embed_texts(_texts(2))
    assert len(vectors) == 2


async def test_a_cache_read_failure_is_not_swallowed(
    settings: Settings, provider: FakeEmbeddingProvider
) -> None:
    """Unlike a write, a failed read is not caught: it happens before any vector
    exists, so there is nothing to salvage and the caller must know."""

    class BrokenCache(InMemoryEmbeddingCache):
        async def get_many(
            self, content_hashes: list[str], *, model: str, dimensions: int
        ) -> dict[str, list[float]]:
            raise RuntimeError("the cache table is unavailable")

    service = EmbeddingService(provider, settings, BrokenCache())
    with pytest.raises(RuntimeError):
        await service.embed_texts(_texts(1))


async def test_the_cache_is_consulted_with_the_configured_model_and_width(
    settings: Settings, provider: FakeEmbeddingProvider
) -> None:
    """A stale entry from a different model or width must not be returned, which
    is why both are part of the key rather than implicit."""

    class RecordingCache(InMemoryEmbeddingCache):
        def __init__(self) -> None:
            super().__init__()
            self.keys: list[tuple[str, int]] = []

        async def get_many(
            self, content_hashes: list[str], *, model: str, dimensions: int
        ) -> dict[str, list[float]]:
            self.keys.append((model, dimensions))
            return await super().get_many(content_hashes, model=model, dimensions=dimensions)

    cache = RecordingCache()
    service = EmbeddingService(provider, settings, cache)
    await service.embed_texts(_texts(1))
    assert cache.keys == [(settings.embedding_model, provider.dimensions)]


async def test_the_cache_can_be_turned_off(
    settings: Settings, provider: FakeEmbeddingProvider, cache: InMemoryEmbeddingCache
) -> None:
    service = EmbeddingService(
        provider, settings.model_copy(update={"embedding_cache_enabled": False}), cache
    )
    texts = _texts(2)
    await service.embed_texts(texts)
    await service.embed_texts(texts)
    assert cache.reads == 0
    assert cache.writes == 0
    assert provider.batch_sizes == [2, 2]


async def test_the_retry_budget_is_per_batch(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    """A retry budget spent on batch 1 must not leave batch 2 with none: each
    batch is an independent call with an independent chance of succeeding.

    (The 30 s provider timeout itself is enforced in the provider, and is
    asserted there -- this service has no timeout of its own to test.)
    """
    provider = FakeEmbeddingProvider(transient_failures=0)
    service = EmbeddingService(provider, settings.model_copy(update={"embed_batch_size": 2}), cache)

    calls: list[list[str]] = []
    original = provider.embed

    async def fail_each_batch_once(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        if len(calls) <= 2:
            raise ProviderError("The provider is busy.", transient=True)
        return await original(texts)

    provider.embed = fail_each_batch_once  # type: ignore[method-assign]
    vectors = await service.embed_texts(_texts(4))
    assert len(calls) == 4  # two batches, each retried once
    assert vectors == [fake_vector(text) for text in _texts(4)]


async def test_dimensions_come_from_the_provider(
    settings: Settings, cache: InMemoryEmbeddingCache
) -> None:
    """Read from the provider rather than config: the width that will actually be
    returned is what the vector column has to match."""
    provider = FakeEmbeddingProvider(dimensions=1536)
    service = EmbeddingService(provider, settings, cache)
    assert service.dimensions == 1536
    assert len((await service.embed_texts(_texts(1)))[0]) == 1536
