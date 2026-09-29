"""Retrieval: what gets searched, and which hits survive to be cited.

The repository here is the in-memory double, whose `search` narrows a scripted
ranking by category the way `filter_category` does, and whose `hydrate`
reproduces the searchable filter. The re-mapping and dropping behaviour is the
Supabase repository's, so those two are exercised separately by patching the
query module.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.db import queries
from app.services.embedding import EmbeddingService
from app.services.retrieval import (
    RetrievalResult,
    RetrievalService,
    SupabaseChunkRepository,
    _best_similarity,
)
from tests.fakes import (
    FakeEmbeddingProvider,
    InMemoryChunkRepository,
    InMemoryEmbeddingCache,
)

BELOW = -0.2
# Comfortably above any configured threshold: these tests are about which scope
# was searched, not about where the line sits.
GOOD = 0.9


@pytest.fixture
def repository() -> InMemoryChunkRepository:
    return InMemoryChunkRepository()


@pytest.fixture
def retrieval(
    settings: Settings,
    repository: InMemoryChunkRepository,
    embedding_provider: FakeEmbeddingProvider,
) -> RetrievalService:
    return RetrievalService(
        EmbeddingService(embedding_provider, settings, InMemoryEmbeddingCache()),
        repository,
        settings,
    )


def seed(
    repository: InMemoryChunkRepository,
    *,
    category: str = "general",
    **document: object,
) -> UUID:
    """One document with one chunk, and the chunk's id back.

    Seeding does not script the ranking: `prime` does that, once per test. A
    helper that primed on every call would silently discard the ranking set by
    the call before it.
    """
    document_id = repository.seed_document(category=category, **document)
    return repository.seed_chunk(document_id, content=f"A passage filed under {category}.")


async def test_no_filter_is_passed_through_as_none(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    await retrieval.retrieve(search_text="anything", category=None)

    assert repository.searched == [None]


async def test_a_filter_is_applied_when_given(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    examinations = seed(repository, category="examinations")
    repository.prime([(examinations, GOOD)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations"]
    assert result.best_similarity == pytest.approx(GOOD)


async def test_a_good_filtered_result_is_not_searched_again(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    """The retry costs a query, so it must not happen when it is not needed."""
    examinations = seed(repository, category="examinations")
    admissions = seed(repository, category="admissions")
    repository.prime([(examinations, GOOD), (admissions, 0.99)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations"]
    assert result.best_similarity == pytest.approx(GOOD)


async def test_a_weak_filtered_result_is_searched_again_unfiltered(
    retrieval: RetrievalService, repository: InMemoryChunkRepository, settings: Settings
) -> None:
    """The case the retry exists for.

    Not an empty filtered result -- filtered rows that all score below the
    threshold, where one wrong category guess would turn an answerable question
    into a fallback.
    """
    weak = seed(repository, category="examinations")
    better = seed(repository, category="admissions")
    repository.prime([(better, GOOD), (weak, settings.similarity_threshold + BELOW)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations", None]
    assert result.best_similarity == pytest.approx(GOOD)
    assert result.chunks[0].chunk_id == better


async def test_the_unfiltered_result_is_only_adopted_if_it_clears_the_threshold(
    retrieval: RetrievalService, repository: InMemoryChunkRepository, settings: Settings
) -> None:
    """Widening the search does not lower the bar for answering."""
    examinations = seed(repository, category="examinations")
    admissions = seed(repository, category="admissions")
    below = settings.similarity_threshold + BELOW
    repository.prime([(admissions, below + 0.1), (examinations, below)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations", None]
    # The filtered scope is what the student asked for, and neither scope is
    # going to be answered from.
    assert result.best_similarity == pytest.approx(below)


async def test_an_empty_filtered_result_is_searched_again(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    """Nothing in the chosen category is not the same as nothing anywhere."""
    admissions = seed(repository, category="admissions")
    repository.prime([(admissions, GOOD)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations", None]
    assert result.best_similarity == pytest.approx(GOOD)


async def test_a_weak_result_from_an_empty_scope_is_still_preferred(
    retrieval: RetrievalService, repository: InMemoryChunkRepository, settings: Settings
) -> None:
    """Both scopes fail the threshold, and the wider one is returned anyway.

    The question falls back either way, so the choice is only about what the
    fallback can say: it names the office of the best-ranked document, and an
    empty result has no document to read one from.
    """
    admissions = seed(repository, category="admissions", department="Admissions")
    repository.prime([(admissions, settings.similarity_threshold + BELOW)])

    result = await retrieval.retrieve(search_text="anything", category="examinations")

    assert repository.searched == ["examinations", None]
    assert [chunk.chunk_id for chunk in result.chunks] == [admissions]


async def test_an_empty_search_has_no_similarity(retrieval: RetrievalService) -> None:
    result = await retrieval.retrieve(search_text="anything", category=None)

    assert result.chunks == []
    assert result.best_similarity is None


async def test_keyword_only_hits_have_no_similarity(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    """`hybrid_search` returns NULL similarity for a keyword-only hit.

    There is no cosine evidence for one, so there is nothing to compare against
    the threshold -- which is what makes the decision honest rather than
    optimistic.
    """
    keyword_only = seed(repository)
    repository.prime([(keyword_only, None)])

    result = await retrieval.retrieve(search_text="anything", category=None)

    assert result.best_similarity is None
    assert len(result.chunks) == 1


async def test_the_similarity_is_the_best_of_all_the_rows_not_the_top_one(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    """The constraint migration 0002's own comment puts on the caller.

    RRF can rank a keyword-only hit above every semantic one, so reading the
    first row's similarity would see NULL and fall back on a question the search
    had in fact matched well.
    """
    document_id = repository.seed_document()
    keyword_only = repository.seed_chunk(document_id, content="Keyword hit.")
    semantic = repository.seed_chunk(document_id, content="Semantic hit.")
    repository.prime([(keyword_only, None), (semantic, 0.91)])

    result = await retrieval.retrieve(search_text="anything", category=None)

    assert result.chunks[0].chunk_id == keyword_only
    assert result.best_similarity == pytest.approx(0.91)


async def test_a_chunk_whose_document_was_deactivated_is_dropped(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    """AGENTS.md section 6.12, as a condition on what may be cited.

    The ranking and the passage lookup are two requests, so a document taken out
    of service in between must not be cited from the stale ranking.
    """
    deactivated = seed(repository, is_active=False)
    repository.prime([(deactivated, 0.95)])

    result = await retrieval.retrieve(search_text="anything", category=None)

    assert result.chunks == []
    assert result.best_similarity is None


async def test_a_chunk_whose_document_is_not_ready_is_dropped(
    retrieval: RetrievalService, repository: InMemoryChunkRepository
) -> None:
    processing = seed(repository, status="processing")
    repository.prime([(processing, 0.95)])

    result = await retrieval.retrieve(search_text="anything", category=None)

    assert result.chunks == []


async def test_the_question_is_embedded_as_a_query(
    retrieval: RetrievalService, embedding_provider: FakeEmbeddingProvider
) -> None:
    """Not as a document.

    The provider's two task types are asymmetric, and the single-text entry point
    is what selects the query one.
    """
    await retrieval.retrieve(search_text="when is the exam fee due", category=None)

    assert embedding_provider.queries == ["when is the exam fee due"]
    assert embedding_provider.texts == []


async def test_the_configured_top_k_is_what_the_search_is_asked_for(
    retrieval: RetrievalService, repository: InMemoryChunkRepository, settings: Settings
) -> None:
    """AGENTS.md section 7: TOP_K comes from config, not from a literal here."""
    await retrieval.retrieve(search_text="anything", category=None)

    assert repository.match_counts == [settings.top_k]


def test_the_threshold_decision_answers_at_exactly_the_threshold(settings: Settings) -> None:
    """Above the line is `>=`, not `>`.

    SIMILARITY_THRESHOLD is documented as the point below which an answer is not
    attempted, so the value itself is attempted.
    """
    service = RetrievalService(
        EmbeddingService(FakeEmbeddingProvider(), settings, InMemoryEmbeddingCache()),
        InMemoryChunkRepository(),
        settings,
    )

    assert service.clears_threshold(
        RetrievalResult(chunks=[], best_similarity=settings.similarity_threshold)
    )
    assert not service.clears_threshold(
        RetrievalResult(chunks=[], best_similarity=settings.similarity_threshold - 0.001)
    )
    assert not service.clears_threshold(RetrievalResult(chunks=[], best_similarity=None))


def test_best_similarity_ignores_the_nulls() -> None:
    class Chunk:
        def __init__(self, similarity: float | None) -> None:
            self.similarity = similarity

    assert _best_similarity([Chunk(None), Chunk(0.4), Chunk(0.8)]) == 0.8
    assert _best_similarity([Chunk(None), Chunk(None)]) is None
    assert _best_similarity([]) is None


# ---------------------------------------------------------------------------
# The Supabase repository's hydration, which is where the row-order trap is
# ---------------------------------------------------------------------------


@pytest.fixture
def canned_rows(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict]]:
    """Replace the two hydration queries with canned rows.

    The real `fetch_searchable_documents` filters on `is_active` and `status`;
    these tests put only searchable documents in, so that filter is proven
    against the in-memory repository above instead.
    """
    rows: dict[str, list[dict]] = {"chunks": [], "documents": []}

    async def fetch_chunks(chunk_ids: list[UUID]) -> list[dict]:
        wanted = {str(chunk_id) for chunk_id in chunk_ids}
        return [row for row in rows["chunks"] if str(row["id"]) in wanted]

    async def fetch_documents(document_ids: list[UUID]) -> list[dict]:
        wanted = {str(document_id) for document_id in document_ids}
        return [row for row in rows["documents"] if str(row["id"]) in wanted]

    monkeypatch.setattr(queries, "fetch_searchable_chunks", fetch_chunks)
    monkeypatch.setattr(queries, "fetch_searchable_documents", fetch_documents)
    return rows


def document_row(document_id: UUID, **overrides: object) -> dict:
    row = {
        "id": str(document_id),
        "title": "One document",
        "department": None,
        "updated_at": "2026-09-10T09:00:00+00:00",
    }
    row.update(overrides)
    return row


def chunk_row(chunk_id: UUID, document_id: UUID, **overrides: object) -> dict:
    row = {
        "id": str(chunk_id),
        "document_id": str(document_id),
        "content": "A passage.",
        "page_number": 1,
        "section_heading": None,
    }
    row.update(overrides)
    return row


def hit(chunk_id: UUID, document_id: UUID, *, score: float, similarity: float | None) -> dict:
    return {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "score": score,
        "similarity": similarity,
    }


async def test_hydration_remaps_by_id_when_rows_come_back_out_of_order(
    canned_rows: dict[str, list[dict]],
) -> None:
    """Row order is not part of the contract.

    Zipping the hits against the returned rows would attach the wrong passage to
    the wrong score, and the result would still read as a plausible answer.
    """
    first, second, document_id = uuid4(), uuid4(), uuid4()
    canned_rows["documents"] = [document_row(document_id)]
    canned_rows["chunks"] = [
        # Deliberately the reverse of the order the hits arrive in.
        chunk_row(second, document_id, content="Second passage.", page_number=2),
        chunk_row(first, document_id, content="First passage."),
    ]
    hits = [
        hit(first, document_id, score=0.9, similarity=0.8),
        hit(second, document_id, score=0.1, similarity=0.2),
    ]

    hydrated = await SupabaseChunkRepository().hydrate(hits)

    assert [chunk.content for chunk in hydrated] == ["First passage.", "Second passage."]
    assert [chunk.score for chunk in hydrated] == [0.9, 0.1]
    assert [chunk.similarity for chunk in hydrated] == [0.8, 0.2]


async def test_hydration_drops_a_hit_whose_row_is_gone(
    canned_rows: dict[str, list[dict]],
) -> None:
    """A missing row is not an error.

    It means the chunk went with a deleted document, and the useful answer is to
    cite one less thing, not to fail the question.
    """
    present, absent, document_id = uuid4(), uuid4(), uuid4()
    canned_rows["documents"] = [document_row(document_id)]
    canned_rows["chunks"] = [chunk_row(present, document_id)]
    hits = [
        hit(present, document_id, score=0.9, similarity=0.8),
        hit(absent, document_id, score=0.5, similarity=0.7),
    ]

    hydrated = await SupabaseChunkRepository().hydrate(hits)

    assert [chunk.chunk_id for chunk in hydrated] == [present]


async def test_hydration_drops_a_hit_whose_document_is_no_longer_searchable(
    canned_rows: dict[str, list[dict]],
) -> None:
    """The real `fetch_searchable_documents` omits those, so a hit whose document
    is absent from its result is one that may no longer be cited."""
    chunk_id, document_id = uuid4(), uuid4()
    canned_rows["documents"] = []
    canned_rows["chunks"] = [chunk_row(chunk_id, document_id)]

    hydrated = await SupabaseChunkRepository().hydrate(
        [hit(chunk_id, document_id, score=0.9, similarity=0.9)]
    )

    assert hydrated == []


async def test_a_chunk_with_no_section_or_page_still_hydrates(
    canned_rows: dict[str, list[dict]],
) -> None:
    """A DOCX or TXT chunk genuinely has neither, and that is not a reason to
    drop the only evidence for an answer."""
    chunk_id, document_id = uuid4(), uuid4()
    canned_rows["documents"] = [document_row(document_id, department="Examinations")]
    canned_rows["chunks"] = [
        chunk_row(chunk_id, document_id, page_number=None, section_heading=None)
    ]

    hydrated = await SupabaseChunkRepository().hydrate(
        [hit(chunk_id, document_id, score=0.9, similarity=0.9)]
    )

    assert len(hydrated) == 1
    assert hydrated[0].page_number is None
    assert hydrated[0].section_heading is None
    assert hydrated[0].department == "Examinations"
    assert hydrated[0].document_updated_at == "2026-09-10T09:00:00+00:00"


async def test_hydrating_nothing_asks_the_database_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(*args: object, **kwargs: object) -> list[dict]:
        raise AssertionError("The database was queried for an empty hit list.")

    monkeypatch.setattr(queries, "fetch_searchable_chunks", explode)
    monkeypatch.setattr(queries, "fetch_searchable_documents", explode)

    assert await SupabaseChunkRepository().hydrate([]) == []
