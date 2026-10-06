from datetime import date
from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import (
    SPORTS_SCIENTIST_TRAINING_FIELDS,
    TRAINING_READ_ROLES,
)
from app.core.roles import RoleName
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.models.training import TrainingParticipation, TrainingSession
from app.db.models.user import User
from app.repositories import training
from app.schemas.training import (
    TrainingParticipationCreate,
    TrainingParticipationUpdate,
    TrainingSessionCreate,
    TrainingSessionUpdate,
)
from app.services.player_scope import get_player_for_actor


async def list_sessions(
    session: AsyncSession,
    team_id: UUID | None,
    session_date_from: date | None,
    session_date_to: date | None,
    limit: int,
    offset: int,
) -> list[TrainingSession]:
    return await training.list_sessions(
        session, team_id, session_date_from, session_date_to, limit, offset
    )


async def get_session(session: AsyncSession, session_id: UUID) -> TrainingSession:
    record = await training.get_session(session, session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found"
        )
    return record


async def create_session(
    session: AsyncSession, payload: TrainingSessionCreate, actor: User
) -> TrainingSession:
    if await session.get(Team, payload.team_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    record = TrainingSession(**payload.model_dump(), created_by=actor.id)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def update_session(
    session: AsyncSession, session_id: UUID, payload: TrainingSessionUpdate
) -> TrainingSession:
    record = await get_session(session, session_id)
    changes = payload.model_dump(exclude_unset=True)
    new_date = changes.get("session_date", record.session_date)
    new_start = changes.get("start_time", record.start_time)
    new_end = changes.get("end_time", record.end_time)
    if new_end <= new_start:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="end_time must be after start_time",
        )
    if new_date != record.session_date:
        if await training.has_participant_without_team_membership_on_date(
            session, session_id, record.team_id, new_date
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session date conflicts with a participant's team membership",
            )
    for field, value in changes.items():
        setattr(record, field, value)
    await session.commit()
    await session.refresh(record)
    return record


async def delete_session(session: AsyncSession, session_id: UUID) -> None:
    record = await get_session(session, session_id)
    participations = await training.list_participations(
        session, session_id, limit=1, offset=0
    )
    if participations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Training sessions with participation records cannot be deleted",
        )
    await session.delete(record)
    await session.commit()


async def list_participations(
    session: AsyncSession, session_id: UUID, limit: int, offset: int
) -> list[TrainingParticipation]:
    await get_session(session, session_id)
    return await training.list_participations(session, session_id, limit, offset)


async def create_participation(
    session: AsyncSession,
    session_id: UUID,
    payload: TrainingParticipationCreate,
) -> TrainingParticipation:
    record = await get_session(session, session_id)
    if await session.get(Player, payload.player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if not await training.player_belongs_to_team_on_date(
        session, payload.player_id, record.team_id, record.session_date
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player was not a member of this team on the session date",
        )
    if await training.get_participation(session, session_id, payload.player_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Participation already exists for this player and session",
        )
    participation = TrainingParticipation(
        training_session_id=session_id,
        **payload.model_dump(),
    )
    session.add(participation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Participation already exists for this player and session",
        ) from exc
    await session.refresh(participation)
    return await training.get_participation(session, session_id, payload.player_id)


async def update_participation(
    session: AsyncSession,
    session_id: UUID,
    player_id: UUID,
    payload: TrainingParticipationUpdate,
    actor: User,
) -> TrainingParticipation:
    changed_fields = payload.model_fields_set
    if actor.role.name == RoleName.SPORTS_SCIENTIST and not changed_fields.issubset(
        SPORTS_SCIENTIST_TRAINING_FIELDS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sports scientists may update training-load fields only",
        )
    participation = await training.get_participation(session, session_id, player_id)
    if participation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participation not found"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(participation, field, value)
    await session.commit()
    await session.refresh(participation)
    return await training.get_participation(session, session_id, player_id)


async def delete_participation(
    session: AsyncSession, session_id: UUID, player_id: UUID
) -> None:
    participation = await training.get_participation(session, session_id, player_id)
    if participation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participation not found"
        )
    await session.delete(participation)
    await session.commit()


async def get_player_training_history(
    session: AsyncSession,
    player_id: UUID,
    actor: User,
    limit: int,
    offset: int,
) -> tuple[Player, list[TrainingParticipation]]:
    player = await get_player_for_actor(session, player_id, actor, TRAINING_READ_ROLES)
    records = await training.list_player_history(session, player_id, limit, offset)
    return player, records
