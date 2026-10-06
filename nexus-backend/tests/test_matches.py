from datetime import date
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.football import PlayerPosition
from app.core.matches import CompetitionType, MatchSquadStatus
from app.core.roles import RoleName
from app.db.models.competition import Competition
from app.db.models.match import MatchSquad
from app.db.models.opponent import Opponent
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.models.venue import Venue
from tests.conftest import DatabaseFixture
from tests.factories import create_user


async def create_match_catalog(database: DatabaseFixture) -> dict[str, UUID]:
    async with database.sessions() as session:
        team = Team(
            name="Match API Team",
            short_name="MAT",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Match API Opponent")
        venue = Venue(name="Match API Ground")
        competition = Competition(
            name="Match API League",
            competition_type=CompetitionType.LEAGUE,
            season="2026/27",
        )
        session.add_all([team, opponent, venue, competition])
        await session.commit()
        return {
            "team_id": team.id,
            "opponent_id": opponent.id,
            "venue_id": venue.id,
            "competition_id": competition.id,
        }


def match_payload(catalog: dict[str, UUID], **overrides: object) -> dict[str, object]:
    return {
        **catalog,
        "scheduled_at": "2026-10-01T15:00:00Z",
        "home_away": "HOME",
        **overrides,
    }


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_match_crud_validates_merged_state_and_blocks_dependent_delete(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "match-api-coach@example.com", RoleName.HEAD_COACH
    )
    catalog = await create_match_catalog(database)
    response = await client.post(
        "/api/v1/matches",
        json=match_payload(catalog, created_by=str(UUID(int=0))),
        headers=bearer(coach_token),
    )
    assert response.status_code == 422

    response = await client.post(
        "/api/v1/matches",
        json=match_payload(catalog),
        headers=bearer(coach_token),
    )
    assert response.status_code == 201
    match = response.json()
    assert match["created_by"]
    match_id = match["id"]

    assert (
        await client.get(f"/api/v1/matches/{match_id}", headers=bearer(coach_token))
    ).status_code == 200
    assert (
        len(
            (
                await client.get(
                    "/api/v1/matches",
                    params={"team_id": catalog["team_id"], "status": "SCHEDULED"},
                    headers=bearer(coach_token),
                )
            ).json()
        )
        == 1
    )

    transition = await client.patch(
        f"/api/v1/matches/{match_id}",
        json={"status": "COMPLETED"},
        headers=bearer(coach_token),
    )
    assert transition.status_code == 409
    invalid_score_pair = await client.patch(
        f"/api/v1/matches/{match_id}",
        json={"home_score": 1},
        headers=bearer(coach_token),
    )
    assert invalid_score_pair.status_code == 422

    async with database.sessions() as session:
        player = Player(
            first_name="Match",
            last_name="Player",
            date_of_birth=date(2000, 1, 1),
            preferred_position=PlayerPosition.CM,
        )
        session.add(player)
        await session.flush()
        session.add(
            MatchSquad(
                match_id=UUID(match_id),
                player_id=player.id,
                squad_status=MatchSquadStatus.SELECTED,
                starting=False,
                captain=False,
            )
        )
        await session.commit()

    deletion = await client.delete(
        f"/api/v1/matches/{match_id}", headers=bearer(coach_token)
    )
    assert deletion.status_code == 409


@pytest.mark.asyncio
async def test_players_only_list_and_view_matches_in_their_own_squad(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    player_user_id, player_token = await create_user(
        database, "match-api-player@example.com", RoleName.PLAYER
    )
    _, coach_token = await create_user(
        database, "match-api-coach-2@example.com", RoleName.HEAD_COACH
    )
    catalog = await create_match_catalog(database)
    responses = [
        await client.post(
            "/api/v1/matches",
            json=match_payload(catalog, scheduled_at=f"2026-10-0{day}T15:00:00Z"),
            headers=bearer(coach_token),
        )
        for day in (1, 2)
    ]
    assert all(response.status_code == 201 for response in responses)
    visible_match_id = UUID(responses[0].json()["id"])

    async with database.sessions() as session:
        player = Player(
            user_id=player_user_id,
            first_name="Scoped",
            last_name="Player",
            date_of_birth=date(2000, 1, 1),
            preferred_position=PlayerPosition.CM,
        )
        session.add(player)
        await session.flush()
        session.add(
            MatchSquad(
                match_id=visible_match_id,
                player_id=player.id,
                squad_status=MatchSquadStatus.SELECTED,
                starting=False,
                captain=False,
            )
        )
        await session.commit()

    listed = await client.get("/api/v1/matches", headers=bearer(player_token))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(visible_match_id)]
    hidden = await client.get(
        f"/api/v1/matches/{responses[1].json()['id']}",
        headers=bearer(player_token),
    )
    assert hidden.status_code == 404
    forbidden_create = await client.post(
        "/api/v1/matches",
        json=match_payload(catalog),
        headers=bearer(player_token),
    )
    assert forbidden_create.status_code == 403


@pytest.mark.asyncio
async def test_match_endpoints_require_auth_and_missing_references_are_controlled(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, coach_token = await create_user(
        database, "match-api-coach-3@example.com", RoleName.HEAD_COACH
    )
    unauthenticated = await client.get("/api/v1/matches")
    assert unauthenticated.status_code == 401

    catalog = await create_match_catalog(database)
    catalog["opponent_id"] = UUID(int=0)
    missing_reference = await client.post(
        "/api/v1/matches",
        json=match_payload(catalog),
        headers=bearer(coach_token),
    )
    assert missing_reference.status_code == 404

    missing_match = await client.get(
        f"/api/v1/matches/{UUID(int=0)}", headers=bearer(coach_token)
    )
    assert missing_match.status_code == 404
