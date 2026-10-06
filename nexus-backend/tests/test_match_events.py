from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.football import PlayerPosition, SquadStatus
from app.core.roles import RoleName
from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_match_squad import bearer, create_match_context


async def add_player(
    database: DatabaseFixture,
    team_id: UUID,
    name: str,
    left_at: datetime | None = None,
) -> UUID:
    async with database.sessions() as session:
        player = Player(
            first_name=name,
            last_name="Events",
            date_of_birth=date(2002, 2, 2),
            preferred_position=PlayerPosition.ST,
        )
        session.add(player)
        await session.flush()
        session.add(
            PlayerTeamMembership(
                player_id=player.id,
                team_id=team_id,
                joined_at=datetime(2026, 6, 1, tzinfo=UTC),
                left_at=left_at,
                squad_status=(
                    SquadStatus.INACTIVE if left_at is not None else SquadStatus.ACTIVE
                ),
            )
        )
        await session.commit()
        return player.id


def goal(player_id: str, minute: int = 23) -> dict[str, object]:
    return {
        "side": "HOME",
        "event_type": "GOAL",
        "minute": minute,
        "player_id": player_id,
    }


async def select_player(
    client: AsyncClient,
    match_id: UUID,
    token: str,
    player_id: UUID,
    squad_status: str,
    starting: bool,
) -> None:
    response = await client.post(
        f"/api/v1/matches/{match_id}/squad",
        json={
            "player_id": str(player_id),
            "squad_status": squad_status,
            "starting": starting,
        },
        headers=bearer(token),
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_match_event_create_retrieve_update_and_delete(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    coach = str(context["coach_token"])
    player_id = str(context["player_id"])
    player_id_value = context["player_id"]
    assert isinstance(player_id_value, UUID)
    await select_player(client, match_id, coach, player_id_value, "STARTER", True)

    created = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(player_id),
        headers=bearer(coach),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["event_type"] == "GOAL"
    assert body["player_id"] == player_id
    assert body["minute"] == 23
    assert body["own_goal"] is False
    event_id = body["id"]

    card = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json={
            "side": "HOME",
            "event_type": "YELLOW_CARD",
            "minute": 70,
            "player_id": player_id,
        },
        headers=bearer(coach),
    )
    assert card.status_code == 201
    card_id = card.json()["id"]

    fetched = await client.get(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(coach),
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == event_id

    listed = await client.get(
        f"/api/v1/matches/{match_id}/events", headers=bearer(coach)
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [event_id, card_id]

    updated = await client.patch(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        json={"minute": 24, "description": " Close range "},
        headers=bearer(coach),
    )
    assert updated.status_code == 200
    assert updated.json()["minute"] == 24
    assert updated.json()["description"] == "Close range"

    removed = await client.delete(
        f"/api/v1/matches/{match_id}/events/{card_id}",
        headers=bearer(coach),
    )
    assert removed.status_code == 204
    missing = await client.get(
        f"/api/v1/matches/{match_id}/events/{card_id}",
        headers=bearer(coach),
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_match_event_rejects_invalid_references_and_membership(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    coach = str(context["coach_token"])
    player_id = str(context["player_id"])
    player_id_value = context["player_id"]
    assert isinstance(player_id_value, UUID)
    await select_player(client, match_id, coach, player_id_value, "STARTER", True)
    departed_id = await add_player(
        database,
        context["team_id"],
        "Departed",
        left_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    missing_match = await client.post(
        f"/api/v1/matches/{UUID(int=0)}/events",
        json=goal(player_id),
        headers=bearer(coach),
    )
    assert missing_match.status_code == 404

    missing_player = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(str(UUID(int=0))),
        headers=bearer(coach),
    )
    assert missing_player.status_code == 404

    invalid_membership = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(str(departed_id)),
        headers=bearer(coach),
    )
    assert invalid_membership.status_code == 409

    team_id = context["team_id"]
    assert isinstance(team_id, UUID)
    unselected_id = await add_player(database, team_id, "Unselected")
    unselected_event = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(str(unselected_id)),
        headers=bearer(coach),
    )
    assert unselected_event.status_code == 409

    invalid_assist = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json={**goal(player_id), "assist_player_id": str(departed_id)},
        headers=bearer(coach),
    )
    assert invalid_assist.status_code == 409

    late_minute = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(player_id, minute=131),
        headers=bearer(coach),
    )
    assert late_minute.status_code == 422

    card_without_player = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json={"side": "HOME", "event_type": "YELLOW_CARD", "minute": 10},
        headers=bearer(coach),
    )
    assert card_without_player.status_code == 422

    substitution_via_events = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json={"side": "HOME", "event_type": "SUBSTITUTION", "minute": 60},
        headers=bearer(coach),
    )
    assert substitution_via_events.status_code == 422

    created = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(player_id),
        headers=bearer(coach),
    )
    assert created.status_code == 201
    event_id = created.json()["id"]
    reassigned = await client.patch(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        json={"player_id": str(departed_id)},
        headers=bearer(coach),
    )
    assert reassigned.status_code == 409


