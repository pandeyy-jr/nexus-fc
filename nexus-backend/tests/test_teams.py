import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def team_payload(**changes: object) -> dict[str, object]:
    return {
        "name": "Development Squad",
        "short_name": "DEV",
        "age_group": "U21",
        "gender_category": "Men",
        "season": "2026/27",
        **changes,
    }


@pytest.mark.asyncio
async def test_head_coach_can_create_list_get_update_and_delete_team(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    headers = bearer(coach_token)
    created = await client.post("/api/v1/teams", headers=headers, json=team_payload())

    assert created.status_code == 201, created.text
    team_id = created.json()["id"]
    listing = await client.get("/api/v1/teams", headers=headers)
    profile = await client.get(f"/api/v1/teams/{team_id}", headers=headers)
    updated = await client.patch(
        f"/api/v1/teams/{team_id}", headers=headers, json={"season": "2027/28"}
    )
    null_season = await client.patch(
        f"/api/v1/teams/{team_id}", headers=headers, json={"season": None}
    )
    deleted = await client.delete(
        f"/api/v1/teams/{team_id}", headers=bearer(coach_token)
    )

    assert listing.status_code == 200 and len(listing.json()) == 1
    assert profile.status_code == 200
    assert updated.status_code == 200 and updated.json()["season"] == "2027/28"
    assert null_season.status_code == 422
    assert deleted.status_code == 403

    _, director_token = await create_user(
        database, "director@example.com", RoleName.DIRECTOR
    )
    deleted_by_director = await client.delete(
        f"/api/v1/teams/{team_id}", headers=bearer(director_token)
    )
    assert deleted_by_director.status_code == 204


@pytest.mark.asyncio
async def test_player_cannot_manage_teams_and_only_sees_assigned_teams(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    player_id, player_token = await create_user(database, "player@example.com")
    team = await client.post(
        "/api/v1/teams", headers=bearer(coach_token), json=team_payload()
    )
    create_team = await client.post(
        "/api/v1/teams", headers=bearer(player_token), json=team_payload(name="Other")
    )
    visible_teams = await client.get("/api/v1/teams", headers=bearer(player_token))
    hidden_team = await client.get(
        f"/api/v1/teams/{team.json()['id']}", headers=bearer(player_token)
    )
    assert create_team.status_code == 403
    assert visible_teams.status_code == 200 and visible_teams.json() == []
    assert hidden_team.status_code == 404


@pytest.mark.asyncio
async def test_team_input_validation_and_invalid_id(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "coach@example.com", RoleName.HEAD_COACH
    )
    headers = bearer(coach_token)
    invalid_name = await client.post(
        "/api/v1/teams", headers=headers, json=team_payload(name=" ")
    )
    invalid_id = await client.get("/api/v1/teams/not-a-uuid", headers=headers)

    assert invalid_name.status_code == 422
    assert invalid_id.status_code == 422
