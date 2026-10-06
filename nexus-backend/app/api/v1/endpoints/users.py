from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import SessionDependency, require_roles
from app.core.roles import RoleName
from app.db.models.user import User
from app.schemas.auth import UserResponse, UserRoleUpdate, UserStatusUpdate
from app.services.users import (
    get_user,
    list_users,
    update_user_role,
    update_user_status,
)

router = APIRouter()
AdminUser = Annotated[User, Depends(require_roles(RoleName.ADMIN))]


@router.get("", response_model=list[UserResponse])
async def get_users(
    session: SessionDependency,
    _: AdminUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[User]:
    return await list_users(session, limit, offset)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: UUID,
    session: SessionDependency,
    _: AdminUser,
) -> User:
    return await get_user(session, user_id)


@router.patch("/{user_id}/status", response_model=UserResponse)
async def patch_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    session: SessionDependency,
    actor: AdminUser,
) -> User:
    return await update_user_status(session, user_id, payload.is_active, actor.id)


@router.patch("/{user_id}/role", response_model=UserResponse)
async def patch_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    session: SessionDependency,
    actor: AdminUser,
) -> User:
    return await update_user_role(session, user_id, payload.role, actor.id)
