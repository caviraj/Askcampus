"""Upload validation: every way a file can be refused, and the one that must not be.

AGENTS.md section 6.9 ("validate uploads by extension, magic bytes, and size")
made executable. Two things here were established by probing the installed
Starlette rather than by assumption:

- `max_part_size` is enforced **only for non-file parts**. A 5 MB file part
  streams to a spooled temporary file and is accepted no matter what the limit is,
  while a 2 MB *text* field is refused. So the parser's limit bounds a runaway
  metadata field, and the upload's size is bounded by `_read_capped` counting the
  bytes that actually arrive.
- `Content-Length` is never consulted, which is why the test below sends a lying
  one and expects it to be ignored.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from tests.fakes import InMemoryDocumentRepository, InMemoryFileStorage
from tests.filebuilders import docx_bytes, large_pdf, simple_pdf

DOCUMENTS = "/admin/documents"
_METADATA = {"title": "Student Handbook", "category": "general"}


async def _upload(
    client: httpx.AsyncClient,
    filename: str,
    data: bytes,
    *,
    metadata: dict[str, str] | None = None,
    content_type: str = "application/octet-stream",
    **kwargs: object,
) -> httpx.Response:
    return await client.post(
        DOCUMENTS,
        files={"file": (filename, data, content_type)},
        data=metadata if metadata is not None else _METADATA,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


async def test_a_valid_pdf_is_accepted(authorized: httpx.AsyncClient) -> None:
    response = await _upload(authorized, "handbook.pdf", simple_pdf("Fees are payable in June."))
    assert response.status_code == 202


async def test_a_valid_docx_is_accepted(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized,
        "handbook.docx",
        docx_bytes(paragraphs=[("Fees are payable in June.", None)]),
    )
    assert response.status_code == 202


async def test_a_valid_txt_is_accepted(authorized: httpx.AsyncClient) -> None:
    response = await _upload(authorized, "notes.txt", b"Fees are payable in June.")
    assert response.status_code == 202


async def test_a_utf16_text_file_is_accepted(authorized: httpx.AsyncClient) -> None:
    """A Notepad-saved .txt is UTF-16 with a BOM. Its bytes are mostly NULs, so a
    naive binary check would refuse a file WordPad just wrote."""
    response = await _upload(authorized, "notes.txt", "Fees are payable in June.".encode("utf-16"))
    assert response.status_code == 202


async def test_the_extension_check_is_case_insensitive(authorized: httpx.AsyncClient) -> None:
    """A file named HANDBOOK.PDF is a PDF, and refusing it would be a support
    ticket rather than a security win."""
    response = await _upload(authorized, "HANDBOOK.PDF", simple_pdf("Fees."))
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["payload.exe", "notes.md", "sheet.xlsx", "noextension"])
async def test_a_disallowed_extension_is_rejected(
    authorized: httpx.AsyncClient, filename: str
) -> None:
    response = await _upload(authorized, filename, simple_pdf("Fees."))
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"


async def test_the_rejection_names_what_is_allowed(authorized: httpx.AsyncClient) -> None:
    """AGENTS.md section 8: an error explains what happened and the next action."""
    response = await _upload(authorized, "notes.md", b"Fees.")
    assert ".pdf" in response.json()["detail"]
    assert ".docx" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Magic bytes
# ---------------------------------------------------------------------------


async def test_text_renamed_as_a_pdf_is_rejected(authorized: httpx.AsyncClient) -> None:
    """The check the extension cannot pass on its own."""
    response = await _upload(authorized, "handbook.pdf", b"Fees are payable in June.")
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"


async def test_a_pdf_with_leading_bytes_before_the_header_is_accepted(
    authorized: httpx.AsyncClient,
) -> None:
    """The PDF specification permits leading bytes, so requiring the signature at
    offset 0 would reject files some generators legitimately emit."""
    response = await _upload(
        authorized, "handbook.pdf", b"%junk\n" + simple_pdf("Fees are payable in June.")
    )
    assert response.status_code == 202


async def test_a_zip_that_is_not_a_word_document_is_rejected(
    authorized: httpx.AsyncClient,
) -> None:
    """PK\\x03\\x04 alone proves nothing: an .xlsx and a .pptx pass it too."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")

    response = await _upload(authorized, "handbook.docx", buffer.getvalue())
    assert response.status_code == 415


