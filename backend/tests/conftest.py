"""Shared fixtures.

The environment is set before anything under app is imported, because
app.main builds the application at import time and Settings requires these
values. Without this, collecting any test module would raise ValidationError.
"""

from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from collections.abc import AsyncIterator  # noqa: E402
from uuid import UUID  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app.api.auth_deps import get_profile_repository, get_token_verifier  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas.auth import Profile  # noqa: E402
from app.services.auth import TokenVerifier  # noqa: E402
from tests.fakes import (  # noqa: E402
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_KID,
    TEST_SUPABASE_URL,
    InMemoryProfileRepository,
    StubJWKClient,
    generate_keypair,
    jwks_for,
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
def app(
    settings: Settings,
    verifier: TokenVerifier,
    profile_repository: InMemoryProfileRepository,
) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_token_verifier] = lambda: verifier
    application.dependency_overrides[get_profile_repository] = lambda: profile_repository
    return application


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
