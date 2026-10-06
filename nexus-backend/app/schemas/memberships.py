from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.football import SquadStatus
from app.schemas.players import PlayerSummary


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    left_at: datetime | None = None
    squad_status: SquadStatus = SquadStatus.ACTIVE

    @field_validator("joined_at", "left_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value) if value is not None else None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "MembershipCreate":
        if self.left_at is not None and self.left_at < self.joined_at:
            raise ValueError("left_at must be on or after joined_at")
        return self


class MembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    squad_status: SquadStatus | None = None
    left_at: datetime | None = None

    @field_validator("left_at")
    @classmethod
    def timestamp_is_utc(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_update(self) -> "MembershipUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "squad_status" in self.model_fields_set and self.squad_status is None:
            raise ValueError("squad_status cannot be null")
        if "left_at" in self.model_fields_set and self.left_at is None:
            raise ValueError(
                "left_at cannot be cleared; create a new membership instead"
            )
        return self


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_id: UUID
    team_id: UUID
    joined_at: datetime
    left_at: datetime | None
    squad_status: SquadStatus
    created_at: datetime
    updated_at: datetime
    player: PlayerSummary
