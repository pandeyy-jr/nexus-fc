from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.phase04_dependencies import AvailabilityManager
from app.schemas.availability import (
    PlayerAvailabilityCreate,
    PlayerAvailabilityResponse,
    PlayerAvailabilityUpdate,
)
from app.services.availability import (
    create_availability,
    end_availability,
    get_current_availability,
    list_availability,
    update_availability,
)

router = APIRouter()


@router.get(
    "/players/{player_id}/availability",
    response_model=list[PlayerAvailabilityResponse],
)
async def get_player_availability(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlayerAvailabilityResponse]:
    return await list_availability(session, player_id, actor, limit, offset)


@router.get(
    "/players/{player_id}/availability/current",
    response_model=PlayerAvailabilityResponse | None,
)
async def get_current_player_availability(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> PlayerAvailabilityResponse | None:
    return await get_current_availability(session, player_id, actor)


@router.post(
    "/players/{player_id}/availability",
    response_model=PlayerAvailabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_player_availability(
    player_id: UUID,
    payload: PlayerAvailabilityCreate,
    session: SessionDependency,
    actor: AvailabilityManager,
) -> PlayerAvailabilityResponse:
    return await create_availability(session, player_id, payload, actor)


@router.patch(
    "/players/{player_id}/availability/{availability_id}",
    response_model=PlayerAvailabilityResponse,
)
async def patch_player_availability(
    player_id: UUID,
    availability_id: UUID,
    payload: PlayerAvailabilityUpdate,
    session: SessionDependency,
    _: AvailabilityManager,
) -> PlayerAvailabilityResponse:
    return await update_availability(session, player_id, availability_id, payload)


@router.delete(
    "/players/{player_id}/availability/{availability_id}",
    response_model=PlayerAvailabilityResponse,
)
async def delete_player_availability(
    player_id: UUID,
    availability_id: UUID,
    session: SessionDependency,
    _: AvailabilityManager,
) -> PlayerAvailabilityResponse:
    return await end_availability(session, player_id, availability_id)
