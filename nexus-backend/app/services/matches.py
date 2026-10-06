from datetime import UTC, date, datetime, time, timedelta
from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import MATCH_READ_ROLES
from app.core.matches import (
    MatchEventSource,
    MatchEventType,
    MatchSide,
    MatchSquadStatus,
    MatchStatus,
)
from app.core.roles import RoleName
from app.db.models.match import (
    Match,
    MatchEvent,
    MatchParticipation,
    MatchSquad,
    Substitution,
)
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.models.user import User
from app.repositories import match_catalog, matches, players
from app.schemas.match_events import (
    MatchEventCreate,
    MatchEventUpdate,
    MatchParticipationCreate,
    MatchParticipationUpdate,
    MatchSquadCreate,
    MatchSquadUpdate,
    SubstitutionCreate,
)
from app.schemas.matches import MatchCreate, MatchUpdate
from app.services.player_scope import get_player_for_actor

_ALLOWED_TRANSITIONS: dict[MatchStatus, frozenset[MatchStatus]] = {
    MatchStatus.SCHEDULED: frozenset(
        {
            MatchStatus.LIVE,
            MatchStatus.POSTPONED,
            MatchStatus.CANCELLED,
            MatchStatus.ABANDONED,
        }
    ),
    MatchStatus.POSTPONED: frozenset(
        {MatchStatus.SCHEDULED, MatchStatus.CANCELLED, MatchStatus.ABANDONED}
    ),
    MatchStatus.LIVE: frozenset({MatchStatus.COMPLETED, MatchStatus.ABANDONED}),
    MatchStatus.COMPLETED: frozenset(),
    MatchStatus.CANCELLED: frozenset(),
    MatchStatus.ABANDONED: frozenset(),
}


def _invalid(detail: str) -> HTTPException:
    return HTTPException(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        detail=detail,
    )


