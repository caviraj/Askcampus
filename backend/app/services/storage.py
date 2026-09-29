"""File storage.

A Protocol so the ingestion pipeline can be tested without a Supabase project,
with one implementation backed by Storage.
"""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from app.db.client import get_db_client


class StorageError(Exception):
    """Raised when a storage operation fails."""


class FileStorage(Protocol):
    async def put(self, path: str, data: bytes, content_type: str) -> None: ...

    async def get(self, path: str) -> bytes: ...

    async def delete(self, path: str) -> None: ...


def build_object_path(file_type: str) -> str:
    """A random storage key, extension preserved.

    AGENTS.md section 9 requires files to be stored under random names, so an
    uploaded document is not reachable by guessing its title. The extension is
    kept because it identifies the file type; `documents.file_type` is the
    authority, this is a convenience.
    """
    return f"{uuid4().hex}.{file_type.strip().lstrip('.').lower()}"


class SupabaseFileStorage:
    """Storage-backed FileStorage using the service role."""

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        try:
            await (
                get_db_client()
                .storage.from_(self._bucket)
                .upload(
                    path=path,
                    file=data,
                    # content-type is always passed explicitly: the storage client
                    # defaults to text/plain, so omitting it stores a PDF as plain
                    # text and nothing about the response looks wrong.
                    file_options={"content-type": content_type, "upsert": "false"},
                )
            )
        except Exception as exc:  # noqa: BLE001 - storage3 raises several unrelated types
            raise StorageError(f"Could not store the file: {exc}") from exc

    async def get(self, path: str) -> bytes:
        try:
            return await get_db_client().storage.from_(self._bucket).download(path)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not read the stored file: {exc}") from exc

    async def delete(self, path: str) -> None:
        try:
            await get_db_client().storage.from_(self._bucket).remove([path])
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Could not delete the stored file: {exc}") from exc
