from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.competition import Competition
from app.db.models.match import Match
from app.db.models.opponent import Opponent
from app.db.models.venue import Venue


async def get_opponent(session: AsyncSession, opponent_id: UUID) -> Opponent | None:
    return await session.get(Opponent, opponent_id)


async def list_opponents(session: AsyncSession, limit: int, offset: int) -> list[Opponent]:
    result = await session.execute(
        select(Opponent).order_by(Opponent.name).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def opponent_has_matches(session: AsyncSession, opponent_id: UUID) -> bool:
    result = await session.execute(
        select(exists().where(Match.opponent_id == opponent_id))
    )
    return bool(result.scalar_one())


async def get_venue(session: AsyncSession, venue_id: UUID) -> Venue | None:
    return await session.get(Venue, venue_id)


async def list_venues(session: AsyncSession, limit: int, offset: int) -> list[Venue]:
    result = await session.execute(
        select(Venue).order_by(Venue.name).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def venue_has_matches(session: AsyncSession, venue_id: UUID) -> bool:
    result = await session.execute(
        select(exists().where(Match.venue_id == venue_id))
    )
    return bool(result.scalar_one())


async def get_competition(
    session: AsyncSession, competition_id: UUID
) -> Competition | None:
    return await session.get(Competition, competition_id)


async def list_competitions(
    session: AsyncSession, limit: int, offset: int
) -> list[Competition]:
    result = await session.execute(
        select(Competition)
        .order_by(Competition.season.desc(), Competition.name)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def competition_has_matches(
    session: AsyncSession, competition_id: UUID
) -> bool:
    result = await session.execute(
        select(exists().where(Match.competition_id == competition_id))
    )
    return bool(result.scalar_one())