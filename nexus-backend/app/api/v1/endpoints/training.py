from datetime import date
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.phase04_dependencies import (
    TrainingParticipationCreator,
    TrainingParticipationDeleter,
    TrainingParticipationManager,
    TrainingReader,
    TrainingSessionManager,
)
from app.schemas.training import (
    PlayerTrainingHistoryResponse,
    TrainingParticipationCreate,
    TrainingParticipationResponse,
    TrainingParticipationUpdate,
    TrainingSessionCreate,
    TrainingSessionResponse,
    TrainingSessionUpdate,
)
from app.services.training import (
    create_participation,
    create_session,
    delete_participation,
    delete_session,
    get_player_training_history,
    get_session,
    list_participations,
    list_sessions,
    update_participation,
    update_session,
)

router = APIRouter()


@router.get("/training/sessions", response_model=list[TrainingSessionResponse])
async def get_training_sessions(
    session: SessionDependency,
    _: TrainingReader,
    team_id: UUID | None = None,
    session_date_from: date | None = None,
    session_date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TrainingSessionResponse]:
    if (
        session_date_from is not None
        and session_date_to is not None
        and session_date_to < session_date_from
    ):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="session_date_to must be on or after session_date_from",
        )
    return await list_sessions(
        session, team_id, session_date_from, session_date_to, limit, offset
    )


@router.post(
    "/training/sessions",
    response_model=TrainingSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_training_session(
    payload: TrainingSessionCreate,
    session: SessionDependency,
    actor: TrainingSessionManager,
) -> TrainingSessionResponse:
    return await create_session(session, payload, actor)


@router.get("/training/sessions/{session_id}", response_model=TrainingSessionResponse)
async def get_training_session(
    session_id: UUID,
    session: SessionDependency,
    _: TrainingReader,
) -> TrainingSessionResponse:
    return await get_session(session, session_id)


@router.patch("/training/sessions/{session_id}", response_model=TrainingSessionResponse)
async def patch_training_session(
    session_id: UUID,
    payload: TrainingSessionUpdate,
    session: SessionDependency,
    _: TrainingSessionManager,
) -> TrainingSessionResponse:
    return await update_session(session, session_id, payload)


@router.delete(
    "/training/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_training_session(
    session_id: UUID,
    session: SessionDependency,
    _: TrainingSessionManager,
) -> Response:
    await delete_session(session, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/training/sessions/{session_id}/players",
    response_model=list[TrainingParticipationResponse],
)
async def get_session_players(
    session_id: UUID,
    session: SessionDependency,
    _: TrainingReader,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TrainingParticipationResponse]:
    return await list_participations(session, session_id, limit, offset)


@router.post(
    "/training/sessions/{session_id}/players",
    response_model=TrainingParticipationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_session_player(
    session_id: UUID,
    payload: TrainingParticipationCreate,
    session: SessionDependency,
    _: TrainingParticipationCreator,
) -> TrainingParticipationResponse:
    return await create_participation(session, session_id, payload)


@router.patch(
    "/training/sessions/{session_id}/players/{player_id}",
    response_model=TrainingParticipationResponse,
)
async def patch_session_player(
    session_id: UUID,
    player_id: UUID,
    payload: TrainingParticipationUpdate,
    session: SessionDependency,
    actor: TrainingParticipationManager,
) -> TrainingParticipationResponse:
    return await update_participation(session, session_id, player_id, payload, actor)


@router.delete(
    "/training/sessions/{session_id}/players/{player_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_session_player(
    session_id: UUID,
    player_id: UUID,
    session: SessionDependency,
    _: TrainingParticipationDeleter,
) -> Response:
    await delete_participation(session, session_id, player_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/players/{player_id}/training",
    response_model=list[PlayerTrainingHistoryResponse],
)
async def get_player_training(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlayerTrainingHistoryResponse]:
    _, history = await get_player_training_history(
        session, player_id, actor, limit, offset
    )
    return history
