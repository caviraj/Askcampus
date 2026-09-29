"""Token verification.

Real EC keys and real signatures throughout -- only the JWKS HTTP fetch is
faked -- so these assertions exercise PyJWT's actual verification path.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.services.auth import TokenError, TokenVerifier
from tests.conftest import ADMIN_ID
from tests.fakes import (
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_KID,
    StubJWKClient,
    forge_hs256_token,
    generate_keypair,
    jwks_for,
    mint_token,
    public_key_pem,
    unsigned_token,
)


async def test_valid_token_returns_its_claims(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    claims = await verifier.verify(mint_token(private_key, sub=ADMIN_ID))
    assert claims.sub == ADMIN_ID


async def test_expired_token_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub=ADMIN_ID, expires_in=dt.timedelta(minutes=-5))
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_token_expired_within_leeway_is_still_accepted(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    # Default leeway is 10s; clock skew of a few seconds must not sign a user out.
    token = mint_token(private_key, sub=ADMIN_ID, expires_in=dt.timedelta(seconds=-3))
    claims = await verifier.verify(token)
    assert claims.sub == ADMIN_ID


async def test_token_signed_by_a_different_key_is_rejected(
    verifier: TokenVerifier,
) -> None:
    other_key = generate_keypair()
    with pytest.raises(TokenError):
        await verifier.verify(mint_token(other_key, sub=ADMIN_ID))


async def test_wrong_issuer_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub=ADMIN_ID, issuer="https://attacker.example/auth/v1")
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_wrong_audience_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub=ADMIN_ID, audience="some-other-service")
    with pytest.raises(TokenError):
        await verifier.verify(token)


@pytest.mark.parametrize(
    ("missing", "override"),
    [
        ("sub", {"sub": None}),
        ("aud", {"audience": None}),
        ("iss", {"issuer": None}),
        ("exp", {"expires_in": None}),
    ],
    ids=["sub", "aud", "iss", "exp"],
)
async def test_missing_required_claim_is_rejected(
    verifier: TokenVerifier,
    private_key: ec.EllipticCurvePrivateKey,
    missing: str,
    override: dict[str, object],
) -> None:
    kwargs: dict[str, object] = {
        "sub": ADMIN_ID,
        "audience": TEST_AUDIENCE,
        "issuer": TEST_ISSUER,
        "expires_in": dt.timedelta(hours=1),
    }
    kwargs.update(override)
    token = mint_token(private_key, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_unsigned_alg_none_token_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(TokenError):
        await verifier.verify(unsigned_token(sub=ADMIN_ID))


async def test_hs256_signed_with_the_public_key_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    """The classic algorithm-confusion attack.

    An attacker re-signs a forged payload with HMAC, using the server's *public*
    key as the shared secret, and sets alg=HS256 with a valid kid. It must fail
    because the verifier's algorithm allowlist is not read from the token.
    """
    forged = forge_hs256_token(
        {
            "sub": str(ADMIN_ID),
            "aud": TEST_AUDIENCE,
            "iss": TEST_ISSUER,
            "exp": int((dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=1)).timestamp()),
        },
        secret=public_key_pem(private_key),
        kid=TEST_KID,
    )
    with pytest.raises(TokenError):
        await verifier.verify(forged)


async def test_unknown_kid_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub=ADMIN_ID, kid="not-a-real-kid")
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_token_without_kid_is_rejected(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub=ADMIN_ID, kid=None)
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_rotated_key_is_accepted_after_a_refresh() -> None:
    """A token signed by the project's current key verifies after rotation."""
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        supabase_url="https://test-project.supabase.co",
        supabase_service_role_key="test-service-role-key",
    )
    old_key, new_key = generate_keypair(), generate_keypair()

    rotating = TokenVerifier(settings, StubJWKClient(jwks_for(old_key, kid="old")))
    rotating._jwks_client = StubJWKClient(jwks_for(new_key, kid="new"))  # type: ignore[assignment]

    claims = await rotating.verify(mint_token(new_key, sub=ADMIN_ID, kid="new"))
    assert claims.sub == ADMIN_ID


async def test_claims_carry_the_supabase_role_not_an_application_role(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    # Documents the trap the admin gate must not fall into: `role` here is
    # "authenticated" for every signed-in user, never "admin".
    token = mint_token(private_key, sub=uuid4(), extra_claims={"role": "authenticated"})
    assert (await verifier.verify(token)).role == "authenticated"


async def test_sub_must_be_a_uuid(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    token = mint_token(private_key, sub="not-a-uuid")
    with pytest.raises(TokenError):
        await verifier.verify(token)


async def test_verify_returns_claims_only_for_the_matching_user(
    verifier: TokenVerifier, private_key: ec.EllipticCurvePrivateKey
) -> None:
    first, second = uuid4(), uuid4()
    assert (await verifier.verify(mint_token(private_key, sub=first))).sub == first
    assert (await verifier.verify(mint_token(private_key, sub=second))).sub == second
    assert first != second
    assert isinstance(UUID(str(first)), UUID)
