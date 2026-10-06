from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.staff import Staff


async def get_by_id(session: AsyncSession, staff_id: UUID) -> Staff | None:
    return await session.get(Staff, staff_id)


async def get_by_user_id(session: AsyncSession, user_id: UUID) -> Staff | None:
    result = await session.execute(select(Staff).where(Staff.user_id == user_id))
    return result.scalar_one_or_none()


async def list_staff(session: AsyncSession, limit: int, offset: int) -> list[Staff]:
    result = await session.execute(
        select(Staff)
        .order_by(Staff.last_name, Staff.first_name)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
