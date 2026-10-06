from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from app.db.models.training import TrainingParticipation, TrainingSession


async def get_session(
    session: AsyncSession, session_id: UUID
) -> TrainingSession | None:
    return await session.get(TrainingSession, session_id)


async def list_sessions(
    session: AsyncSession,
    team_id: UUID | None,
    session_date_from: date | None,
    session_date_to: date | None,
    limit: int,
    offset: int,
) -> list[TrainingSession]:
    statement = select(TrainingSession).order_by(
        TrainingSession.session_date.desc(), TrainingSession.start_time.desc()
    )
    if team_id is not None:
        statement = statement.where(TrainingSession.team_id == team_id)
    if session_date_from is not None:
        statement = statement.where(TrainingSession.session_date >= session_date_from)
    if session_date_to is not None:
        statement = statement.where(TrainingSession.session_date <= session_date_to)
    result = await session.execute(statement.limit(limit).offset(offset))
    return list(result.scalars().all())


async def get_participation(
    session: AsyncSession, session_id: UUID, player_id: UUID
) -> TrainingParticipation | None:
    result = await session.execute(
        select(TrainingParticipation)
        .options(selectinload(TrainingParticipation.session))
        .where(
            TrainingParticipation.training_session_id == session_id,
            TrainingParticipation.player_id == player_id,
        )
    )
    return result.scalar_one_or_none()


async def list_participations(
    session: AsyncSession, session_id: UUID, limit: int, offset: int
) -> list[TrainingParticipation]:
    result = await session.execute(
        select(TrainingParticipation)
        .options(selectinload(TrainingParticipation.session))
        .where(TrainingParticipation.training_session_id == session_id)
        .order_by(TrainingParticipation.created_at, TrainingParticipation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_player_history(
    session: AsyncSession, player_id: UUID, limit: int, offset: int
) -> list[TrainingParticipation]:
    result = await session.execute(
        select(TrainingParticipation)
        .options(selectinload(TrainingParticipation.session))
        .where(TrainingParticipation.player_id == player_id)
        .order_by(TrainingParticipation.recorded_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def player_belongs_to_team_on_date(
    session: AsyncSession, player_id: UUID, team_id: UUID, session_date: date
) -> bool:
    day_start = datetime.combine(session_date, time.min, tzinfo=UTC)
    next_day = day_start + timedelta(days=1)
    result = await session.execute(
        select(PlayerTeamMembership.id)
        .where(
            PlayerTeamMembership.player_id == player_id,
            PlayerTeamMembership.team_id == team_id,
            PlayerTeamMembership.joined_at < next_day,
            or_(
                PlayerTeamMembership.left_at.is_(None),
                PlayerTeamMembership.left_at >= day_start,
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def has_participant_without_team_membership_on_date(
    session: AsyncSession,
    session_id: UUID,
    team_id: UUID,
    session_date: date,
) -> bool:
    day_start = datetime.combine(session_date, time.min, tzinfo=UTC)
    next_day = day_start + timedelta(days=1)
    membership_exists = exists(
        select(PlayerTeamMembership.id).where(
            PlayerTeamMembership.player_id == TrainingParticipation.player_id,
            PlayerTeamMembership.team_id == team_id,
            PlayerTeamMembership.joined_at < next_day,
            or_(
                PlayerTeamMembership.left_at.is_(None),
                PlayerTeamMembership.left_at >= day_start,
            ),
        )
    )
    result = await session.execute(
        select(TrainingParticipation.id)
        .where(
            TrainingParticipation.training_session_id == session_id,
            ~membership_exists,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def player_summary_exists(session: AsyncSession, player_id: UUID) -> bool:
    return await session.get(Player, player_id) is not None
