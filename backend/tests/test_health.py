"""Health endpoint and the shared error shape."""

from __future__ import annotations

import httpx


async def test_health_reports_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "local"
    assert body["version"]


async def test_unknown_route_uses_the_shared_error_shape(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/no-such-route")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "not_found"
    assert body["detail"]


async def test_wrong_method_uses_the_shared_error_shape(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/health")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
