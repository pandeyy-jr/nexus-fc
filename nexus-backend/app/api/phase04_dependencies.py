from typing import Annotated

from fastapi import Depends

from app.api.dependencies import require_roles
from app.core.domain_roles import (
    AVAILABILITY_MANAGE_ROLES,
    AVAILABILITY_READ_ROLES,
    DEVELOPMENT_MANAGE_ROLES,
    DEVELOPMENT_READ_ROLES,
    TRAINING_PARTICIPATION_CREATE_ROLES,
    TRAINING_PARTICIPATION_DELETE_ROLES,
    TRAINING_PARTICIPATION_MANAGE_ROLES,
    TRAINING_READ_ROLES,
    TRAINING_SESSION_MANAGE_ROLES,
)
from app.db.models.user import User

TrainingReader = Annotated[User, Depends(require_roles(*TRAINING_READ_ROLES))]
TrainingSessionManager = Annotated[
    User, Depends(require_roles(*TRAINING_SESSION_MANAGE_ROLES))
]
TrainingParticipationManager = Annotated[
    User, Depends(require_roles(*TRAINING_PARTICIPATION_MANAGE_ROLES))
]
TrainingParticipationCreator = Annotated[
    User, Depends(require_roles(*TRAINING_PARTICIPATION_CREATE_ROLES))
]
TrainingParticipationDeleter = Annotated[
    User, Depends(require_roles(*TRAINING_PARTICIPATION_DELETE_ROLES))
]
AvailabilityReader = Annotated[User, Depends(require_roles(*AVAILABILITY_READ_ROLES))]
AvailabilityManager = Annotated[
    User, Depends(require_roles(*AVAILABILITY_MANAGE_ROLES))
]
DevelopmentReader = Annotated[User, Depends(require_roles(*DEVELOPMENT_READ_ROLES))]
DevelopmentManager = Annotated[User, Depends(require_roles(*DEVELOPMENT_MANAGE_ROLES))]
