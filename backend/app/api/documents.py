"""Admin document routes: upload, list, read, update, reprocess, replace, delete.

require_admin is attached at the router level, so a route added here is protected
by construction. test_admin_route_protection.py asserts that holds for every
/admin path.

Two things in this module look more complicated than they need to be and are not:

**The upload route parses the body itself.** FastAPI's `File()`/`Form()` path calls
`request.form()` with no arguments, so Starlette's defaults apply: `max_part_size`
of 1 MB, `max_files` and `max_fields` of 1000. Parsing explicitly lets all three
come from settings instead. Measured against the installed Starlette 1.7.0,
`max_part_size` is enforced **only for non-file parts** -- file parts stream
straight to a spooled temporary file -- so it bounds a runaway metadata field, not
the upload. The authoritative size check is `_read_capped`, which counts the bytes
that actually arrive; `Content-Length` is attacker-controlled and never consulted.

**Every dependency provider is a plain `def`.** A `yield`-based provider runs its
cleanup on FastAPI's exit stack, which closes *after* the response but can be
before a background task finishes with the object. Nothing here is a resource
that needs closing per request, so there is nothing to tear down.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import ValidationError
from starlette.datastructures import FormData, UploadFile

from app.api.auth_deps import require_admin
from app.api.errors import ApiError
from app.config import Settings
from app.schemas.documents import (
    Category,
    DocumentListResponse,
    DocumentRead,
    DocumentStatus,
    DocumentUpdate,
    DocumentUploadMetadata,
)
from app.services.documents import DocumentRepository, SupabaseDocumentRepository
from app.services.embedding import EmbeddingService, SupabaseEmbeddingCache
from app.services.filetypes import (
    UnsupportedFileError,
    content_type_for,
    normalise_extension,
    validate_file_bytes,
)
from app.services.hashing import sha256_hex
from app.services.ingestion import IngestionService
from app.services.storage import FileStorage, SupabaseFileStorage, build_object_path

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/documents",
    tags=["documents"],
    dependencies=[Depends(require_admin)],
)

# Read the upload in 1 MB steps so the size cap is enforced by counting rather
# than by trusting a header. Content-Length is attacker-controlled and is never
# consulted.
_READ_CHUNK_BYTES = 1024 * 1024

# Headroom over the configured file cap, so the parser's own limit for a metadata
# field is never tighter than the limit the route actually enforces. Without the
# headroom a large `title` field would be refused by the parser with a message
# naming a smaller number than the one this app advertises.
_MULTIPART_OVERHEAD = 1024 * 1024


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_document_repository() -> DocumentRepository:
    """Overridden in tests with an in-memory implementation."""
    return SupabaseDocumentRepository()


def get_file_storage(request: Request) -> FileStorage:
    settings: Settings = request.app.state.settings
    return SupabaseFileStorage(settings.storage_bucket)


def get_embedding_service(request: Request) -> EmbeddingService:
    settings: Settings = request.app.state.settings
    return EmbeddingService(
        # Built once at app creation: constructing a genai client per request
        # would rebuild an HTTP connection pool on every upload.
        provider=request.app.state.embedding_provider,
        settings=settings,
        cache=SupabaseEmbeddingCache(),
    )


def get_ingestion_service(
    request: Request,
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
    embeddings: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> IngestionService:
    settings: Settings = request.app.state.settings
    return IngestionService(repository, storage, embeddings, settings)


RepositoryDep = Annotated[DocumentRepository, Depends(get_document_repository)]
StorageDep = Annotated[FileStorage, Depends(get_file_storage)]
IngestionDep = Annotated[IngestionService, Depends(get_ingestion_service)]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=DocumentRead, status_code=202, summary="Upload a document")
async def upload_document(
    request: Request,
    background: BackgroundTasks,
    repository: RepositoryDep,
    storage: StorageDep,
    ingestion: IngestionDep,
) -> DocumentRead:
    """Store an uploaded document and start processing it.

    202 rather than 201: the row exists but the work has not happened yet, and the
    status the caller must poll is in the response body.
    """
    settings: Settings = request.app.state.settings
    form = await request.form(
        max_part_size=settings.max_upload_bytes + _MULTIPART_OVERHEAD,
        max_files=1,
        max_fields=10,
    )

    filename, data, file_type = await _read_upload(form, settings)
    metadata = _metadata_from_form(form)

    digest = sha256_hex(data)
    existing = await repository.find_by_hash(digest)
    if existing is not None:
        raise _duplicate_error(existing)

    path = await _store(storage, data, file_type)
    try:
        row = await repository.insert(
            {
                "title": metadata.title,
                "category": metadata.category,
                "academic_year": metadata.academic_year,
                "department": metadata.department,
                "file_path": path,
                "file_type": file_type,
                "original_filename": filename,
                "file_size_bytes": len(data),
                "content_hash": digest,
                "status": "uploaded",
                "is_active": True,
            }
        )
    except Exception:
        # Compensating delete. The row is what makes an object reachable, so an
        # object with no row is unreachable from the API and would accumulate
        # silently in the bucket forever.
        await _discard(storage, path)
        raise

    # The bytes are already in hand, so processing does not re-download them from
    # Storage. See IngestionService.process for why that is safe.
    background.add_task(ingestion.process, _as_uuid(row["id"]), data=data)
    return DocumentRead.model_validate(row)


@router.get("", response_model=DocumentListResponse, summary="List documents")
async def list_documents(
    request: Request,
    repository: RepositoryDep,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[DocumentStatus | None, Query()] = None,
    category: Annotated[Category | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> DocumentListResponse:
    settings: Settings = request.app.state.settings
    effective_limit = min(
        limit or settings.document_list_default_limit, settings.document_list_max_limit
    )

    items, total = await repository.list_documents(
        limit=effective_limit,
        offset=offset,
        status=status,
        category=category,
        is_active=is_active,
    )
    return DocumentListResponse(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=effective_limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentRead, summary="Read one document")
async def read_document(document_id: UUID, repository: RepositoryDep) -> DocumentRead:
    """The endpoint the admin UI polls while a document processes."""
    return DocumentRead.model_validate(await _require_document(repository, document_id))


@router.patch("/{document_id}", response_model=DocumentRead, summary="Update a document")
async def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    repository: RepositoryDep,
) -> DocumentRead:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise ApiError(400, "Send at least one field to update.", "bad_request")

    row = await repository.update(document_id, patch)
    if row is None:
        raise _not_found()
    return DocumentRead.model_validate(row)


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentRead,
    status_code=202,
    summary="Re-extract and re-embed a document",
)
async def reprocess_document(
    document_id: UUID,
    background: BackgroundTasks,
    repository: RepositoryDep,
    ingestion: IngestionDep,
) -> DocumentRead:
    """Run the pipeline again against the stored file.

    The status check here is a courtesy, not the guard: `process` claims the
    document with a conditional update, so a request that slips through this check
    is a no-op rather than a second concurrent run. It exists so a double-click
    gets a clear 409 instead of a silent success.
    """
    document = await _require_document(repository, document_id)
    if document["status"] == "processing":
        raise ApiError(409, "This document is already being processed.", "conflict")

    background.add_task(ingestion.process, document_id)
    return DocumentRead.model_validate(document)


@router.post(
    "/{document_id}/replace",
    response_model=DocumentRead,
    status_code=202,
    summary="Replace a document's file",
)
async def replace_document(
    document_id: UUID,
    request: Request,
    background: BackgroundTasks,
    repository: RepositoryDep,
    storage: StorageDep,
    ingestion: IngestionDep,
) -> DocumentRead:
    """Swap the file behind an existing document, keeping its id.

    Separate from delete-and-re-upload because keeping the id is the point: query
    history and existing citations name this document, and FR-9 promises that
    history survives.
    """
    settings: Settings = request.app.state.settings
    document = await _require_document(repository, document_id)
    if document["status"] == "processing":
        raise ApiError(409, "This document is already being processed.", "conflict")

    reference = await repository.get_file_reference(document_id)
    if reference is None:
        raise _not_found()

    form = await request.form(
        max_part_size=settings.max_upload_bytes + _MULTIPART_OVERHEAD,
        max_files=1,
        max_fields=10,
    )
    filename, data, file_type = await _read_upload(form, settings)

    digest = sha256_hex(data)
    existing = await repository.find_by_hash(digest)
    if existing is not None and _as_uuid(existing["id"]) != document_id:
        raise _duplicate_error(existing)

    patch: dict[str, Any] = {
        "file_path": await _store(storage, data, file_type),
        "file_type": file_type,
        "original_filename": filename,
        "file_size_bytes": len(data),
        "content_hash": digest,
    }
    # Metadata sent with the replacement wins; the old title is kept otherwise, so
    # this can be used to swap the file alone.
    title = _form_text(form, "title")
    if title:
        patch["title"] = title

    try:
        row = await repository.update(document_id, patch)
    except Exception:
        await _discard(storage, str(patch["file_path"]))
        raise
    if row is None:
        await _discard(storage, str(patch["file_path"]))
        raise _not_found()

    # Only after the row points at the new object. The reverse order would leave
    # the row naming a file that no longer exists if the update failed.
    old_path = reference.get("file_path")
    if old_path and str(old_path) != patch["file_path"]:
        await _discard(storage, str(old_path))

    background.add_task(ingestion.process, document_id)
    return DocumentRead.model_validate(row)


@router.delete("/{document_id}", status_code=204, summary="Delete a document")
async def delete_document(
    document_id: UUID,
    repository: RepositoryDep,
    storage: StorageDep,
) -> Response:
    """Remove the document, its chunks (by cascade) and its stored file."""
    reference = await repository.get_file_reference(document_id)
    if reference is None:
        raise _not_found()

    # The row first. If the object delete then fails, the result is an orphaned
    # object in the bucket -- recoverable and invisible. The reverse order could
    # leave a row pointing at a missing file, which breaks reprocess and replace
    # for a document the admin still sees in the list.
    await repository.delete(document_id)
    path = reference.get("file_path")
    if path:
        await _discard(storage, str(path))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_document(repository: DocumentRepository, document_id: UUID) -> dict[str, Any]:
    document = await repository.get(document_id)
    if document is None:
        raise _not_found()
    return document


async def _read_upload(form: FormData, settings: Settings) -> tuple[str, bytes, str]:
    """Validate the `file` part, returning (filename, bytes, file type).

    The four checks that guard the pipeline: the part is present, the extension is
    allowed, the size is within the cap *by counting*, and the bytes really are
    the type the extension claims.
    """
    part = form.get("file")
    if not isinstance(part, UploadFile):
        raise ApiError(400, "Attach a file to upload.", "bad_request")

    filename = part.filename or ""
    file_type = normalise_extension(filename)
    if file_type not in settings.allowed_upload_extensions:
        allowed = ", ".join(f".{item}" for item in settings.allowed_upload_extensions)
        raise ApiError(
            415,
            f"{filename or 'That file'} is not a supported type. Upload {allowed}.",
            "unsupported_media_type",
        )

    data = await _read_capped(part, settings.max_upload_bytes)
    if not data:
        raise ApiError(400, "That file is empty.", "bad_request")

    try:
        validate_file_bytes(
            data,
            file_type,
            max_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
        )
    except UnsupportedFileError as exc:
        raise ApiError(415, str(exc), "unsupported_media_type") from exc

    return filename, data, file_type


async def _read_capped(part: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, refusing anything larger.

    Read in steps rather than via `part.read()` so a file of unbounded size cannot
    be pulled into memory before the cap is applied.
    """
    collected: list[bytes] = []
    total = 0
    while chunk := await part.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise ApiError(
                413,
                f"That file is larger than {limit // (1024 * 1024)} MB. "
                "Split it or upload a smaller version.",
                "payload_too_large",
            )
        collected.append(chunk)
    return b"".join(collected)


