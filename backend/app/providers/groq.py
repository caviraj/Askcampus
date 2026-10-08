"""Groq implementation of the LLM provider interface.

Communicates with Groq's OpenAI-compatible chat completions endpoint over httpx.
Services depend on the LLMProvider Protocol, so Groq can be swapped with Gemini
or other providers without touching business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from app.providers.errors import ProviderError
from app.providers.llm import ResponseT

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# HTTP statuses worth retrying. 429 and the 5xx family are capacity or throttle
# responses; the 4xx family generally is not.
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Grounded question answering wants deterministic responses for the same evidence.
_TEMPERATURE = 0.0


class GroqProvider:
    """JSON generation over Groq's completions API.

    Implements `LLMProvider`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is required to initialize GroqProvider.")

        self._settings = settings
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(timeout=settings.provider_timeout_seconds)
            self._owns_client = True

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def generate_json(self, prompt: str, schema: type[ResponseT]) -> ResponseT:
        """Generate a structured response conforming to `schema`.

        Retries on transient errors (rate limit, gateway timeout, 5xx), falling
        back across models in `settings.groq_fallback_models`.
        """
        models = [self._settings.groq_model, *self._settings.groq_fallback_models]

        for attempt in range(self._settings.llm_max_retries + 1):
            model = models[min(attempt, len(models) - 1)]
            try:
                return await self._generate_once(prompt, schema, model=model)
            except ProviderError as exc:
                last_attempt = attempt >= self._settings.llm_max_retries
                if not exc.transient or last_attempt:
                    raise

                following = models[min(attempt + 1, len(models) - 1)]
                delay = self._settings.retry_backoff_seconds * (2**attempt)
                logger.warning(
                    "Groq generation with %s failed, retrying with %s in %.1fs (%d of %d): %s",
                    model,
                    following,
                    delay,
                    attempt + 1,
                    self._settings.llm_max_retries,
                    exc,
                )
                await asyncio.sleep(delay)

        raise ProviderError("The model could not be reached.", transient=True)

    async def _generate_once(
        self, prompt: str, schema: type[ResponseT], *, model: str
    ) -> ResponseT:
        """Single generation attempt without retries."""
        api_key = self._settings.groq_api_key.get_secret_value()  # type: ignore[union-attr]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        schema_json = json.dumps(schema.model_json_schema())
        system_content = (
            "You are a helpful assistant. You must respond with valid JSON "
            f"that conforms to this JSON Schema:\n{schema_json}"
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": _TEMPERATURE,
        }

        try:
            response = await self._client.post(
                _GROQ_API_URL,
                headers=headers,
                json=payload,
            )
        except Exception as exc:  # noqa: BLE001
            raise _wrap(exc, "generation") from exc

        if response.status_code != 200:
            is_transient = response.status_code in _TRANSIENT_STATUS
            msg = f"Groq API returned status {response.status_code}: {response.text}"
            raise ProviderError(msg, transient=is_transient)

        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("Groq response was not valid JSON.", transient=True) from exc

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise ProviderError("The model returned no choices.", transient=True)

        content = choices[0].get("message", {}).get("content")
        if not content:
            raise ProviderError("The model returned no content.", transient=True)

        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            # Not transient: the same prompt produced non-conforming JSON
            raise ProviderError(
                "The model returned JSON that did not match the expected shape.",
                transient=False,
            ) from exc


def _wrap(exc: Exception, action: str) -> ProviderError:
    return ProviderError(
        f"The {action} request to Groq failed: {exc}",
        transient=_is_transient(exc),
    )


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
