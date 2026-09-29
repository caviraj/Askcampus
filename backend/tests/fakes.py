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
import math
from typing import Any
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient
from jwt.algorithms import ECAlgorithm

from app.providers.errors import ProviderError
from app.schemas.auth import Profile
from app.services.storage import StorageError

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


# ---------------------------------------------------------------------------
# Phase 2: ingestion
# ---------------------------------------------------------------------------

# Statuses a document can be claimed from. Mirrors _CLAIMABLE_STATUSES in
# app/db/queries.py, and asserted against it in test_ingestion_service.py so the
# fake cannot drift from the real conditional update.
CLAIMABLE_STATUSES = frozenset({"uploaded", "ready", "failed"})


class InMemoryDocumentRepository:
    """DocumentRepository over dicts, with a call log and a failure hook.

    The log and `fail_on` exist for one property in particular: that a pipeline
    which dies part-way leaves the previous chunks intact. Proving that needs a
    repository that can be told to fail at an exact step, which a real database
    would only allow by arrangement.
    """

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.chunks: dict[UUID, list[dict[str, Any]]] = {}
        self.calls: list[str] = []
        self.fail_on: set[str] = set()

    def seed(self, **row: Any) -> dict[str, Any]:
        """Insert a row directly, bypassing the call log."""
        document_id = row.pop("id", uuid4())
        full: dict[str, Any] = {
            "id": document_id,
            "title": "Seeded document",
            "category": "general",
            "academic_year": None,
            "department": None,
            "file_path": f"{uuid4().hex}.pdf",
            "file_type": "pdf",
            "original_filename": "seeded.pdf",
            "file_size_bytes": 10,
            "content_hash": None,
            "status": "uploaded",
            "is_active": True,
            "error_message": None,
            "page_count": None,
            "chunk_count": None,
            "extracted_chars": None,
            "low_text_yield": False,
            "text_preview": None,
            "created_at": None,
            "updated_at": None,
        }
        full.update(row)
        self.rows[document_id] = full
        return full

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail_on:
            raise RuntimeError(f"The fake repository was told to fail on {name}.")

    async def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        self._record("insert")
        return self.seed(**row)

    async def get(self, document_id: UUID) -> dict[str, Any] | None:
        self._record("get")
        row = self.rows.get(document_id)
        return dict(row) if row else None

    async def get_file_reference(self, document_id: UUID) -> dict[str, Any] | None:
        self._record("get_file_reference")
        row = self.rows.get(document_id)
        if row is None:
            return None
        return {key: row[key] for key in ("id", "file_path", "file_type", "title")}

    async def list_documents(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        self._record("list_documents")
        rows = [dict(row) for row in self.rows.values()]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if category is not None:
            rows = [row for row in rows if row["category"] == category]
        if is_active is not None:
            rows = [row for row in rows if row["is_active"] is is_active]
        return rows[offset : offset + limit], len(rows)

    async def update(self, document_id: UUID, patch: dict[str, Any]) -> dict[str, Any] | None:
        self._record("update")
        row = self.rows.get(document_id)
        if row is None:
            return None
        row.update(patch)
        return dict(row)

    async def claim_for_processing(self, document_id: UUID) -> dict[str, Any] | None:
        self._record("claim_for_processing")
        row = self.rows.get(document_id)
        # The conditional update is the lock, so the fake reproduces its
        # condition rather than always succeeding.
        if row is None or row["status"] not in CLAIMABLE_STATUSES:
            return None
        row["status"] = "processing"
        row["error_message"] = None
        return dict(row)

    async def mark_failed(self, document_id: UUID, message: str) -> None:
        self._record("mark_failed")
        row = self.rows.get(document_id)
        if row is not None:
            row["status"] = "failed"
            row["error_message"] = message

    async def delete(self, document_id: UUID) -> None:
        self._record("delete")
        self.rows.pop(document_id, None)
        self.chunks.pop(document_id, None)

    async def find_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        self._record("find_by_hash")
        for row in self.rows.values():
            if row["content_hash"] == content_hash and row["is_active"]:
                return dict(row)
        return None

    async def replace_chunks(
        self,
        document_id: UUID,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
        *,
        mark_ready: bool = True,
    ) -> int:
        self._record("replace_chunks")
        row = self.rows.get(document_id)
        if row is None:
            raise KeyError(document_id)
        # Delete-then-insert, matching the RPC. The failure hook fires before
        # either, so a test can prove the *old* chunks survived a failed run.
        self.chunks[document_id] = [dict(chunk) for chunk in chunks]
        row["chunk_count"] = len(chunks)
        for key in ("page_count", "extracted_chars", "text_preview", "low_text_yield"):
            if key in metadata:
                row[key] = metadata[key]
        if mark_ready:
            row["status"] = "ready"
            row["error_message"] = None
        return len(chunks)


class InMemoryFileStorage:
    """FileStorage over a dict, recording what was written and deleted."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.deleted: list[str] = []

    async def put(self, path: str, data: bytes, content_type: str) -> None:
        self.objects[path] = data
        self.content_types[path] = content_type

    async def get(self, path: str) -> bytes:
        try:
            return self.objects[path]
        except KeyError as exc:
            raise StorageError(f"No object at {path}") from exc

    async def delete(self, path: str) -> None:
        self.objects.pop(path, None)
        self.deleted.append(path)


class InMemoryEmbeddingCache:
    """EmbeddingCache over a dict, counting reads and writes."""

    def __init__(self) -> None:
        self.entries: dict[str, list[float]] = {}
        self.reads = 0
        self.writes = 0

    async def get_many(
        self, content_hashes: list[str], *, model: str, dimensions: int
    ) -> dict[str, list[float]]:
        self.reads += 1
        return {key: self.entries[key] for key in content_hashes if key in self.entries}

    async def put_many(
        self, entries: dict[str, list[float]], *, model: str, dimensions: int
    ) -> None:
        self.writes += 1
        self.entries.update(entries)


class FakeEmbeddingProvider:
    """Deterministic vectors derived from the text, in requested order.

    Records each batch's size, which is how the batching test proves
    embed_batch_size is honoured rather than assuming it.
    """

    def __init__(
        self,
        dimensions: int = 768,
        *,
        transient_failures: int = 0,
        error: ProviderError | None = None,
    ) -> None:
        self._dimensions = dimensions
        self.batch_sizes: list[int] = []
        self.texts: list[str] = []
        self.transient_failures = transient_failures
        self.error = error

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        self.texts.extend(texts)
        if self.error is not None:
            raise self.error
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise ProviderError("The provider is busy.", transient=True)
        return [fake_vector(text, self._dimensions) for text in texts]


def fake_vector(text: str, dimensions: int = 768) -> list[float]:
    """A deterministic unit-length vector for `text`.

    Derived from the text's digest rather than random, so a test can assert both
    that a value came back and that it belongs to the text it was asked for.
    """
    raw = [byte / 255.0 for byte in hashlib.sha256(text.encode()).digest()]
    repeats = -(-dimensions // len(raw))
    vector = (raw * repeats)[:dimensions]
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]
