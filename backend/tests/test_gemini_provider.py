"""The Gemini provider's request shaping and error classification.

No test here touches the network: the vendor client is replaced, and what is
asserted is the request the provider builds and the mapping it applies to what
comes back. Those are the parts that can be wrong in a way nothing downstream
notices -- a batch folded into one embedding, or a retired model retried three
times instead of failing once.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.providers import gemini as gemini_module
from app.providers.errors import ProviderError
from app.providers.gemini import GeminiProvider, _is_transient

DIMENSIONS = 768


class _Payload(BaseModel):
    answerable: bool
    answer: str


class _FakeModels:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.embed_calls: list[dict[str, Any]] = []
        self.generate_calls: list[dict[str, Any]] = []

    async def embed_content(self, **kwargs: Any) -> Any:
        self.embed_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def generate_content(self, **kwargs: Any) -> Any:
        self.generate_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.aio = SimpleNamespace(models=models)
        self.init_kwargs: dict[str, Any] = {}


def _embedding_response(vectors: list[list[float]]) -> Any:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=vector) for vector in vectors])


@pytest.fixture
def models() -> _FakeModels:
    return _FakeModels()


@pytest.fixture
def provider(
    settings: Settings, models: _FakeModels, monkeypatch: pytest.MonkeyPatch
) -> GeminiProvider:
    """A real GeminiProvider whose vendor client is replaced.

    The client is built in __init__, so patching the class is the only way to keep
    construction real -- and constructing for real is what proves the API key and
    HttpOptions arguments are accepted.
    """
    client = _FakeClient(models)
    monkeypatch.setattr(gemini_module.genai, "Client", lambda **kwargs: _record(client, kwargs))
    return GeminiProvider(settings)


def _record(client: _FakeClient, kwargs: dict[str, Any]) -> _FakeClient:
    client.init_kwargs = kwargs
    return client


def test_the_client_is_built_with_the_configured_timeout(settings: Settings) -> None:
    """AGENTS.md section 10 names a 30 s provider timeout, and HttpOptions takes
    milliseconds -- passing 30 would mean a 30 ms timeout, which fails every
    request in a way that looks like a network problem."""
    captured: dict[str, Any] = {}

    def capture(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return _FakeClient(_FakeModels())

    original = gemini_module.genai.Client
    gemini_module.genai.Client = capture
    try:
        GeminiProvider(settings)
    finally:
        gemini_module.genai.Client = original

    options = captured["http_options"]
    assert options.timeout == int(settings.provider_timeout_seconds * 1000) == 30_000
    assert captured["api_key"] == "test-gemini-api-key"


def test_dimensions_follow_the_configuration(settings: Settings, provider: GeminiProvider) -> None:
    assert provider.dimensions == settings.embedding_dimensions == DIMENSIONS


async def test_no_texts_makes_no_call(provider: GeminiProvider, models: _FakeModels) -> None:
    assert await provider.embed([]) == []
    assert models.embed_calls == []


async def test_each_text_is_sent_as_its_own_content(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    """A bare list[str] can be folded into one multi-part content and yield a
    single embedding for the whole batch. One Content per text removes the
    ambiguity."""
    models.result = _embedding_response([[0.1] * DIMENSIONS, [0.2] * DIMENSIONS])
    await provider.embed(["Fees are due.", "Hostel forms open."])

    call = models.embed_calls[0]
    assert [part.text for content in call["contents"] for part in content.parts] == [
        "Fees are due.",
        "Hostel forms open.",
    ]


async def test_the_task_type_and_width_are_requested(
    settings: Settings, provider: GeminiProvider, models: _FakeModels
) -> None:
    """Asymmetric retrieval needs RETRIEVAL_DOCUMENT at ingestion and
    RETRIEVAL_QUERY for the question; using the wrong one degrades recall
    silently. Without the width, the model returns 3072 floats and the insert into
    vector(768) fails with an error that never mentions dimensions."""
    models.result = _embedding_response([[0.1] * DIMENSIONS])
    await provider.embed(["Fees are due."])

    config = models.embed_calls[0]["config"]
    assert config.task_type == settings.embedding_task_type == "RETRIEVAL_DOCUMENT"
    assert config.output_dimensionality == DIMENSIONS
    assert models.embed_calls[0]["model"] == settings.embedding_model


async def test_vectors_are_normalised(provider: GeminiProvider, models: _FakeModels) -> None:
    """gemini-embedding-001 returns un-normalised vectors at non-default widths,
    so a cached vector and a fresh one must still be interchangeable."""
    models.result = _embedding_response([[3.0] * DIMENSIONS])
    vector = (await provider.embed(["Fees are due."]))[0]

    norm = sum(value * value for value in vector) ** 0.5
    assert norm == pytest.approx(1.0)


async def test_a_zero_vector_is_returned_rather_than_divided_by_zero(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    models.result = _embedding_response([[0.0] * DIMENSIONS])
    assert (await provider.embed(["Fees are due."]))[0] == [0.0] * DIMENSIONS


async def test_too_few_embeddings_raises(provider: GeminiProvider, models: _FakeModels) -> None:
    """Finding 3's guard. A batch of two folded into one vector would still be
    stored -- just mapped to the wrong chunks -- and nothing would look wrong."""
    models.result = _embedding_response([[0.1] * DIMENSIONS])
    with pytest.raises(ProviderError, match="Asked for 2 embeddings and received 1"):
        await provider.embed(["Fees are due.", "Hostel forms open."])


async def test_too_many_embeddings_raises(provider: GeminiProvider, models: _FakeModels) -> None:
    models.result = _embedding_response([[0.1] * DIMENSIONS, [0.1] * DIMENSIONS])
    with pytest.raises(ProviderError, match="received 2"):
        await provider.embed(["Fees are due."])


async def test_an_empty_response_raises(provider: GeminiProvider, models: _FakeModels) -> None:
    models.result = SimpleNamespace(embeddings=None)
    with pytest.raises(ProviderError, match="received 0"):
        await provider.embed(["Fees are due."])


async def test_a_wrong_width_raises(provider: GeminiProvider, models: _FakeModels) -> None:
    """The provider's own width check, so the failure names dimensions instead of
    surfacing later as a Postgres cast error."""
    models.result = _embedding_response([[0.1] * 3072])
    with pytest.raises(ProviderError, match="returned 3072 dimensions"):
        await provider.embed(["Fees are due."])


async def test_a_provider_error_is_mapped_and_marked_transient(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    models.error = _http_error(429)
    with pytest.raises(ProviderError) as raised:
        await provider.embed(["Fees are due."])
    assert raised.value.transient is True


async def test_a_retired_model_fails_permanently(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    """Finding 1: a 404 model_not_found fails identically on every attempt, and
    retrying it turns a fast, clear failure into a slow one."""
    models.error = _http_error(404)
    with pytest.raises(ProviderError) as raised:
        await provider.embed(["Fees are due."])
    assert raised.value.transient is False


async def test_generate_json_returns_a_validated_model(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    models.result = SimpleNamespace(text='{"answerable": true, "answer": "Fees are due in June."}')
    payload = await provider.generate_json("prompt", _Payload)
    assert payload == _Payload(answerable=True, answer="Fees are due in June.")


async def test_generate_json_constrains_the_response(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    models.result = SimpleNamespace(text='{"answerable": false, "answer": ""}')
    await provider.generate_json("prompt", _Payload)

    call = models.generate_calls[0]
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is _Payload
    # Grounded answering wants the same answer for the same evidence.
    assert config.temperature == 0.0
    assert call["contents"] == "prompt"


async def test_generate_json_rejects_a_malformed_payload(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    """Not transient: the same prompt against the same model should not be retried
    blindly. Phase 3 retries once and then falls back."""
    models.result = SimpleNamespace(text='{"answerable": "yes"}')
    with pytest.raises(ProviderError) as raised:
        await provider.generate_json("prompt", _Payload)
    assert raised.value.transient is False


async def test_generate_json_rejects_an_empty_response(
    provider: GeminiProvider, models: _FakeModels
) -> None:
    """Transient, unlike a malformed payload: an empty response is what a safety
    block or a truncated stream looks like, and it may well succeed on a retry."""
    models.result = SimpleNamespace(text="")
    with pytest.raises(ProviderError) as raised:
        await provider.generate_json("prompt", _Payload)
    assert raised.value.transient is True


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_throttle_and_capacity_statuses_are_transient(status: int) -> None:
    assert _is_transient(_http_error(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_permanent(status: int) -> None:
    assert _is_transient(_http_error(status)) is False


def test_a_timeout_is_transient() -> None:
    assert _is_transient(httpx.ReadTimeout("timed out")) is True


def test_a_connection_failure_is_transient() -> None:
    assert _is_transient(httpx.ConnectError("no route to host")) is True


def test_an_unrecognised_failure_is_permanent() -> None:
    """The safe default: retrying an unknown error three times with backoff just
    turns a fast failure into a slow one."""
    assert _is_transient(ValueError("something new")) is False


def _http_error(status: int) -> Exception:
    """An exception shaped like the SDK's, which carries the status on `.code`."""
    error = Exception(f"HTTP {status}")
    error.code = status  # type: ignore[attr-defined]
    return error
