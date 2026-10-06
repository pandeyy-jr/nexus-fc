from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.matches import MatchSide, MatchStatus


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID
    opponent_id: UUID
    competition_id: UUID | None = None
    venue_id: UUID | None = None
    scheduled_at: datetime
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    home_away: MatchSide
    status: MatchStatus = MatchStatus.SCHEDULED
    matchday: int | None = Field(default=None, ge=1, le=100)
    season: str | None = Field(default=None, max_length=20)
    home_score: int | None = Field(default=None, ge=0, le=99)
    away_score: int | None = Field(default=None, ge=0, le=99)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("scheduled_at", "actual_start_at", "actual_end_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @field_validator("season", "notes")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_match(self) -> "MatchCreate":
        if (self.home_score is None) != (self.away_score is None):
            raise ValueError("home_score and away_score must be supplied together")
        if (
            self.actual_start_at is not None
            and self.actual_end_at is not None
            and self.actual_end_at < self.actual_start_at
        ):
            raise ValueError("actual_end_at must be on or after actual_start_at")
        return self


class MatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID | None = None
    opponent_id: UUID | None = None
    competition_id: UUID | None = None
    venue_id: UUID | None = None
    scheduled_at: datetime | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    home_away: MatchSide | None = None
    status: MatchStatus | None = None
    matchday: int | None = Field(default=None, ge=1, le=100)
    season: str | None = Field(default=None, max_length=20)
    home_score: int | None = Field(default=None, ge=0, le=99)
    away_score: int | None = Field(default=None, ge=0, le=99)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("scheduled_at", "actual_start_at", "actual_end_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @field_validator("season", "notes")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "MatchUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"team_id", "opponent_id", "scheduled_at", "home_away", "status"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required match fields cannot be null")
        return self


class MatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    opponent_id: UUID
    competition_id: UUID | None
    venue_id: UUID | None
    scheduled_at: datetime
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    home_away: MatchSide
    status: MatchStatus
    matchday: int | None
    season: str | None
    home_score: int | None
    away_score: int | None
    notes: str | None
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime