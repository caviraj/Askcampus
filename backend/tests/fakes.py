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
from app.services.retrieval import RetrievedChunk
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
    embed_batch_size is honoured rather than assuming it. Question embeddings are
    recorded separately, under `queries`: a query is one text and no batch, and
    counting it as a batch would break the batching assertions.
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
        self.queries: list[str] = []
        self.transient_failures = transient_failures
        self.error = error

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        self.texts.extend(texts)
        self._maybe_fail()
        return [fake_vector(text, self._dimensions) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        self._maybe_fail()
        return fake_vector(text, self._dimensions)

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise ProviderError("The provider is busy.", transient=True)


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


# ---------------------------------------------------------------------------
# Phase 3: retrieval and answering
# ---------------------------------------------------------------------------


class FakeLLMProvider:
    """Scripted answers, one per call, with every prompt recorded.

    A queue rather than one fixed answer, because the behaviour worth testing is
    what happens on the *second* call -- the one after a rejected response. A
    provider that returned the same thing every time could not express that.

    A queued item may be a dict, a ModelAnswer, or an exception to raise, so a
    test can script a malformed response or a provider failure at an exact call.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        error: ProviderError | None = None,
    ) -> None:
        self.responses: list[Any] = list(responses or [])
        self.error = error
        self.prompts: list[str] = []
        self.schemas: list[type[Any]] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def generate_json(self, prompt: str, schema: type[Any]) -> Any:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("The fake LLM was asked for more answers than were scripted.")

        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict):
            return schema.model_validate(response)
        return response


def answer_payload(
    answer: str = "Registration closes on 12 December 2026.",
    *,
    sources: list[str] | None = None,
    answerable: bool = True,
) -> dict[str, Any]:
    """A model response in the shape ARCHITECTURE.md section 6 fixes."""
    return {
        "answerable": answerable,
        "answer": answer,
        "used_sources": ["S1"] if sources is None else sources,
    }


class InMemoryChunkRepository:
    """ChunkRepository over dicts, with a scripted ranking.

    `search` returns the primed ranking narrowed to the requested category, which
    is what `filter_category` does in the real function: the ranking itself is
    global, and the filter selects from it. Recording the categories asked for is
    what lets a test prove the unfiltered retry happened -- and prove it did not
    when the filtered search was already good enough.

    `hydrate` reproduces the real filter rather than trusting the ranking: a
    chunk whose document is inactive or not ready is dropped, exactly as
    `fetch_searchable_documents` drops it.
    """

    def __init__(self) -> None:
        self.documents: dict[UUID, dict[str, Any]] = {}
        self.chunks: dict[UUID, dict[str, Any]] = {}
        self.ranking: list[dict[str, Any]] = []
        self.searched: list[str | None] = []
        self.match_counts: list[int] = []

    def seed_document(self, **overrides: Any) -> UUID:
        """Insert a searchable document and return its id."""
        document_id: UUID = overrides.pop("id", uuid4())
        row: dict[str, Any] = {
            "id": document_id,
            "title": "Seeded document",
            "department": None,
            "updated_at": "2026-09-10T09:00:00+00:00",
            "category": "general",
            "is_active": True,
            "status": "ready",
        }
        row.update(overrides)
        self.documents[document_id] = row
        return document_id

    def seed_chunk(self, document_id: UUID, **overrides: Any) -> UUID:
        """Insert a chunk belonging to a seeded document."""
        chunk_id: UUID = overrides.pop("id", uuid4())
        row: dict[str, Any] = {
            "id": chunk_id,
            "document_id": document_id,
            "content": "Seeded content.",
            "page_number": 1,
            "section_heading": None,
        }
        row.update(overrides)
        self.chunks[chunk_id] = row
        return chunk_id

    def prime(self, ranked: list[tuple[UUID, float | None]]) -> None:
        """Script what `search` finds, best first.

        Each entry is (chunk_id, cosine similarity). The RRF score is derived
        from the rank the way the real function derives it, so nothing in a test
        depends on a number that was invented here.
        """
        self.ranking = [
            {
                "chunk_id": chunk_id,
                "document_id": self.chunks[chunk_id]["document_id"],
                "score": 1.0 / (60 + rank),
                "similarity": similarity,
            }
            for rank, (chunk_id, similarity) in enumerate(ranked, start=1)
        ]

    async def search(
        self, *, query_text: str, embedding: list[float], match_count: int, category: str | None
    ) -> list[dict[str, Any]]:
        self.searched.append(category)
        self.match_counts.append(match_count)
        narrowed = [
            hit for hit in self.ranking if category is None or self._category_of(hit) == category
        ]
        return [dict(hit) for hit in narrowed[:match_count]]

    def _category_of(self, hit: dict[str, Any]) -> Any:
        return self.documents[_as_uuid(hit["document_id"])]["category"]

    async def hydrate(self, hits: list[dict[str, Any]]) -> list[RetrievedChunk]:
        hydrated: list[RetrievedChunk] = []
        for hit in hits:
            chunk = self.chunks.get(_as_uuid(hit["chunk_id"]))
            document = self.documents.get(_as_uuid(hit["document_id"]))
            if chunk is None or document is None:
                continue
            if not document["is_active"] or document["status"] != "ready":
                continue
            hydrated.append(
                RetrievedChunk(
                    chunk_id=chunk["id"],
                    document_id=document["id"],
                    score=float(hit["score"]),
                    similarity=hit["similarity"],
                    content=chunk["content"],
                    page_number=chunk["page_number"],
                    section_heading=chunk["section_heading"],
                    document_title=document["title"],
                    department=document["department"],
                    document_updated_at=document["updated_at"],
                )
            )
        return hydrated


class InMemoryQueryLogRepository:
    """QueryLogRepository over lists, with a failure hook.

    Every call is kept rather than the last, because "the fallback wrote both
    rows" is a statement about one call: `log_query` is handed `unanswered=True`
    and the real function writes the `queries` row and the `unanswered_queries`
    row in one transaction, so what a fake can record is the flag the transaction
    was asked to act on.

    `record_feedback` reproduces the ownership rule, including the upsert.
    """

    def __init__(self, *, error: Exception | None = None) -> None:
        self.entries: list[dict[str, Any]] = []
        self.feedback: list[dict[str, Any]] = []
        self.sessions: dict[UUID, UUID] = {}
        self.error = error

    async def log_query(self, **kwargs: Any) -> None:
        if self.error is not None:
            raise self.error
        self.entries.append(kwargs)
        self.sessions[kwargs["query_id"]] = kwargs["session_id"]

    async def record_feedback(self, *, query_id: UUID, session_id: UUID, helpful: bool) -> bool:
        if self.sessions.get(query_id) != session_id:
            return False
        self.feedback = [row for row in self.feedback if row["query_id"] != query_id]
        self.feedback.append({"query_id": query_id, "session_id": session_id, "helpful": helpful})
        return True


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
