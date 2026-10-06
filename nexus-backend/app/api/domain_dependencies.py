from typing import Annotated

from fastapi import Depends

from app.api.dependencies import require_roles
from app.core.domain_roles import (
    MEMBERSHIP_MANAGE_ROLES,
    PLAYER_CREATE_ROLES,
    PLAYER_DELETE_ROLES,
    PLAYER_UPDATE_ROLES,
    STAFF_MANAGE_ROLES,
    STAFF_VIEW_ROLES,
    TEAM_DELETE_ROLES,
    TEAM_MANAGE_ROLES,
)
from app.core.roles import RoleName
from app.db.models.user import User

PlayerCreator = Annotated[User, Depends(require_roles(*PLAYER_CREATE_ROLES))]
PlayerUpdater = Annotated[User, Depends(require_roles(*PLAYER_UPDATE_ROLES))]
PlayerDeleter = Annotated[User, Depends(require_roles(*PLAYER_DELETE_ROLES))]
StaffReader = Annotated[User, Depends(require_roles(*STAFF_VIEW_ROLES))]
StaffManager = Annotated[User, Depends(require_roles(*STAFF_MANAGE_ROLES))]
TeamManager = Annotated[User, Depends(require_roles(*TEAM_MANAGE_ROLES))]
TeamDeleter = Annotated[User, Depends(require_roles(*TEAM_DELETE_ROLES))]
MembershipManager = Annotated[User, Depends(require_roles(*MEMBERSHIP_MANAGE_ROLES))]
_PlayerRole = RoleName.PLAYER
