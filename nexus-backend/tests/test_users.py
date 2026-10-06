from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_can_list_and_read_safe_user_profiles(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)
    player_id, _ = await create_user(database, "player@example.com")

    listing = await client.get("/api/v1/users", headers=bearer(admin_token))
    profile = await client.get(
        f"/api/v1/users/{player_id}", headers=bearer(admin_token)
    )

    assert listing.status_code == 200
    assert len(listing.json()) == 2
    assert "hashed_password" not in listing.text
    assert profile.status_code == 200
    assert profile.json()["id"] == str(player_id)
    assert profile.json()["role"]["name"] == RoleName.PLAYER
    assert "hashed_password" not in profile.text


@pytest.mark.asyncio
async def test_admin_endpoints_distinguish_401_and_403(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, player_token = await create_user(database, "player@example.com")

    unauthenticated = await client.get("/api/v1/users")
    wrong_role = await client.get("/api/v1/users", headers=bearer(player_token))

    assert unauthenticated.status_code == 401
    assert wrong_role.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_update_role_and_invalid_roles_are_rejected(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)
    player_id, _ = await create_user(database, "player@example.com")

    invalid = await client.patch(
        f"/api/v1/users/{player_id}/role",
        headers=bearer(admin_token),
        json={"role": "COACH"},
    )
    updated = await client.patch(
        f"/api/v1/users/{player_id}/role",
        headers=bearer(admin_token),
        json={"role": RoleName.ANALYST},
    )

    assert invalid.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["role"]["name"] == RoleName.ANALYST
    assert "hashed_password" not in updated.text


@pytest.mark.asyncio
async def test_admin_can_activate_and_deactivate_users(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)
    player_id, player_token = await create_user(
        database, "inactive@example.com", is_active=False
    )

    inactive_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "secure-password-123"},
    )
    inactive_response = await client.get(
        "/api/v1/auth/me", headers=bearer(player_token)
    )
    activated = await client.patch(
        f"/api/v1/users/{player_id}/status",
        headers=bearer(admin_token),
        json={"is_active": True},
    )
    active_response = await client.get("/api/v1/auth/me", headers=bearer(player_token))
    deactivated = await client.patch(
        f"/api/v1/users/{player_id}/status",
        headers=bearer(admin_token),
        json={"is_active": False},
    )
    inactive_again = await client.get("/api/v1/auth/me", headers=bearer(player_token))

    assert inactive_login.status_code == 401
    assert inactive_response.status_code == 401
    assert activated.status_code == 200 and activated.json()["is_active"] is True
    assert active_response.status_code == 200
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    assert inactive_again.status_code == 401


@pytest.mark.asyncio
async def test_admin_self_lockout_and_last_admin_are_prevented(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    admin_id, admin_token = await create_user(
        database, "only-admin@example.com", RoleName.ADMIN
    )

    deactivate_self = await client.patch(
        f"/api/v1/users/{admin_id}/status",
        headers=bearer(admin_token),
        json={"is_active": False},
    )
    demote_self = await client.patch(
        f"/api/v1/users/{admin_id}/role",
        headers=bearer(admin_token),
        json={"role": RoleName.PLAYER},
    )
    still_admin = await client.get("/api/v1/users", headers=bearer(admin_token))

    assert deactivate_self.status_code == 409
    assert demote_self.status_code == 409
    assert still_admin.status_code == 200


@pytest.mark.asyncio
async def test_nonexistent_user_returns_404(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)

    response = await client.get(f"/api/v1/users/{uuid4()}", headers=bearer(admin_token))

    assert response.status_code == 404
