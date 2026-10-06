from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.matches import MatchSide
from app.core.roles import RoleName
from app.db.models.match import Match
from app.db.models.team import Team
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_match_catalog_crud_rbac_and_referenced_delete_conflict(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    admin_id, admin_token = await create_user(
        database, "catalog-admin@example.com", RoleName.ADMIN
    )
    _, player_token = await create_user(
        database, "catalog-player@example.com", RoleName.PLAYER
    )
    admin_headers = bearer(admin_token)
    root = "/api/v1/matches"

    assert (await client.get(f"{root}/opponents")).status_code == 401
    assert (
        await client.post(
            f"{root}/opponents",
            json={"name": "Unauthorised"},
            headers=bearer(player_token),
        )
    ).status_code == 403

    opponent = await client.post(
        f"{root}/opponents", json={"name": "North City"}, headers=admin_headers
    )
    venue = await client.post(
        f"{root}/venues",
        json={"name": "North Ground", "capacity": 12000},
        headers=admin_headers,
    )
    competition = await client.post(
        f"{root}/competitions",
        json={
            "name": "Regional League",
            "competition_type": "LEAGUE",
            "season": "2026/27",
        },
        headers=admin_headers,
    )
    assert opponent.status_code == 201, opponent.text
    assert venue.status_code == 201, venue.text
    assert competition.status_code == 201, competition.text

    catalog_records = (
        ("opponents", opponent),
        ("venues", venue),
        ("competitions", competition),
    )
    for resource, created in catalog_records:
        item_id = created.json()["id"]
        listing = await client.get(f"{root}/{resource}", headers=admin_headers)
        detail = await client.get(f"{root}/{resource}/{item_id}", headers=admin_headers)
        assert listing.status_code == 200
        assert item_id in {item["id"] for item in listing.json()}
        assert detail.status_code == 200
        assert detail.json()["id"] == item_id

    updated = await client.patch(
        f"{root}/venues/{venue.json()['id']}",
        json={"capacity": 12500},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["capacity"] == 12500

    async with database.sessions() as session:
        team = Team(
            name="Catalog Match Team",
            short_name="CMT",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        session.add(team)
        await session.flush()
        match = Match(
            team_id=team.id,
            opponent_id=UUID(opponent.json()["id"]),
            venue_id=UUID(venue.json()["id"]),
            competition_id=UUID(competition.json()["id"]),
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            home_away=MatchSide.HOME,
            created_by=admin_id,
        )
        session.add(match)
        await session.commit()

    for resource, created in catalog_records:
        response = await client.delete(
            f"{root}/{resource}/{created.json()['id']}", headers=admin_headers
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_match_catalog_missing_resources_return_404(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, token = await create_user(database, "catalog-reader@example.com")
    headers = bearer(token)
    missing_id = UUID(int=0)
    root = "/api/v1/matches"

    for resource in ("opponents", "venues", "competitions"):
        response = await client.get(f"{root}/{resource}/{missing_id}", headers=headers)
        assert response.status_code == 404
