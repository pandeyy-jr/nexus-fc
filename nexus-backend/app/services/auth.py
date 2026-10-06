from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.repositories import roles, users


async def register_user(
    session: AsyncSession, email: str, password: str, full_name: str
) -> tuple[User, str]:
    if await users.get_by_email(session, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    player_role = await roles.get_by_name(session, RoleName.PLAYER)
    if player_role is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Role configuration is unavailable",
        )

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=player_role,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    await session.refresh(user)
    return user, create_access_token(user.id)


async def authenticate_user(
    session: AsyncSession, email: str, password: str
) -> tuple[User, str]:
    user = await users.get_by_email(session, email)
    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user, create_access_token(user.id)