async def _validate_catalog_references(
    session: AsyncSession,
    team_id: UUID,
    opponent_id: UUID,
    competition_id: UUID | None,
    venue_id: UUID | None,
) -> None:
    if await session.get(Team, team_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    if await match_catalog.get_opponent(session, opponent_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opponent not found"
        )
    if (
        competition_id is not None
        and await match_catalog.get_competition(session, competition_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if (
        venue_id is not None
        and await match_catalog.get_venue(session, venue_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        )


async def list_matches(
    session: AsyncSession,
    actor: User,
    team_id: UUID | None,
    opponent_id: UUID | None,
    status_value: MatchStatus | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> list[Match]:
    if date_from is not None and date_to is not None and date_to < date_from:
        raise _invalid("date_to must be on or after date_from")
    scheduled_from = (
        datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    )
    scheduled_before = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        if date_to
        else None
    )
    if actor.role.name == RoleName.PLAYER:
        player = await players.get_by_user_id(session, actor.id)
        if player is None:
            return []
        return await matches.list_player_matches(
            session,
            player.id,
            limit,
            offset,
            team_id,
            opponent_id,
            status_value,
            scheduled_from,
            scheduled_before,
        )
    if actor.role.name not in MATCH_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    return await matches.list_matches(
        session,
        team_id,
        opponent_id,
        status_value,
        scheduled_from,
        scheduled_before,
        limit,
        offset,
    )


async def get_match_for_actor(
    session: AsyncSession, match_id: UUID, actor: User
) -> Match:
    if actor.role.name == RoleName.PLAYER:
        item = await matches.get_match_for_player(session, match_id, actor.id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
        return item
    if actor.role.name not in MATCH_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    item = await matches.get_match(session, match_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )
    return item


async def get_match(session: AsyncSession, match_id: UUID) -> Match:
    item = await matches.get_match(session, match_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )
    return item


async def create_match(
    session: AsyncSession, payload: MatchCreate, actor: User
) -> Match:
    await _validate_catalog_references(
        session,
        payload.team_id,
        payload.opponent_id,
        payload.competition_id,
        payload.venue_id,
    )
    item = Match(**payload.model_dump(), created_by=actor.id, updated_by=actor.id)
    session.add(item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match conflicts with existing domain data",
        ) from exc
    await session.refresh(item)
    return item


async def update_match(
    session: AsyncSession, match_id: UUID, payload: MatchUpdate, actor: User
) -> Match:
    item = await get_match(session, match_id)
    changes = payload.model_dump(exclude_unset=True)
    new_team_id = changes.get("team_id", item.team_id)
    new_opponent_id = changes.get("opponent_id", item.opponent_id)
    new_competition_id = changes.get("competition_id", item.competition_id)
    new_venue_id = changes.get("venue_id", item.venue_id)
    await _validate_catalog_references(
        session, new_team_id, new_opponent_id, new_competition_id, new_venue_id
    )

    new_status = changes.get("status", item.status)
    if (
        new_status != item.status
        and new_status not in _ALLOWED_TRANSITIONS[item.status]
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Match cannot transition from {item.status} to {new_status}",
        )

    home_score = changes.get("home_score", item.home_score)
    away_score = changes.get("away_score", item.away_score)
    if (home_score is None) != (away_score is None):
        raise _invalid("home_score and away_score must be supplied together")

    actual_start = changes.get("actual_start_at", item.actual_start_at)
    actual_end = changes.get("actual_end_at", item.actual_end_at)
    if (
        actual_start is not None
        and actual_end is not None
        and actual_end < actual_start
    ):
        raise _invalid("actual_end_at must be on or after actual_start_at")

    scheduled_at = changes.get("scheduled_at", item.scheduled_at)
    if (
        scheduled_at != item.scheduled_at or new_team_id != item.team_id
    ) and await matches.squad_player_membership_mismatch(
        session, item.id, new_team_id, scheduled_at
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=" ".join(
                (
                    "Updated match team/date conflicts with a selected",
                    "player's membership",
                )
            ),
        )
    for field, value in changes.items():
        setattr(item, field, value)
    item.updated_by = actor.id
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match update conflicts with existing domain data",
        ) from exc
    await session.refresh(item)
    return item


async def delete_match(session: AsyncSession, match_id: UUID) -> None:
    item = await get_match(session, match_id)
    if await matches.match_has_history(session, match_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matches with squad or event history cannot be deleted",
        )
    await session.delete(item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match has dependent records and cannot be deleted",
        ) from exc


async def list_squad(
    session: AsyncSession, match_id: UUID, actor: User
) -> list[MatchSquad]:
    await get_match_for_actor(session, match_id, actor)
    squad = await matches.list_squad(session, match_id)
    if actor.role.name == RoleName.PLAYER:
        return [entry for entry in squad if entry.player.user_id == actor.id]
    return squad


async def add_squad_player(
    session: AsyncSession, match_id: UUID, payload: MatchSquadCreate
) -> MatchSquad:
    item = await get_match(session, match_id)
    player = await session.get(Player, payload.player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if not await matches.player_belongs_to_team_on_match_date(
        session, item, payload.player_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player was not a member of this team on the match date",
        )
    entry = MatchSquad(match_id=match_id, **payload.model_dump())
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=" ".join(
                (
                    "Player is already in this match squad or the captain is",
                    "already assigned",
                )
            ),
        ) from exc
    await session.refresh(entry)
    return await matches.get_squad_entry(session, match_id, payload.player_id)


async def update_squad_player(
    session: AsyncSession,
    match_id: UUID,
    player_id: UUID,
    payload: MatchSquadUpdate,
) -> MatchSquad:
    entry = await matches.get_squad_entry(session, match_id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match squad entry not found"
        )
    changes = payload.model_dump(exclude_unset=True)
    new_status = changes.get("squad_status", entry.squad_status)
    new_starting = changes.get("starting", entry.starting)
    if new_status == MatchSquadStatus.STARTER and not new_starting:
        raise _invalid("STARTER status requires starting=true")
    if new_starting and new_status not in {
        MatchSquadStatus.STARTER,
        MatchSquadStatus.WITHDRAWN,
    }:
        raise _invalid("starting=true requires STARTER or WITHDRAWN status")
    participation = await matches.get_participation(session, entry.id)
    if participation is not None and new_status in {
        MatchSquadStatus.SELECTED,
        MatchSquadStatus.UNUSED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A player with recorded participation cannot be marked unused",
        )
    if participation is not None and participation.started_at_minute is not None:
        if new_starting != (participation.started_at_minute == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Squad starter state conflicts with recorded participation",
            )
    for field, value in changes.items():
        setattr(entry, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The match already has a captain assigned",
        ) from exc
    await session.refresh(entry)
    return await matches.get_squad_entry(session, match_id, player_id)


async def remove_squad_player(
    session: AsyncSession, match_id: UUID, player_id: UUID
) -> None:
    entry = await matches.get_squad_entry(session, match_id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match squad entry not found"
        )
    if await matches.squad_entry_has_history(session, match_id, player_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=" ".join(
                (
                    "Squad entries with participation or event history cannot be",
                    "removed",
                )
            ),
        )
    await session.delete(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match squad entry has dependent records and cannot be removed",
        ) from exc


def _validate_participation_minutes(
    squad: MatchSquad,
    started_at_minute: int | None,
    ended_at_minute: int | None,
) -> None:
    if (
        started_at_minute is not None
        and ended_at_minute is not None
        and ended_at_minute < started_at_minute
    ):
        raise _invalid("ended_at_minute must not precede started_at_minute")
    if squad.starting and started_at_minute not in (None, 0):
        raise _invalid("Starting players must start at minute 0")
    if (
        not squad.starting
        and started_at_minute == 0
        and squad.squad_status != MatchSquadStatus.WITHDRAWN
    ):
        raise _invalid("Substitute participation cannot start at minute 0")


async def create_participation(
    session: AsyncSession,
    match_id: UUID,
    player_id: UUID,
    payload: MatchParticipationCreate,
) -> MatchParticipation:
    match = await get_match(session, match_id)
    if match.status not in {
        MatchStatus.LIVE,
        MatchStatus.COMPLETED,
        MatchStatus.ABANDONED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Participation can only be recorded for a match that has started",
        )
    entry = await matches.get_squad_entry(session, match_id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player is not in this match squad",
        )
    if entry.squad_status in {MatchSquadStatus.UNUSED, MatchSquadStatus.WITHDRAWN}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unused or withdrawn players cannot have participation recorded",
        )
    _validate_participation_minutes(
        entry, payload.started_at_minute, payload.ended_at_minute
    )
    if await matches.get_participation(session, entry.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player participation is already recorded",
        )
    participation = MatchParticipation(match_squad_id=entry.id, **payload.model_dump())
    session.add(participation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player participation is already recorded",
        ) from exc
    await session.refresh(participation)
    return participation


async def update_participation(
    session: AsyncSession,
    match_id: UUID,
    player_id: UUID,
    payload: MatchParticipationUpdate,
) -> MatchParticipation:
    entry = await matches.get_squad_entry(session, match_id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player is not in this match squad",
        )
    participation = await matches.get_participation(session, entry.id)
    if participation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participation not found"
        )
    changes = payload.model_dump(exclude_unset=True)
    started_at = changes.get("started_at_minute", participation.started_at_minute)
    ended_at = changes.get("ended_at_minute", participation.ended_at_minute)
    _validate_participation_minutes(entry, started_at, ended_at)
    for field, value in changes.items():
        setattr(participation, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Participation update conflicts with existing match data",
        ) from exc
    await session.refresh(participation)
    return participation


async def list_player_match_history(
    session: AsyncSession, player_id: UUID, actor: User, limit: int, offset: int
) -> list[Match]:
    await get_player_for_actor(session, player_id, actor, MATCH_READ_ROLES)
    return await matches.list_player_matches(session, player_id, limit, offset)


async def get_squad_entry_for_actor(
    session: AsyncSession, match_id: UUID, player_id: UUID, actor: User
) -> MatchSquad:
    await get_match_for_actor(session, match_id, actor)
    entry = await matches.get_squad_entry(session, match_id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match squad entry not found"
        )
    if actor.role.name == RoleName.PLAYER and entry.player.user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match squad entry not found"
        )
    return entry


async def get_participation_for_actor(
    session: AsyncSession, match_id: UUID, player_id: UUID, actor: User
) -> MatchParticipation:
    entry = await get_squad_entry_for_actor(session, match_id, player_id, actor)
    if entry.participation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participation not found"
        )
    return entry.participation


