"""Admin authentication: JWT verification and role resolution.

Deliberately free of FastAPI imports so the security logic is unit-testable on
its own. The HTTP wiring lives in app/api/auth_deps.py.

Tokens are verified locally against the project's JWKS endpoint. There is no
shared-secret (HS256) path: projects created since May 2025 issue asymmetric
signing keys, and mixing HS256 with ES256 in one verifier is the classic
algorithm-confusion setup that RFC 8725 section 2.1 warns about.
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

import anyio
import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.db.queries import fetch_profile
from app.schemas.auth import Profile

logger = logging.getLogger(__name__)

# Never derived from the token header -- that is the vulnerability. Supabase
# signs with ES256 when the project uses the current asymmetric signing keys.
ALLOWED_ALGORITHMS = ["ES256"]

# Rejected explicitly rather than relying on the signature check alone, so a
# token that simply omits a claim cannot be treated as valid.
REQUIRED_CLAIMS = ["exp", "sub", "aud", "iss"]


class TokenError(Exception):
    """The token was present but not valid. Maps to 401."""


class TokenVerificationUnavailable(Exception):
    """The JWKS endpoint could not be reached. Maps to 503, and fails closed."""


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: UUID
    # Supabase sets this to "authenticated" for every signed-in user. It is NOT
    # the application role; that lives in public.profiles.role.
    role: str | None = None
    email: str | None = None


class ProfileRepository(Protocol):
    """Read access to public.profiles.

    A Protocol rather than a direct call so tests can substitute an in-memory
    implementation instead of faking postgrest's fluent builder chain.
    """

    async def get_profile(self, user_id: UUID) -> Profile | None: ...


class TokenVerifier:
    def __init__(self, settings: Settings, jwks_client: PyJWKClient | None = None) -> None:
        # jwks_client is injectable so tests can serve a fixed key set from
        # memory while still exercising real signature verification.
        self._jwks_client = jwks_client or PyJWKClient(
            settings.jwks_url,
            # cache_keys=False is a security choice, not a default: PyJWT's
            # per-key cache has no time-based expiry, so a key Supabase has
            # revoked would keep verifying indefinitely. The tier-1 JWKS cache
            # below does expire, and a kid miss refreshes it.
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=float(settings.jwks_cache_seconds),
            timeout=5,
        )
        self._audience = settings.jwt_audience
        self._issuer = settings.jwt_issuer
        self._leeway = settings.jwt_leeway_seconds

    async def verify(self, token: str) -> TokenClaims:
        """Verify a bearer token and return its claims.

        Raises TokenError (401) or TokenVerificationUnavailable (503). Never
        returns claims for an unverified token.
        """
        try:
            # PyJWKClient is synchronous and uses urllib, so a cache miss would
            # block the event loop for a whole HTTPS round trip. Off-thread it
            # costs microseconds on a warm cache and removes that stall.
            signing_key = await anyio.to_thread.run_sync(
                self._jwks_client.get_signing_key_from_jwt, token
            )
        except jwt.PyJWKClientConnectionError as exc:
            logger.warning("JWKS endpoint unreachable: %s", exc)
            raise TokenVerificationUnavailable("Could not reach the signing key endpoint.") from exc
        except jwt.PyJWTError as exc:
            # Covers both PyJWKClientError (no matching key) and the DecodeError
            # raised for a token that is not a JWT at all. Both mean "this token
            # is not usable", so both must be a 401 rather than an unhandled 500.
            raise TokenError("The token is malformed or uses an unknown signing key.") from exc

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise TokenError("The token is invalid or has expired.") from exc

        try:
            return TokenClaims.model_validate(payload)
        except ValidationError as exc:
            # A signature-valid token whose claims do not fit the expected shape
            # is still not usable. Raised as TokenError so it becomes a 401
            # rather than an unhandled 500.
            raise TokenError("The token claims are not in the expected format.") from exc

    async def warm_cache(self) -> None:
        """Pre-fetch the JWKS so the first admin request is not slow.

        Best-effort on purpose: a startup with no network (local development, or
        a test run) must still boot. Settings validation is what fails fast.
        """
        try:
            await anyio.to_thread.run_sync(self._jwks_client.get_jwk_set)
        except Exception:  # noqa: BLE001 - warm-up must never be fatal
            logger.warning(
                "Could not pre-fetch the JWKS from %s; the first admin request will fetch it.",
                self._jwks_client.uri,
                exc_info=True,
            )


class SupabaseProfileRepository:
    """ProfileRepository backed by the real database."""

    async def get_profile(self, user_id: UUID) -> Profile | None:
        return await fetch_profile(user_id)
