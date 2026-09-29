"""LLM provider interface.

Services depend on this Protocol, never on a vendor SDK, so the model can be
swapped without touching business logic. The implementation is
app/providers/gemini.py; it is exercised in Phase 3, when answering arrives.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class LLMProvider(Protocol):
    async def generate_json(self, prompt: str, schema: type[ResponseT]) -> ResponseT:
        """Generate a response constrained to `schema`.

        Implementations must ask the model for JSON and validate it against
        `schema` before returning, so callers never parse raw text.
        """
        ...