def _metadata_from_form(form: FormData) -> DocumentUploadMetadata:
    """Build and validate the metadata fields by hand.

    FastAPI cannot validate them because the route parses the form itself, so the
    ValidationError is caught here and turned into the shared error shape. The raw
    pydantic errors are not sent to the client -- validation_error_handler takes
    the same line for the routes FastAPI does validate.
    """
    try:
        return DocumentUploadMetadata(
            title=_form_text(form, "title") or "",
            category=_form_text(form, "category") or "",
            academic_year=_form_text(form, "academic_year"),
            department=_form_text(form, "department"),
        )
    except ValidationError as exc:
        raise ApiError(
            422,
            "Check the document details: a title and a valid category are required.",
            "validation_error",
        ) from exc


def _form_text(form: FormData, name: str) -> str | None:
    """A text field's value, or None if absent.

    Guards against a part submitted as a file: `form.get` would then return an
    UploadFile, and str() on it would produce a repr that looks like a title.
    """
    value = form.get(name)
    return value if isinstance(value, str) else None


async def _store(storage: FileStorage, data: bytes, file_type: str) -> str:
    """Write the file under a random name and return the key."""
    path = build_object_path(file_type)
    await storage.put(path, data, content_type_for(file_type))
    return path


async def _discard(storage: FileStorage, path: str) -> None:
    """Best-effort delete of a stored object.

    Never raises. Every caller is either already failing or has already succeeded,
    and neither should be turned into a 500 because a cleanup call did not land.
    """
    try:
        await storage.delete(path)
    except Exception:  # noqa: BLE001 - cleanup must not mask the real outcome
        logger.warning("Could not delete the stored object %s", path, exc_info=True)


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _not_found() -> ApiError:
    return ApiError(404, "That document does not exist.", "not_found")


def _duplicate_error(existing: dict[str, Any]) -> ApiError:
    """409 with the existing id in a header.

    A header rather than a field in the body: ErrorResponse is one shape for the
    whole API (app/api/errors.py), and widening it for a single route would mean
    every client learns a special case.
    """
    return ApiError(
        409,
        "That file has already been uploaded.",
        "duplicate_document",
        headers={"X-Existing-Document-Id": str(existing["id"])},
    )
