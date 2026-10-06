from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import DEVELOPMENT_READ_ROLES
from app.core.training import DevelopmentStatus
from app.db.models.development import (
    PlayerDevelopmentAssessment,
    PlayerDevelopmentGoal,
)
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.models.user import User
from app.repositories import development
from app.repositories.memberships import get_current as get_current_membership
from app.schemas.development import (
    PlayerDevelopmentAssessmentCreate,
    PlayerDevelopmentAssessmentUpdate,
    PlayerDevelopmentGoalCreate,
    PlayerDevelopmentGoalUpdate,
)
from app.services.player_scope import get_player_for_actor


async def list_goals(
    session: AsyncSession,
    player_id: UUID,
    actor: User,
    limit: int,
    offset: int,
) -> list[PlayerDevelopmentGoal]:
    await get_player_for_actor(session, player_id, actor, DEVELOPMENT_READ_ROLES)
    return await development.list_goals(session, player_id, limit, offset)


async def get_goal(
    session: AsyncSession,
    player_id: UUID,
    goal_id: UUID,
    actor: User,
) -> PlayerDevelopmentGoal:
    await get_player_for_actor(session, player_id, actor, DEVELOPMENT_READ_ROLES)
    goal = await development.get_goal(session, player_id, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Development goal not found"
        )
    return goal


async def _validate_goal_team(
    session: AsyncSession, player_id: UUID, team_id: UUID | None
) -> None:
    if team_id is None:
        return
    if await session.get(Team, team_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    if await get_current_membership(session, team_id, player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player must have a current membership in the goal team",
        )


async def create_goal(
    session: AsyncSession,
    player_id: UUID,
    payload: PlayerDevelopmentGoalCreate,
    actor: User,
) -> PlayerDevelopmentGoal:
    if await session.get(Player, player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    await _validate_goal_team(session, player_id, payload.team_id)
    goal = PlayerDevelopmentGoal(
        player_id=player_id,
        created_by=actor.id,
        **payload.model_dump(),
    )
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return goal


async def update_goal(
    session: AsyncSession,
    player_id: UUID,
    goal_id: UUID,
    payload: PlayerDevelopmentGoalUpdate,
) -> PlayerDevelopmentGoal:
    goal = await development.get_goal(session, player_id, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Development goal not found"
        )
    changes = payload.model_dump(exclude_unset=True)
    await _validate_goal_team(session, player_id, changes.get("team_id", goal.team_id))
    for field, value in changes.items():
        setattr(goal, field, value)
    await session.commit()
    await session.refresh(goal)
    return goal


async def cancel_goal(session: AsyncSession, player_id: UUID, goal_id: UUID) -> None:
    goal = await development.get_goal(session, player_id, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Development goal not found"
        )
    goal.status = DevelopmentStatus.CANCELLED
    await session.commit()


async def list_assessments(
    session: AsyncSession,
    player_id: UUID,
    actor: User,
    limit: int,
    offset: int,
) -> list[PlayerDevelopmentAssessment]:
    await get_player_for_actor(session, player_id, actor, DEVELOPMENT_READ_ROLES)
    return await development.list_assessments(session, player_id, limit, offset)


async def get_assessment(
    session: AsyncSession,
    player_id: UUID,
    assessment_id: UUID,
    actor: User,
) -> PlayerDevelopmentAssessment:
    await get_player_for_actor(session, player_id, actor, DEVELOPMENT_READ_ROLES)
    assessment = await development.get_assessment(session, player_id, assessment_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development assessment not found",
        )
    return assessment


async def create_assessment(
    session: AsyncSession,
    player_id: UUID,
    payload: PlayerDevelopmentAssessmentCreate,
    actor: User,
) -> PlayerDevelopmentAssessment:
    if await session.get(Player, player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if payload.goal_id is not None:
        goal = await development.get_goal(session, player_id, payload.goal_id)
        if goal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Development goal not found for this player",
            )
    assessment = PlayerDevelopmentAssessment(
        player_id=player_id,
        assessor_id=actor.id,
        **payload.model_dump(),
    )
    session.add(assessment)
    await session.commit()
    await session.refresh(assessment)
    return assessment


async def update_assessment(
    session: AsyncSession,
    player_id: UUID,
    assessment_id: UUID,
    payload: PlayerDevelopmentAssessmentUpdate,
) -> PlayerDevelopmentAssessment:
    assessment = await development.get_assessment(session, player_id, assessment_id)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development assessment not found",
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(assessment, field, value)
    await session.commit()
    await session.refresh(assessment)
    return assessment
