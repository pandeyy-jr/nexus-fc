import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "nexus-backend",
        "version": "0.1.0",
    }


@pytest.mark.asyncio
async def test_database_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_info(client: AsyncClient) -> None:
    response = await client.get("/api/v1/info")

    assert response.status_code == 200
    assert response.json() == {
        "name": "TACTUSBALL Backend",
        "version": "0.1.0",
        "environment": "test",
        "api_version": "v1",
    }
