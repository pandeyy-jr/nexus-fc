from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    job_title: str = Field(min_length=1, max_length=120)
    department: str | None = Field(default=None, max_length=100)

    @field_validator("first_name", "last_name", "job_title")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("department")
    @classmethod
    def clean_department(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class StaffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    job_title: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = Field(default=None, max_length=100)

    @field_validator("first_name", "last_name", "job_title")
    @classmethod
    def clean_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("department")
    @classmethod
    def clean_department(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> "StaffUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"first_name", "last_name", "job_title"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required staff fields cannot be null")
        return self


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    first_name: str
    last_name: str
    job_title: str
    department: str | None
    created_at: datetime
    updated_at: datetime
