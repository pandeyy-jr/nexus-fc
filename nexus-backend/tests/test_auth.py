from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import verify_password
from app.db.models.user import User
from tests.conftest import DatabaseFixture

credentials = {
    "email": "coach@example.com",
    "full_name": "Alex Coach",
    "password": "secure-password-123",
}


@pytest.mark.asyncio
async def test_registration_normalizes_email_and_returns_safe_user(
    client: AsyncClient,
) -> None:
    payload = {**credentials, "email": "  Coach@Example.COM "}
    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201
    result = response.json()
    assert result["user"]["email"] == "coach@example.com"
    assert result["user"]["full_name"] == "Alex Coach"
    assert result["user"]["role"]["name"] == "PLAYER"
    created_at = datetime.fromisoformat(result["user"]["created_at"])
    updated_at = datetime.fromisoformat(result["user"]["updated_at"])
    assert created_at.utcoffset() == timedelta(0)
    assert updated_at.utcoffset() == timedelta(0)
    assert "hashed_password" not in response.text
    assert credentials["password"] not in response.text


@pytest.mark.asyncio
async def test_registration_stores_only_a_password_hash(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    response = await client.post("/api/v1/auth/register", json=credentials)
    assert response.status_code == 201

    async with database.sessions() as session:
        user = await session.scalar(
            select(User).where(User.email == credentials["email"])
        )
        assert user is not None
        assert user.hashed_password != credentials["password"]
        assert verify_password(credentials["password"], user.hashed_password)


@pytest.mark.asyncio
async def test_duplicate_registration_returns_conflict(client: AsyncClient) -> None:
    first = await client.post("/api/v1/auth/register", json=credentials)
    duplicate = await client.post("/api/v1/auth/register", json=credentials)

    assert first.status_code == 201
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_registration_rejects_role_overposting(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={**credentials, "role": "ADMIN"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registration_rejects_short_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={**credentials, "password": "short"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_and_me_return_safe_user(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=credentials)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert "hashed_password" not in login.text

    current_user = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["email"] == credentials["email"]
    assert current_user.json()["full_name"] == credentials["full_name"]
    assert "hashed_password" not in current_user.text


@pytest.mark.asyncio
async def test_invalid_password_and_unknown_email_are_generic_401(
    client: AsyncClient,
) -> None:
    await client.post("/api/v1/auth/register", json=credentials)
    invalid_password = await client.post(
        "/api/v1/auth/login",
        json={"email": credentials["email"], "password": "incorrect-password-123"},
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": credentials["password"]},
    )

    assert invalid_password.status_code == 401
    assert unknown_email.status_code == 401
    assert invalid_password.json() == unknown_email.json()


@pytest.mark.asyncio
async def test_me_rejects_missing_and_malformed_tokens(client: AsyncClient) -> None:
    missing = await client.get("/api/v1/auth/me")
    malformed = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert missing.status_code == 401
    assert malformed.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_expired_token(client: AsyncClient) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_unknown_subject(client: AsyncClient) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(uuid4()), "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
