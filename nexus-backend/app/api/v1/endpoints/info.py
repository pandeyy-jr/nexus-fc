from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/info")
async def api_info() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "api_version": "v1",
    }
