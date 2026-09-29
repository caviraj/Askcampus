"""Gemini implementation of the embedding and LLM provider interfaces.

The only module that imports the vendor SDK. Services depend on the Protocols in
this package, so the model can be replaced without touching business logic.
"""

from __future__ import annotations

import logging
import math

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.config import Settings
from app.providers.errors import ProviderError
from app.providers.llm import ResponseT

logger = logging.getLogger(__name__)

# HTTP statuses worth retrying. 429 and the 5xx family are capacity or throttle
# responses; the 4xx family generally is not -- a 404 model_not_found will fail
# identically on every attempt, and retrying it just delays the error.
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Milliseconds, which is what HttpOptions.timeout expects.
_MS_PER_SECOND = 1000

# Grounded question answering wants the same answer for the same evidence.
_TEMPERATURE = 0.0


class GeminiProvider:
    """Embeddings and JSON generation over one client.

    Implements both `EmbeddingProvider` and `LLMProvider`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dimensions = settings.embedding_dimensions
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=int(settings.provider_timeout_seconds * _MS_PER_SECOND)
            ),
        )

    @property
    def dimensions(self) -> int:
        """Vector width. Must equal the chunks.embedding column width."""
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document text, for storage."""
        return await self._embed(texts, task_type=self._settings.embedding_task_type)

    async def embed_query(self, text: str) -> list[float]:
        """Embed one question, for searching.

        A separate method rather than a task_type argument on `embed`, so a
        caller cannot pass the wrong one: the two sides of the asymmetric pair
        are chosen by which method is called, not by which constant the caller
        remembered.
        """
        vectors = await self._embed([text], task_type=self._settings.query_embedding_task_type)
        return vectors[0]

    async def _embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        """Embed a batch, returning one vector per input, in input order."""
        if not texts:
            return []

        try:
            response = await self._client.aio.models.embed_content(
                model=self._settings.embedding_model,
                # Each text goes in its own Content. Google's documentation shows a
                # plain list[str] yielding one embedding per string, but the common
                # workaround wraps each in a Content because a bare list can be
                # folded into a single multi-part content and yield ONE embedding
                # for the whole batch. Wrapping costs nothing and removes the
                # ambiguity.
                contents=[types.Content(parts=[types.Part(text=text)]) for text in texts],
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    # Without this the model returns its native 3072 floats and the
                    # insert into vector(768) fails with a cast error that never
                    # mentions dimensions.
                    output_dimensionality=self._dimensions,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - mapped into ProviderError below
            raise _wrap(exc, "embedding") from exc

        embeddings = response.embeddings or []
        if len(embeddings) != len(texts):
            # The failure this guards against is silent: a batch of 50 texts
            # returning 1 vector would still be stored, just mapped to the wrong
            # chunks, and nothing downstream would look wrong.
            raise ProviderError(
                f"Asked for {len(texts)} embeddings and received {len(embeddings)}.",
                transient=False,
            )

        vectors: list[list[float]] = []
        for embedding in embeddings:
            values = list(embedding.values or [])
            if len(values) != self._dimensions:
                raise ProviderError(
                    f"The model returned {len(values)} dimensions, expected {self._dimensions}.",
                    transient=False,
                )
            vectors.append(_l2_normalise(values))
        return vectors

    async def generate_json(self, prompt: str, schema: type[ResponseT]) -> ResponseT:
        """Generate a response constrained to `schema`, already validated."""
        try:
            response = await self._client.aio.models.generate_content(
                model=self._settings.llm_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=_TEMPERATURE,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - mapped into ProviderError below
            raise _wrap(exc, "generation") from exc

        text = getattr(response, "text", None)
        if not text:
            raise ProviderError("The model returned no content.", transient=True)

        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            # Not transient: the same prompt against the same model should not be
            # retried blindly. Phase 3 retries once and then falls back.
            raise ProviderError(
                "The model returned JSON that did not match the expected shape.",
                transient=False,
            ) from exc


def _l2_normalise(vector: list[float]) -> list[float]:
    """Scale to unit length.

    Cosine distance is scale-invariant, so this changes nothing for retrieval; it
    matters because gemini-embedding-001 is documented to return un-normalised
    vectors at non-default output widths, and cached vectors should be
    interchangeable with freshly generated ones.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _wrap(exc: Exception, action: str) -> ProviderError:
    return ProviderError(
        f"The {action} request to Gemini failed: {exc}", transient=_is_transient(exc)
    )


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in _TRANSIENT_STATUS
    if isinstance(exc, (genai_errors.ServerError, genai_errors.UnknownApiResponseError)):
        return True
    # An unrecognised failure is treated as permanent: retrying an unknown error
    # three times with backoff turns a fast failure into a slow one.
    return False
