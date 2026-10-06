from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.availability import PlayerAvailability
from app.db.models.development import (
    PlayerDevelopmentAssessment,
    PlayerDevelopmentGoal,
)
from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from app.db.models.training import TrainingParticipation


async def get_by_id(session: AsyncSession, player_id: UUID) -> Player | None:
    return await session.get(Player, player_id)


async def get_by_user_id(session: AsyncSession, user_id: UUID) -> Player | None:
    result = await session.execute(select(Player).where(Player.user_id == user_id))
    return result.scalar_one_or_none()


async def list_players(
    session: AsyncSession, user_id: UUID | None = None
) -> list[Player]:
    statement = select(Player).order_by(Player.last_name, Player.first_name)
    if user_id is not None:
        statement = statement.where(Player.user_id == user_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def has_memberships(session: AsyncSession, player_id: UUID) -> bool:
    count = await session.scalar(
        select(func.count(PlayerTeamMembership.id)).where(
            PlayerTeamMembership.player_id == player_id
        )
    )
    return bool(count)


async def has_phase04_records(session: AsyncSession, player_id: UUID) -> bool:
    has_records = or_(
        exists(
            select(TrainingParticipation.id).where(
                TrainingParticipation.player_id == player_id
            )
        ),
        exists(
            select(PlayerAvailability.id).where(
                PlayerAvailability.player_id == player_id
            )
        ),
        exists(
            select(PlayerDevelopmentGoal.id).where(
                PlayerDevelopmentGoal.player_id == player_id
            )
        ),
        exists(
            select(PlayerDevelopmentAssessment.id).where(
                PlayerDevelopmentAssessment.player_id == player_id
            )
        ),
    )
    result = await session.execute(
        select(Player.id).where(Player.id == player_id, has_records).limit(1)
    )
    return result.scalar_one_or_none() is not None
