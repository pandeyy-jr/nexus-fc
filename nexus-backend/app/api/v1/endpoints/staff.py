from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import SessionDependency
from app.api.domain_dependencies import StaffManager, StaffReader
from app.schemas.staff import StaffCreate, StaffResponse, StaffUpdate
from app.services.staff import (
    create_staff,
    delete_staff,
    get_staff,
    list_staff,
    update_staff,
)

router = APIRouter()


@router.get("", response_model=list[StaffResponse])
async def get_staff_profiles(
    session: SessionDependency,
    _: StaffReader,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list:
    return await list_staff(session, limit, offset)


@router.post("", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def post_staff(
    payload: StaffCreate,
    session: SessionDependency,
    _: StaffManager,
) -> StaffResponse:
    return await create_staff(session, payload)


@router.get("/{staff_id}", response_model=StaffResponse)
async def get_staff_profile(
    staff_id: UUID,
    session: SessionDependency,
    _: StaffReader,
) -> StaffResponse:
    return await get_staff(session, staff_id)


@router.patch("/{staff_id}", response_model=StaffResponse)
async def patch_staff(
    staff_id: UUID,
    payload: StaffUpdate,
    session: SessionDependency,
    _: StaffManager,
) -> StaffResponse:
    return await update_staff(session, staff_id, payload)


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_staff(
    staff_id: UUID,
    session: SessionDependency,
    _: StaffManager,
) -> Response:
    await delete_staff(session, staff_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
