"""CORS, lifespan startup and shutdown."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.services.auth import TokenVerifier


async def test_allowed_origin_is_echoed_on_preflight(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_disallowed_origin_is_not_echoed(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


async def test_authorization_header_is_an_allowed_cors_header(
    client: httpx.AsyncClient,
) -> None:
    response = await client.options(
        "/admin/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed


async def test_retry_after_is_readable_from_the_browser(client: httpx.AsyncClient) -> None:
    """`Retry-After` is not a CORS-safelisted response header.

    Without `expose_headers`, the browser hides it from the 429 handler on
    /chat: the request still fails correctly, so nothing looks wrong, and the
    rate-limit countdown silently falls back to a hardcoded default forever.
    Asserted on the preflight here because no other test would notice.
    """
    response = await client.get("/health", headers={"Origin": "http://localhost:5173"})

    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert "retry-after" in exposed


async def test_lifespan_starts_and_stops_without_network(app: FastAPI) -> None:
    """Startup and shutdown must complete with no Supabase project reachable.

    The JWKS warm-up is replaced with a no-op so the test does not wait on the
    real client's 5s timeout; that the warm-up is non-fatal is covered below.
    """

    class _NoNetworkVerifier:
        async def warm_cache(self) -> None:
            return None

    app.state.token_verifier = _NoNetworkVerifier()
    async with app.router.lifespan_context(app):
        pass


async def test_jwks_warm_up_failure_is_not_fatal(settings: Settings) -> None:
    class _FailingJWKSClient:
        uri = "https://stub.invalid/.well-known/jwks.json"

        def get_jwk_set(self, refresh: bool = False) -> object:
            raise RuntimeError("network is unreachable")

    verifier = TokenVerifier(settings, _FailingJWKSClient())  # type: ignore[arg-type]
    await verifier.warm_cache()  # must not raise


async def test_app_exposes_settings_and_verifier_for_dependencies(app: FastAPI) -> None:
    assert app.state.settings.environment == "local"
    assert isinstance(app.state.token_verifier, TokenVerifier)
