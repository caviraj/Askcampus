"""Test doubles.

The JWT double fakes only the HTTP fetch: keys are real EC keys and tokens are
really signed, so signature, expiry, issuer, audience and the algorithm
allowlist are all exercised for real rather than mocked away.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm

from app.schemas.auth import Profile

TEST_SUPABASE_URL = "https://test-project.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
TEST_AUDIENCE = "authenticated"
TEST_KID = "test-key-1"


class StubJWKClient(PyJWKClient):
    """A PyJWKClient that serves a fixed key set from memory.

    fetch_data() is the documented extension point; overriding it means no HTTP
    server is needed while every other part of verification stays real.
    """

    def __init__(self, jwks: dict[str, Any]) -> None:
        super().__init__("https://stub.invalid/.well-known/jwks.json", cache_keys=False)
        self._stub_jwks = jwks

    def fetch_data(self) -> Any:
        return self._stub_jwks


def generate_keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def jwks_for(private_key: ec.EllipticCurvePrivateKey, kid: str = TEST_KID) -> dict[str, Any]:
    """Build a JWKS document for the public half of an EC key."""
    jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
    return {"keys": [jwk]}


def mint_token(
    key: Any,
    *,
    algorithm: str = "ES256",
    kid: str | None = TEST_KID,
    sub: str | UUID | None = None,
    audience: str | None = TEST_AUDIENCE,
    issuer: str | None = TEST_ISSUER,
    expires_in: dt.timedelta | None = dt.timedelta(hours=1),
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a token. Pass None for a claim to omit it entirely."""
    now = dt.datetime.now(tz=dt.UTC)
    payload: dict[str, Any] = {"iat": now}
    if sub is not None:
        payload["sub"] = str(sub)
    if audience is not None:
        payload["aud"] = audience
    if issuer is not None:
        payload["iss"] = issuer
    if expires_in is not None:
        payload["exp"] = now + expires_in
    if extra_claims:
        payload.update(extra_claims)

    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, key, algorithm=algorithm, headers=headers)


def unsigned_token(
    *,
    sub: str | UUID | None = None,
    kid: str | None = TEST_KID,
) -> str:
    """An alg:none token, assembled by hand.

    PyJWT's encoder usually refuses to produce these, and the point of the test
    is that a hand-crafted one is still rejected.
    """

    def b64(data: dict[str, Any]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = {"alg": "none", "typ": "JWT"}
    if kid:
        header["kid"] = kid
    payload = {
        "sub": str(sub) if sub else "00000000-0000-0000-0000-000000000000",
        "aud": TEST_AUDIENCE,
        "iss": TEST_ISSUER,
        "exp": int((dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=1)).timestamp()),
    }
    return f"{b64(header)}.{b64(payload)}."


def forge_hs256_token(payload: dict[str, Any], secret: bytes, kid: str | None = TEST_KID) -> str:
    """Hand-assemble an HS256 token.

    PyJWT's encoder refuses to use an asymmetric PEM as an HMAC secret, so the
    algorithm-confusion token has to be built by hand -- which is what a real
    attacker would do anyway, since they are not using PyJWT's guard rails.
    `payload` must contain only JSON-native values.
    """

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header: dict[str, Any] = {"alg": "HS256", "typ": "JWT"}
    if kid:
        header["kid"] = kid

    def encode(data: dict[str, Any]) -> str:
        return b64(json.dumps(data, separators=(",", ":")).encode())

    signing_input = f"{encode(header)}.{encode(payload)}"
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(signature)}"


def public_key_pem(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


class InMemoryProfileRepository:
    """ProfileRepository over a dict, so tests never fake postgrest."""

    def __init__(
        self,
        profiles: dict[UUID, Profile] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._profiles = profiles or {}
        self._error = error

    async def get_profile(self, user_id: UUID) -> Profile | None:
        if self._error is not None:
            raise self._error
        return self._profiles.get(user_id)
