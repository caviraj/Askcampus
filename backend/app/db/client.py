"""Supabase client lifecycle.

Uses supabase-py's native async client, whose .table() and .rpc() are genuinely
async over httpx. That is preferable to wrapping the synchronous client in a
threadpool: less code, and .rpc() being async is what Phase 3 needs for
hybrid_search.
"""

from __future__ import annotations

import logging

from supabase import AsyncClient, create_async_client

from app.config import Settings

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when the client is used before startup or after shutdown."""


async def init_db_client(settings: Settings) -> AsyncClient:
    """Construct the process-wide client. No network call happens here."""
    global _client
    if _client is None:
        _client = await create_async_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        logger.info("Supabase client initialised for %s", settings.supabase_url)
    return _client


def get_db_client() -> AsyncClient:
    if _client is None:
        raise DatabaseUnavailableError("The database client is not initialised.")
    return _client


async def close_db_client() -> None:
    """Close the sub-clients' HTTP transports.

    supabase-py 2.31.0's AsyncClient exposes no close()/aclose() of its own, so
    the httpx transports are closed through the sub-clients. `auth` and
    `realtime` are built eagerly in __init__; `postgrest` is built on the first
    .table()/.rpc() call and kept in a private slot -- reading that slot via
    getattr avoids *creating* a postgrest client purely in order to close it.
    `storage` and `functions` are lazy and untouched in Phase 1; Phase 2 closes
    storage when uploads arrive.

    Failures here are logged, not raised: a shutdown error must not mask the
    real exit status.
    """
    global _client
    client, _client = _client, None
    if client is None:
        return

    sub_clients = (client.auth, client.realtime, getattr(client, "_postgrest", None))
    for sub in sub_clients:
        if sub is None:
            continue
        close = getattr(sub, "aclose", None) or getattr(sub, "close", None)
        if close is None:
            continue
        try:
            await close()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.warning("Failed to close a Supabase sub-client", exc_info=True)
