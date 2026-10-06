from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def player_payload(**changes: object) -> dict[str, object]:
    return {
        "first_name": "Alex",
        "last_name": "Striker",
        "date_of_birth": "2000-05-12",
        "nationality": "England",
        "preferred_position": "ST",
        "secondary_position": "LW",
        "squad_number": 9,
        "dominant_foot": "RIGHT",
        "height_cm": 183,
        "weight_kg": 78.5,
        **changes,
    }


@pytest.mark.asyncio
async def test_head_coach_can_create_list_get_update_and_delete_player(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    _, admin_token = await create_user(database, "admin@example.com", RoleName.ADMIN)
    headers = bearer(coach_token)
    created = await client.post(
        "/api/v1/players", headers=headers, json=player_payload()
    )
    assert created.status_code == 201, created.text
    player_id = created.json()["id"]
    assert created.json()["status"] == "ACTIVE"
    assert "hashed_password" not in created.text

    duplicate_position = await client.patch(
        f"/api/v1/players/{player_id}",
        headers=headers,
        json={"preferred_position": "LW"},
    )
    assert duplicate_position.status_code == 422

    listing = await client.get("/api/v1/players", headers=headers)
    profile = await client.get(f"/api/v1/players/{player_id}", headers=headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert profile.status_code == 200
    assert profile.json()["preferred_position"] == "ST"

    updated = await client.patch(
        f"/api/v1/players/{player_id}",
        headers=headers,
        json={"preferred_position": "CF", "status": "SUSPENDED"},
    )
    assert updated.status_code == 200
    assert updated.json()["preferred_position"] == "CF"
    assert updated.json()["status"] == "SUSPENDED"

    deleted = await client.delete(
        f"/api/v1/players/{player_id}", headers=bearer(admin_token)
    )
    missing = await client.get(f"/api/v1/players/{player_id}", headers=headers)
    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_player_creation_requires_authorized_role(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, player_token = await create_user(database, "player@example.com")
    response = await client.post(
        "/api/v1/players",
        headers=bearer(player_token),
        json=player_payload(),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_player_validation_rejects_invalid_position_status_and_date(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    headers = bearer(coach_token)
    invalid_position = await client.post(
        "/api/v1/players",
        headers=headers,
        json=player_payload(preferred_position="GOALKEEPER"),
    )
    invalid_status = await client.post(
        "/api/v1/players",
        headers=headers,
        json=player_payload(status="INJURED"),
    )
    future_dob = await client.post(
        "/api/v1/players",
        headers=headers,
        json=player_payload(
            date_of_birth=(date.today() + timedelta(days=1)).isoformat()
        ),
    )
    out_of_range_number = await client.post(
        "/api/v1/players",
        headers=headers,
        json=player_payload(squad_number=100),
    )

    assert invalid_position.status_code == 422
    assert invalid_status.status_code == 422
    assert future_dob.status_code == 422
    assert out_of_range_number.status_code == 422


@pytest.mark.asyncio
async def test_linked_player_account_is_unique_and_must_have_player_role(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    player_user_id, _ = await create_user(database, "athlete@example.com")
    analyst_user_id, _ = await create_user(
        database, "analyst@example.com", RoleName.ANALYST
    )

    first = await client.post(
        "/api/v1/players",
        headers=bearer(coach_token),
        json=player_payload(user_id=str(player_user_id)),
    )
    duplicate = await client.post(
        "/api/v1/players",
        headers=bearer(coach_token),
        json=player_payload(
            first_name="Second", user_id=str(player_user_id), squad_number=10
        ),
    )
    wrong_role = await client.post(
        "/api/v1/players",
        headers=bearer(coach_token),
        json=player_payload(user_id=str(analyst_user_id)),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert wrong_role.status_code == 422


@pytest.mark.asyncio
async def test_player_can_only_list_and_view_own_profile(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    player_user_id, player_token = await create_user(database, "athlete@example.com")
    own_player = await client.post(
        "/api/v1/players",
        headers=bearer(coach_token),
        json=player_payload(user_id=str(player_user_id)),
    )
    other_player = await client.post(
        "/api/v1/players", headers=bearer(coach_token), json=player_payload()
    )
    own_id = own_player.json()["id"]
    other_id = other_player.json()["id"]

    listing = await client.get("/api/v1/players", headers=bearer(player_token))
    own_profile = await client.get(
        f"/api/v1/players/{own_id}", headers=bearer(player_token)
    )
    other_profile = await client.get(
        f"/api/v1/players/{other_id}", headers=bearer(player_token)
    )

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [own_id]
    assert own_profile.status_code == 200
    assert other_profile.status_code == 404


@pytest.mark.asyncio
async def test_player_cannot_patch_even_own_protected_profile_fields(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    player_user_id, player_token = await create_user(database, "athlete@example.com")
    created = await client.post(
        "/api/v1/players",
        headers=bearer(coach_token),
        json=player_payload(user_id=str(player_user_id)),
    )

    response = await client.patch(
        f"/api/v1/players/{created.json()['id']}",
        headers=bearer(player_token),
        json={"first_name": "Changed"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_assistant_coach_can_update_football_fields_not_identity(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, head_token = await create_user(database, "head@example.com", RoleName.HEAD_COACH)
    _, assistant_token = await create_user(
        database, "assistant@example.com", RoleName.ASSISTANT_COACH
    )
    created = await client.post(
        "/api/v1/players", headers=bearer(head_token), json=player_payload()
    )
    player_id = created.json()["id"]

    allowed = await client.patch(
        f"/api/v1/players/{player_id}",
        headers=bearer(assistant_token),
        json={"squad_number": 17},
    )
    denied = await client.patch(
        f"/api/v1/players/{player_id}",
        headers=bearer(assistant_token),
        json={"first_name": "Changed"},
    )

    assert allowed.status_code == 200
    assert allowed.json()["squad_number"] == 17
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_invalid_player_id_returns_422(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )

    response = await client.get(
        "/api/v1/players/not-a-uuid", headers=bearer(coach_token)
    )

    assert response.status_code == 422