_SIDE_REQUIRED_EVENTS = frozenset(
    {
        MatchEventType.GOAL,
        MatchEventType.OWN_GOAL,
        MatchEventType.YELLOW_CARD,
        MatchEventType.RED_CARD,
        MatchEventType.SECOND_YELLOW,
        MatchEventType.SUBSTITUTION,
        MatchEventType.PENALTY_WON,
        MatchEventType.PENALTY_MISSED,
    }
)
_CARD_EVENTS = frozenset(
    {
        MatchEventType.YELLOW_CARD,
        MatchEventType.RED_CARD,
        MatchEventType.SECOND_YELLOW,
    }
)
_ASSIST_EVENTS = frozenset({MatchEventType.GOAL, MatchEventType.OWN_GOAL})
_PENALTY_EVENTS = frozenset(
    {
        MatchEventType.GOAL,
        MatchEventType.OWN_GOAL,
        MatchEventType.PENALTY_MISSED,
    }
)
_UNAVAILABLE_SQUAD = frozenset({MatchSquadStatus.UNUSED, MatchSquadStatus.WITHDRAWN})


def _validate_event_shape(
    event_type: MatchEventType,
    side: MatchSide,
    player_id: UUID | None,
    assist_player_id: UUID | None,
    is_penalty: bool,
) -> None:
    if event_type == MatchEventType.SUBSTITUTION:
        raise _invalid("Use the substitutions endpoint for substitution events")
    if event_type in _SIDE_REQUIRED_EVENTS and side == MatchSide.NEUTRAL:
        raise _invalid("This event requires HOME or AWAY side")
    if event_type in _CARD_EVENTS and player_id is None:
        raise _invalid("Card events require a player")
    if assist_player_id is not None and event_type not in _ASSIST_EVENTS:
        raise _invalid("An assist can only be recorded for a goal")
    if is_penalty and event_type not in _PENALTY_EVENTS:
        raise _invalid("is_penalty is only valid for goal/penalty events")


