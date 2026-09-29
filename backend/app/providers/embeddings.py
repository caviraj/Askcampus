"""Embedding provider interface.

Services depend on this Protocol, never on a vendor SDK. The implementation is
app/providers/gemini.py; tests use a fake, so the suite runs offline.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int:
        """Vector width. Must match vector(768) in the chunks table."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input, in order."""
        ...
