"""Shared fixtures.

The environment is set before anything under app is imported, because
app.main builds the application at import time and Settings requires these
values. Without this, collecting any test module would raise ValidationError.
"""

from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
# Required from Phase 2. A dummy value is enough: every test that would reach
# Gemini runs against a fake provider, so no network call is ever made.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-api-key")

from collections.abc import AsyncIterator  # noqa: E402
from uuid import UUID  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app.api.auth_deps import get_profile_repository, get_token_verifier  # noqa: E402
from app.api.chat import (  # noqa: E402
    get_answering_service,
    get_chunk_repository,
    get_query_log_repository,
)
from app.api.documents import (  # noqa: E402
    get_document_repository,
    get_file_storage,
    get_ingestion_service,
)
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas.auth import Profile  # noqa: E402
from app.services.answering import AnsweringService  # noqa: E402
from app.services.auth import TokenVerifier  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.ingestion import IngestionService  # noqa: E402
from app.services.retrieval import RetrievalService  # noqa: E402
from tests.fakes import (  # noqa: E402
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_KID,
    TEST_SUPABASE_URL,
    FakeEmbeddingProvider,
    FakeLLMProvider,
    InMemoryChunkRepository,
    InMemoryDocumentRepository,
    InMemoryEmbeddingCache,
    InMemoryFileStorage,
    InMemoryProfileRepository,
    InMemoryQueryLogRepository,
    StubJWKClient,
    generate_keypair,
    jwks_for,
    mint_token,
)

ADMIN_ID = UUID("11111111-1111-1111-1111-111111111111")
STAFF_ID = UUID("22222222-2222-2222-2222-222222222222")

__all__ = ["ADMIN_ID", "STAFF_ID", "TEST_AUDIENCE", "TEST_ISSUER", "TEST_KID"]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url=TEST_SUPABASE_URL,
        supabase_service_role_key="test-service-role-key",
        gemini_api_key="test-gemini-api-key",
    )


@pytest.fixture(scope="session")
def private_key() -> ec.EllipticCurvePrivateKey:
    return generate_keypair()


@pytest.fixture
def verifier(settings: Settings, private_key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    """A real TokenVerifier whose key set comes from memory."""
    return TokenVerifier(settings, StubJWKClient(jwks_for(private_key)))


@pytest.fixture
def profile_repository() -> InMemoryProfileRepository:
    return InMemoryProfileRepository(
        {
            ADMIN_ID: Profile(id=ADMIN_ID, full_name="Ada Admin", role="admin"),
            STAFF_ID: Profile(id=STAFF_ID, full_name="Sam Staff", role="staff"),
        }
    )


@pytest.fixture
def document_repository() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def file_storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def embedding_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def chunk_repository() -> InMemoryChunkRepository:
    return InMemoryChunkRepository()


@pytest.fixture
def query_log_repository() -> InMemoryQueryLogRepository:
    return InMemoryQueryLogRepository()


@pytest.fixture
def llm_provider() -> FakeLLMProvider:
    """No scripted answers by default.

    A test that reaches the model without saying what it should return gets an
    AssertionError rather than a plausible-looking answer, so a path that was
    meant to fall back before the model call cannot pass by accident.
    """
    return FakeLLMProvider()


@pytest.fixture
def app(
    settings: Settings,
    verifier: TokenVerifier,
    profile_repository: InMemoryProfileRepository,
    document_repository: InMemoryDocumentRepository,
    file_storage: InMemoryFileStorage,
    embedding_provider: FakeEmbeddingProvider,
    chunk_repository: InMemoryChunkRepository,
    query_log_repository: InMemoryQueryLogRepository,
    llm_provider: FakeLLMProvider,
) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_token_verifier] = lambda: verifier
    application.dependency_overrides[get_profile_repository] = lambda: profile_repository
    # The document routes are wired to fakes for every API test, so no test can
    # reach Supabase or Gemini by forgetting to override something. The ingestion
    # service is built here rather than overridden wholesale so its real
    # orchestration runs behind the routes.
    application.dependency_overrides[get_document_repository] = lambda: document_repository
    application.dependency_overrides[get_file_storage] = lambda: file_storage
    application.dependency_overrides[get_ingestion_service] = lambda: IngestionService(
        document_repository,
        file_storage,
        EmbeddingService(embedding_provider, settings, InMemoryEmbeddingCache()),
        settings,
    )
    # The same choice for chat: the real RetrievalService and AnsweringService run
    # behind the routes, with only the providers and the two repositories faked.
    # Overriding the answering service wholesale would mean the citation rules,
    # the fallback decision and the retry were never exercised through the API.
    application.dependency_overrides[get_chunk_repository] = lambda: chunk_repository
    application.dependency_overrides[get_query_log_repository] = lambda: query_log_repository
    application.dependency_overrides[get_answering_service] = lambda: AnsweringService(
        retrieval=RetrievalService(
            EmbeddingService(embedding_provider, settings, InMemoryEmbeddingCache()),
            chunk_repository,
            settings,
        ),
        llm=llm_provider,
        query_log=query_log_repository,
    )
    return application


@pytest.fixture
def admin_headers(private_key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    """Authorization for an admin, which every /admin route requires."""
    return {"Authorization": f"Bearer {mint_token(private_key, sub=ADMIN_ID)}"}


@pytest.fixture
def staff_headers(private_key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(private_key, sub=STAFF_ID)}"}


@pytest.fixture
async def authorized(
    app: FastAPI, admin_headers: dict[str, str]
) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose every request is already authorized as an admin."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=admin_headers,
    ) as http_client:
        yield http_client


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the app.

    ASGITransport does not run the lifespan, so no database client or network
    call is involved. test_app_wiring.py exercises the lifespan separately.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client
