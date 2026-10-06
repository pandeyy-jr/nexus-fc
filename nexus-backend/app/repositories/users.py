from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.db.models.role import Role
from app.db.models.user import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession, limit: int, offset: int) -> list[User]:
    result = await session.execute(
        select(User).order_by(User.created_at, User.id).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def count_active_admins(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(User.id))
        .join(User.role)
        .where(User.is_active.is_(True), Role.name == RoleName.ADMIN)
    )
    return result.scalar_one()
