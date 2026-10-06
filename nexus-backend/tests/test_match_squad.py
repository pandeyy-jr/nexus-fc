from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.football import PlayerPosition, SquadStatus
from app.core.roles import RoleName
from app.db.models.membership import PlayerTeamMembership
from app.db.models.opponent import Opponent
from app.db.models.player import Player
from app.db.models.team import Team
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_match_context(
    client: AsyncClient, database: DatabaseFixture
) -> dict[str, UUID | str]:
    _, coach_token = await create_user(
        database, "squad-coach@example.com", RoleName.HEAD_COACH
    )
    player_user_id, player_token = await create_user(
        database, "squad-player@example.com", RoleName.PLAYER
    )
    async with database.sessions() as session:
        team = Team(
            name="Squad Test Team",
            short_name="STT",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Squad Test Opponent")
        player = Player(
            user_id=player_user_id,
            first_name="Squad",
            last_name="Player",
            date_of_birth=date(2000, 1, 1),
            preferred_position=PlayerPosition.CM,
        )
        session.add_all([team, opponent, player])
        await session.flush()
        membership = PlayerTeamMembership(
            player_id=player.id,
            team_id=team.id,
            joined_at=datetime(2026, 9, 1, tzinfo=UTC),
            squad_status=SquadStatus.ACTIVE,
        )
        session.add(membership)
        await session.commit()
        team_id = team.id
        opponent_id = opponent.id
        player_id = player.id

    response = await client.post(
        "/api/v1/matches",
        json={
            "team_id": str(team_id),
            "opponent_id": str(opponent_id),
            "scheduled_at": "2026-10-01T15:00:00Z",
            "home_away": "HOME",
        },
        headers=bearer(str(coach_token)),
    )
    assert response.status_code == 201
    return {
        "coach_token": coach_token,
        "player_token": player_token,
        "player_user_id": player_user_id,
        "team_id": team_id,
        "opponent_id": opponent_id,
        "player_id": player_id,
        "match_id": UUID(response.json()["id"]),
    }


@pytest.mark.asyncio
async def test_match_squad_create_retrieve_duplicate_and_invalid_membership(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    coach_token = str(context["coach_token"])
    player_id = str(context["player_id"])

    payload = {
        "player_id": player_id,
        "squad_status": "STARTER",
        "starting": True,
        "shirt_number": 8,
        "captain": True,
    }
    created = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json=payload,
        headers=bearer(coach_token),
    )
    assert created.status_code == 201
    assert created.json()["player_id"] == player_id
    updated = await client.patch(
        f"/api/v1/matches/{match_id}/squad/{player_id}",
        json={"shirt_number": 9},
        headers=bearer(coach_token),
    )
    assert updated.status_code == 200
    assert updated.json()["shirt_number"] == 9

    squad = await client.get(
        f"/api/v1/matches/{match_id}/squad", headers=bearer(coach_token)
    )
    assert squad.status_code == 200
    assert [entry["player_id"] for entry in squad.json()] == [player_id]

    player_cannot_manage = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={"player_id": player_id},
        headers=bearer(str(context["player_token"])),
    )
    assert player_cannot_manage.status_code == 403

    duplicate = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json=payload,
        headers=bearer(coach_token),
    )
    assert duplicate.status_code == 409
    removed = await client.delete(
        f"/api/v1/matches/{match_id}/squad/{player_id}",
        headers=bearer(coach_token),
    )
    assert removed.status_code == 204
    empty_squad = await client.get(
        f"/api/v1/matches/{match_id}/squad", headers=bearer(coach_token)
    )
    assert empty_squad.json() == []

    async with database.sessions() as session:
        unassigned = Player(
            first_name="Unassigned",
            last_name="Player",
            date_of_birth=date(2001, 1, 1),
            preferred_position=PlayerPosition.ST,
        )
        session.add(unassigned)
        await session.flush()
        session.add(
            PlayerTeamMembership(
                player_id=unassigned.id,
                team_id=context["team_id"],
                joined_at=datetime(2026, 6, 1, tzinfo=UTC),
                left_at=datetime(2026, 9, 1, tzinfo=UTC),
                squad_status=SquadStatus.INACTIVE,
            )
        )
        await session.commit()
        unassigned_id = unassigned.id
        previous_left_at = datetime(2026, 9, 1, tzinfo=UTC)

    invalid_membership = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={"player_id": str(unassigned_id)},
        headers=bearer(coach_token),
    )
    assert invalid_membership.status_code == 409
    async with database.sessions() as session:
        membership = await session.scalar(
            select(PlayerTeamMembership).where(
                PlayerTeamMembership.player_id == unassigned_id
            )
        )
        assert membership is not None
        assert membership.left_at == previous_left_at


