from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.domain_dependencies import (
    MembershipManager,
    TeamDeleter,
    TeamManager,
)
from app.core.roles import RoleName
from app.schemas.memberships import (
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
)
from app.schemas.teams import TeamCreate, TeamResponse, TeamUpdate
from app.services.memberships import (
    create_membership,
    end_membership,
    list_team_memberships,
    update_membership,
)
from app.services.teams import (
    create_team,
    delete_team,
    get_team,
    list_teams,
    update_team,
)

router = APIRouter()


@router.get("", response_model=list[TeamResponse])
async def get_teams(
    session: SessionDependency, actor: CurrentUser
) -> list[TeamResponse]:
    return await list_teams(session, actor)


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def post_team(
    payload: TeamCreate,
    session: SessionDependency,
    _: TeamManager,
) -> TeamResponse:
    return await create_team(session, payload)


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team_profile(
    team_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> TeamResponse:
    return await get_team(session, team_id, actor)


@router.patch("/{team_id}", response_model=TeamResponse)
async def patch_team(
    team_id: UUID,
    payload: TeamUpdate,
    session: SessionDependency,
    _: TeamManager,
) -> TeamResponse:
    return await update_team(session, team_id, payload)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team(
    team_id: UUID,
    session: SessionDependency,
    _: TeamDeleter,
) -> Response:
    await delete_team(session, team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{team_id}/players",
    response_model=list[MembershipResponse],
)
async def get_team_players(
    team_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
    include_history: bool = False,
) -> list[MembershipResponse]:
    await get_team(session, team_id, actor)
    player_user_id = actor.id if actor.role.name == RoleName.PLAYER else None
    return await list_team_memberships(
        session, team_id, include_history, player_user_id
    )


@router.post(
    "/{team_id}/players/{player_id}",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_team_player(
    team_id: UUID,
    player_id: UUID,
    payload: MembershipCreate,
    session: SessionDependency,
    _: MembershipManager,
) -> MembershipResponse:
    return await create_membership(session, team_id, player_id, payload)


@router.patch("/{team_id}/players/{player_id}", response_model=MembershipResponse)
async def patch_team_player(
    team_id: UUID,
    player_id: UUID,
    payload: MembershipUpdate,
    session: SessionDependency,
    _: MembershipManager,
) -> MembershipResponse:
    return await update_membership(session, team_id, player_id, payload)


@router.delete("/{team_id}/players/{player_id}", response_model=MembershipResponse)
async def delete_team_player(
    team_id: UUID,
    player_id: UUID,
    session: SessionDependency,
    _: MembershipManager,
) -> MembershipResponse:
    return await end_membership(session, team_id, player_id)
