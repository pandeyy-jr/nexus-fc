import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db.database import get_engine
from app.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok", service="nexus-backend", version=settings.app_version
    )


@router.get("/db", response_model=DatabaseHealthResponse)
async def database_health(
    engine: Annotated[AsyncEngine, Depends(get_engine)],
) -> DatabaseHealthResponse:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    return DatabaseHealthResponse(status="ok", database="ok")
