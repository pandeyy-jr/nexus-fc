from datetime import date, datetime
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.football import DominantFoot, PlayerPosition, PlayerStatus


class PlayerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date
    nationality: str | None = Field(default=None, max_length=80)
    preferred_position: PlayerPosition
    secondary_position: PlayerPosition | None = None
    squad_number: int | None = Field(default=None, ge=0, le=99)
    dominant_foot: DominantFoot | None = None
    height_cm: int | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    profile_photo_url: AnyHttpUrl | None = None
    status: PlayerStatus = PlayerStatus.ACTIVE

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name fields cannot be blank")
        return value

    @field_validator("nationality")
    @classmethod
    def clean_nationality(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("date_of_birth")
    @classmethod
    def date_is_not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Date of birth cannot be in the future")
        return value

    @model_validator(mode="after")
    def positions_must_differ(self) -> "PlayerCreate":
        if (
            self.secondary_position is not None
            and self.secondary_position == self.preferred_position
        ):
            raise ValueError("Secondary position must differ from preferred position")
        return self


class PlayerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=80)
    preferred_position: PlayerPosition | None = None
    secondary_position: PlayerPosition | None = None
    squad_number: int | None = Field(default=None, ge=0, le=99)
    dominant_foot: DominantFoot | None = None
    height_cm: int | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=30, le=200)
    profile_photo_url: AnyHttpUrl | None = None
    status: PlayerStatus | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name fields cannot be blank")
        return value

    @field_validator("nationality")
    @classmethod
    def clean_nationality(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("date_of_birth")
    @classmethod
    def date_is_not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Date of birth cannot be in the future")
        return value

    @model_validator(mode="after")
    def validate_update(self) -> "PlayerUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {
            "first_name",
            "last_name",
            "date_of_birth",
            "preferred_position",
            "status",
        }
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required player fields cannot be null")
        if (
            self.secondary_position is not None
            and self.preferred_position is not None
            and self.secondary_position == self.preferred_position
        ):
            raise ValueError("Secondary position must differ from preferred position")
        return self


class PlayerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    squad_number: int | None
    preferred_position: PlayerPosition


class PlayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    first_name: str
    last_name: str
    date_of_birth: date
    nationality: str | None
    preferred_position: PlayerPosition
    secondary_position: PlayerPosition | None
    squad_number: int | None
    dominant_foot: DominantFoot | None
    height_cm: int | None
    weight_kg: float | None
    profile_photo_url: str | None
    status: PlayerStatus
    created_at: datetime
    updated_at: datetime
