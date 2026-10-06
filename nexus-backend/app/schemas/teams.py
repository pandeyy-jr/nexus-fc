from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    short_name: str = Field(min_length=1, max_length=30)
    age_group: str = Field(min_length=1, max_length=40)
    gender_category: str = Field(min_length=1, max_length=40)
    season: str = Field(min_length=1, max_length=20)
    is_active: bool = True

    @field_validator("name", "short_name", "age_group", "gender_category", "season")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    short_name: str | None = Field(default=None, min_length=1, max_length=30)
    age_group: str | None = Field(default=None, min_length=1, max_length=40)
    gender_category: str | None = Field(default=None, min_length=1, max_length=40)
    season: str | None = Field(default=None, min_length=1, max_length=20)
    is_active: bool | None = None

    @field_validator("name", "short_name", "age_group", "gender_category", "season")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @model_validator(mode="after")
    def require_changes(self) -> "TeamUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {
            "name",
            "short_name",
            "age_group",
            "gender_category",
            "season",
            "is_active",
        }
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required team fields cannot be null")
        return self


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    short_name: str
    age_group: str
    gender_category: str
    season: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
