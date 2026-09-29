"""The ingestion orchestrator: uploaded bytes to embedded, searchable chunks.

    bytes -> extract -> clean -> chunk -> embed -> replace_document_chunks

Free of FastAPI imports, so the status machine is unit-testable without an HTTP
client. The pipeline is invoked as a background task; see app/api/documents.py for
why it is `BackgroundTasks` rather than `asyncio.create_task`.

Three properties this module is responsible for:

**Every run ends in a terminal state.** A background task that raises is swallowed
by the server, so `process` never lets an exception escape: each failure path ends
in `mark_failed`. A row left in `processing` is the one outcome with no recovery.

**A failed reprocess leaves the previous version searchable.** Embeddings are
computed before the database is touched, and the write is a single RPC, so a
failure at any point leaves the old chunks exactly as they were.

**A concurrent run on the same document is a no-op.** The conditional update in
`claim_for_processing` is the lock; a second run matches no row and returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anyio

from app.config import Settings
from app.providers.errors import ProviderError
from app.services.chunking import Chunk, chunk_document
from app.services.cleaning import clean_document
from app.services.documents import DocumentRepository
from app.services.embedding import EmbeddingService
from app.services.extraction import (
    ExtractedDocument,
    ExtractionError,
    extract_document,
    is_low_text_yield,
)
from app.services.storage import FileStorage, StorageError

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """A failure the admin is meant to read and act on.

    Separate from a crash: the message ends up on the document row and in the
    documents list, so it has to make sense to a person.
    """


@dataclass(frozen=True)
class _Prepared:
    """What the CPU-bound section produces, ready for the database."""

    chunks: list[Chunk]
    page_count: int | None
    extracted_chars: int
    text_preview: str | None
    low_text_yield: bool


class IngestionService:
    """Runs the pipeline for one document."""

    def __init__(
        self,
        repository: DocumentRepository,
        storage: FileStorage,
        embeddings: EmbeddingService,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._embeddings = embeddings
        self._settings = settings

    async def process(self, document_id: UUID, *, data: bytes | None = None) -> None:
        """Run the full pipeline for one document. Never raises.

        `data` is the file's bytes when the caller already has them in hand, which
        is the upload path: the request body was just validated, so re-downloading
        it from Storage would be a second round trip of up to 20 MB for bytes that
        are already in memory. Reprocessing and replacing pass None and read from
        Storage, which is the only copy that survives a restart.
        """
        try:
            await self._run(document_id, data)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            logger.exception("Ingestion failed for document %s", document_id)
            await self._mark_failed(document_id, _message_for(exc))

    async def _run(self, document_id: UUID, data: bytes | None) -> None:
        claimed = await self._repository.claim_for_processing(document_id)
        if claimed is None:
            # Either the document does not exist or another run already owns it.
            # Returning without touching chunks is the point of the lock: a second
            # concurrent run must not delete chunks out from under the first.
            logger.info("Document %s is not claimable; skipping this run.", document_id)
            return

        reference = await self._repository.get_file_reference(document_id)
        if reference is None:
            raise IngestionError("The document disappeared while it was being processed.")

        payload = data if data is not None else await self._download(reference)
        file_type = str(reference.get("file_type") or "")

        # Extraction, cleaning and chunking are CPU-bound and hold the GIL for
        # long stretches on a 20 MB PDF, so they run in a worker thread and the
        # event loop keeps serving requests while they do.
        prepared = await anyio.to_thread.run_sync(self._prepare, payload, file_type)

        if not prepared.chunks:
            # A scanned document with no text layer reaches here. PRD section 10
            # asks for such documents to be flagged rather than rejected, so this
            # is the one case where "no text" is an error rather than a warning:
            # zero chunks means the document cannot answer anything at all.
            raise IngestionError(
                "No text could be read from this file. If it is a scan, it needs a "
                "text layer before it can be searched."
            )

        vectors = await self._embeddings.embed_texts([chunk.content for chunk in prepared.chunks])

        # Embeddings are complete before the write, so this call either replaces
        # the chunks wholesale or changes nothing at all.
        count = await self._repository.replace_chunks(
            document_id,
            _chunk_rows(prepared.chunks, vectors),
            {
                "page_count": prepared.page_count,
                "extracted_chars": prepared.extracted_chars,
                "text_preview": prepared.text_preview,
                "low_text_yield": prepared.low_text_yield,
            },
        )
        logger.info("Document %s is ready with %d chunks.", document_id, count)

    def _prepare(self, data: bytes, file_type: str) -> _Prepared:
        """The synchronous, CPU-bound section. Runs on a worker thread."""
        extracted = extract_document(data, file_type, self._settings)
        cleaned = clean_document(extracted)
        chunks = chunk_document(cleaned, self._settings)
        return _Prepared(
            chunks=chunks,
            page_count=_page_count(cleaned),
            extracted_chars=cleaned.char_count,
            text_preview=_preview(cleaned, self._settings.text_preview_chars),
            low_text_yield=is_low_text_yield(
                cleaned,
                min_chars_per_page=self._settings.min_chars_per_page,
                page_ratio=self._settings.low_yield_page_ratio,
            ),
        )

    async def _download(self, reference: dict[str, Any]) -> bytes:
        path = reference.get("file_path")
        if not path:
            raise IngestionError("The document has no stored file to process.")
        return await self._storage.get(str(path))

    async def _mark_failed(self, document_id: UUID, message: str) -> None:
        try:
            await self._repository.mark_failed(document_id, message)
        except Exception:  # noqa: BLE001 - already handling a failure
            # If the database is unreachable this cannot be recorded, and raising
            # here would only replace a logged failure with an unhandled one. The
            # startup reaper in app/main.py is the backstop: the row is still
            # `processing`, and the next boot marks it failed.
            logger.exception("Could not record the failure of document %s", document_id)


def _chunk_rows(chunks: list[Chunk], vectors: list[list[float]]) -> list[dict[str, Any]]:
    """Build the JSON payload `replace_document_chunks` reads.

    Deliberately no `token_count`: the chunks table has no such column, and
    `Chunk.token_count` exists only to drive the chunker's budget and its tests.
    `category` is also absent -- the function copies it from the document row so
    the denormalized column cannot drift.
    """
    if len(chunks) != len(vectors):
        # Unreachable while EmbeddingService guarantees one vector per input, and
        # checked anyway because the consequence is silent: zip would truncate to
        # the shorter list and store a document missing its final chunks.
        raise IngestionError(f"Produced {len(chunks)} chunks but {len(vectors)} embeddings.")

    return [
        {
            "chunk_index": chunk.index,
            # None for DOCX and for text files with no page separators. The RPC
            # stores SQL NULL for a JSON null, so no page number is ever invented.
            "page_number": chunk.page_number,
            "section_heading": chunk.section_heading,
            "content": chunk.content,
            # Sent as an array of numbers; jsonb renders it as "[1, 2, 3]" and the
            # function strips the spaces before casting to vector.
            "embedding": vector,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]


def _page_count(document: ExtractedDocument) -> int | None:
    """Pages to record, or None when the format does not say.

    Prefers the count the format declared over the number of pages we produced,
    because for a PDF they can differ and the declared one is the truth. None is
    recorded as NULL rather than 0: a DOCX has no page count, and writing 0 would
    read as "empty document" in the admin list.
    """
    if document.page_count is not None:
        return document.page_count
    pages = [page.page_number for page in document.pages if page.page_number is not None]
    return max(pages) if pages else None


def _preview(document: ExtractedDocument, limit: int) -> str | None:
    """The opening of the cleaned text, so an admin can see what was read."""
    text = " ".join(document.text.split())
    if not text:
        return None
    return text[:limit]


def _message_for(exc: Exception) -> str:
    """An admin-facing reason, with no internal detail and no secrets."""
    if isinstance(exc, (IngestionError, ExtractionError)):
        return str(exc)
    if isinstance(exc, StorageError):
        return f"The stored file could not be read: {exc}"
    if isinstance(exc, ProviderError):
        return f"The text could not be embedded: {exc}"
    return f"Processing failed with an unexpected error ({type(exc).__name__})."
