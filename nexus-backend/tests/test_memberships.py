from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_squad(
    client: AsyncClient,
    database: DatabaseFixture,
    player_email: str = "player@example.com",
) -> tuple[str, str, str, str, str]:
    _, head_token = await create_user(database, "head@example.com", RoleName.HEAD_COACH)
    player_user_id, player_token = await create_user(database, player_email)
    player_response = await client.post(
        "/api/v1/players",
        headers=bearer(head_token),
        json={
            "user_id": str(player_user_id),
            "first_name": "Jamie",
            "last_name": "Winger",
            "date_of_birth": "2001-02-03",
            "preferred_position": "RW",
        },
    )
    team_response = await client.post(
        "/api/v1/teams",
        headers=bearer(head_token),
        json={
            "name": "First Team",
            "short_name": "FT",
            "age_group": "Senior",
            "gender_category": "Men",
            "season": "2026/27",
        },
    )
    assert player_response.status_code == 201, player_response.text
    assert team_response.status_code == 201, team_response.text
    return (
        head_token,
        player_token,
        player_response.json()["id"],
        team_response.json()["id"],
        str(player_user_id),
    )


@pytest.mark.asyncio
async def test_membership_duplicate_end_and_history_are_preserved(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    head_token, _, player_id, team_id, _ = await create_squad(client, database)
    headers = bearer(head_token)
    path = f"/api/v1/teams/{team_id}/players/{player_id}"

    created = await client.post(path, headers=headers, json={})
    duplicate = await client.post(path, headers=headers, json={})
    assert created.status_code == 201, created.text
    assert created.json()["player"]["first_name"] == "Jamie"
    assert duplicate.status_code == 409

    loaned = await client.patch(path, headers=headers, json={"squad_status": "LOANED"})
    ended = await client.delete(path, headers=headers)
    current = await client.get(f"/api/v1/teams/{team_id}/players", headers=headers)
    history = await client.get(
        f"/api/v1/teams/{team_id}/players?include_history=true", headers=headers
    )
    historical_update = await client.patch(
        path, headers=headers, json={"squad_status": "ACTIVE"}
    )

    assert loaned.status_code == 200 and loaned.json()["squad_status"] == "LOANED"
    assert ended.status_code == 200 and ended.json()["left_at"] is not None
    assert ended.json()["squad_status"] == "INACTIVE"
    assert current.status_code == 200 and current.json() == []
    assert history.status_code == 200 and len(history.json()) == 1
    assert historical_update.status_code == 409

    rejoined = await client.post(path, headers=headers, json={})
    assert rejoined.status_code == 201
    all_history = await client.get(
        f"/api/v1/teams/{team_id}/players?include_history=true", headers=headers
    )
    assert len(all_history.json()) == 2


@pytest.mark.asyncio
async def test_membership_requires_existing_player_and_team_and_valid_dates(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    head_token, _, player_id, team_id, _ = await create_squad(client, database)
    headers = bearer(head_token)
    missing_player = await client.post(
        f"/api/v1/teams/{team_id}/players/{uuid4()}", headers=headers, json={}
    )
    missing_team = await client.post(
        f"/api/v1/teams/{uuid4()}/players/{player_id}", headers=headers, json={}
    )
    invalid_status = await client.post(
        f"/api/v1/teams/{team_id}/players/{player_id}",
        headers=headers,
        json={"squad_status": "PROMOTED"},
    )
    invalid_dates = await client.post(
        f"/api/v1/teams/{team_id}/players/{player_id}",
        headers=headers,
        json={
            "joined_at": "2025-02-02T00:00:00Z",
            "left_at": "2025-02-01T00:00:00Z",
        },
    )

    assert missing_player.status_code == 404
    assert missing_team.status_code == 404
    assert invalid_status.status_code == 422
    assert invalid_dates.status_code == 422

    created = await client.post(
        f"/api/v1/teams/{team_id}/players/{player_id}", headers=headers, json={}
    )
    null_status = await client.patch(
        f"/api/v1/teams/{team_id}/players/{player_id}",
        headers=headers,
        json={"squad_status": None},
    )
    assert created.status_code == 201
    assert null_status.status_code == 422


@pytest.mark.asyncio
async def test_player_cannot_manage_memberships_and_only_sees_own_roster_row(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    head_token, player_token, player_id, team_id, _ = await create_squad(
        client, database
    )
    other_user_id, _ = await create_user(database, "other-account@example.com")
    other_profile = await client.post(
        "/api/v1/players",
        headers=bearer(head_token),
        json={
            "user_id": str(other_user_id),
            "first_name": "Other",
            "last_name": "Player",
            "date_of_birth": "2002-01-01",
            "preferred_position": "CM",
        },
    )
    assert other_profile.status_code == 201, other_profile.text
    other_player_id = other_profile.json()["id"]
    admin_headers = bearer(head_token)
    own_path = f"/api/v1/teams/{team_id}/players/{player_id}"
    other_path = f"/api/v1/teams/{team_id}/players/{other_player_id}"
    await client.post(own_path, headers=admin_headers, json={})
    await client.post(other_path, headers=admin_headers, json={})

    visible_roster = await client.get(
        f"/api/v1/teams/{team_id}/players", headers=bearer(player_token)
    )
    add = await client.post(own_path, headers=bearer(player_token), json={})
    modify = await client.patch(
        own_path,
        headers=bearer(player_token),
        json={"squad_status": "INACTIVE"},
    )
    remove = await client.delete(own_path, headers=bearer(player_token))

    assert visible_roster.status_code == 200
    assert [row["player_id"] for row in visible_roster.json()] == [player_id]
    assert add.status_code == 403
    assert modify.status_code == 403
    assert remove.status_code == 403


@pytest.mark.asyncio
async def test_profiles_and_teams_with_membership_history_cannot_be_deleted(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    head_token, _, player_id, team_id, _ = await create_squad(client, database)
    path = f"/api/v1/teams/{team_id}/players/{player_id}"
    created = await client.post(path, headers=bearer(head_token), json={})
    assert created.status_code == 201

    _, director_token = await create_user(
        database, "director@example.com", RoleName.DIRECTOR
    )
    player_delete = await client.delete(
        f"/api/v1/players/{player_id}", headers=bearer(director_token)
    )
    team_delete = await client.delete(
        f"/api/v1/teams/{team_id}", headers=bearer(director_token)
    )

    assert player_delete.status_code == 409
    assert team_delete.status_code == 409
