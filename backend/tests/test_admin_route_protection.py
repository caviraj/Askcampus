"""Guardrail: no /admin route may be reachable without the admin gate.

This walks the app's real routing table rather than trusting that whoever adds
the next admin route remembers the dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.auth_deps import require_admin


def _depends_on(dependant: Any, target: Any) -> bool:
    """Recursively look for `target` in a route's dependency tree."""
    for sub in getattr(dependant, "dependencies", []):
        if sub.call is target:
            return True
        if _depends_on(sub, target):
            return True
    return False


def _iter_api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Yield every APIRoute, descending into included routers.

    FastAPI 0.141 no longer flattens `include_router` results into app.routes:
    each inclusion stays a wrapper object holding the original router. Older
    versions list the routes directly. Duck-typing on `original_router` handles
    both, so this guardrail does not silently stop finding routes if the
    internal class is renamed or the behaviour changes back.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _iter_api_routes(nested.routes)


def _admin_routes(app: FastAPI) -> list[APIRoute]:
    return [route for route in _iter_api_routes(app.routes) if route.path.startswith("/admin")]


def test_the_detector_itself_works(app: FastAPI) -> None:
    """Prove the guardrail is not vacuous in either direction.

    Without this, a bug in _depends_on would make the real assertion below pass
    for the wrong reason.
    """
    admin_route = _admin_routes(app)[0]
    assert _depends_on(admin_route.dependant, require_admin) is True

    public_route = next(r for r in _iter_api_routes(app.routes) if r.path == "/health")
    assert _depends_on(public_route.dependant, require_admin) is False


def test_every_admin_route_requires_admin(app: FastAPI) -> None:
    routes = _admin_routes(app)
    assert routes, "expected the app to expose at least one /admin route"

    unprotected = [r.path for r in routes if not _depends_on(r.dependant, require_admin)]
    assert unprotected == [], f"/admin routes missing require_admin: {unprotected}"


def test_the_known_admin_route_is_covered(app: FastAPI) -> None:
    paths = {route.path for route in _admin_routes(app)}
    assert "/admin/me" in paths
