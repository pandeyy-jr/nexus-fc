from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.availability import PlayerAvailability
from app.db.models.player import Player


async def lock_player(session: AsyncSession, player_id: UUID) -> None:
    await session.execute(
        select(Player.id).where(Player.id == player_id).with_for_update()
    )


async def get_by_id(
    session: AsyncSession, player_id: UUID, availability_id: UUID
) -> PlayerAvailability | None:
    result = await session.execute(
        select(PlayerAvailability).where(
            PlayerAvailability.id == availability_id,
            PlayerAvailability.player_id == player_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_player(
    session: AsyncSession, player_id: UUID, limit: int, offset: int
) -> list[PlayerAvailability]:
    result = await session.execute(
        select(PlayerAvailability)
        .where(PlayerAvailability.player_id == player_id)
        .order_by(PlayerAvailability.effective_from.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_current(
    session: AsyncSession, player_id: UUID, at: datetime
) -> PlayerAvailability | None:
    result = await session.execute(
        select(PlayerAvailability)
        .where(
            PlayerAvailability.player_id == player_id,
            PlayerAvailability.effective_from <= at,
            or_(
                PlayerAvailability.effective_until.is_(None),
                PlayerAvailability.effective_until > at,
            ),
        )
        .order_by(PlayerAvailability.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_overlap(
    session: AsyncSession,
    player_id: UUID,
    effective_from: datetime,
    effective_until: datetime | None,
    exclude_id: UUID | None = None,
) -> PlayerAvailability | None:
    statement = select(PlayerAvailability).where(
        PlayerAvailability.player_id == player_id,
        or_(
            PlayerAvailability.effective_until.is_(None),
            PlayerAvailability.effective_until >= effective_from,
        ),
    )
    if effective_until is not None:
        statement = statement.where(
            PlayerAvailability.effective_from <= effective_until
        )
    if exclude_id is not None:
        statement = statement.where(PlayerAvailability.id != exclude_id)
    result = await session.execute(statement.limit(1))
    return result.scalar_one_or_none()
