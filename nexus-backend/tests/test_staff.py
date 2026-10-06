import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_staff_crud_uses_an_existing_user_account(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, head_token = await create_user(database, "head@example.com", RoleName.HEAD_COACH)
    analyst_id, _ = await create_user(database, "analyst@example.com", RoleName.ANALYST)
    headers = bearer(head_token)
    created = await client.post(
        "/api/v1/staff",
        headers=headers,
        json={
            "user_id": str(analyst_id),
            "first_name": "Sam",
            "last_name": "Analyst",
            "job_title": "Performance Analyst",
            "department": "First Team",
        },
    )
    assert created.status_code == 201, created.text
    staff_id = created.json()["id"]
    assert created.json()["user_id"] == str(analyst_id)
    assert "hashed_password" not in created.text

    listing = await client.get("/api/v1/staff", headers=headers)
    profile = await client.get(f"/api/v1/staff/{staff_id}", headers=headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert profile.status_code == 200

    updated = await client.patch(
        f"/api/v1/staff/{staff_id}",
        headers=headers,
        json={"job_title": "Lead Analyst"},
    )
    null_job_title = await client.patch(
        f"/api/v1/staff/{staff_id}", headers=headers, json={"job_title": None}
    )
    assert updated.status_code == 200
    assert updated.json()["job_title"] == "Lead Analyst"
    assert null_job_title.status_code == 422

    deleted = await client.delete(f"/api/v1/staff/{staff_id}", headers=headers)
    missing = await client.get(f"/api/v1/staff/{staff_id}", headers=headers)
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@example.com", "password": "secure-password-123"},
    )
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_player_cannot_view_or_create_staff_profiles(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    player_id, player_token = await create_user(database, "player@example.com")
    response = await client.post(
        "/api/v1/staff",
        headers=bearer(player_token),
        json={
            "user_id": str(player_id),
            "first_name": "Player",
            "last_name": "Account",
            "job_title": "Head Coach",
        },
    )
    listing = await client.get("/api/v1/staff", headers=bearer(player_token))

    assert response.status_code == 403
    assert listing.status_code == 403


@pytest.mark.asyncio
async def test_staff_requires_an_existing_non_player_user_and_unique_link(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)
    player_id, _ = await create_user(database, "player@example.com")
    body = {
        "user_id": str(player_id),
        "first_name": "Player",
        "last_name": "Account",
        "job_title": "Coach",
    }
    player_account = await client.post(
        "/api/v1/staff", headers=bearer(admin_token), json=body
    )
    missing_user = await client.post(
        "/api/v1/staff",
        headers=bearer(admin_token),
        json={**body, "user_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert player_account.status_code == 422
    assert missing_user.status_code == 404

    analyst_id, _ = await create_user(database, "analyst@example.com", RoleName.ANALYST)
    valid_body = {**body, "user_id": str(analyst_id)}
    first = await client.post(
        "/api/v1/staff", headers=bearer(admin_token), json=valid_body
    )
    duplicate = await client.post(
        "/api/v1/staff", headers=bearer(admin_token), json=valid_body
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
