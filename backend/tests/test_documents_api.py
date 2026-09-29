"""The admin document routes: shapes, filters, errors, and side effects.

Every route is exercised over HTTP with the real ingestion service behind it and
only the database, Storage and Gemini faked. Because Starlette awaits background
tasks within the same ASGI cycle, `httpx.ASGITransport` does not return until the
upload has finished processing -- so these tests observe the terminal state
deterministically, with no polling.
"""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from tests.fakes import InMemoryDocumentRepository, InMemoryFileStorage, fake_vector
from tests.filebuilders import scanned_pdf, simple_pdf

DOCUMENTS = "/admin/documents"
_METADATA = {"title": "Student Handbook", "category": "general"}
_PDF = simple_pdf("1. Examination Fees", "The examination fee for the semester is 500 rupees.")


def _seeded(repository: InMemoryDocumentRepository, **row: object) -> dict:
    return repository.seed(**row)


def _key(uploaded: dict) -> UUID:
    """The fake keys its dicts by UUID; a JSON response carries the id as a string."""
    return UUID(uploaded["id"])


async def _upload(client: httpx.AsyncClient, **metadata: str) -> httpx.Response:
    return await client.post(
        DOCUMENTS,
        files={"file": ("handbook.pdf", _PDF, "application/pdf")},
        data={**_METADATA, **metadata},
    )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", DOCUMENTS),
        ("POST", DOCUMENTS),
        ("GET", f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111"),
        ("PATCH", f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111"),
        ("POST", f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111/reprocess"),
        ("POST", f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111/replace"),
        ("DELETE", f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111"),
    ],
)
async def test_every_route_requires_an_admin(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """AGENTS.md section 6.8. The dependency is attached at the router level, so
    this is checking the guardrail as much as the routes."""
    response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_a_signed_in_non_admin_is_forbidden(
    client: httpx.AsyncClient, staff_headers: dict[str, str]
) -> None:
    """Authenticated but not an admin: 403, not 401 -- the distinction tells a
    client whether retrying with a different token could ever help."""
    response = await client.get(DOCUMENTS, headers=staff_headers)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_an_unknown_document_is_not_found_for_an_admin(
    authorized: httpx.AsyncClient,
) -> None:
    """The counterpart to the 401 above, so the tests cannot pass merely by
    refusing everything."""
    response = await authorized.get(f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def test_upload_returns_202(authorized: httpx.AsyncClient) -> None:
    """202 rather than 201: the row exists but the work has not happened yet."""
    response = await _upload(authorized)
    assert response.status_code == 202


async def test_the_upload_response_carries_the_whole_row(authorized: httpx.AsyncClient) -> None:
    """The client polls the status in this body, so it has to be complete enough
    to render the documents list without a second request."""
    body = (await _upload(authorized)).json()
    assert set(body) == {
        "id",
        "title",
        "category",
        "academic_year",
        "department",
        "file_type",
        "original_filename",
        "file_size_bytes",
        "status",
        "is_active",
        "error_message",
        "page_count",
        "chunk_count",
        "extracted_chars",
        "low_text_yield",
        "text_preview",
        "created_at",
        "updated_at",
    }
    assert body["title"] == "Student Handbook"
    assert body["category"] == "general"
    assert body["file_type"] == "pdf"
    assert body["is_active"] is True


async def test_processing_finishes_by_the_time_the_upload_returns(
    authorized: httpx.AsyncClient,
) -> None:
    """`BackgroundTasks` is awaited by Starlette as part of the same ASGI cycle, so
    the terminal state is observable without polling."""
    document_id = (await _upload(authorized)).json()["id"]
    document = (await authorized.get(f"{DOCUMENTS}/{document_id}")).json()
    assert document["status"] == "ready"
    assert document["chunk_count"] > 0


async def test_the_uploaded_row_carries_its_extraction_metadata(
    authorized: httpx.AsyncClient,
) -> None:
    document_id = (await _upload(authorized)).json()["id"]
    document = (await authorized.get(f"{DOCUMENTS}/{document_id}")).json()
    assert document["page_count"] == 2
    assert document["extracted_chars"] > 0
    assert "Examination Fees" in document["text_preview"]


async def test_a_document_that_cannot_be_read_is_reported_not_hidden(
    authorized: httpx.AsyncClient,
) -> None:
    """A scanned PDF with no text layer ends `failed` with a message the admin can
    act on, rather than sitting in `processing` forever."""
    response = await authorized.post(
        DOCUMENTS,
        files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")},
        data=_METADATA,
    )
    assert response.status_code == 202

    document = (await authorized.get(f"{DOCUMENTS}/{response.json()['id']}")).json()
    assert document["status"] == "failed"
    assert document["error_message"]


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def test_the_list_is_empty_to_begin_with(authorized: httpx.AsyncClient) -> None:
    body = (await authorized.get(DOCUMENTS)).json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_the_list_reports_the_unpaged_total(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """PostgREST silently caps an unpaged select at 1000 rows, so the list is
    always paged and `total` is what lets the UI say "showing 2 of 5"."""
    for index in range(5):
        _seeded(document_repository, title=f"Document {index}")

    body = (await authorized.get(DOCUMENTS, params={"limit": 2})).json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["limit"] == 2


async def test_the_offset_walks_the_result_set(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    for index in range(5):
        _seeded(document_repository, title=f"Document {index}")

    first = (await authorized.get(DOCUMENTS, params={"limit": 2, "offset": 0})).json()
    second = (await authorized.get(DOCUMENTS, params={"limit": 2, "offset": 2})).json()
    ids = {item["id"] for item in first["items"]}
    assert ids.isdisjoint({item["id"] for item in second["items"]})
    assert second["offset"] == 2


async def test_the_limit_is_clamped_to_the_configured_maximum(
    authorized: httpx.AsyncClient,
) -> None:
    """A caller asking for a million rows gets the configured ceiling rather than
    a database doing a million rows of work."""
    body = (await authorized.get(DOCUMENTS, params={"limit": 500})).json()
    assert body["limit"] == 100


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"offset": -1}])
async def test_an_invalid_page_is_a_422(
    authorized: httpx.AsyncClient, params: dict[str, int]
) -> None:
    response = await authorized.get(DOCUMENTS, params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_documents_can_be_filtered_by_status(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    _seeded(document_repository, status="ready")
    _seeded(document_repository, status="failed")

    body = (await authorized.get(DOCUMENTS, params={"status": "failed"})).json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


async def test_documents_can_be_filtered_by_category(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    _seeded(document_repository, category="admissions")
    _seeded(document_repository, category="general")

    body = (await authorized.get(DOCUMENTS, params={"category": "admissions"})).json()
    assert body["total"] == 1


async def test_documents_can_be_filtered_by_active(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    _seeded(document_repository, is_active=True)
    _seeded(document_repository, is_active=False)

    body = (await authorized.get(DOCUMENTS, params={"is_active": "false"})).json()
    assert body["total"] == 1
    assert body["items"][0]["is_active"] is False


async def test_an_unknown_status_filter_is_a_422(authorized: httpx.AsyncClient) -> None:
    response = await authorized.get(DOCUMENTS, params={"status": "archived"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def test_a_document_can_be_read_by_id(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository, title="Hostel Rules")
    response = await authorized.get(f"{DOCUMENTS}/{seeded['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "Hostel Rules"


async def test_a_malformed_id_is_a_422(authorized: httpx.AsyncClient) -> None:
    """FastAPI validates the path parameter, so a typo gets a clear error rather
    than a 500 from the database."""
    response = await authorized.get(f"{DOCUMENTS}/not-a-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def test_a_document_can_be_updated(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository)
    response = await authorized.patch(
        f"{DOCUMENTS}/{seeded['id']}",
        json={"title": "Hostel Rules", "category": "admissions", "academic_year": "2026-27"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Hostel Rules"
    assert response.json()["category"] == "admissions"
    assert response.json()["academic_year"] == "2026-27"


async def test_an_omitted_field_is_left_alone(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """`exclude_unset` is what makes this a partial update: omitting department must
    not clear the value that is already there."""
    seeded = _seeded(document_repository, department="Examinations")
    response = await authorized.patch(f"{DOCUMENTS}/{seeded['id']}", json={"title": "Hostel Rules"})
    assert response.json()["department"] == "Examinations"


async def test_an_explicit_null_clears_a_field(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository, department="Examinations")
    response = await authorized.patch(f"{DOCUMENTS}/{seeded['id']}", json={"department": None})
    assert response.json()["department"] is None


async def test_a_document_can_be_deactivated(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """AGENTS.md section 6.12: only active, ready documents are searchable, so
    this is the switch that takes a wrong document out of retrieval without
    deleting the query history that cites it."""
    seeded = _seeded(document_repository, status="ready")
    response = await authorized.patch(f"{DOCUMENTS}/{seeded['id']}", json={"is_active": False})
    assert response.json()["is_active"] is False


async def test_an_empty_update_body_is_a_400(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository)
    response = await authorized.patch(f"{DOCUMENTS}/{seeded['id']}", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


async def test_an_invalid_update_is_a_422(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository)
    response = await authorized.patch(
        f"{DOCUMENTS}/{seeded['id']}", json={"category": "not-a-category"}
    )
    assert response.status_code == 422


async def test_updating_an_unknown_document_is_a_404(authorized: httpx.AsyncClient) -> None:
    response = await authorized.patch(
        f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111", json={"title": "Hostel Rules"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Reprocess
# ---------------------------------------------------------------------------


async def test_reprocess_returns_202(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository, status="ready")
    response = await authorized.post(f"{DOCUMENTS}/{seeded['id']}/reprocess")
    assert response.status_code == 202


async def test_reprocess_rebuilds_the_chunks(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    uploaded = (await _upload(authorized)).json()
    document_repository.chunks[_key(uploaded)] = [{"chunk_index": 0, "content": "Stale."}]

    await authorized.post(f"{DOCUMENTS}/{uploaded['id']}/reprocess")

    assert all(row["content"] != "Stale." for row in document_repository.chunks[_key(uploaded)])


async def test_reprocess_reads_the_file_back_from_storage(
    authorized: httpx.AsyncClient,
    document_repository: InMemoryDocumentRepository,
    file_storage: InMemoryFileStorage,
) -> None:
    """The upload path hands over the bytes it already holds; reprocess has none to
    hand over, so it re-reads Storage. Removing the object is what makes that
    observable -- nothing in the request carries the file, so a run that still
    produced chunks would have to have kept them somewhere it should not."""
    uploaded = (await _upload(authorized)).json()
    path = document_repository.rows[_key(uploaded)]["file_path"]
    file_storage.objects.pop(path)

    await authorized.post(f"{DOCUMENTS}/{uploaded['id']}/reprocess")

    document = (await authorized.get(f"{DOCUMENTS}/{uploaded['id']}")).json()
    assert document["status"] == "failed"
    assert document["error_message"].startswith("The stored file could not be read:")


async def test_reprocessing_a_document_rebuilds_it_from_the_stored_copy(
    authorized: httpx.AsyncClient,
    document_repository: InMemoryDocumentRepository,
) -> None:
    uploaded = (await _upload(authorized)).json()
    before = document_repository.rows[_key(uploaded)]["chunk_count"]

    response = await authorized.post(f"{DOCUMENTS}/{uploaded['id']}/reprocess")
    assert response.status_code == 202

    document = (await authorized.get(f"{DOCUMENTS}/{uploaded['id']}")).json()
    assert document["status"] == "ready"
    assert document["chunk_count"] == before


async def test_reprocessing_a_busy_document_is_a_409(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """A courtesy check so a double-click gets a clear answer. It is not the guard:
    `process` claims the document with a conditional update, so a request that
    slips past this is a no-op rather than a second concurrent run."""
    seeded = _seeded(document_repository, status="processing")
    response = await authorized.post(f"{DOCUMENTS}/{seeded['id']}/reprocess")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_reprocessing_an_unknown_document_is_a_404(
    authorized: httpx.AsyncClient,
) -> None:
    response = await authorized.post(f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111/reprocess")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Replace
# ---------------------------------------------------------------------------


async def test_replace_keeps_the_document_id(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """The whole reason replace is separate from delete-and-re-upload: query history
    and existing citations name this document, and FR-9 promises that history
    survives."""
    uploaded = (await _upload(authorized)).json()
    replacement = simple_pdf("1. Hostel Fees", "Hostel fees are payable in June.")

    response = await authorized.post(
        f"{DOCUMENTS}/{uploaded['id']}/replace",
        files={"file": ("hostel.pdf", replacement, "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["id"] == uploaded["id"]


async def test_replace_rebuilds_the_chunks_from_the_new_file(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    uploaded = (await _upload(authorized)).json()
    replacement = simple_pdf("1. Hostel Fees", "Hostel fees are payable in June.")

    await authorized.post(
        f"{DOCUMENTS}/{uploaded['id']}/replace",
        files={"file": ("hostel.pdf", replacement, "application/pdf")},
    )

    contents = " ".join(row["content"] for row in document_repository.chunks[_key(uploaded)])
    assert "Hostel fees" in contents
    assert "Examination Fees" not in contents


async def test_replace_removes_the_old_stored_object(
    authorized: httpx.AsyncClient, file_storage: InMemoryFileStorage
) -> None:
    """Otherwise every replacement leaves a copy of the previous handbook in the
    bucket, unreachable from the API."""
    uploaded = (await _upload(authorized)).json()
    original_path = next(iter(file_storage.objects))

    await authorized.post(
        f"{DOCUMENTS}/{uploaded['id']}/replace",
        files={"file": ("hostel.pdf", simple_pdf("Hostel fees."), "application/pdf")},
    )

    assert original_path in file_storage.deleted
    assert original_path not in file_storage.objects
    assert len(file_storage.objects) == 1


async def test_replace_updates_the_file_metadata(
    authorized: httpx.AsyncClient,
) -> None:
    uploaded = (await _upload(authorized)).json()
    replacement = simple_pdf("Hostel fees are payable in June.")

    body = (
        await authorized.post(
            f"{DOCUMENTS}/{uploaded['id']}/replace",
            files={"file": ("hostel-rules.pdf", replacement, "application/pdf")},
        )
    ).json()

    assert body["original_filename"] == "hostel-rules.pdf"
    assert body["file_type"] == "pdf"
    assert body["file_size_bytes"] == len(replacement)


async def test_replace_keeps_the_title_when_none_is_sent(
    authorized: httpx.AsyncClient,
) -> None:
    """So the endpoint can be used to swap the file alone."""
    uploaded = (await _upload(authorized)).json()
    body = (
        await authorized.post(
            f"{DOCUMENTS}/{uploaded['id']}/replace",
            files={"file": ("hostel.pdf", simple_pdf("Hostel fees."), "application/pdf")},
        )
    ).json()
    assert body["title"] == "Student Handbook"


async def test_replace_can_change_the_title(
    authorized: httpx.AsyncClient,
) -> None:
    uploaded = (await _upload(authorized)).json()
    body = (
        await authorized.post(
            f"{DOCUMENTS}/{uploaded['id']}/replace",
            files={"file": ("hostel.pdf", simple_pdf("Hostel fees."), "application/pdf")},
            data={"title": "Hostel Rules"},
        )
    ).json()
    assert body["title"] == "Hostel Rules"


async def test_replacing_with_a_file_already_uploaded_is_a_409(
    authorized: httpx.AsyncClient,
) -> None:
    """Otherwise two documents would share one content hash and the duplicate check
    would start refusing the original."""
    first = (await _upload(authorized)).json()
    second = (
        await authorized.post(
            DOCUMENTS,
            files={"file": ("hostel.pdf", simple_pdf("Hostel fees."), "application/pdf")},
            data=_METADATA,
        )
    ).json()

    # Re-uploading the first document's own bytes under the second id.
    response = await authorized.post(
        f"{DOCUMENTS}/{second['id']}/replace",
        files={"file": ("handbook.pdf", _PDF, "application/pdf")},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "duplicate_document"
    assert response.headers["X-Existing-Document-Id"] == first["id"]


async def test_replacing_with_a_documents_own_file_is_allowed(
    authorized: httpx.AsyncClient,
) -> None:
    """The duplicate check excludes the document being replaced, or a no-op replace
    would conflict with itself."""
    uploaded = (await _upload(authorized)).json()
    response = await authorized.post(
        f"{DOCUMENTS}/{uploaded['id']}/replace",
        files={"file": ("handbook.pdf", _PDF, "application/pdf")},
    )
    assert response.status_code == 202


async def test_replacing_a_busy_document_is_a_409(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    seeded = _seeded(document_repository, status="processing")
    response = await authorized.post(
        f"{DOCUMENTS}/{seeded['id']}/replace",
        files={"file": ("hostel.pdf", simple_pdf("Hostel fees."), "application/pdf")},
    )
    assert response.status_code == 409


async def test_a_rejected_replacement_leaves_no_new_object(
    authorized: httpx.AsyncClient, file_storage: InMemoryFileStorage
) -> None:
    """The file is validated before anything is stored, so a rejected replace adds
    nothing to the bucket."""
    uploaded = (await _upload(authorized)).json()
    before = set(file_storage.objects)

    response = await authorized.post(
        f"{DOCUMENTS}/{uploaded['id']}/replace",
        files={"file": ("hostel.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert set(file_storage.objects) == before


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_returns_204(authorized: httpx.AsyncClient) -> None:
    uploaded = (await _upload(authorized)).json()
    response = await authorized.delete(f"{DOCUMENTS}/{uploaded['id']}")
    assert response.status_code == 204
    assert response.content == b""


async def test_delete_removes_the_row(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    uploaded = (await _upload(authorized)).json()
    await authorized.delete(f"{DOCUMENTS}/{uploaded['id']}")

    assert (await authorized.get(f"{DOCUMENTS}/{uploaded['id']}")).status_code == 404
    assert (await authorized.get(DOCUMENTS)).json()["total"] == 0


async def test_delete_removes_the_stored_file(
    authorized: httpx.AsyncClient, file_storage: InMemoryFileStorage
) -> None:
    uploaded = (await _upload(authorized)).json()
    await authorized.delete(f"{DOCUMENTS}/{uploaded['id']}")
    assert file_storage.objects == {}


async def test_delete_removes_the_chunks(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """In Postgres this is the cascade on chunks.document_id; the fake reproduces
    it so the assertion means something."""
    uploaded = (await _upload(authorized)).json()
    assert document_repository.chunks[_key(uploaded)]

    await authorized.delete(f"{DOCUMENTS}/{uploaded['id']}")
    assert document_repository.chunks.get(_key(uploaded)) in (None, [])


async def test_deleting_an_unknown_document_is_a_404(authorized: httpx.AsyncClient) -> None:
    response = await authorized.delete(f"{DOCUMENTS}/11111111-1111-1111-1111-111111111111")
    assert response.status_code == 404


async def test_delete_does_not_remove_a_file_that_still_has_a_row(
    authorized: httpx.AsyncClient,
    document_repository: InMemoryDocumentRepository,
    file_storage: InMemoryFileStorage,
) -> None:
    """If the row delete fails the object must stay, or the admin is left with a
    document in the list whose file cannot be read."""
    uploaded = (await _upload(authorized)).json()
    document_repository.fail_on = {"delete"}

    with pytest.raises(RuntimeError):
        await authorized.delete(f"{DOCUMENTS}/{uploaded['id']}")

    assert file_storage.objects
    assert uploaded["id"] in {str(key) for key in document_repository.rows}


# ---------------------------------------------------------------------------
# Chunk integrity
# ---------------------------------------------------------------------------


async def test_stored_embeddings_have_the_column_width(
    authorized: httpx.AsyncClient, document_repository: InMemoryDocumentRepository
) -> None:
    """A width mismatch fails at insert time with a pgvector cast error that never
    mentions dimensions, so it is asserted here where the reason is legible."""
    uploaded = (await _upload(authorized)).json()
    for row in document_repository.chunks[_key(uploaded)]:
        assert len(row["embedding"]) == 768
        assert row["embedding"] == fake_vector(row["content"])
