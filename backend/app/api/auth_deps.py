"""FastAPI wiring for admin authentication.

The security logic itself lives in app/services/auth.py; this module only turns
the outcome into HTTP. Every failure path denies access.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import ApiError
from app.schemas.auth import AdminUser, Profile
from app.services.auth import (
    ProfileRepository,
    SupabaseProfileRepository,
    TokenError,
    TokenVerificationUnavailable,
    TokenVerifier,
)

logger = logging.getLogger(__name__)

# auto_error=False so a missing or non-Bearer header reaches our own handler and
# produces the shared ErrorResponse shape rather than FastAPI's default body.
bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_token_verifier(request: Request) -> TokenVerifier:
    """The verifier built once at app creation; overridden in tests."""
    return request.app.state.token_verifier


def get_profile_repository() -> ProfileRepository:
    """Overridden in tests with an in-memory implementation."""
    return SupabaseProfileRepository()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    profiles: Annotated[ProfileRepository, Depends(get_profile_repository)],
) -> Profile:
    if credentials is None:
        raise ApiError(401, "Sign in to continue.", "unauthorized", headers=_UNAUTHORIZED_HEADERS)

    try:
        claims = await verifier.verify(credentials.credentials)
    except TokenVerificationUnavailable as exc:
        raise ApiError(
            503,
            "Sign-in could not be verified. Try again.",
            "service_unavailable",
        ) from exc
    except TokenError as exc:
        raise ApiError(
            401,
            "Your session is invalid or has expired. Sign in again.",
            "unauthorized",
            headers=_UNAUTHORIZED_HEADERS,
        ) from exc

    try:
        profile = await profiles.get_profile(claims.sub)
    except Exception as exc:  # noqa: BLE001 - any lookup failure must deny, not allow
        logger.exception("Profile lookup failed for user %s", claims.sub)
        raise ApiError(
            503,
            "Sign-in could not be verified. Try again.",
            "service_unavailable",
        ) from exc

    if profile is None:
        raise ApiError(403, "Your account is not set up for admin access.", "forbidden")

    return profile


async def require_admin(user: Annotated[Profile, Depends(get_current_user)]) -> AdminUser:
    """Resolve the caller to an admin, or deny.

    The role is read from public.profiles, never from the token. A Supabase
    token's `role` claim is "authenticated" for every signed-in user, and
    `user_metadata` is writable by the user -- trusting either would let any
    signed-in account grant itself admin access.
    """
    if user.role != "admin":
        raise ApiError(403, "This area is for staff administrators.", "forbidden")
    return AdminUser(id=user.id, full_name=user.full_name)
