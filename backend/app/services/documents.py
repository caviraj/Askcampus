"""Document repository: the ingestion pipeline's view of `documents` and `chunks`.

A Protocol rather than direct calls into `app/db/queries.py`, matching
`ProfileRepository` in app/services/auth.py, so the ingestion tests can substitute
an in-memory implementation. That matters more here than elsewhere: the tests that
prove a half-finished reprocess leaves the previous chunks intact need a
repository that can be told to fail at an exact step.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.db.queries import (
    claim_document_for_processing,
    delete_document,
    fetch_document,
    fetch_document_file_path,
    find_active_document_by_hash,
    insert_document,
    list_documents,
    mark_document_failed,
    replace_document_chunks,
    update_document,
)


class DocumentRepository(Protocol):
    """Reads and writes for the documents a pipeline run touches."""

    async def insert(self, row: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, document_id: UUID) -> dict[str, Any] | None: ...

    async def get_file_reference(self, document_id: UUID) -> dict[str, Any] | None: ...

    async def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def update(self, document_id: UUID, patch: dict[str, Any]) -> dict[str, Any] | None: ...

    async def claim_for_processing(self, document_id: UUID) -> dict[str, Any] | None: ...

    async def mark_failed(self, document_id: UUID, message: str) -> None: ...

    async def delete(self, document_id: UUID) -> None: ...

    async def find_by_hash(self, content_hash: str) -> dict[str, Any] | None: ...

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
        *,
        mark_ready: bool = True,
    ) -> int: ...


class SupabaseDocumentRepository:
    """DocumentRepository backed by the real database."""

    async def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        return await insert_document(row)

    async def get(self, document_id: UUID) -> dict[str, Any] | None:
        return await fetch_document(document_id)

    async def get_file_reference(self, document_id: UUID) -> dict[str, Any] | None:
        return await fetch_document_file_path(document_id)

    async def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        return await list_documents(
            limit=limit, offset=offset, status=status, category=category, is_active=is_active
        )

    async def update(self, document_id: UUID, patch: dict[str, Any]) -> dict[str, Any] | None:
        return await update_document(document_id, patch)

    async def claim_for_processing(self, document_id: UUID) -> dict[str, Any] | None:
        return await claim_document_for_processing(document_id)

    async def mark_failed(self, document_id: UUID, message: str) -> None:
        await mark_document_failed(document_id, message)

    async def delete(self, document_id: UUID) -> None:
        await delete_document(document_id)

    async def find_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        return await find_active_document_by_hash(content_hash)

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
        *,
        mark_ready: bool = True,
    ) -> int:
        return await replace_document_chunks(document_id, chunks, metadata, mark_ready=mark_ready)
