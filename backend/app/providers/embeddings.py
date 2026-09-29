"""Embedding provider interface.

No implementation yet: the Gemini provider arrives in Phase 2 with ingestion.
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
