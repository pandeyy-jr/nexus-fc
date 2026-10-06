from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.matches import MatchEventType
from app.db.models.match import (
    Match,
    MatchEvent,
    MatchParticipation,
    MatchSquad,
    Substitution,
)
from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from app.repositories.training import player_belongs_to_team_on_date


async def get_match(session: AsyncSession, match_id: UUID) -> Match | None:
    return await session.get(Match, match_id)


async def list_matches(
    session: AsyncSession,
    team_id: UUID | None,
    opponent_id: UUID | None,
    status_value: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    offset: int,
) -> list[Match]:
    statement = select(Match).order_by(Match.scheduled_at.desc(), Match.id)
    if team_id is not None:
        statement = statement.where(Match.team_id == team_id)
    if opponent_id is not None:
        statement = statement.where(Match.opponent_id == opponent_id)
    if status_value is not None:
        statement = statement.where(Match.status == status_value)
    if date_from is not None:
        statement = statement.where(Match.scheduled_at >= date_from)
    if date_to is not None:
        statement = statement.where(Match.scheduled_at < date_to)
    result = await session.execute(statement.limit(limit).offset(offset))
    return list(result.scalars().all())


async def get_match_for_player(
    session: AsyncSession, match_id: UUID, user_id: UUID
) -> Match | None:
    result = await session.execute(
        select(Match)
        .join(Match.squad)
        .join(MatchSquad.player)
        .where(Match.id == match_id, Player.user_id == user_id)
    )
    return result.unique().scalar_one_or_none()


async def list_player_matches(
    session: AsyncSession,
    player_id: UUID,
    limit: int,
    offset: int,
    team_id: UUID | None = None,
    opponent_id: UUID | None = None,
    status_value: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Match]:
    statement = (
        select(Match)
        .join(Match.squad)
        .where(MatchSquad.player_id == player_id)
        .order_by(Match.scheduled_at.desc(), Match.id)
    )
    if team_id is not None:
        statement = statement.where(Match.team_id == team_id)
    if opponent_id is not None:
        statement = statement.where(Match.opponent_id == opponent_id)
    if status_value is not None:
        statement = statement.where(Match.status == status_value)
    if date_from is not None:
        statement = statement.where(Match.scheduled_at >= date_from)
    if date_to is not None:
        statement = statement.where(Match.scheduled_at < date_to)
    result = await session.execute(statement.limit(limit).offset(offset))
    return list(result.unique().scalars().all())


async def get_squad_entry(
    session: AsyncSession, match_id: UUID, player_id: UUID
) -> MatchSquad | None:
    result = await session.execute(
        select(MatchSquad)
        .options(selectinload(MatchSquad.participation))
        .where(MatchSquad.match_id == match_id, MatchSquad.player_id == player_id)
    )
    return result.scalar_one_or_none()


async def list_squad(session: AsyncSession, match_id: UUID) -> list[MatchSquad]:
    result = await session.execute(
        select(MatchSquad)
        .options(selectinload(MatchSquad.participation))
        .where(MatchSquad.match_id == match_id)
        .order_by(MatchSquad.starting.desc(), MatchSquad.shirt_number, MatchSquad.id)
    )
    return list(result.scalars().all())


async def get_participation(
    session: AsyncSession, match_squad_id: UUID
) -> MatchParticipation | None:
    result = await session.execute(
        select(MatchParticipation).where(
            MatchParticipation.match_squad_id == match_squad_id
        )
    )
    return result.scalar_one_or_none()


async def get_event(
    session: AsyncSession, match_id: UUID, event_id: UUID
) -> MatchEvent | None:
    return await session.scalar(
        select(MatchEvent).where(
            MatchEvent.match_id == match_id,
            MatchEvent.id == event_id,
        )
    )


