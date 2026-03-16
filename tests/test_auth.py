import pytest
from httpx import AsyncClient


async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_get_me_unauthenticated(client: AsyncClient):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_refresh_with_invalid_token(client: AsyncClient):
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "this.is.garbage"},
    )
    assert response.status_code == 401
