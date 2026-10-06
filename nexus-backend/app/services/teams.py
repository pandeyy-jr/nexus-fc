from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import TEAM_VIEW_ROLES
from app.core.roles import RoleName
from app.db.models.team import Team
from app.db.models.user import User
from app.repositories import teams
from app.schemas.teams import TeamCreate, TeamUpdate


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


async def list_teams(session: AsyncSession, actor: User) -> list[Team]:
    if actor.role.name == RoleName.PLAYER:
        return await teams.list_teams(session, player_user_id=actor.id)
    if actor.role.name not in TEAM_VIEW_ROLES:
        raise _forbidden()
    return await teams.list_teams(session)


async def get_team(session: AsyncSession, team_id: UUID, actor: User) -> Team:
    team = await teams.get_by_id(session, team_id)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    if actor.role.name == RoleName.PLAYER:
        visible_teams = await teams.list_teams(session, player_user_id=actor.id)
        if all(visible.id != team_id for visible in visible_teams):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
            )
    elif actor.role.name not in TEAM_VIEW_ROLES:
        raise _forbidden()
    return team


async def create_team(session: AsyncSession, payload: TeamCreate) -> Team:
    team = Team(**payload.model_dump())
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


async def update_team(
    session: AsyncSession, team_id: UUID, payload: TeamUpdate
) -> Team:
    team = await teams.get_by_id(session, team_id)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(team, field, value)
    await session.commit()
    await session.refresh(team)
    return team


async def delete_team(session: AsyncSession, team_id: UUID) -> None:
    team = await teams.get_by_id(session, team_id)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    if await teams.has_memberships(session, team_id) or await teams.has_phase04_records(
        session, team_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teams with historical records cannot be deleted",
        )
    await session.delete(team)
    await session.commit()
