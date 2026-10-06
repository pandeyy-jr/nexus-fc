from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player


async def get_current(
    session: AsyncSession, team_id: UUID, player_id: UUID
) -> PlayerTeamMembership | None:
    result = await session.execute(
        select(PlayerTeamMembership).where(
            PlayerTeamMembership.team_id == team_id,
            PlayerTeamMembership.player_id == player_id,
            PlayerTeamMembership.left_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def get_latest(
    session: AsyncSession, team_id: UUID, player_id: UUID
) -> PlayerTeamMembership | None:
    result = await session.execute(
        select(PlayerTeamMembership)
        .where(
            PlayerTeamMembership.team_id == team_id,
            PlayerTeamMembership.player_id == player_id,
        )
        .order_by(PlayerTeamMembership.joined_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_team(
    session: AsyncSession,
    team_id: UUID,
    include_history: bool,
    player_user_id: UUID | None = None,
) -> list[PlayerTeamMembership]:
    statement = select(PlayerTeamMembership).where(
        PlayerTeamMembership.team_id == team_id
    )
    if not include_history:
        statement = statement.where(PlayerTeamMembership.left_at.is_(None))
    if player_user_id is not None:
        statement = statement.join(PlayerTeamMembership.player).where(
            Player.user_id == player_user_id
        )
    result = await session.execute(
        statement.order_by(PlayerTeamMembership.joined_at.desc())
    )
    return list(result.scalars().all())


async def has_any_for_player(session: AsyncSession, player_id: UUID) -> bool:
    result = await session.execute(
        select(PlayerTeamMembership.id)
        .where(PlayerTeamMembership.player_id == player_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
