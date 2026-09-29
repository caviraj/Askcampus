"""Auth-related response models."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Application roles live in public.profiles.role. Note this is NOT the JWT `role`
# claim, which Supabase sets to "authenticated" for every signed-in user.
Role = Literal["staff", "admin"]


class Profile(BaseModel):
    """Mirrors a row in public.profiles."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    full_name: str | None = None
    role: Role


class AdminUser(BaseModel):
    """A Profile already narrowed to an admin.

    The role field is pinned to the literal so a caller cannot construct this
    from a staff profile: the type system carries the authorization decision.
    """

    id: UUID
    full_name: str | None = None
    role: Literal["admin"] = "admin"
