from typing import Annotated

from fastapi import Depends

from app.api.dependencies import require_roles
from app.core.roles import RoleName
from app.db.models.user import User

# Any authenticated user may read; governance filters rows afterwards.
# Writes exclude PLAYER; redaction is ADMIN/DIRECTOR only (also enforced
# inside the governance service itself).
MemoryWriter = Annotated[
    User,
    Depends(
        require_roles(
            RoleName.ADMIN,
            RoleName.DIRECTOR,
            RoleName.HEAD_COACH,
            RoleName.ASSISTANT_COACH,
            RoleName.ANALYST,
            RoleName.SPORTS_SCIENTIST,
            RoleName.MEDICAL_STAFF,
            RoleName.SCOUT,
        )
    ),
]
MemoryRedactor = Annotated[
    User, Depends(require_roles(RoleName.ADMIN, RoleName.DIRECTOR))
]