async def _validate_referenced_players(
    session: AsyncSession,
    match: Match,
    player_ids: tuple[UUID | None, ...],
) -> None:
    seen: set[UUID] = set()
    for player_id in player_ids:
        if player_id is None or player_id in seen:
            continue
        seen.add(player_id)
        if await session.get(Player, player_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
            )
        if not await matches.player_belongs_to_team_on_match_date(
            session, match, player_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player was not a member of this team on the match date",
            )
        if not await matches.player_has_squad_membership(session, match.id, player_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Player is not in this match squad",
            )


def _merged(changes: dict[str, object], field: str, current: object) -> object:
    return changes[field] if field in changes else current


async def list_events(
    session: AsyncSession,
    match_id: UUID,
    actor: User,
    limit: int,
    offset: int,
) -> list[MatchEvent]:
    await get_match_for_actor(session, match_id, actor)
    if actor.role.name == RoleName.PLAYER:
        return await matches.list_player_events(
            session, match_id, actor.id, limit, offset
        )
    return await matches.list_events(session, match_id, limit, offset)


async def get_event_for_actor(
    session: AsyncSession, match_id: UUID, event_id: UUID, actor: User
) -> MatchEvent:
    await get_match_for_actor(session, match_id, actor)
    if actor.role.name == RoleName.PLAYER:
        event = await matches.get_player_event(session, match_id, event_id, actor.id)
    else:
        event = await matches.get_event(session, match_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match event not found"
        )
    return event


async def create_event(
    session: AsyncSession, match_id: UUID, payload: MatchEventCreate, actor: User
) -> MatchEvent:
    match = await get_match(session, match_id)
    _validate_event_shape(
        payload.event_type,
        payload.side,
        payload.player_id,
        payload.assist_player_id,
        payload.is_penalty,
    )
    await _validate_referenced_players(
        session, match, (payload.player_id, payload.assist_player_id)
    )
    event = MatchEvent(match_id=match.id, created_by=actor.id, **payload.model_dump())
    session.add(event)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match event conflicts with existing domain data",
        ) from exc
    await session.refresh(event)
    return event


async def update_event(
    session: AsyncSession,
    match_id: UUID,
    event_id: UUID,
    payload: MatchEventUpdate,
) -> MatchEvent:
    event = await matches.get_event(session, match_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match event not found"
        )
    if event.event_type == MatchEventType.SUBSTITUTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Substitution events cannot be updated",
        )
    changes = payload.model_dump(exclude_unset=True)
    event_type = _merged(changes, "event_type", event.event_type)
    side = _merged(changes, "side", event.side)
    player_id = _merged(changes, "player_id", event.player_id)
    assist_player_id = _merged(changes, "assist_player_id", event.assist_player_id)
    is_penalty = _merged(changes, "is_penalty", event.is_penalty)
    _validate_event_shape(
        event_type, side, player_id, assist_player_id, bool(is_penalty)
    )
    match = await get_match(session, match_id)
    await _validate_referenced_players(session, match, (player_id, assist_player_id))
    for field, value in changes.items():
        setattr(event, field, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match event update conflicts with existing domain data",
        ) from exc
    await session.refresh(event)
    return event


