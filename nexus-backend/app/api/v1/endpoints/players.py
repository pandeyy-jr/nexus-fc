from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.domain_dependencies import PlayerCreator, PlayerDeleter, PlayerUpdater
from app.schemas.players import PlayerCreate, PlayerResponse, PlayerUpdate
from app.services.players import (
    create_player,
    delete_player,
    get_player,
    list_players,
    update_player,
)

router = APIRouter()


@router.get("", response_model=list[PlayerResponse])
async def get_players(actor: CurrentUser, session: SessionDependency) -> list:
    return await list_players(session, actor)


@router.post("", response_model=PlayerResponse, status_code=status.HTTP_201_CREATED)
async def post_player(
    payload: PlayerCreate,
    session: SessionDependency,
    _: PlayerCreator,
) -> PlayerResponse:
    return await create_player(session, payload)


@router.get("/{player_id}", response_model=PlayerResponse)
async def get_player_profile(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> PlayerResponse:
    return await get_player(session, player_id, actor)


@router.patch("/{player_id}", response_model=PlayerResponse)
async def patch_player(
    player_id: UUID,
    payload: PlayerUpdate,
    session: SessionDependency,
    actor: PlayerUpdater,
) -> PlayerResponse:
    return await update_player(session, player_id, payload, actor)


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_player(
    player_id: UUID,
    session: SessionDependency,
    _: PlayerDeleter,
) -> Response:
    await delete_player(session, player_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
