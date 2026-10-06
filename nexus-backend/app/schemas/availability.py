from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.training import AvailabilityReasonCategory, AvailabilityStatus


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PlayerAvailabilityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AvailabilityStatus
    effective_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    effective_until: datetime | None = None
    reason_category: AvailabilityReasonCategory
    note: str | None = Field(default=None, max_length=500)

    @field_validator("effective_from", "effective_until")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value) if value is not None else None

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_period(self) -> "PlayerAvailabilityCreate":
        if (
            self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must be on or after effective_from")
        return self


class PlayerAvailabilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AvailabilityStatus | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    reason_category: AvailabilityReasonCategory | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("effective_from", "effective_until")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return normalize_utc(value) if value is not None else None

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "PlayerAvailabilityUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"status", "effective_from", "reason_category"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required availability fields cannot be null")
        if "effective_until" in self.model_fields_set and self.effective_until is None:
            raise ValueError("effective_until cannot be cleared")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must be on or after effective_from")
        return self


class PlayerAvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_id: UUID
    status: AvailabilityStatus
    effective_from: datetime
    effective_until: datetime | None
    reason_category: AvailabilityReasonCategory
    note: str | None
    recorded_by: UUID
    created_at: datetime
    updated_at: datetime