async def test_text_containing_nul_bytes_is_rejected(authorized: httpx.AsyncClient) -> None:
    """A JPEG renamed to .txt has no magic number to catch it, so the honest check
    is that the bytes are plausibly text at all."""
    response = await _upload(authorized, "notes.txt", b"Fees\x00\x01\x02 payable")
    assert response.status_code == 415


async def test_an_empty_file_is_rejected(authorized: httpx.AsyncClient) -> None:
    response = await _upload(authorized, "handbook.pdf", b"")
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


async def test_a_missing_file_part_is_rejected(authorized: httpx.AsyncClient) -> None:
    response = await authorized.post(DOCUMENTS, data=_METADATA)
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------


async def test_a_large_upload_is_accepted(authorized: httpx.AsyncClient) -> None:
    """A real two-megabyte college handbook. This is the size a multipart default
    would have threatened, and it is asserted directly rather than inferred from
    the parser's configuration."""
    data = large_pdf()
    assert len(data) > 2 * 1024 * 1024

    response = await _upload(authorized, "handbook.pdf", data)
    assert response.status_code == 202, response.text


async def test_the_recorded_size_is_the_bytes_that_arrived(
    authorized: httpx.AsyncClient,
) -> None:
    data = large_pdf()
    response = await _upload(authorized, "handbook.pdf", data)
    assert response.json()["file_size_bytes"] == len(data)


async def test_a_lying_content_length_is_ignored(authorized: httpx.AsyncClient) -> None:
    """The cap is enforced by counting, never by trusting a header the caller
    controls."""
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees are payable in June."),
        headers={"Content-Length": "1"},
    )
    assert response.status_code == 202


async def test_a_file_over_the_configured_cap_is_413(
    app: FastAPI, admin_headers: dict[str, str], settings: Settings
) -> None:
    """Tested with a 1 MB cap rather than by building a 20 MB file: same code path,
    and the suite stays fast."""
    app.state.settings = settings.model_copy(update={"max_upload_mb": 1})
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            response = await client.post(
                DOCUMENTS,
                files={"file": ("big.pdf", large_pdf(), "application/pdf")},
                data=_METADATA,
            )
    finally:
        app.state.settings = settings

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
    assert "1 MB" in response.json()["detail"]


async def test_an_enormous_metadata_field_is_stopped_by_the_parser(
    app: FastAPI, admin_headers: dict[str, str], settings: Settings
) -> None:
    """`max_part_size` is a parser limit on *non-file* parts, and this is the case
    it exists for: a three-megabyte title field is refused before the route body
    reads it. The message names the limit this app configured, because the limit
    is derived from settings rather than left at Starlette's 1 MB default."""
    app.state.settings = settings.model_copy(update={"max_upload_mb": 1})
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            response = await _upload(
                client,
                "handbook.pdf",
                simple_pdf("Fees."),
                metadata={**_METADATA, "title": "x" * (3 * 1024 * 1024)},
            )
    finally:
        app.state.settings = settings

    assert response.status_code == 400
    assert "2048KB" in response.json()["detail"]


async def test_an_over_long_title_within_the_part_limit_is_a_422(
    authorized: httpx.AsyncClient,
) -> None:
    """The parser's limit is a crude outer bound; the real rule is Pydantic's 300
    characters, and a field that passes the parser still has to pass that."""
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={**_METADATA, "title": "x" * 400_000},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


async def test_uploading_the_same_bytes_twice_is_a_409(authorized: httpx.AsyncClient) -> None:
    payload = simple_pdf("Fees are payable in June.")
    first = await _upload(authorized, "handbook.pdf", payload)
    assert first.status_code == 202

    second = await _upload(authorized, "handbook-again.pdf", payload)
    assert second.status_code == 409
    assert second.json()["code"] == "duplicate_document"


