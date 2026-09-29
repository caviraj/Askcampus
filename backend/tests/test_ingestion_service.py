"""The ingestion orchestrator: status transitions and failure containment.

The pipeline runs for real here -- real extraction, real cleaning, real chunking
-- against generated files. Only the database, Storage and the embedding provider
are fakes, which is what makes the status assertions meaningful: the stages that
actually do the work are the ones under test.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.config import Settings
from app.db import queries
from app.providers.errors import ProviderError
from app.services.documents import DocumentRepository
from app.services.embedding import EmbeddingService
from app.services.ingestion import IngestionService
from app.services.storage import StorageError
from tests.fakes import (
    CLAIMABLE_STATUSES,
    FakeEmbeddingProvider,
    InMemoryDocumentRepository,
    InMemoryEmbeddingCache,
    InMemoryFileStorage,
)
from tests.filebuilders import PdfLine, pdf_bytes, scanned_pdf

_SEARCHABLE_PDF = pdf_bytes(
    [
        [
            PdfLine("1. Examination Fees", size=14.0),
            PdfLine(
                "The examination fee for the semester is 500 rupees, "
                "payable at the accounts office in June."
            ),
        ],
        [
            PdfLine("1.1 Late payment", size=14.0),
            PdfLine(
                "A late payment of 100 rupees is charged after the due date, "
                "and the exam form is withheld until it is paid."
            ),
        ],
    ]
)


@pytest.fixture
def repository() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def service(
    settings: Settings,
    repository: InMemoryDocumentRepository,
    storage: InMemoryFileStorage,
    provider: FakeEmbeddingProvider,
) -> IngestionService:
    embeddings = EmbeddingService(provider, settings, InMemoryEmbeddingCache())
    return IngestionService(repository, storage, embeddings, settings)


def _seeded(
    repository: InMemoryDocumentRepository, *, data: bytes = _SEARCHABLE_PDF, **row: object
) -> dict:
    return repository.seed(**row)


async def test_a_successful_run_ends_ready(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)
    assert repository.rows[document["id"]]["status"] == "ready"


async def test_the_status_transitions_happen_in_order(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """`claim_for_processing` before any real work, `replace_chunks` after: the
    document must never be marked ready before its chunks exist."""
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)
    assert repository.calls == ["claim_for_processing", "get_file_reference", "replace_chunks"]


async def test_chunks_and_embeddings_are_written(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    rows = repository.chunks[document["id"]]
    assert rows
    assert all(len(row["embedding"]) == 768 for row in rows)
    assert [row["chunk_index"] for row in rows] == list(range(len(rows)))


async def test_a_chunk_row_carries_only_columns_that_exist(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """`token_count` has no column in the chunks table and `category` is copied
    from the document row inside the RPC, so sending either would be ignored at
    best and a column-mismatch error at worst."""
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    assert set(repository.chunks[document["id"]][0]) == {
        "chunk_index",
        "page_number",
        "section_heading",
        "content",
        "embedding",
    }


async def test_the_section_heading_reaches_the_chunk(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)
    headings = {row["section_heading"] for row in repository.chunks[document["id"]]}
    assert "1. Examination Fees" in headings


async def test_page_numbers_are_recorded(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)
    pages = {row["page_number"] for row in repository.chunks[document["id"]]}
    assert pages <= {1, 2}
    assert pages


async def test_metadata_is_recorded_on_the_document(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    row = repository.rows[document["id"]]
    assert row["page_count"] == 2
    assert row["chunk_count"] == len(repository.chunks[document["id"]])
    assert row["extracted_chars"] > 0
    assert row["text_preview"]
    assert row["low_text_yield"] is False


async def test_the_preview_is_the_opening_of_the_text(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=_SEARCHABLE_PDF)
    preview = repository.rows[document["id"]]["text_preview"]
    assert "Examination Fees" in preview
    assert len(preview) <= 500


async def test_an_extraction_failure_marks_the_document_failed(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository)
    await service.process(document["id"], data=b"this is not a pdf")

    row = repository.rows[document["id"]]
    assert row["status"] == "failed"
    assert row["error_message"]
    assert "replace_chunks" not in repository.calls


async def test_an_embedding_failure_marks_the_document_failed(
    service: IngestionService,
    repository: InMemoryDocumentRepository,
    provider: FakeEmbeddingProvider,
) -> None:
    document = _seeded(repository)
    provider.error = ProviderError("The provider is unavailable.", transient=False)
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    row = repository.rows[document["id"]]
    assert row["status"] == "failed"
    assert "embed" in row["error_message"].lower() or "generation" in row["error_message"].lower()


async def test_an_embedding_failure_never_touches_the_existing_chunks(
    service: IngestionService,
    repository: InMemoryDocumentRepository,
    provider: FakeEmbeddingProvider,
) -> None:
    """The property that makes reprocessing safe: embeddings are computed before
    the database is written, so the previous version stays searchable until the
    new one is whole."""
    document = _seeded(repository, status="ready")
    repository.chunks[document["id"]] = [{"chunk_index": 0, "content": "The old text."}]
    provider.error = ProviderError("The provider is unavailable.", transient=False)

    await service.process(document["id"], data=_SEARCHABLE_PDF)

    assert "replace_chunks" not in repository.calls
    assert repository.chunks[document["id"]] == [{"chunk_index": 0, "content": "The old text."}]


async def test_a_document_with_no_text_is_failed_rather_than_stored_empty(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """A scanned PDF has no text layer. PRD section 10 asks for those to be
    flagged, but zero chunks means the document can answer nothing at all, so this
    is the one "no text" case that is an error."""
    document = _seeded(repository)
    await service.process(document["id"], data=scanned_pdf())

    row = repository.rows[document["id"]]
    assert row["status"] == "failed"
    assert "scan" in row["error_message"].lower()
    assert "replace_chunks" not in repository.calls


async def test_a_low_yield_but_readable_document_is_ready_with_the_flag(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """Flagged, not failed: an admin can see the extraction was thin and decide
    whether the document belongs in the knowledge base."""
    thin = pdf_bytes([[PdfLine("Fees.")], [PdfLine("Hostel.")]])
    document = _seeded(repository)
    await service.process(document["id"], data=thin)

    row = repository.rows[document["id"]]
    assert row["status"] == "ready"
    assert row["low_text_yield"] is True
    assert row["chunk_count"] == 1


async def test_a_document_that_does_not_exist_is_left_alone(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    await service.process(uuid4(), data=_SEARCHABLE_PDF)
    assert repository.calls == ["claim_for_processing"]


async def test_a_concurrent_run_is_a_no_op(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """The conditional update is the lock. Without it a second run would delete the
    chunks the first is still writing."""
    document = _seeded(repository, status="processing")
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    assert "replace_chunks" not in repository.calls
    assert repository.rows[document["id"]]["status"] == "processing"


async def test_a_failed_document_can_be_retried(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """`failed` is claimable, which is what makes reprocess work after an admin has
    fixed whatever was wrong."""
    document = _seeded(repository, status="failed", error_message="The provider was unavailable.")
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    row = repository.rows[document["id"]]
    assert row["status"] == "ready"
    assert row["error_message"] is None


async def test_a_ready_document_can_be_reprocessed(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    document = _seeded(repository, status="ready", chunk_count=99)
    repository.chunks[document["id"]] = [{"chunk_index": 0, "content": "Stale text."}]
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    assert repository.rows[document["id"]]["status"] == "ready"
    assert all(row["content"] != "Stale text." for row in repository.chunks[document["id"]])


async def test_a_missing_stored_file_fails_with_a_readable_message(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """No `data` means the bytes come from Storage, which is the only copy that
    survives a restart."""
    document = _seeded(repository)
    await service.process(document["id"])  # nothing was ever put in Storage

    row = repository.rows[document["id"]]
    assert row["status"] == "failed"
    assert row["error_message"].startswith("The stored file could not be read:")


async def test_a_stored_file_is_downloaded_when_no_bytes_are_supplied(
    service: IngestionService,
    repository: InMemoryDocumentRepository,
    storage: InMemoryFileStorage,
) -> None:
    document = _seeded(repository)
    storage.objects[document["file_path"]] = _SEARCHABLE_PDF

    await service.process(document["id"])

    assert repository.rows[document["id"]]["status"] == "ready"


async def test_an_unexpected_failure_still_ends_in_a_terminal_state(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """`process` must never raise: a background task that raises is swallowed by
    the server, and the row would sit in `processing` with no recovery."""
    document = _seeded(repository)
    repository.fail_on = {"replace_chunks"}

    await service.process(document["id"], data=_SEARCHABLE_PDF)

    row = repository.rows[document["id"]]
    assert row["status"] == "failed"
    assert "unexpected error" in row["error_message"]


async def test_a_failure_of_the_failure_handler_does_not_escape(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """If the database is unreachable the failure cannot be recorded, and raising
    here would only replace a logged failure with an unhandled one. The startup
    reaper is the backstop."""
    document = _seeded(repository)
    repository.fail_on = {"replace_chunks", "mark_failed"}

    await service.process(document["id"], data=_SEARCHABLE_PDF)  # must not raise


async def test_a_document_with_no_stored_path_fails_with_a_readable_message(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """A row whose Storage path is missing cannot be reprocessed, and the admin
    needs to be told that rather than shown a stack trace."""
    document = _seeded(repository, file_path=None)
    await service.process(document["id"])

    assert repository.rows[document["id"]]["error_message"] == (
        "The document has no stored file to process."
    )
    assert "replace_chunks" not in repository.calls


async def test_a_document_that_disappears_mid_run_does_not_raise(
    service: IngestionService, repository: InMemoryDocumentRepository
) -> None:
    """Deleted between the claim and the write. There is no row left to record a
    failure on, so the only requirement is that nothing escapes and no chunks are
    written for a document that no longer exists."""
    document = _seeded(repository)
    original = repository.get_file_reference

    async def vanish(document_id: UUID) -> dict | None:
        repository.rows.pop(document_id, None)
        return await original(document_id)

    repository.get_file_reference = vanish  # type: ignore[method-assign]
    await service.process(document["id"], data=_SEARCHABLE_PDF)

    assert repository.chunks == {}


async def test_a_storage_error_is_reported_as_a_file_problem(
    service: IngestionService,
    repository: InMemoryDocumentRepository,
    storage: InMemoryFileStorage,
) -> None:
    document = _seeded(repository)

    async def broken(path: str) -> bytes:
        raise StorageError("the object is gone")

    storage.get = broken  # type: ignore[method-assign]
    await service.process(document["id"])

    assert repository.rows[document["id"]]["error_message"].startswith(
        "The stored file could not be read:"
    )


def test_the_fake_lock_matches_the_real_one() -> None:
    """The concurrency tests are only meaningful if the fake's claim condition is
    the same set of statuses the real query filters on."""
    assert CLAIMABLE_STATUSES == set(queries._CLAIMABLE_STATUSES)


def test_the_repository_fake_implements_the_whole_protocol() -> None:
    """A method added to `DocumentRepository` and forgotten here would make every
    test in this file exercise a fake that silently lacks it."""
    declared = {name for name in vars(DocumentRepository) if not name.startswith("_")}
    assert declared
    assert all(callable(getattr(InMemoryDocumentRepository, name, None)) for name in declared)
