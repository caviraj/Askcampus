"""Data access functions.

Route handlers and services call these rather than touching the Supabase client
directly, so the query surface stays narrow and typed.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.db.client import get_db_client
from app.schemas.auth import Profile

logger = logging.getLogger(__name__)


async def fetch_profile(user_id: UUID) -> Profile | None:
    """Return the profile row for a user, or None if there is no row.

    Returns None rather than raising on a missing row: "no profile" is a normal
    outcome that the auth gate turns into a 403.
    """
    response = await (
        get_db_client()
        .table("profiles")
        .select("id,full_name,role")
        .eq("id", str(user_id))
        .maybe_single()
        .execute()
    )
    data = getattr(response, "data", None)
    if not data:
        return None
    return Profile.model_validate(data)
