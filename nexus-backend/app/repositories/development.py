from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.development import (
    PlayerDevelopmentAssessment,
    PlayerDevelopmentGoal,
)


async def get_goal(
    session: AsyncSession, player_id: UUID, goal_id: UUID
) -> PlayerDevelopmentGoal | None:
    result = await session.execute(
        select(PlayerDevelopmentGoal).where(
            PlayerDevelopmentGoal.id == goal_id,
            PlayerDevelopmentGoal.player_id == player_id,
        )
    )
    return result.scalar_one_or_none()


async def list_goals(
    session: AsyncSession, player_id: UUID, limit: int, offset: int
) -> list[PlayerDevelopmentGoal]:
    result = await session.execute(
        select(PlayerDevelopmentGoal)
        .where(PlayerDevelopmentGoal.player_id == player_id)
        .order_by(PlayerDevelopmentGoal.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def has_assessments(session: AsyncSession, goal_id: UUID) -> bool:
    result = await session.execute(
        select(PlayerDevelopmentAssessment.id)
        .where(PlayerDevelopmentAssessment.goal_id == goal_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_assessment(
    session: AsyncSession, player_id: UUID, assessment_id: UUID
) -> PlayerDevelopmentAssessment | None:
    result = await session.execute(
        select(PlayerDevelopmentAssessment).where(
            PlayerDevelopmentAssessment.id == assessment_id,
            PlayerDevelopmentAssessment.player_id == player_id,
        )
    )
    return result.scalar_one_or_none()


async def list_assessments(
    session: AsyncSession, player_id: UUID, limit: int, offset: int
) -> list[PlayerDevelopmentAssessment]:
    result = await session.execute(
        select(PlayerDevelopmentAssessment)
        .where(PlayerDevelopmentAssessment.player_id == player_id)
        .order_by(PlayerDevelopmentAssessment.assessment_date.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
