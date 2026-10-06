from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.football import PlayerPosition, PlayerStatus, SquadStatus
from app.core.roles import RoleName
from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from app.db.models.team import Team
from tests.conftest import DatabaseFixture
from tests.factories import create_user


@dataclass(frozen=True)
class DomainContext:
    coach_id: UUID
    coach_token: str
    player_user_id: UUID
    player_token: str
    player_id: UUID
    team_id: UUID


async def create_domain_context(
    database: DatabaseFixture,
    player_email: str = "phase4-player@example.com",
    membership_left_at: datetime | None = None,
) -> DomainContext:
    coach_id, coach_token = await create_user(
        database,
        "phase4-coach@example.com",
        RoleName.HEAD_COACH,
    )
    player_user_id, player_token = await create_user(database, player_email)
    now = datetime.now(UTC)
    async with database.sessions() as session:
        player = Player(
            user_id=player_user_id,
            first_name="Phase",
            last_name="Player",
            date_of_birth=datetime(2000, 1, 1).date(),
            preferred_position=PlayerPosition.CM,
            status=PlayerStatus.ACTIVE,
        )
        team = Team(
            name="Phase Four Squad",
            short_name="P4",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        session.add_all([player, team])
        await session.flush()
        session.add(
            PlayerTeamMembership(
                player_id=player.id,
                team_id=team.id,
                joined_at=now - timedelta(days=30),
                left_at=membership_left_at,
                squad_status=(
                    SquadStatus.INACTIVE
                    if membership_left_at is not None
                    else SquadStatus.ACTIVE
                ),
            )
        )
        await session.commit()
        player_id = player.id
        team_id = team.id
    return DomainContext(
        coach_id=coach_id,
        coach_token=coach_token,
        player_user_id=player_user_id,
        player_token=player_token,
        player_id=player_id,
        team_id=team_id,
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
