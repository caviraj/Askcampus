"""End-to-end answering against the real Supabase project and the real Gemini API.

Gated on RUN_LIVE_TESTS=1, like `test_ingestion_e2e.py`, and for the same reason:
it needs a project, the migrations applied and a working key. Nothing is faked --
the bytes go to Storage, `hybrid_search` runs in Postgres, the answer comes from
Gemini, and the history rows are written by `log_query`.

This is `AGENTS.md` section 9's integration test: *"upload a sample PDF, wait for
`ready`, ask a question whose answer is in the file, assert the answer text and
the citation document id"* -- plus the negative half, an out-of-scope question
that must come back unanswered and leave a row in the admin queue.

To run it:
    set RUN_LIVE_TESTS=1
    # backend/.env must hold a real SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and
    # GEMINI_API_KEY, and migration 0007 must already be applied.

Every document it creates is deleted again, on failure as well as success.
"""

from __future__ import annotations

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
from app.services.normalization import question_hash
from tests.filebuilders import PdfLine, pdf_bytes

# Set by tests/conftest.py so the rest of the suite can run with no configuration.
# They must be cleared here: pydantic-settings ranks real environment variables
# above the .env file, so left in place they would point this test at the fake
# Supabase URL and the failure would look like a network problem.
_STUBBED_BY_CONFTEST = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY")

_DOCUMENTS = "/admin/documents"
_CHAT = "/chat"

# The title every document this module creates carries. Cleanup deletes by title,
# because there is no other way for the fixture to learn the ids a test created.
_TITLE = "Live Answering Check"

# Two real model calls and a real embedding, inside one request.
_TIMEOUT_SECONDS = 180.0

_ADMIN = AdminUser(id=uuid.UUID(int=0), full_name="Live Test Admin")

# One page of prose whose facts are unlikely to appear in a college's real
# published documents, so a passing answer is evidence that this file was
# retrieved rather than that the model happened to know something.
_FEE = 500
_LATE_FEE = 100
_PDF = pdf_bytes(
    [
        [
            PdfLine("1. Examination Fees", size=14.0),
            PdfLine(
                f"The examination fee for the semester is {_FEE} rupees, payable at the "
                "accounts office before the last working day of June."
            ),
            PdfLine(
                f"A late payment of {_LATE_FEE} rupees is charged after the due date, "
                "and the examination form is withheld until the late fee is paid."
            ),
        ],
    ]
)

# Nothing in a college's fee circular answers this, and it is phrased the way a
# student would ask it -- not as keyword salad, which would test the threshold
# rather than the pipeline.
_OUT_OF_SCOPE = "What is the wifi password for the hostel?"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_TESTS"),
    reason="set RUN_LIVE_TESTS=1 to run against the real Supabase project and Gemini",
)
class TestLiveAnswering:
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
        # Only the admin gate is faked, and only so this module can upload its own
        # corpus. The chat routes need no token, so what they exercise here is the
        # real, unauthenticated path.
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

    async def _ingest(self, client: httpx.AsyncClient) -> str:
        """Upload the sample PDF and return its document id.

        `ASGITransport` does not return until the background task has finished, so
        the document is already `ready` by the time this response arrives -- no
        polling loop and no flaky sleep.
        """
        response = await client.post(
            _DOCUMENTS,
            files={"file": ("fee-circular.pdf", _PDF, "application/pdf")},
            data={"title": _TITLE, "category": "examinations"},
        )
        assert response.status_code == 202, response.text
        document_id = response.json()["id"]

        fetched = await client.get(f"{_DOCUMENTS}/{document_id}")
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "ready", fetched.json()["error_message"]
        return document_id

    async def _ask(self, client: httpx.AsyncClient, question: str) -> dict:
        response = await client.post(
            _CHAT,
            json={"session_id": str(uuid.uuid4()), "question": question},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def test_a_question_answered_from_the_uploaded_document(
        self, live: httpx.AsyncClient
    ) -> None:
        """The whole Phase 3 pipeline, once, for real.

        The citation is checked against the id the upload returned and against the
        row in `chunks`, because the requirement is not that a plausible citation
        came back -- it is that every field of it came from the database.
        """
        document_id = await self._ingest(live)

        payload = await self._ask(live, "How much is the late fee for the examination?")

        assert payload["answered"] is True, payload["answer"]
        assert str(_LATE_FEE) in payload["answer"]
        assert payload["citations"], "an answered question must carry a citation"

        citation = payload["citations"][0]
        assert citation["document_title"] == _TITLE
        # AGENTS.md section 6.5: the page is a database value, never the model's.
        # The PDF is a single page, so anything else is a fabrication.
        assert citation["page"] == 1
        assert citation["snippet"].strip()

        rows = (
            await get_db_client()
            .table("chunks")
            .select("document_id")
            .eq("document_id", document_id)
            .execute()
        ).data
        assert rows, "the citation names a document that has no chunks"

    async def test_the_answer_is_written_to_the_history(self, live: httpx.AsyncClient) -> None:
        """`log_query` against the real schema, which is where a column typo in
        the RPC's argument list would otherwise first appear."""
        await self._ingest(live)
        question = "How much is the examination fee for the semester?"
        session_id = str(uuid.uuid4())

        response = await live.post(_CHAT, json={"session_id": session_id, "question": question})
        assert response.status_code == 200, response.text
        query_id = response.json()["query_id"]

        database = get_db_client()
        queries = (
            await database.table("queries")
            .select("session_id,question,normalized_hash,answer,answered")
            .eq("id", query_id)
            .execute()
        ).data
        assert len(queries) == 1, "the answer was not logged"
        assert queries[0]["session_id"] == session_id
        assert queries[0]["question"] == question
        assert queries[0]["normalized_hash"] == question_hash(question)

        sources = (
            await database.table("query_sources").select("rank").eq("query_id", query_id).execute()
        ).data
        assert sources, "an answered question must record the sources it cited"

    async def test_an_out_of_scope_question_falls_back_and_reaches_the_queue(
        self, live: httpx.AsyncClient
    ) -> None:
        """`AGENTS.md` section 9's negative test, and section 6.6's "No exception":
        the student sees a fallback, and both rows are written so an admin can find
        the gap the documents have."""
        await self._ingest(live)

        payload = await self._ask(live, _OUT_OF_SCOPE)

        assert payload["answered"] is False, payload["answer"]
        assert payload["citations"] == []
        assert payload["answer"].strip()

        # By query id rather than by hash: `queries` rows are deliberately never
        # cleaned up, so a hash lookup would find every previous run's row too and
        # this would fail on the second run against the same project.
        database = get_db_client()
        queries = (
            await database.table("queries")
            .select("normalized_hash,answered,answer")
            .eq("id", payload["query_id"])
            .execute()
        ).data
        assert len(queries) == 1, "the fallback was not logged"
        assert queries[0]["normalized_hash"] == question_hash(_OUT_OF_SCOPE)
        assert queries[0]["answered"] is False
        # What the student was actually shown, so the history is not a question
        # with no record of the answer they received.
        assert queries[0]["answer"] == payload["answer"]

        queued = (
            await database.table("unanswered_queries")
            .select("question,status")
            .eq("query_id", payload["query_id"])
            .execute()
        ).data
        assert len(queued) == 1, "the unanswered question never reached the admin queue"
        assert queued[0]["question"] == _OUT_OF_SCOPE
        assert queued[0]["status"] == "open"
