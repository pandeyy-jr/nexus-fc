from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.db.models.user import User
from app.repositories import roles, users


async def list_users(session: AsyncSession, limit: int, offset: int) -> list[User]:
    return await users.list_users(session, limit, offset)


async def get_user(session: AsyncSession, user_id: UUID) -> User:
    user = await users.get_by_id(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


async def update_user_status(
    session: AsyncSession,
    user_id: UUID,
    is_active: bool,
    actor_id: UUID,
) -> User:
    user = await get_user(session, user_id)
    if user.is_active == is_active:
        return user
    if user_id == actor_id and not is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admins cannot deactivate their own account",
        )
    if user.is_active and user.role.name == RoleName.ADMIN and not is_active:
        await roles.lock_by_name(session, RoleName.ADMIN)
        if await users.count_active_admins(session) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate the only active admin",
            )

    user.is_active = is_active
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_role(
    session: AsyncSession,
    user_id: UUID,
    role_name: RoleName,
    actor_id: UUID,
) -> User:
    user = await get_user(session, user_id)
    if user.role.name == role_name:
        return user
    if user_id == actor_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admins cannot change their own role",
        )
    if (
        user.is_active
        and user.role.name == RoleName.ADMIN
        and role_name != RoleName.ADMIN
    ):
        await roles.lock_by_name(session, RoleName.ADMIN)
        if await users.count_active_admins(session) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the role from the only active admin",
            )

    role = await roles.get_by_name(session, role_name)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Role configuration is unavailable",
        )
    user.role = role
    await session.commit()
    await session.refresh(user)
    return user
