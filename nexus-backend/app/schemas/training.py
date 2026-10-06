from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.football import PlayerPosition
from app.core.training import AttendanceStatus, TrainingSessionType


class TrainingSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID
    session_date: date
    start_time: time
    end_time: time
    session_type: TrainingSessionType
    objective: str | None = Field(default=None, max_length=500)
    planned_intensity: int | None = Field(default=None, ge=1, le=10)
    planned_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    location: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("objective", "location", "notes")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_time_order(self) -> "TrainingSessionCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class TrainingSessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    session_type: TrainingSessionType | None = None
    objective: str | None = Field(default=None, max_length=500)
    planned_intensity: int | None = Field(default=None, ge=1, le=10)
    planned_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    location: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("objective", "location", "notes")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "TrainingSessionUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"session_date", "start_time", "end_time", "session_type"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required session fields cannot be null")
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValueError("end_time must be after start_time")
        return self


class TrainingSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    session_date: date
    start_time: time
    end_time: time
    session_type: TrainingSessionType
    objective: str | None
    planned_intensity: int | None
    planned_duration_minutes: int | None
    location: str | None
    notes: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class TrainingSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    session_date: date
    start_time: time
    session_type: TrainingSessionType
    objective: str | None


class TrainingPlayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    preferred_position: PlayerPosition
    squad_number: int | None


class TrainingParticipationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: UUID
    attendance_status: AttendanceStatus = AttendanceStatus.PLANNED
    planned_load: float | None = Field(default=None, ge=0, le=1000)
    actual_load: float | None = Field(default=None, ge=0, le=1000)
    duration_minutes: int | None = Field(default=None, ge=0, le=600)
    player_response: str | None = Field(default=None, max_length=1000)
    coach_note: str | None = Field(default=None, max_length=1000)

    @field_validator("player_response", "coach_note")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class TrainingParticipationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attendance_status: AttendanceStatus | None = None
    planned_load: float | None = Field(default=None, ge=0, le=1000)
    actual_load: float | None = Field(default=None, ge=0, le=1000)
    duration_minutes: int | None = Field(default=None, ge=0, le=600)
    player_response: str | None = Field(default=None, max_length=1000)
    coach_note: str | None = Field(default=None, max_length=1000)

    @field_validator("player_response", "coach_note")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "TrainingParticipationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if (
            "attendance_status" in self.model_fields_set
            and self.attendance_status is None
        ):
            raise ValueError("attendance_status cannot be null")
        return self


class TrainingParticipationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    training_session_id: UUID
    player_id: UUID
    attendance_status: AttendanceStatus
    planned_load: float | None
    actual_load: float | None
    duration_minutes: int | None
    player_response: str | None
    coach_note: str | None
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime
    player: TrainingPlayerSummary
    session: TrainingSessionSummary


class PlayerTrainingHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    training_session_id: UUID
    attendance_status: AttendanceStatus
    planned_load: float | None
    actual_load: float | None
    duration_minutes: int | None
    player_response: str | None
    recorded_at: datetime
    session: TrainingSessionSummary
