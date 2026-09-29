"""Content hashing.

One function, used for two different things: the fingerprint of an uploaded file
(`documents.content_hash`, for duplicate detection) and the key of a chunk's text
in the embedding cache. Both want the same property -- the same input always
produces the same hex string -- so they share the implementation.
"""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes | str) -> str:
    """Hex SHA-256 of bytes, or of a string encoded as UTF-8."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()