@pytest.mark.asyncio
async def test_substitution_create_retrieve_and_conflicts(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    coach = str(context["coach_token"])
    starter_id = context["player_id"]
    assert isinstance(starter_id, UUID)
    team_id = context["team_id"]
    assert isinstance(team_id, UUID)
    first_sub = await add_player(database, team_id, "Bench")
    second_sub = await add_player(database, team_id, "Next")
    unselected = await add_player(database, team_id, "Unselected")
    departed_id = await add_player(
        database,
        team_id,
        "Former",
        left_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    await select_player(client, match_id, coach, starter_id, "STARTER", True)
    await select_player(client, match_id, coach, first_sub, "SUBSTITUTE", False)
    await select_player(client, match_id, coach, second_sub, "SUBSTITUTE", False)

    not_on_pitch = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(first_sub),
            "player_in_id": str(second_sub),
            "minute": 60,
        },
        headers=bearer(coach),
    )
    assert not_on_pitch.status_code == 409

    missing_player = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(UUID(int=0)),
            "player_in_id": str(first_sub),
            "minute": 60,
        },
        headers=bearer(coach),
    )
    assert missing_player.status_code == 404

    departed = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(departed_id),
            "minute": 60,
        },
        headers=bearer(coach),
    )
    assert departed.status_code == 409

    outside_squad = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(unselected),
            "minute": 60,
        },
        headers=bearer(coach),
    )
    assert outside_squad.status_code == 409

    same_player = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(starter_id),
            "minute": 60,
        },
        headers=bearer(coach),
    )
    assert same_player.status_code == 422

    player_blocked = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(first_sub),
            "minute": 60,
            "reason": "TACTICAL",
        },
        headers=bearer(str(context["player_token"])),
    )
    assert player_blocked.status_code == 403

    created = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(first_sub),
            "minute": 60,
            "reason": "TACTICAL",
        },
        headers=bearer(coach),
    )
    assert created.status_code == 201
    substitution = created.json()
    assert substitution["player_out_id"] == str(starter_id)
    assert substitution["player_in_id"] == str(first_sub)
    assert substitution["side"] == "HOME"
    assert substitution["reason"] == "TACTICAL"
    substitution_id = substitution["id"]
    event_id = substitution["event_id"]

    fetched = await client.get(
        f"/api/v1/matches/{match_id}/substitutions/{substitution_id}",
        headers=bearer(coach),
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == substitution_id

    event = await client.get(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(coach),
    )
    assert event.status_code == 200
    assert event.json()["event_type"] == "SUBSTITUTION"
    assert event.json()["player_id"] == str(starter_id)
    assert event.json()["related_player_id"] == str(first_sub)

    locked = await client.patch(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        json={"minute": 61},
        headers=bearer(coach),
    )
    assert locked.status_code == 409

    duplicate = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(starter_id),
            "player_in_id": str(second_sub),
            "minute": 70,
        },
        headers=bearer(coach),
    )
    assert duplicate.status_code == 409

    returning = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(first_sub),
            "player_in_id": str(starter_id),
            "minute": 75,
        },
        headers=bearer(coach),
    )
    assert returning.status_code == 409

    chained = await client.post(
        f"/api/v1/matches/{match_id}/substitutions",
        json={
            "player_out_id": str(first_sub),
            "player_in_id": str(second_sub),
            "minute": 80,
        },
        headers=bearer(coach),
    )
    assert chained.status_code == 201

    listed = await client.get(
        f"/api/v1/matches/{match_id}/substitutions", headers=bearer(coach)
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [
        substitution_id,
        chained.json()["id"],
    ]

    player_token = str(context["player_token"])
    player_list = await client.get(
        f"/api/v1/matches/{match_id}/substitutions", headers=bearer(player_token)
    )
    assert player_list.status_code == 200
    assert [item["id"] for item in player_list.json()] == [substitution_id]
    own_substitution = await client.get(
        f"/api/v1/matches/{match_id}/substitutions/{substitution_id}",
        headers=bearer(player_token),
    )
    assert own_substitution.status_code == 200
    other_substitution = await client.get(
        f"/api/v1/matches/{match_id}/substitutions/{chained.json()['id']}",
        headers=bearer(player_token),
    )
    assert other_substitution.status_code == 404

    removed = await client.delete(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(coach),
    )
    assert removed.status_code == 204
    gone = await client.get(
        f"/api/v1/matches/{match_id}/substitutions/{substitution_id}",
        headers=bearer(coach),
    )
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_match_event_rbac_blocks_players_and_limits_analysts(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_match_context(client, database)
    match_id = context["match_id"]
    coach = str(context["coach_token"])
    player_id = context["player_id"]
    assert isinstance(player_id, UUID)
    await select_player(client, match_id, coach, player_id, "STARTER", True)
    _, scout_token = await create_user(
        database, "event-scout@example.com", RoleName.SCOUT
    )
    _, analyst_token = await create_user(
        database, "event-analyst@example.com", RoleName.ANALYST
    )
    payload = goal(str(player_id))

    player_create = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=payload,
        headers=bearer(str(context["player_token"])),
    )
    assert player_create.status_code == 403

    player_list = await client.get(
        f"/api/v1/matches/{match_id}/events",
        headers=bearer(str(context["player_token"])),
    )
    assert player_list.status_code == 200

    scout_create = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=payload,
        headers=bearer(scout_token),
    )
    assert scout_create.status_code == 403

    created = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=payload,
        headers=bearer(analyst_token),
    )
    assert created.status_code == 201
    event_id = created.json()["id"]

    team_id = context["team_id"]
    assert isinstance(team_id, UUID)
    other_player_id = await add_player(database, team_id, "Teammate")
    await select_player(client, match_id, coach, other_player_id, "STARTER", True)
    other_event = await client.post(
        f"/api/v1/matches/{match_id}/events",
        json=goal(str(other_player_id), minute=40),
        headers=bearer(coach),
    )
    assert other_event.status_code == 201

    player_token = str(context["player_token"])
    player_events = await client.get(
        f"/api/v1/matches/{match_id}/events", headers=bearer(player_token)
    )
    assert player_events.status_code == 200
    assert [event["id"] for event in player_events.json()] == [event_id]
    own_event = await client.get(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(player_token),
    )
    assert own_event.status_code == 200
    other_event_detail = await client.get(
        f"/api/v1/matches/{match_id}/events/{other_event.json()['id']}",
        headers=bearer(player_token),
    )
    assert other_event_detail.status_code == 404

    player_update = await client.patch(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        json={"minute": 30},
        headers=bearer(str(context["player_token"])),
    )
    assert player_update.status_code == 403

    analyst_delete = await client.delete(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(analyst_token),
    )
    assert analyst_delete.status_code == 403

    coach_delete = await client.delete(
        f"/api/v1/matches/{match_id}/events/{event_id}",
        headers=bearer(coach),
    )
    assert coach_delete.status_code == 204