async def list_events(
    session: AsyncSession, match_id: UUID, limit: int, offset: int
) -> list[MatchEvent]:
    result = await session.execute(
        select(MatchEvent)
        .where(MatchEvent.match_id == match_id)
        .order_by(
            MatchEvent.minute, MatchEvent.added_time_minute, MatchEvent.created_at
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_player_events(
    session: AsyncSession,
    match_id: UUID,
    user_id: UUID,
    limit: int,
    offset: int,
) -> list[MatchEvent]:
    player_ids = select(Player.id).where(Player.user_id == user_id)
    result = await session.execute(
        select(MatchEvent)
        .where(
            MatchEvent.match_id == match_id,
            or_(
                MatchEvent.player_id.in_(player_ids),
                MatchEvent.assist_player_id.in_(player_ids),
                MatchEvent.related_player_id.in_(player_ids),
            ),
        )
        .order_by(
            MatchEvent.minute, MatchEvent.added_time_minute, MatchEvent.created_at
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_player_event(
    session: AsyncSession, match_id: UUID, event_id: UUID, user_id: UUID
) -> MatchEvent | None:
    player_ids = select(Player.id).where(Player.user_id == user_id)
    return await session.scalar(
        select(MatchEvent).where(
            MatchEvent.match_id == match_id,
            MatchEvent.id == event_id,
            or_(
                MatchEvent.player_id.in_(player_ids),
                MatchEvent.assist_player_id.in_(player_ids),
                MatchEvent.related_player_id.in_(player_ids),
            ),
        )
    )


async def list_substitutions(
    session: AsyncSession, match_id: UUID
) -> list[Substitution]:
    result = await session.execute(
        select(Substitution)
        .where(Substitution.match_id == match_id)
        .order_by(Substitution.minute, Substitution.added_time_minute)
    )
    return list(result.scalars().all())


async def list_player_substitutions(
    session: AsyncSession, match_id: UUID, user_id: UUID
) -> list[Substitution]:
    player_ids = select(Player.id).where(Player.user_id == user_id)
    result = await session.execute(
        select(Substitution)
        .where(
            Substitution.match_id == match_id,
            or_(
                Substitution.player_out_id.in_(player_ids),
                Substitution.player_in_id.in_(player_ids),
            ),
        )
        .order_by(Substitution.minute, Substitution.added_time_minute)
    )
    return list(result.scalars().all())


async def get_substitution(
    session: AsyncSession, match_id: UUID, substitution_id: UUID
) -> Substitution | None:
    return await session.scalar(
        select(Substitution).where(
            Substitution.match_id == match_id,
            Substitution.id == substitution_id,
        )
    )


async def get_player_substitution(
    session: AsyncSession, match_id: UUID, substitution_id: UUID, user_id: UUID
) -> Substitution | None:
    player_ids = select(Player.id).where(Player.user_id == user_id)
    return await session.scalar(
        select(Substitution).where(
            Substitution.match_id == match_id,
            Substitution.id == substitution_id,
            or_(
                Substitution.player_out_id.in_(player_ids),
                Substitution.player_in_id.in_(player_ids),
            ),
        )
    )


async def get_substitution_for_event(
    session: AsyncSession, event_id: UUID
) -> Substitution | None:
    return await session.scalar(
        select(Substitution).where(Substitution.event_id == event_id)
    )


async def player_has_entered_match(
    session: AsyncSession, match_id: UUID, player_id: UUID
) -> bool:
    result = await session.execute(
        select(
            exists().where(
                Substitution.match_id == match_id,
                Substitution.player_in_id == player_id,
            )
        )
    )
    return bool(result.scalar_one())


async def substitution_conflict_detail(
    session: AsyncSession,
    match_id: UUID,
    player_out_id: UUID,
    player_in_id: UUID,
) -> str | None:
    result = await session.execute(
        select(Substitution.player_out_id, Substitution.player_in_id).where(
            Substitution.match_id == match_id,
            or_(
                Substitution.player_out_id == player_out_id,
                Substitution.player_in_id == player_in_id,
                Substitution.player_out_id == player_in_id,
            ),
        )
    )
    rows = result.all()
    if any(existing_out == player_out_id for existing_out, _ in rows):
        return "Player has already been substituted off"
    if any(existing_in == player_in_id for _, existing_in in rows):
        return "Player has already been substituted on"
    if any(existing_out == player_in_id for existing_out, _ in rows):
        return "Player coming on has already left the match"
    return None


async def player_has_squad_membership(
    session: AsyncSession, match_id: UUID, player_id: UUID
) -> bool:
    result = await session.execute(
        select(
            exists().where(
                MatchSquad.match_id == match_id,
                MatchSquad.player_id == player_id,
            )
        )
    )
    return bool(result.scalar_one())


async def player_belongs_to_team_on_match_date(
    session: AsyncSession, match: Match, player_id: UUID
) -> bool:
    return await player_belongs_to_team_on_date(
        session, player_id, match.team_id, match.scheduled_at.date()
    )


async def squad_player_membership_mismatch(
    session: AsyncSession,
    match_id: UUID,
    team_id: UUID,
    scheduled_at,
) -> bool:
    session_date = scheduled_at.date()
    from datetime import UTC, datetime, time, timedelta

    day_start = datetime.combine(session_date, time.min, tzinfo=UTC)
    next_day = day_start + timedelta(days=1)
    membership_exists = exists(
        select(PlayerTeamMembership.id).where(
            PlayerTeamMembership.player_id == MatchSquad.player_id,
            PlayerTeamMembership.team_id == team_id,
            PlayerTeamMembership.joined_at < next_day,
            or_(
                PlayerTeamMembership.left_at.is_(None),
                PlayerTeamMembership.left_at >= day_start,
            ),
        )
    )
    result = await session.execute(
        select(MatchSquad.id)
        .where(MatchSquad.match_id == match_id, ~membership_exists)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def match_has_history(session: AsyncSession, match_id: UUID) -> bool:
    conditions = (
        exists(select(MatchSquad.id).where(MatchSquad.match_id == match_id)),
        exists(select(MatchEvent.id).where(MatchEvent.match_id == match_id)),
        exists(select(Substitution.id).where(Substitution.match_id == match_id)),
    )
    result = await session.execute(
        select(Match.id).where(Match.id == match_id, or_(*conditions)).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def match_has_substitutions(session: AsyncSession, match_id: UUID) -> bool:
    result = await session.execute(
        select(
            exists().where(
                MatchEvent.match_id == match_id,
                MatchEvent.event_type == MatchEventType.SUBSTITUTION,
            )
        )
    )
    return bool(result.scalar_one())


async def squad_entry_has_history(
    session: AsyncSession, match_id: UUID, player_id: UUID
) -> bool:
    result = await session.execute(
        select(MatchSquad.id)
        .join(
            MatchParticipation,
            MatchParticipation.match_squad_id == MatchSquad.id,
            isouter=True,
        )
        .where(
            MatchSquad.match_id == match_id,
            MatchSquad.player_id == player_id,
            or_(
                MatchParticipation.id.is_not(None),
                exists(
                    select(MatchEvent.id).where(
                        MatchEvent.match_id == match_id,
                        or_(
                            MatchEvent.player_id == player_id,
                            MatchEvent.assist_player_id == player_id,
                            MatchEvent.related_player_id == player_id,
                        ),
                    )
                ),
                exists(
                    select(Substitution.id).where(
                        Substitution.match_id == match_id,
                        or_(
                            Substitution.player_out_id == player_id,
                            Substitution.player_in_id == player_id,
                        ),
                    )
                ),
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def catalog_has_matches(session: AsyncSession, column, catalog_id: UUID) -> bool:
    result = await session.execute(select(exists().where(column == catalog_id)))
    return bool(result.scalar_one())
