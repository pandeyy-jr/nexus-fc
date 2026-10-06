from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.training import (
    DevelopmentCategory,
    DevelopmentPriority,
    DevelopmentStatus,
)


class PlayerDevelopmentGoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID | None = None
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    category: DevelopmentCategory
    target_date: date | None = None
    status: DevelopmentStatus = DevelopmentStatus.NOT_STARTED
    priority: DevelopmentPriority = DevelopmentPriority.MEDIUM

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlayerDevelopmentGoalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    category: DevelopmentCategory | None = None
    target_date: date | None = None
    status: DevelopmentStatus | None = None
    priority: DevelopmentPriority | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "PlayerDevelopmentGoalUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"title", "category", "status", "priority"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required development goal fields cannot be null")
        return self


class PlayerDevelopmentGoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_id: UUID
    team_id: UUID | None
    title: str
    description: str | None
    category: DevelopmentCategory
    target_date: date | None
    status: DevelopmentStatus
    priority: DevelopmentPriority
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class PlayerDevelopmentAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: UUID | None = None
    assessment_date: date = Field(default_factory=date.today)
    progress_status: DevelopmentStatus
    assessment_note: str = Field(min_length=1, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator("assessment_note")
    @classmethod
    def clean_assessment_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("assessment_note cannot be blank")
        return value

    @field_validator("next_action")
    @classmethod
    def clean_next_action(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("assessment_date")
    @classmethod
    def assessment_date_not_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("assessment_date cannot be in the future")
        return value


class PlayerDevelopmentAssessmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_date: date | None = None
    progress_status: DevelopmentStatus | None = None
    assessment_note: str | None = Field(default=None, min_length=1, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator("assessment_note")
    @classmethod
    def clean_assessment_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("assessment_note cannot be blank")
        return value

    @field_validator("next_action")
    @classmethod
    def clean_next_action(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("assessment_date")
    @classmethod
    def assessment_date_not_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("assessment_date cannot be in the future")
        return value

    @model_validator(mode="after")
    def require_patch_fields(self) -> "PlayerDevelopmentAssessmentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"assessment_date", "progress_status", "assessment_note"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required assessment fields cannot be null")
        return self


class PlayerDevelopmentAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    player_id: UUID
    goal_id: UUID | None
    assessment_date: date
    assessor_id: UUID
    progress_status: DevelopmentStatus
    assessment_note: str
    next_action: str | None
    created_at: datetime
    updated_at: datetime
