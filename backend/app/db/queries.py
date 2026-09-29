"""Data access functions.

Route handlers and services call these rather than touching the Supabase client
directly, so the query surface stays narrow and typed.
"""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from app.db.client import get_db_client
from app.schemas.auth import Profile

# Must match vector(768) in supabase/migrations/0001_initial_schema.sql. Declared
# here because it is a fact about the schema, and checked against the configured
# embedding width at startup -- an insert with the wrong width fails with a
# pgvector cast error that never mentions dimensions.
CHUNK_EMBEDDING_DIMENSIONS = 768

# The columns the admin API needs. Spelled out rather than "*" so a later
# migration adding a large column does not silently start shipping it.
_DOCUMENT_COLUMNS = (
    "id,title,category,academic_year,department,file_type,original_filename,"
    "file_size_bytes,status,is_active,error_message,page_count,chunk_count,"
    "extracted_chars,low_text_yield,text_preview,created_at,updated_at"
)

# Statuses a document can be reprocessed from. A document already `processing`
# must not be claimed, which is what makes a double-click harmless.
_CLAIMABLE_STATUSES = ["uploaded", "ready", "failed"]

_PROCESSING_LOST_MESSAGE = "Processing was interrupted. Reprocess the document."


async def fetch_profile(user_id: UUID) -> Profile | None:
    """Return the profile row for a user, or None if there is no row.

    Returns None rather than raising on a missing row: "no profile" is a normal
    outcome that the auth gate turns into a 403.
    """
    response = await (
        get_db_client()
        .table("profiles")
        .select("id,full_name,role")
        .eq("id", str(user_id))
        .maybe_single()
        .execute()
    )
    data = getattr(response, "data", None)
    if not data:
        return None
    return Profile.model_validate(data)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def insert_document(row: dict[str, Any]) -> dict[str, Any]:
    response = (
        await get_db_client().table("documents").insert(row).select(_DOCUMENT_COLUMNS).execute()
    )
    return _first(response)


