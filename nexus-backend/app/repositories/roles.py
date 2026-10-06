from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.db.models.role import Role


async def get_by_name(session: AsyncSession, name: RoleName) -> Role | None:
    result = await session.execute(select(Role).where(Role.name == name))
    return result.scalar_one_or_none()


async def lock_by_name(session: AsyncSession, name: RoleName) -> Role | None:
    result = await session.execute(
        select(Role).where(Role.name == name).with_for_update()
    )
    return result.scalar_one_or_none()
