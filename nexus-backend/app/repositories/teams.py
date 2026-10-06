from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.development import PlayerDevelopmentGoal
from app.db.models.membership import PlayerTeamMembership
from app.db.models.team import Team
from app.db.models.training import TrainingSession


async def get_by_id(session: AsyncSession, team_id: UUID) -> Team | None:
    return await session.get(Team, team_id)


async def list_teams(
    session: AsyncSession, player_user_id: UUID | None = None
) -> list[Team]:
    statement = select(Team).order_by(Team.name, Team.season)
    if player_user_id is not None:
        statement = (
            statement.join(Team.memberships)
            .join(PlayerTeamMembership.player)
            .where(
                PlayerTeamMembership.left_at.is_(None),
                PlayerTeamMembership.player.has(user_id=player_user_id),
            )
            .distinct()
        )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def has_memberships(session: AsyncSession, team_id: UUID) -> bool:
    count = await session.scalar(
        select(func.count(PlayerTeamMembership.id)).where(
            PlayerTeamMembership.team_id == team_id
        )
    )
    return bool(count)


async def has_phase04_records(session: AsyncSession, team_id: UUID) -> bool:
    has_records = or_(
        exists(select(TrainingSession.id).where(TrainingSession.team_id == team_id)),
        exists(
            select(PlayerDevelopmentGoal.id).where(
                PlayerDevelopmentGoal.team_id == team_id
            )
        ),
    )
    result = await session.execute(
        select(Team.id).where(Team.id == team_id, has_records).limit(1)
    )
    return result.scalar_one_or_none() is not None
