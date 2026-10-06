from typing import Annotated

from fastapi import Depends

from app.api.dependencies import require_roles
from app.core.domain_roles import (
    MATCH_CATALOG_MANAGE_ROLES,
    MATCH_EVENT_DELETE_ROLES,
    MATCH_EVENT_WRITE_ROLES,
    MATCH_MANAGE_ROLES,
    MATCH_READ_ROLES,
)
from app.db.models.user import User

MatchReader = Annotated[User, Depends(require_roles(*MATCH_READ_ROLES))]
MatchManager = Annotated[User, Depends(require_roles(*MATCH_MANAGE_ROLES))]
MatchEventWriter = Annotated[User, Depends(require_roles(*MATCH_EVENT_WRITE_ROLES))]
MatchEventDeleter = Annotated[User, Depends(require_roles(*MATCH_EVENT_DELETE_ROLES))]
MatchCatalogManager = Annotated[
    User, Depends(require_roles(*MATCH_CATALOG_MANAGE_ROLES))
]