@pytest.mark.asyncio
async def test_participation_is_unique_and_player_access_is_self_scoped(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    player_id = str(context["player_id"])
    coach_token = str(context["coach_token"])
    player_token = str(context["player_token"])

    to_live = await client.patch(
        f"/api/v1/matches/{match_id}",
        json={"status": "LIVE"},
        headers=bearer(coach_token),
    )
    assert to_live.status_code == 200
    not_in_squad = await client.post(
        f"/api/v1/matches/{match_id}/squad/{UUID(int=0)}/participation",
        json={"minutes_played": 45},
        headers=bearer(coach_token),
    )
    assert not_in_squad.status_code == 404
    added = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={
            "player_id": player_id,
            "squad_status": "STARTER",
            "starting": True,
        },
        headers=bearer(coach_token),
    )
    assert added.status_code == 201

    participation_url = f"/api/v1/matches/{match_id}/squad/{player_id}/participation"
    participation_payload = {
        "started_at_minute": 0,
        "ended_at_minute": 70,
        "minutes_played": 70,
    }
    created = await client.post(
        participation_url,
        json=participation_payload,
        headers=bearer(coach_token),
    )
    assert created.status_code == 201
    duplicate = await client.post(
        participation_url,
        json=participation_payload,
        headers=bearer(coach_token),
    )
    assert duplicate.status_code == 409
    invalid_update = await client.patch(
        participation_url,
        json={"started_at_minute": 80},
        headers=bearer(coach_token),
    )
    assert invalid_update.status_code == 422
    updated = await client.patch(
        participation_url,
        json={"minutes_played": 65},
        headers=bearer(coach_token),
    )
    assert updated.status_code == 200

    own_record = await client.get(participation_url, headers=bearer(player_token))
    assert own_record.status_code == 200
    assert own_record.json()["minutes_played"] == 65
    own_squad = await client.get(
        f"/api/v1/matches/{match_id}/squad", headers=bearer(player_token)
    )
    assert own_squad.status_code == 200
    assert len(own_squad.json()) == 1

    _, other_player_token = await create_user(
        database, "other-squad-player@example.com", RoleName.PLAYER
    )
    hidden_record = await client.get(
        participation_url, headers=bearer(other_player_token)
    )
    assert hidden_record.status_code == 404

    cannot_remove_history = await client.delete(
        f"/api/v1/matches/{match_id}/squad/{player_id}",
        headers=bearer(coach_token),
    )
    assert cannot_remove_history.status_code == 409


@pytest.mark.asyncio
async def test_match_squad_rbac_and_missing_resources(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    _, analyst_token = await create_user(
        database, "squad-analyst@example.com", RoleName.ANALYST
    )

    visible = await client.get(
        f"/api/v1/matches/{match_id}/squad", headers=bearer(analyst_token)
    )
    assert visible.status_code == 200
    forbidden = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={"player_id": str(context["player_id"])},
        headers=bearer(analyst_token),
    )
    assert forbidden.status_code == 403

    missing_match = await client.get(
        f"/api/v1/matches/{UUID(int=0)}/squad",
        headers=bearer(str(context["coach_token"])),
    )
    assert missing_match.status_code == 404
    missing_player = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={"player_id": str(UUID(int=0))},
        headers=bearer(str(context["coach_token"])),
    )
    assert missing_player.status_code == 404
