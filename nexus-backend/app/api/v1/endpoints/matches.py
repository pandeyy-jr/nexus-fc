from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from fastapi import status as http_status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.match_dependencies import (
    MatchEventDeleter,
    MatchEventWriter,
    MatchManager,
)
from app.core.matches import MatchStatus
from app.schemas.match_events import (
    MatchEventCreate,
    MatchEventResponse,
    MatchEventUpdate,
    MatchParticipationCreate,
    MatchParticipationResponse,
    MatchParticipationUpdate,
    MatchSquadCreate,
    MatchSquadResponse,
    MatchSquadUpdate,
    SubstitutionCreate,
    SubstitutionResponse,
)
from app.schemas.matches import MatchCreate, MatchResponse, MatchUpdate
from app.services.matches import (
    add_squad_player,
    create_event,
    create_match,
    create_participation,
    create_substitution,
    delete_event,
    delete_match,
    get_event_for_actor,
    get_match_for_actor,
    get_participation_for_actor,
    get_substitution_for_actor,
    list_events,
    list_matches,
    list_squad,
    list_substitutions,
    remove_squad_player,
    update_event,
    update_match,
    update_participation,
    update_squad_player,
)

router = APIRouter()


@router.get("", response_model=list[MatchResponse])
async def get_matches(
    session: SessionDependency,
    actor: CurrentUser,
    team_id: UUID | None = None,
    opponent_id: UUID | None = None,
    status: MatchStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchResponse]:
    return await list_matches(
        session,
        actor,
        team_id,
        opponent_id,
        status,
        date_from,
        date_to,
        limit,
        offset,
    )


@router.get("/{match_id}", response_model=MatchResponse)
async def get_match_detail(
    match_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> MatchResponse:
    return await get_match_for_actor(session, match_id, actor)


@router.post("", response_model=MatchResponse, status_code=http_status.HTTP_201_CREATED)
async def post_match(
    payload: MatchCreate,
    session: SessionDependency,
    actor: MatchManager,
) -> MatchResponse:
    return await create_match(session, payload, actor)


@router.patch("/{match_id}", response_model=MatchResponse)
async def patch_match(
    match_id: UUID,
    payload: MatchUpdate,
    session: SessionDependency,
    actor: MatchManager,
) -> MatchResponse:
    return await update_match(session, match_id, payload, actor)


@router.delete("/{match_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def remove_match(
    match_id: UUID,
    session: SessionDependency,
    _: MatchManager,
) -> Response:
    await delete_match(session, match_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get("/{match_id}/squad", response_model=list[MatchSquadResponse])
async def get_match_squad(
    match_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> list[MatchSquadResponse]:
    return await list_squad(session, match_id, actor)


@router.post(
    "/{match_id}/squad",
    response_model=MatchSquadResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_match_squad_player(
    match_id: UUID,
    payload: MatchSquadCreate,
    session: SessionDependency,
    _: MatchManager,
) -> MatchSquadResponse:
    return await add_squad_player(session, match_id, payload)


@router.patch("/{match_id}/squad/{player_id}", response_model=MatchSquadResponse)
async def patch_match_squad_player(
    match_id: UUID,
    player_id: UUID,
    payload: MatchSquadUpdate,
    session: SessionDependency,
    _: MatchManager,
) -> MatchSquadResponse:
    return await update_squad_player(session, match_id, player_id, payload)


@router.delete(
    "/{match_id}/squad/{player_id}", status_code=http_status.HTTP_204_NO_CONTENT
)
async def delete_match_squad_player(
    match_id: UUID,
    player_id: UUID,
    session: SessionDependency,
    _: MatchManager,
) -> Response:
    await remove_squad_player(session, match_id, player_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get(
    "/{match_id}/squad/{player_id}/participation",
    response_model=MatchParticipationResponse,
)
async def get_match_participation(
    match_id: UUID,
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> MatchParticipationResponse:
    return await get_participation_for_actor(session, match_id, player_id, actor)


@router.post(
    "/{match_id}/squad/{player_id}/participation",
    response_model=MatchParticipationResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_match_participation(
    match_id: UUID,
    player_id: UUID,
    payload: MatchParticipationCreate,
    session: SessionDependency,
    _: MatchManager,
) -> MatchParticipationResponse:
    return await create_participation(session, match_id, player_id, payload)


@router.patch(
    "/{match_id}/squad/{player_id}/participation",
    response_model=MatchParticipationResponse,
)
async def patch_match_participation(
    match_id: UUID,
    player_id: UUID,
    payload: MatchParticipationUpdate,
    session: SessionDependency,
    _: MatchManager,
) -> MatchParticipationResponse:
    return await update_participation(session, match_id, player_id, payload)


@router.get("/{match_id}/events", response_model=list[MatchEventResponse])
async def get_match_events(
    match_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MatchEventResponse]:
    return await list_events(session, match_id, actor, limit, offset)


@router.post(
    "/{match_id}/events",
    response_model=MatchEventResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_match_event(
    match_id: UUID,
    payload: MatchEventCreate,
    session: SessionDependency,
    actor: MatchEventWriter,
) -> MatchEventResponse:
    return await create_event(session, match_id, payload, actor)


@router.get("/{match_id}/events/{event_id}", response_model=MatchEventResponse)
async def get_match_event(
    match_id: UUID,
    event_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> MatchEventResponse:
    return await get_event_for_actor(session, match_id, event_id, actor)


@router.patch("/{match_id}/events/{event_id}", response_model=MatchEventResponse)
async def patch_match_event(
    match_id: UUID,
    event_id: UUID,
    payload: MatchEventUpdate,
    session: SessionDependency,
    _: MatchEventWriter,
) -> MatchEventResponse:
    return await update_event(session, match_id, event_id, payload)


@router.delete(
    "/{match_id}/events/{event_id}", status_code=http_status.HTTP_204_NO_CONTENT
)
async def remove_match_event(
    match_id: UUID,
    event_id: UUID,
    session: SessionDependency,
    _: MatchEventDeleter,
) -> Response:
    await delete_event(session, match_id, event_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.get("/{match_id}/substitutions", response_model=list[SubstitutionResponse])
async def get_match_substitutions(
    match_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> list[SubstitutionResponse]:
    return await list_substitutions(session, match_id, actor)


@router.post(
    "/{match_id}/substitutions",
    response_model=SubstitutionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_match_substitution(
    match_id: UUID,
    payload: SubstitutionCreate,
    session: SessionDependency,
    actor: MatchEventWriter,
) -> SubstitutionResponse:
    return await create_substitution(session, match_id, payload, actor)


@router.get(
    "/{match_id}/substitutions/{substitution_id}",
    response_model=SubstitutionResponse,
)
async def get_match_substitution(
    match_id: UUID,
    substitution_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> SubstitutionResponse:
    return await get_substitution_for_actor(session, match_id, substitution_id, actor)
