from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.db.database import get_session
from app.schemas.auth import (
    LoginRequest,
    RegistrationRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import authenticate_user, register_user

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    credentials: RegistrationRequest, session: SessionDependency
) -> TokenResponse:
    user, token = await register_user(
        session,
        str(credentials.email),
        credentials.password.get_secret_value(),
        credentials.full_name,
    )
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest, session: SessionDependency) -> TokenResponse:
    user, token = await authenticate_user(
        session, str(credentials.email), credentials.password.get_secret_value()
    )
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def current_user(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
