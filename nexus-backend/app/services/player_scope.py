from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.db.models.player import Player
from app.db.models.user import User
from app.repositories.players import get_by_id


async def get_player_for_actor(
    session: AsyncSession,
    player_id: UUID,
    actor: User,
    staff_roles: tuple[RoleName, ...],
) -> Player:
    player = await get_by_id(session, player_id)
    if actor.role.name == RoleName.PLAYER:
        if player is None or player.user_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
            )
        return player
    if actor.role.name not in staff_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
        )
    return player
