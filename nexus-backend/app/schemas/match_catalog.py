from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.matches import CompetitionType


def _clean_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("This field cannot be blank")
    return value


class OpponentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    short_name: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("short_name", "country", "city")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class OpponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    short_name: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return _clean_required(value) if value is not None else None

    @field_validator("short_name", "country", "city")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> "OpponentUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class OpponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    short_name: str | None
    country: str | None
    city: str | None
    created_at: datetime
    updated_at: datetime


class VenueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    capacity: int | None = Field(default=None, ge=1, le=200000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("city", "country")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class VenueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    capacity: int | None = Field(default=None, ge=1, le=200000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return _clean_required(value) if value is not None else None

    @field_validator("city", "country")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> "VenueUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class VenueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    city: str | None
    country: str | None
    capacity: int | None
    created_at: datetime
    updated_at: datetime


class CompetitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    short_name: str | None = Field(default=None, max_length=40)
    competition_type: CompetitionType
    season: str = Field(min_length=1, max_length=20)

    @field_validator("name", "season")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("short_name")
    @classmethod
    def clean_short_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CompetitionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    short_name: str | None = Field(default=None, max_length=40)
    competition_type: CompetitionType | None = None
    season: str | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("name", "season")
    @classmethod
    def clean_required_text(cls, value: str | None) -> str | None:
        return _clean_required(value) if value is not None else None

    @field_validator("short_name")
    @classmethod
    def clean_short_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> "CompetitionUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in {"name", "competition_type", "season"}
        ):
            raise ValueError("Required competition fields cannot be null")
        return self


class CompetitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    short_name: str | None
    competition_type: CompetitionType
    season: str
    created_at: datetime
    updated_at: datetime