async def fetch_document(document_id: UUID) -> dict[str, Any] | None:
    response = await (
        get_db_client()
        .table("documents")
        .select(_DOCUMENT_COLUMNS)
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    return getattr(response, "data", None) or None


async def fetch_document_file_path(document_id: UUID) -> dict[str, Any] | None:
    """Just the storage key and type, for reprocessing."""
    response = await (
        get_db_client()
        .table("documents")
        .select("id,file_path,file_type,title")
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    return getattr(response, "data", None) or None


async def list_documents(
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    category: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """A page of documents, newest first, with the total before the range.

    Paginated explicitly because PostgREST silently caps a select at 1000 rows:
    an unpaginated list would truncate without saying so.
    """
    query = get_db_client().table("documents").select(_DOCUMENT_COLUMNS, count="exact")
    if status is not None:
        query = query.eq("status", status)
    if category is not None:
        query = query.eq("category", category)
    if is_active is not None:
        query = query.eq("is_active", is_active)

    response = (
        await query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    )
    items = getattr(response, "data", None) or []
    return items, int(getattr(response, "count", 0) or 0)


async def update_document(document_id: UUID, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Apply a partial update. `.select()` is required or no row comes back."""
    response = await (
        get_db_client()
        .table("documents")
        .update(patch)
        .eq("id", str(document_id))
        .select(_DOCUMENT_COLUMNS)
        .execute()
    )
    return _first_or_none(response)


async def claim_document_for_processing(document_id: UUID) -> dict[str, Any] | None:
    """Move a document to `processing`, returning it, or None if it was not claimable.

    The conditional update *is* the lock: a second concurrent run on the same
    document matches no row and returns None. `.select()` is what makes the
    returned row count observable -- without it PostgREST returns nothing and the
    caller cannot tell whether it won.
    """
    response = await (
        get_db_client()
        .table("documents")
        .update({"status": "processing", "error_message": None})
        .eq("id", str(document_id))
        .in_("status", _CLAIMABLE_STATUSES)
        .select(_DOCUMENT_COLUMNS)
        .execute()
    )
    return _first_or_none(response)


async def mark_document_failed(document_id: UUID, message: str) -> None:
    await (
        get_db_client()
        .table("documents")
        .update({"status": "failed", "error_message": message[:1000]})
        .eq("id", str(document_id))
        .execute()
    )


async def delete_document(document_id: UUID) -> None:
    """Delete the row. Chunks cascade via the foreign key in migration 0001."""
    await get_db_client().table("documents").delete().eq("id", str(document_id)).execute()


async def find_active_document_by_hash(content_hash: str) -> dict[str, Any] | None:
    """An active document with the same bytes, for duplicate detection."""
    response = await (
        get_db_client()
        .table("documents")
        .select("id,title")
        .eq("content_hash", content_hash)
        .eq("is_active", True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return getattr(response, "data", None) or None


async def reap_orphaned_processing_documents() -> int:
    """Mark documents left in `processing` by a previous process as failed.

    Background processing does not survive a kill -9, so a document can be left
    mid-flight forever. At startup nothing in this process is processing, so there
    are no false positives -- which assumes a single backend instance, as
    ARCHITECTURE.md section 11 deploys.
    """
    response = await (
        get_db_client()
        .table("documents")
        .update({"status": "failed", "error_message": _PROCESSING_LOST_MESSAGE})
        .eq("status", "processing")
        .select("id")
        .execute()
    )
    return len(getattr(response, "data", None) or [])


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


async def replace_document_chunks(
    document_id: UUID,
    chunks: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    mark_ready: bool = True,
) -> int:
    """Replace a document's chunks atomically and update its derived counts.

    Goes through the `replace_document_chunks` function rather than a
    delete-then-insert pair, because PostgREST exposes one statement per request
    and a crash between the two would leave the document with no chunks at all --
    the exact failure AGENTS.md section 13 exists to prevent.
    """
    response = await (
        get_db_client()
        .rpc(
            "replace_document_chunks",
            {
                "p_document_id": str(document_id),
                "p_chunks": chunks,
                "p_metadata": metadata,
                "p_mark_ready": mark_ready,
            },
        )
        .execute()
    )
    data = getattr(response, "data", None)
    if isinstance(data, int):
        return data
    # PostgREST returns a scalar function's result bare in some versions and as a
    # single-element list in others.
    if isinstance(data, list) and data and isinstance(data[0], int):
        return data[0]
    return len(chunks)


# ---------------------------------------------------------------------------
# Embedding cache
# ---------------------------------------------------------------------------


async def fetch_cached_embeddings(
    content_hashes: list[str],
    *,
    model: str,
    dimensions: int,
) -> dict[str, list[float]]:
    """Cached vectors for the given hashes, keyed by hash.

    Chunked into groups so a document with thousands of chunks does not build a
    URL longer than the server accepts.
    """
    found: dict[str, list[float]] = {}
    for batch in _batched(content_hashes, 100):
        response = await (
            get_db_client()
            .table("embedding_cache")
            .select("content_hash,embedding")
            .in_("content_hash", batch)
            .eq("model", model)
            .eq("dimensions", dimensions)
            .execute()
        )
        for row in getattr(response, "data", None) or []:
            vector = _parse_vector(row.get("embedding"))
            if vector is not None:
                found[str(row["content_hash"])] = vector
    return found


async def store_cached_embeddings(
    entries: dict[str, list[float]],
    *,
    model: str,
    dimensions: int,
) -> None:
    """Write vectors through as they are produced.

    Upserted rather than inserted so a partially warmed cache from an interrupted
    run does not fail the next one.
    """
    if not entries:
        return
    rows = [
        {
            "content_hash": content_hash,
            "model": model,
            "dimensions": dimensions,
            "embedding": vector,
        }
        for content_hash, vector in entries.items()
    ]
    await get_db_client().table("embedding_cache").upsert(rows).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first(response: Any) -> dict[str, Any]:
    rows = getattr(response, "data", None) or []
    if not rows:
        raise RuntimeError("The database returned no row where one was required.")
    return rows[0]


def _first_or_none(response: Any) -> dict[str, Any] | None:
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def _parse_vector(value: object) -> list[float] | None:
    """Read a pgvector column.

    PostgREST has no native vector type, so it serialises the column using its
    text form and it arrives as a JSON *string* like "[0.1,0.2]". Both shapes are
    accepted because that is an implementation detail of the server version.
    """
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, str):
        body = value.strip().removeprefix("[").removesuffix("]")
        if not body:
            return None
        return [float(part) for part in body.split(",") if part.strip()]
    return None


def _batched(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


# Re-exported so callers do not need math for the dimension sanity check.
def embedding_width_matches(configured: int) -> bool:
    return configured == CHUNK_EMBEDDING_DIMENSIONS and not math.isnan(float(configured))
