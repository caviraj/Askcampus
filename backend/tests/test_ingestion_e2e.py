"""End-to-end ingestion against the real Supabase project and the real Gemini API.

Gated on RUN_LIVE_TESTS=1, because it needs a Supabase project, a Storage bucket,
the migrations applied and a working Gemini key. Nothing here is faked: the bytes
go to Storage, the chunks go to Postgres through `replace_document_chunks`, and the
embeddings come from Google.

Phase 2's half of `AGENTS.md` section 9's integration test: the upload, the
extraction, the embedding and the chunks. The question half -- asking something
the file answers and asserting the answer and the citation, plus the negative
case that must reach `unanswered_queries` -- needs retrieval, and lives in
`test_chat_e2e.py`.

To run it:
    set RUN_LIVE_TESTS=1
    # backend/.env must hold a real SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and
    # GEMINI_API_KEY, and the migrations must already be applied.

Every document it creates is deleted again, on failure as well as success.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import ValidationError

from app.api.auth_deps import require_admin
from app.config import Settings
from app.db.client import close_db_client, get_db_client, init_db_client
from app.main import create_app
from app.schemas.auth import AdminUser
from tests.filebuilders import PdfLine, pdf_bytes

# Set by tests/conftest.py so the rest of the suite can run with no configuration.
# They must be cleared here: pydantic-settings ranks real environment variables
# above the .env file, so left in place they would point this test at the fake
# Supabase URL and the failure would look like a network problem.
_STUBBED_BY_CONFTEST = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY")

_DOCUMENTS = "/admin/documents"

# The title every document this module creates carries. Cleanup deletes by title,
# because there is no other way for the fixture to learn the ids a test created
# without wrapping every call.
_TITLE = "Live Ingestion Check"

# Real embedding calls take seconds, and the whole pipeline runs inside the request
# because ASGITransport awaits background tasks.
_TIMEOUT_SECONDS = 180.0

# Only the admin gate is faked. Minting a genuine Supabase user and profile for a
# smoke test would exercise Phase 1's auth flow again and leave a real account
# behind if the run failed midway.
_ADMIN = AdminUser(id=uuid.UUID(int=0), full_name="Live Test Admin")

# Two pages of real prose, comfortably over chunk_min_tokens so the pipeline
# produces at least one chunk rather than folding everything into a stub.
_PDF = pdf_bytes(
    [
        [
            PdfLine("1. Examination Fees", size=14.0),
            PdfLine(
                "The examination fee for the semester is 500 rupees, payable at the "
                "accounts office before the last working day of June."
            ),
            PdfLine(
                "A late payment of 100 rupees is charged after the due date, and the "
                "examination form is withheld until the late fee is paid."
            ),
        ],
        [
            PdfLine("1.1 Refunds", size=14.0),
            PdfLine(
                "A refund is issued within thirty days of a written request, provided "
                "the examination form has not been submitted."
            ),
        ],
    ]
)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_TESTS"),
    reason="set RUN_LIVE_TESTS=1 to run against the real Supabase project and Gemini",
)
class TestLiveIngestion:
    """A class so the gate above applies once, and every method shares the fixture."""

    @pytest.fixture(scope="class")
    def live_settings(self) -> Settings:
        saved = {name: os.environ.pop(name, None) for name in _STUBBED_BY_CONFTEST}
        try:
            try:
                return Settings()
            except ValidationError as exc:
                pytest.skip(
                    f"No live environment: {exc.error_count()} required setting(s) missing."
                )
        finally:
            # Restored so the modules imported after this one still see the stubs.
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value

    @pytest.fixture
    async def live(self, live_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
        await init_db_client(live_settings)
        application = create_app(live_settings)
        application.dependency_overrides[require_admin] = lambda: _ADMIN

        database = get_db_client()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://live",
                timeout=_TIMEOUT_SECONDS,
            ) as client:
                yield client
        finally:
            # Best-effort: a failed assertion must not leave rows in a shared
            # project, and a cleanup error must not replace the real test result.
            try:
                await database.table("documents").delete().eq("title", _TITLE).execute()
            except Exception:  # noqa: BLE001 - teardown must not mask the outcome
                pass
            await close_db_client()

    async def _upload(self, client: httpx.AsyncClient, *, filename: str = "handbook.pdf"):
        return await client.post(
            _DOCUMENTS,
            files={"file": (filename, _PDF, "application/pdf")},
            data={"title": _TITLE, "category": "examinations"},
        )

    async def test_a_pdf_goes_from_upload_to_searchable_chunks(
        self, live: httpx.AsyncClient
    ) -> None:
        """The whole Phase 2 pipeline, once, for real.

        `ASGITransport` does not return until the background task has finished, so
        the terminal state is already stored by the time this response arrives --
        no polling loop and no flaky sleep.
        """
        response = await self._upload(live)
        assert response.status_code == 202, response.text

        document_id = response.json()["id"]
        fetched = await live.get(f"{_DOCUMENTS}/{document_id}")
        assert fetched.status_code == 200

        body = fetched.json()
        assert body["status"] == "ready", body["error_message"]
        assert body["chunk_count"] and body["chunk_count"] > 0
        assert body["page_count"] == 2
        assert body["extracted_chars"] > 0
        assert body["low_text_yield"] is False

        chunks = (
            await get_db_client()
            .table("chunks")
            .select("chunk_index,page_number,section_heading,content,embedding")
            .eq("document_id", document_id)
            .order("chunk_index")
            .execute()
        ).data

        assert chunks, "the document is ready but has no chunks in Postgres"
        assert [row["chunk_index"] for row in chunks] == list(range(len(chunks)))
        assert all(row["content"].strip() for row in chunks)
        # 768 is the column width; a provider that ignored output_dimensionality
        # would fail here rather than at some later insert.
        assert all(len(row["embedding"]) == 768 for row in chunks)
        assert any(row["section_heading"] for row in chunks)
        assert all(row["page_number"] in (1, 2) for row in chunks)

    async def test_reuploading_the_same_bytes_is_refused(self, live: httpx.AsyncClient) -> None:
        """The partial index on content_hash, exercised against the real database
        rather than a dict. A unique *constraint* here would surface as a 500 from
        a driver integrity error instead of this 409."""
        first = await self._upload(live)
        assert first.status_code == 202, first.text

        second = await self._upload(live, filename="handbook-again.pdf")

        assert second.status_code == 409
        assert second.json()["code"] == "duplicate_document"
        assert second.headers["X-Existing-Document-Id"] == first.json()["id"]

    async def test_the_embedding_cache_is_populated(self, live: httpx.AsyncClient) -> None:
        """PRD section 10's free-tier mitigation, verified rather than assumed:
        after a run, the text that was embedded has a row in `embedding_cache`
        keyed by its sha256."""
        response = await self._upload(live)
        assert response.status_code == 202, response.text
        document_id = response.json()["id"]

        database = get_db_client()
        chunks = (
            await database.table("chunks")
            .select("content")
            .eq("document_id", document_id)
            .execute()
        ).data
        assert chunks

        hashes = [hashlib.sha256(row["content"].encode()).hexdigest() for row in chunks]
        cached = (
            await database.table("embedding_cache")
            .select("content_hash")
            .in_("content_hash", hashes)
            .execute()
        ).data

        assert {row["content_hash"] for row in cached} == set(hashes)
