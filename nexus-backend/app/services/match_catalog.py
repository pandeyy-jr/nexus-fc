from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.competition import Competition
from app.db.models.match import Match
from app.db.models.opponent import Opponent
from app.db.models.venue import Venue
from app.repositories import match_catalog
from app.schemas.match_catalog import (
    CompetitionCreate,
    CompetitionUpdate,
    OpponentCreate,
    OpponentUpdate,
    VenueCreate,
    VenueUpdate,
)


async def list_opponents(
    session: AsyncSession, limit: int, offset: int
) -> list[Opponent]:
    return await match_catalog.list_opponents(session, limit, offset)


async def get_opponent(session: AsyncSession, opponent_id: UUID) -> Opponent:
    item = await match_catalog.get_opponent(session, opponent_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opponent not found")
    return item


async def create_opponent(session: AsyncSession, payload: OpponentCreate) -> Opponent:
    item = Opponent(**payload.model_dump())
    session.add(item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An opponent with this name already exists",
        ) from exc
    await session.refresh(item)
    return item


async def update_opponent(
    session: AsyncSession, opponent_id: UUID, payload: OpponentUpdate
) -> Opponent:
    item = await get_opponent(session, opponent_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An opponent with this name already exists",
        ) from exc
    await session.refresh(item)
    return item


async def delete_opponent(session: AsyncSession, opponent_id: UUID) -> None:
    item = await get_opponent(session, opponent_id)
    if await match_catalog.opponent_has_matches(session, opponent_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Opponents referenced by matches cannot be deleted",
        )
    await session.delete(item)
    await session.commit()


async def list_venues(session: AsyncSession, limit: int, offset: int) -> list[Venue]:
    return await match_catalog.list_venues(session, limit, offset)


async def get_venue(session: AsyncSession, venue_id: UUID) -> Venue:
    item = await match_catalog.get_venue(session, venue_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return item


async def create_venue(session: AsyncSession, payload: VenueCreate) -> Venue:
    item = Venue(**payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_venue(
    session: AsyncSession, venue_id: UUID, payload: VenueUpdate
) -> Venue:
    item = await get_venue(session, venue_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_venue(session: AsyncSession, venue_id: UUID) -> None:
    item = await get_venue(session, venue_id)
    if await match_catalog.venue_has_matches(session, venue_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Venues referenced by matches cannot be deleted",
        )
    await session.delete(item)
    await session.commit()


async def list_competitions(
    session: AsyncSession, limit: int, offset: int
) -> list[Competition]:
    return await match_catalog.list_competitions(session, limit, offset)


async def get_competition(
    session: AsyncSession, competition_id: UUID
) -> Competition:
    item = await match_catalog.get_competition(session, competition_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return item


async def create_competition(
    session: AsyncSession, payload: CompetitionCreate
) -> Competition:
    item = Competition(**payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_competition(
    session: AsyncSession, competition_id: UUID, payload: CompetitionUpdate
) -> Competition:
    item = await get_competition(session, competition_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return item


async def delete_competition(session: AsyncSession, competition_id: UUID) -> None:
    item = await get_competition(session, competition_id)
    if await match_catalog.competition_has_matches(session, competition_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Competitions referenced by matches cannot be deleted",
        )
    await session.delete(item)
    await session.commit()