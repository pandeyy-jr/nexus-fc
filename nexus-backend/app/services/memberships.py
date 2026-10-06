from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.football import SquadStatus
from app.db.models.membership import PlayerTeamMembership
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.types import utc_now
from app.repositories import memberships
from app.schemas.memberships import MembershipCreate, MembershipUpdate


async def list_team_memberships(
    session: AsyncSession,
    team_id: UUID,
    include_history: bool,
    player_user_id: UUID | None = None,
) -> list[PlayerTeamMembership]:
    return await memberships.list_for_team(
        session, team_id, include_history, player_user_id
    )


async def create_membership(
    session: AsyncSession,
    team_id: UUID,
    player_id: UUID,
    payload: MembershipCreate,
) -> PlayerTeamMembership:
    if await session.get(Team, team_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )
    if await session.get(Player, player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    if payload.left_at is None and await memberships.get_current(
        session, team_id, player_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player already has a current membership in this team",
        )

    left_at = payload.left_at
    if payload.squad_status == SquadStatus.RELEASED and left_at is None:
        left_at = utc_now()
    membership = PlayerTeamMembership(
        team_id=team_id,
        player_id=player_id,
        joined_at=payload.joined_at,
        left_at=left_at,
        squad_status=payload.squad_status,
    )
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player already has a current membership in this team",
        ) from exc
    await session.refresh(membership)
    return membership


async def _get_current_membership(
    session: AsyncSession, team_id: UUID, player_id: UUID
) -> PlayerTeamMembership:
    membership = await memberships.get_current(session, team_id, player_id)
    if membership is not None:
        return membership
    if await memberships.get_latest(session, team_id, player_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Historical memberships cannot be modified",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found"
    )


async def update_membership(
    session: AsyncSession,
    team_id: UUID,
    player_id: UUID,
    payload: MembershipUpdate,
) -> PlayerTeamMembership:
    membership = await _get_current_membership(session, team_id, player_id)
    if payload.left_at is not None and payload.left_at < membership.joined_at:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="left_at must be on or after joined_at",
        )
    if payload.squad_status is not None:
        membership.squad_status = payload.squad_status
        if payload.squad_status == SquadStatus.RELEASED and payload.left_at is None:
            membership.left_at = utc_now()
    if payload.left_at is not None:
        membership.left_at = payload.left_at
    await session.commit()
    await session.refresh(membership)
    return membership


async def end_membership(
    session: AsyncSession, team_id: UUID, player_id: UUID
) -> PlayerTeamMembership:
    membership = await _get_current_membership(session, team_id, player_id)
    now = utc_now()
    if now < membership.joined_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A future membership cannot be ended before it starts",
        )
    membership.left_at = now
    membership.squad_status = SquadStatus.INACTIVE
    await session.commit()
    await session.refresh(membership)
    return membership
