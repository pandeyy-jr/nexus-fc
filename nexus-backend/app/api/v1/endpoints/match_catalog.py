from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.match_dependencies import MatchCatalogManager
from app.schemas.match_catalog import (
    CompetitionCreate,
    CompetitionResponse,
    CompetitionUpdate,
    OpponentCreate,
    OpponentResponse,
    OpponentUpdate,
    VenueCreate,
    VenueResponse,
    VenueUpdate,
)
from app.services.match_catalog import (
    create_competition,
    create_opponent,
    create_venue,
    delete_competition,
    delete_opponent,
    delete_venue,
    get_competition,
    get_opponent,
    get_venue,
    list_competitions,
    list_opponents,
    list_venues,
    update_competition,
    update_opponent,
    update_venue,
)

router = APIRouter()


@router.get("/opponents", response_model=list[OpponentResponse])
async def get_opponents(
    session: SessionDependency,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OpponentResponse]:
    return await list_opponents(session, limit, offset)


@router.post(
    "/opponents",
    response_model=OpponentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_opponent(
    payload: OpponentCreate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> OpponentResponse:
    return await create_opponent(session, payload)


@router.get("/opponents/{opponent_id}", response_model=OpponentResponse)
async def get_opponent_detail(
    opponent_id: UUID, session: SessionDependency, _: CurrentUser
) -> OpponentResponse:
    return await get_opponent(session, opponent_id)


@router.patch("/opponents/{opponent_id}", response_model=OpponentResponse)
async def patch_opponent(
    opponent_id: UUID,
    payload: OpponentUpdate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> OpponentResponse:
    return await update_opponent(session, opponent_id, payload)


@router.delete("/opponents/{opponent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_opponent(
    opponent_id: UUID, session: SessionDependency, _: MatchCatalogManager
) -> Response:
    await delete_opponent(session, opponent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/venues", response_model=list[VenueResponse])
async def get_venues(
    session: SessionDependency,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[VenueResponse]:
    return await list_venues(session, limit, offset)


@router.post(
    "/venues", response_model=VenueResponse, status_code=status.HTTP_201_CREATED
)
async def post_venue(
    payload: VenueCreate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> VenueResponse:
    return await create_venue(session, payload)


@router.get("/venues/{venue_id}", response_model=VenueResponse)
async def get_venue_detail(
    venue_id: UUID, session: SessionDependency, _: CurrentUser
) -> VenueResponse:
    return await get_venue(session, venue_id)


@router.patch("/venues/{venue_id}", response_model=VenueResponse)
async def patch_venue(
    venue_id: UUID,
    payload: VenueUpdate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> VenueResponse:
    return await update_venue(session, venue_id, payload)


@router.delete("/venues/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_venue(
    venue_id: UUID, session: SessionDependency, _: MatchCatalogManager
) -> Response:
    await delete_venue(session, venue_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/competitions", response_model=list[CompetitionResponse])
async def get_competitions(
    session: SessionDependency,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CompetitionResponse]:
    return await list_competitions(session, limit, offset)


@router.post(
    "/competitions",
    response_model=CompetitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_competition(
    payload: CompetitionCreate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> CompetitionResponse:
    return await create_competition(session, payload)


@router.get("/competitions/{competition_id}", response_model=CompetitionResponse)
async def get_competition_detail(
    competition_id: UUID, session: SessionDependency, _: CurrentUser
) -> CompetitionResponse:
    return await get_competition(session, competition_id)


@router.patch("/competitions/{competition_id}", response_model=CompetitionResponse)
async def patch_competition(
    competition_id: UUID,
    payload: CompetitionUpdate,
    session: SessionDependency,
    _: MatchCatalogManager,
) -> CompetitionResponse:
    return await update_competition(session, competition_id, payload)


@router.delete("/competitions/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_competition(
    competition_id: UUID, session: SessionDependency, _: MatchCatalogManager
) -> Response:
    await delete_competition(session, competition_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
