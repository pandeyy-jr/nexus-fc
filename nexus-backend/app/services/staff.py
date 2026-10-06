from http import HTTPStatus
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import RoleName
from app.db.models.staff import Staff
from app.db.models.user import User
from app.repositories import staff as staff_repository
from app.schemas.staff import StaffCreate, StaffUpdate


async def list_staff(session: AsyncSession, limit: int, offset: int) -> list[Staff]:
    return await staff_repository.list_staff(session, limit, offset)


async def get_staff(session: AsyncSession, staff_id: UUID) -> Staff:
    staff = await staff_repository.get_by_id(session, staff_id)
    if staff is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Staff profile not found"
        )
    return staff


async def create_staff(session: AsyncSession, payload: StaffCreate) -> Staff:
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if user.role.name == RoleName.PLAYER:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="Staff profiles must link to a staff account",
        )
    if await staff_repository.get_by_user_id(session, payload.user_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is already linked to a staff profile",
        )
    staff = Staff(**payload.model_dump())
    session.add(staff)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is already linked to a staff profile",
        ) from exc
    await session.refresh(staff)
    return staff


async def update_staff(
    session: AsyncSession, staff_id: UUID, payload: StaffUpdate
) -> Staff:
    staff = await get_staff(session, staff_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(staff, field, value)
    await session.commit()
    await session.refresh(staff)
    return staff


async def delete_staff(session: AsyncSession, staff_id: UUID) -> None:
    staff = await get_staff(session, staff_id)
    await session.delete(staff)
    await session.commit()
