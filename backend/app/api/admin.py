"""Admin routes.

require_admin is attached at the router level so that a route added here is
protected by construction rather than by remembering to add the dependency.
test_admin_route_protection.py asserts this holds for every /admin path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth_deps import require_admin
from app.schemas.auth import AdminUser

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/me", response_model=AdminUser, summary="Who am I")
async def read_current_admin(
    admin: Annotated[AdminUser, Depends(require_admin)],
) -> AdminUser:
    """Return the signed-in admin.

    Doubles as the endpoint the admin UI uses to confirm a session is valid.
    """
    return admin
