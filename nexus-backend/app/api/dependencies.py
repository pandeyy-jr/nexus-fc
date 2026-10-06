from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.core.security import decode_access_token
from app.db.database import get_session
from app.db.models.user import User
from app.repositories.users import get_by_id

bearer_scheme = HTTPBearer(auto_error=False)
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDependency,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        user_id: UUID = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None

    user = await get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: RoleName) -> Callable:
    async def role_checker(user: CurrentUser) -> User:
        if user.role.name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return role_checker
