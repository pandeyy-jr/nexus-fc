from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.phase04_dependencies import DevelopmentManager
from app.schemas.development import (
    PlayerDevelopmentAssessmentCreate,
    PlayerDevelopmentAssessmentResponse,
    PlayerDevelopmentAssessmentUpdate,
    PlayerDevelopmentGoalCreate,
    PlayerDevelopmentGoalResponse,
    PlayerDevelopmentGoalUpdate,
)
from app.services.development import (
    cancel_goal,
    create_assessment,
    create_goal,
    get_assessment,
    get_goal,
    list_assessments,
    list_goals,
    update_assessment,
    update_goal,
)

router = APIRouter()


@router.get(
    "/players/{player_id}/development/goals",
    response_model=list[PlayerDevelopmentGoalResponse],
)
async def get_development_goals(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlayerDevelopmentGoalResponse]:
    return await list_goals(session, player_id, actor, limit, offset)


@router.post(
    "/players/{player_id}/development/goals",
    response_model=PlayerDevelopmentGoalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_development_goal(
    player_id: UUID,
    payload: PlayerDevelopmentGoalCreate,
    session: SessionDependency,
    actor: DevelopmentManager,
) -> PlayerDevelopmentGoalResponse:
    return await create_goal(session, player_id, payload, actor)


@router.get(
    "/players/{player_id}/development/goals/{goal_id}",
    response_model=PlayerDevelopmentGoalResponse,
)
async def get_development_goal(
    player_id: UUID,
    goal_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> PlayerDevelopmentGoalResponse:
    return await get_goal(session, player_id, goal_id, actor)


@router.patch(
    "/players/{player_id}/development/goals/{goal_id}",
    response_model=PlayerDevelopmentGoalResponse,
)
async def patch_development_goal(
    player_id: UUID,
    goal_id: UUID,
    payload: PlayerDevelopmentGoalUpdate,
    session: SessionDependency,
    _: DevelopmentManager,
) -> PlayerDevelopmentGoalResponse:
    return await update_goal(session, player_id, goal_id, payload)


@router.delete(
    "/players/{player_id}/development/goals/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_development_goal(
    player_id: UUID,
    goal_id: UUID,
    session: SessionDependency,
    _: DevelopmentManager,
) -> Response:
    await cancel_goal(session, player_id, goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/players/{player_id}/development/assessments",
    response_model=list[PlayerDevelopmentAssessmentResponse],
)
async def get_development_assessments(
    player_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlayerDevelopmentAssessmentResponse]:
    return await list_assessments(session, player_id, actor, limit, offset)


@router.post(
    "/players/{player_id}/development/assessments",
    response_model=PlayerDevelopmentAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_development_assessment(
    player_id: UUID,
    payload: PlayerDevelopmentAssessmentCreate,
    session: SessionDependency,
    actor: DevelopmentManager,
) -> PlayerDevelopmentAssessmentResponse:
    return await create_assessment(session, player_id, payload, actor)


@router.get(
    "/players/{player_id}/development/assessments/{assessment_id}",
    response_model=PlayerDevelopmentAssessmentResponse,
)
async def get_development_assessment(
    player_id: UUID,
    assessment_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> PlayerDevelopmentAssessmentResponse:
    return await get_assessment(session, player_id, assessment_id, actor)


@router.patch(
    "/players/{player_id}/development/assessments/{assessment_id}",
    response_model=PlayerDevelopmentAssessmentResponse,
)
async def patch_development_assessment(
    player_id: UUID,
    assessment_id: UUID,
    payload: PlayerDevelopmentAssessmentUpdate,
    session: SessionDependency,
    _: DevelopmentManager,
) -> PlayerDevelopmentAssessmentResponse:
    return await update_assessment(session, player_id, assessment_id, payload)
