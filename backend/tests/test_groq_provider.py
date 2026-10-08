"""Tests for the Groq LLM provider.

Validates request shaping, schema injection, error wrapping, retries with model fallback,
and cleanup. All tests use httpx.MockTransport so no external network requests are made.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.providers.errors import ProviderError
from app.providers.groq import GroqProvider


class _SampleSchema(BaseModel):
    answerable: bool
    answer: str


def _make_settings(**kwargs: Any) -> Settings:
    defaults: dict[str, Any] = {
        "supabase_url": "https://example.supabase.co",
        "supabase_service_role_key": "dummy-service-role-key",
        "gemini_api_key": "dummy-gemini-key",
        "groq_api_key": SecretStr("gsk_test_key_12345"),
        "groq_model": "primary-model",
        "groq_fallback_models": ["fallback-model"],
        "llm_max_retries": 1,
        "retry_backoff_seconds": 0.0,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_init_requires_api_key() -> None:
    settings = _make_settings(groq_api_key=None)
    with pytest.raises(ValueError, match="GROQ_API_KEY is required"):
        GroqProvider(settings)


@pytest.mark.asyncio
async def test_generate_json_success() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "primary-model"
        assert body["temperature"] == 0.0
        assert body["response_format"] == {"type": "json_object"}
        assert len(body["messages"]) == 2
        assert body["messages"][1]["content"] == "What is the library timing?"

        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"answerable": True, "answer": "9 AM to 8 PM"})
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = _make_settings()
    provider = GroqProvider(settings, client=client)

    result = await provider.generate_json("What is the library timing?", _SampleSchema)

    assert result.answerable is True
    assert result.answer == "9 AM to 8 PM"
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.headers["authorization"] == "Bearer gsk_test_key_12345"
    assert req.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_generate_json_retries_transient_and_falls_back_model() -> None:
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        attempts.append(body["model"])
        if len(attempts) == 1:
            return httpx.Response(status_code=429, text="Rate limit reached")
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"answerable": True, "answer": "Fallback ok"})
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = _make_settings(
        groq_model="primary-model",
        groq_fallback_models=["fallback-model"],
        llm_max_retries=1,
    )
    provider = GroqProvider(settings, client=client)

    result = await provider.generate_json("Test prompt", _SampleSchema)

    assert result.answer == "Fallback ok"
    assert attempts == ["primary-model", "fallback-model"]


@pytest.mark.asyncio
async def test_generate_json_fails_immediately_on_non_transient_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code=401, text="Invalid API key")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = _make_settings(llm_max_retries=2)
    provider = GroqProvider(settings, client=client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_json("Prompt", _SampleSchema)

    assert not exc_info.value.transient
    assert "401" in str(exc_info.value)
    assert calls == 1


@pytest.mark.asyncio
async def test_generate_json_schema_validation_error_is_non_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {
                            # missing answer field required by _SampleSchema
                            "content": json.dumps({"answerable": True})
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = _make_settings(llm_max_retries=2)
    provider = GroqProvider(settings, client=client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_json("Prompt", _SampleSchema)

    assert not exc_info.value.transient
    assert "did not match the expected shape" in str(exc_info.value)


@pytest.mark.asyncio
async def test_generate_json_exhausts_retries_on_persistent_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=503, text="Service unavailable")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    settings = _make_settings(llm_max_retries=1)
    provider = GroqProvider(settings, client=client)

    with pytest.raises(ProviderError) as exc_info:
        await provider.generate_json("Prompt", _SampleSchema)

    assert exc_info.value.transient
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_aclose_owned_client() -> None:
    settings = _make_settings()
    provider = GroqProvider(settings)
    assert provider._owns_client
    await provider.aclose()
    assert provider._client.is_closed
