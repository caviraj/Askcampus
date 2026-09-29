"""The admin auth gate, exercised over HTTP.

Together these cover the whole fail-closed matrix: every way of being
unauthenticated or unauthorized must deny, and nothing may fall through to allow.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI

from app.api.auth_deps import get_profile_repository, get_token_verifier
from app.schemas.auth import Profile
from app.services.auth import TokenVerificationUnavailable
from tests.conftest import ADMIN_ID, STAFF_ID
from tests.fakes import InMemoryProfileRepository, mint_token

ADMIN_ME = "/admin/me"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _UnavailableVerifier:
    """Stands in for a verifier that cannot reach the JWKS endpoint."""

    async def verify(self, token: str) -> object:
        raise TokenVerificationUnavailable("jwks unreachable")

    async def warm_cache(self) -> None:
        return None


async def test_missing_authorization_header_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(ADMIN_ME)
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_non_bearer_scheme_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(ADMIN_ME, headers={"Authorization": "Basic abc123"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_garbage_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get(ADMIN_ME, headers=_bearer("not-a-jwt"))
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_expired_token_is_401(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    import datetime as dt

    token = mint_token(private_key, sub=ADMIN_ID, expires_in=dt.timedelta(hours=-1))
    response = await client.get(ADMIN_ME, headers=_bearer(token))
    assert response.status_code == 401


async def test_admin_token_is_accepted(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    response = await client.get(ADMIN_ME, headers=_bearer(mint_token(private_key, sub=ADMIN_ID)))
    assert response.status_code == 200
    body = response.json()
    assert body == {"id": str(ADMIN_ID), "full_name": "Ada Admin", "role": "admin"}


async def test_staff_token_is_403(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    response = await client.get(ADMIN_ME, headers=_bearer(mint_token(private_key, sub=STAFF_ID)))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_token_without_a_profile_row_is_403(
    app: FastAPI, client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    app.dependency_overrides[get_profile_repository] = lambda: InMemoryProfileRepository({})
    response = await client.get(ADMIN_ME, headers=_bearer(mint_token(private_key, sub=ADMIN_ID)))
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_role_claim_of_admin_does_not_grant_access(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    """Escalation attempt 1: forge the JWT's own role claim.

    The token is genuinely signed, so only the claim is a lie. Authorization
    must come from profiles.role, which says staff.
    """
    token = mint_token(private_key, sub=STAFF_ID, extra_claims={"role": "admin"})
    response = await client.get(ADMIN_ME, headers=_bearer(token))
    assert response.status_code == 403


async def test_user_metadata_role_does_not_grant_access(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    """Escalation attempt 2: user_metadata is writable by the user themselves."""
    token = mint_token(
        private_key,
        sub=STAFF_ID,
        extra_claims={"user_metadata": {"role": "admin"}},
    )
    response = await client.get(ADMIN_ME, headers=_bearer(token))
    assert response.status_code == 403


async def test_unreachable_jwks_is_503_not_401(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_token_verifier] = lambda: _UnavailableVerifier()
    response = await client.get(ADMIN_ME, headers=_bearer("any-token"))
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


async def test_profile_lookup_failure_is_503_and_denies(
    app: FastAPI, client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    app.dependency_overrides[get_profile_repository] = lambda: InMemoryProfileRepository(
        error=RuntimeError("database is down")
    )
    response = await client.get(ADMIN_ME, headers=_bearer(mint_token(private_key, sub=ADMIN_ID)))
    assert response.status_code == 503


async def test_error_bodies_all_use_the_shared_shape(
    client: httpx.AsyncClient, private_key: ec.EllipticCurvePrivateKey
) -> None:
    staff_token = mint_token(private_key, sub=STAFF_ID)
    for response in (
        await client.get(ADMIN_ME),
        await client.get(ADMIN_ME, headers=_bearer(staff_token)),
    ):
        assert set(response.json()) == {"detail", "code"}
        assert response.json()["detail"]


@pytest.mark.parametrize("role", ["admin", "staff"])
async def test_profile_repository_is_consulted_for_every_request(
    app: FastAPI,
    client: httpx.AsyncClient,
    private_key: ec.EllipticCurvePrivateKey,
    role: str,
) -> None:
    user_id = ADMIN_ID if role == "admin" else STAFF_ID
    app.dependency_overrides[get_profile_repository] = lambda: InMemoryProfileRepository(
        {user_id: Profile(id=user_id, role=role)}  # type: ignore[arg-type]
    )
    response = await client.get(ADMIN_ME, headers=_bearer(mint_token(private_key, sub=user_id)))
    assert response.status_code == (200 if role == "admin" else 403)
