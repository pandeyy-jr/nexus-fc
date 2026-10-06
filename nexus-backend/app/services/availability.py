from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import AVAILABILITY_READ_ROLES
from app.db.models.availability import PlayerAvailability
from app.db.models.user import User
from app.db.types import utc_now
from app.repositories import availability
from app.schemas.availability import (
    PlayerAvailabilityCreate,
    PlayerAvailabilityUpdate,
)
from app.services.player_scope import get_player_for_actor


async def list_availability(
    session: AsyncSession,
    player_id: UUID,
    actor: User,
    limit: int,
    offset: int,
) -> list[PlayerAvailability]:
    await get_player_for_actor(session, player_id, actor, AVAILABILITY_READ_ROLES)
    return await availability.list_for_player(session, player_id, limit, offset)


async def get_current_availability(
    session: AsyncSession, player_id: UUID, actor: User
) -> PlayerAvailability | None:
    await get_player_for_actor(session, player_id, actor, AVAILABILITY_READ_ROLES)
    return await availability.get_current(session, player_id, utc_now())


async def create_availability(
    session: AsyncSession,
    player_id: UUID,
    payload: PlayerAvailabilityCreate,
    actor: User,
) -> PlayerAvailability:
    await get_player_for_actor(session, player_id, actor, AVAILABILITY_READ_ROLES)
    await availability.lock_player(session, player_id)
    if await availability.find_overlap(
        session, player_id, payload.effective_from, payload.effective_until
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability period overlaps an existing record",
        )
    record = PlayerAvailability(
        player_id=player_id,
        recorded_by=actor.id,
        **payload.model_dump(),
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability period overlaps an existing record",
        ) from exc
    await session.refresh(record)
    return record


async def _get_record(
    session: AsyncSession, player_id: UUID, availability_id: UUID
) -> PlayerAvailability:
    record = await availability.get_by_id(session, player_id, availability_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Availability record not found",
        )
    return record


async def update_availability(
    session: AsyncSession,
    player_id: UUID,
    availability_id: UUID,
    payload: PlayerAvailabilityUpdate,
) -> PlayerAvailability:
    await availability.lock_player(session, player_id)
    record = await _get_record(session, player_id, availability_id)
    now = utc_now()
    if record.effective_until is not None and record.effective_until <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Historical availability records cannot be modified",
        )
    changes = payload.model_dump(exclude_unset=True)
    effective_from = changes.get("effective_from", record.effective_from)
    effective_until = changes.get("effective_until", record.effective_until)
    if effective_until is not None and effective_until < effective_from:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="effective_until must be on or after effective_from",
        )
    if await availability.find_overlap(
        session,
        player_id,
        effective_from,
        effective_until,
        exclude_id=record.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability period overlaps an existing record",
        )
    for field, value in changes.items():
        setattr(record, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability period overlaps an existing record",
        ) from exc
    await session.refresh(record)
    return record


async def end_availability(
    session: AsyncSession, player_id: UUID, availability_id: UUID
) -> PlayerAvailability:
    await availability.lock_player(session, player_id)
    record = await _get_record(session, player_id, availability_id)
    now = utc_now()
    if record.effective_until is not None and record.effective_until <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Availability record has already ended",
        )
    record.effective_until = min(
        max(now, record.effective_from),
        record.effective_until or max(now, record.effective_from),
    )
    await session.commit()
    await session.refresh(record)
    return record