async def delete_event(session: AsyncSession, match_id: UUID, event_id: UUID) -> None:
    event = await matches.get_event(session, match_id, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match event not found"
        )
    substitution = await matches.get_substitution_for_event(session, event.id)
    try:
        if substitution is not None:
            await session.delete(substitution)
            await session.flush()
        await session.delete(event)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match event has dependent records and cannot be deleted",
        ) from exc


def _substitution_side(match: Match, requested: MatchSide | None) -> MatchSide:
    if requested == MatchSide.NEUTRAL:
        raise _invalid("Substitution side must be HOME or AWAY")
    if match.home_away == MatchSide.NEUTRAL:
        if requested is None:
            raise _invalid("side is required when the match is neutral")
        return requested
    if requested is not None and requested != match.home_away:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Substitution side does not match the club side",
        )
    return match.home_away if requested is None else requested


async def _require_substitution_player(
    session: AsyncSession, match: Match, player_id: UUID
) -> MatchSquad:
    if await session.get(Player, player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if not await matches.player_belongs_to_team_on_match_date(
        session, match, player_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player was not a member of this team on the match date",
        )
    entry = await matches.get_squad_entry(session, match.id, player_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player is not in this match squad",
        )
    if entry.squad_status in _UNAVAILABLE_SQUAD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unused or withdrawn players cannot be substituted",
        )
    return entry


async def list_substitutions(
    session: AsyncSession, match_id: UUID, actor: User
) -> list[Substitution]:
    await get_match_for_actor(session, match_id, actor)
    if actor.role.name == RoleName.PLAYER:
        return await matches.list_player_substitutions(session, match_id, actor.id)
    return await matches.list_substitutions(session, match_id)


async def get_substitution_for_actor(
    session: AsyncSession, match_id: UUID, substitution_id: UUID, actor: User
) -> Substitution:
    await get_match_for_actor(session, match_id, actor)
    if actor.role.name == RoleName.PLAYER:
        item = await matches.get_player_substitution(
            session, match_id, substitution_id, actor.id
        )
    else:
        item = await matches.get_substitution(session, match_id, substitution_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Substitution not found"
        )
    return item


async def create_substitution(
    session: AsyncSession,
    match_id: UUID,
    payload: SubstitutionCreate,
    actor: User,
) -> Substitution:
    match = await get_match(session, match_id)
    side = _substitution_side(match, payload.side)
    out_entry = await _require_substitution_player(
        session, match, payload.player_out_id
    )
    in_entry = await _require_substitution_player(session, match, payload.player_in_id)
    conflict = await matches.substitution_conflict_detail(
        session, match.id, payload.player_out_id, payload.player_in_id
    )
    if conflict is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)
    if not out_entry.starting and not await matches.player_has_entered_match(
        session, match.id, payload.player_out_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player coming off is not on the pitch",
        )
    if in_entry.starting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player coming on is already in the match",
        )
    event = MatchEvent(
        match_id=match.id,
        side=side,
        player_id=payload.player_out_id,
        related_player_id=payload.player_in_id,
        event_type=MatchEventType.SUBSTITUTION,
        minute=payload.minute,
        added_time_minute=payload.added_time_minute,
        source=MatchEventSource.MANUAL,
        is_penalty=False,
        created_by=actor.id,
    )
    session.add(event)
    try:
        await session.flush()
        substitution = Substitution(
            match_id=match.id,
            player_out_id=payload.player_out_id,
            player_in_id=payload.player_in_id,
            event_id=event.id,
            side=side,
            minute=payload.minute,
            added_time_minute=payload.added_time_minute,
            reason=payload.reason,
            created_by=actor.id,
        )
        session.add(substitution)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Substitution conflicts with existing match data",
        ) from exc
    await session.refresh(substitution)
    return substitution