async def test_the_duplicate_response_names_the_existing_document(
    authorized: httpx.AsyncClient,
) -> None:
    """A header rather than a field in the body: ErrorResponse is one shape for the
    whole API, and widening it for one route would mean every client learns a
    special case."""
    payload = simple_pdf("Fees are payable in June.")
    first = await _upload(authorized, "handbook.pdf", payload)
    second = await _upload(authorized, "handbook.pdf", payload)

    assert second.headers["X-Existing-Document-Id"] == first.json()["id"]


async def test_different_bytes_with_the_same_name_are_not_duplicates(
    authorized: httpx.AsyncClient,
) -> None:
    """The hash is over the content, not the filename, so a corrected handbook
    uploaded under the same name is a new document rather than a false conflict."""
    first = await _upload(authorized, "handbook.pdf", simple_pdf("Fees are 500."))
    second = await _upload(authorized, "handbook.pdf", simple_pdf("Fees are 600."))
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


async def test_a_missing_title_is_a_422(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized, "handbook.pdf", simple_pdf("Fees."), metadata={"category": "general"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_a_blank_title_is_a_422(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={"title": "   ", "category": "general"},
    )
    assert response.status_code == 422


async def test_an_unknown_category_is_a_422(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={"title": "Handbook", "category": "not-a-category"},
    )
    assert response.status_code == 422


async def test_an_over_long_title_is_a_422(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={"title": "x" * 301, "category": "general"},
    )
    assert response.status_code == 422


async def test_an_absent_optional_field_is_stored_as_null(
    authorized: httpx.AsyncClient,
) -> None:
    """Browsers submit every field in a multipart form, including untouched ones,
    so a blank academic_year must not be stored as an empty string."""
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={
            "title": "Handbook",
            "category": "general",
            "academic_year": "",
            "department": "",
        },
    )
    assert response.status_code == 202
    assert response.json()["academic_year"] is None
    assert response.json()["department"] is None


async def test_the_title_is_stripped(authorized: httpx.AsyncClient) -> None:
    response = await _upload(
        authorized,
        "handbook.pdf",
        simple_pdf("Fees."),
        metadata={"title": "  Student Handbook  ", "category": "general"},
    )
    assert response.json()["title"] == "Student Handbook"


# ---------------------------------------------------------------------------
# Storage side effects
# ---------------------------------------------------------------------------


async def test_the_file_is_stored_under_a_random_name(
    authorized: httpx.AsyncClient, file_storage: InMemoryFileStorage
) -> None:
    """AGENTS.md section 6.9. The original name is kept in the row, where it cannot
    collide and cannot escape a directory."""
    response = await _upload(
        authorized, "../../etc/handbook.pdf", simple_pdf("Fees are payable in June.")
    )
    assert response.status_code == 202

    (path,) = file_storage.objects
    assert path.endswith(".pdf")
    assert "handbook" not in path
    assert ".." not in path
    assert response.json()["original_filename"] == "../../etc/handbook.pdf"


async def test_the_content_type_is_passed_to_storage(
    authorized: httpx.AsyncClient, file_storage: InMemoryFileStorage
) -> None:
    """The storage client defaults to text/plain, so omitting it stores a PDF as
    plain text and nothing about the result looks wrong."""
    await _upload(authorized, "handbook.pdf", simple_pdf("Fees."))
    assert set(file_storage.content_types.values()) == {"application/pdf"}


async def test_a_failed_insert_leaves_no_orphaned_object(
    authorized: httpx.AsyncClient,
    document_repository: InMemoryDocumentRepository,
    file_storage: InMemoryFileStorage,
) -> None:
    """The row is what makes an object reachable, so an object with no row would
    accumulate in the bucket forever, invisible."""
    document_repository.fail_on = {"insert"}

    with pytest.raises(RuntimeError):
        await _upload(authorized, "handbook.pdf", simple_pdf("Fees are payable in June."))

    assert file_storage.objects == {}
    assert file_storage.deleted
