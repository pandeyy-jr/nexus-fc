from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    availability,
    copilot,
    counterfactual,
    development,
    health,
    info,
    match_catalog,
    matches,
    memory,
    players,
    staff,
    teams,
    training,
    users,
    videos,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(info.router, tags=["info"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(staff.router, prefix="/staff", tags=["staff"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(training.router, tags=["training"])
api_router.include_router(availability.router, tags=["availability"])
api_router.include_router(development.router, tags=["development"])
api_router.include_router(
    match_catalog.router, prefix="/matches", tags=["match-catalog"]
)
api_router.include_router(videos.router, prefix="/matches", tags=["videos"])
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(copilot.router, prefix="/ai", tags=["copilot"])
api_router.include_router(
    counterfactual.router, prefix="/counterfactual", tags=["counterfactual"]
)
