from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.matches import (
    MatchEventSource,
    MatchEventType,
    MatchSide,
    MatchSquadStatus,
    SubstitutionReason,
)
from app.schemas.matches import MatchResponse


class MatchSquadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: UUID
    squad_status: MatchSquadStatus = MatchSquadStatus.SELECTED
    shirt_number: int | None = Field(default=None, ge=0, le=99)
    starting: bool = False
    captain: bool = False

    @model_validator(mode="after")
    def validate_starting_status(self) -> "MatchSquadCreate":
        if self.squad_status == MatchSquadStatus.STARTER and not self.starting:
            raise ValueError("STARTER status requires starting=true")
        if self.starting and self.squad_status not in {
            MatchSquadStatus.STARTER,
            MatchSquadStatus.WITHDRAWN,
        }:
            raise ValueError("starting=true requires STARTER or WITHDRAWN status")
        return self


class MatchSquadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    squad_status: MatchSquadStatus | None = None
    shirt_number: int | None = Field(default=None, ge=0, le=99)
    starting: bool | None = None
    captain: bool | None = None

    @model_validator(mode="after")
    def require_patch_fields(self) -> "MatchSquadUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        required_fields = {"squad_status", "starting", "captain"}
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in required_fields
        ):
            raise ValueError("Required squad fields cannot be null")
        return self


class MatchParticipationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at_minute: int | None = Field(default=None, ge=0, le=130)
    ended_at_minute: int | None = Field(default=None, ge=0, le=130)
    minutes_played: int | None = Field(default=None, ge=0, le=130)

    @model_validator(mode="after")
    def validate_minute_order(self) -> "MatchParticipationCreate":
        if (
            self.started_at_minute is not None
            and self.ended_at_minute is not None
            and self.ended_at_minute < self.started_at_minute
        ):
            raise ValueError("ended_at_minute must not precede started_at_minute")
        return self


class MatchParticipationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at_minute: int | None = Field(default=None, ge=0, le=130)
    ended_at_minute: int | None = Field(default=None, ge=0, le=130)
    minutes_played: int | None = Field(default=None, ge=0, le=130)

    @model_validator(mode="after")
    def require_patch_and_validate_order(self) -> "MatchParticipationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class MatchParticipationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_squad_id: UUID
    started_at_minute: int | None
    ended_at_minute: int | None
    minutes_played: int | None
    created_at: datetime
    updated_at: datetime


class MatchSquadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    player_id: UUID
    squad_status: MatchSquadStatus
    shirt_number: int | None
    starting: bool
    captain: bool
    created_at: datetime
    updated_at: datetime
    participation: MatchParticipationResponse | None


class MatchEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: MatchSide
    player_id: UUID | None = None
    assist_player_id: UUID | None = None
    event_type: MatchEventType
    minute: int = Field(ge=0, le=130)
    added_time_minute: int | None = Field(default=None, ge=0, le=30)
    description: str | None = Field(default=None, max_length=1000)
    source: MatchEventSource = MatchEventSource.MANUAL
    is_penalty: bool = False

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_event_fields(self) -> "MatchEventCreate":
        if self.event_type == MatchEventType.SUBSTITUTION:
            raise ValueError("Use the substitutions endpoint for substitution events")
        if self.event_type in {
            MatchEventType.GOAL,
            MatchEventType.OWN_GOAL,
            MatchEventType.PENALTY_WON,
            MatchEventType.PENALTY_MISSED,
            MatchEventType.YELLOW_CARD,
            MatchEventType.RED_CARD,
            MatchEventType.SECOND_YELLOW,
        } and self.side == MatchSide.NEUTRAL:
            raise ValueError("This event requires HOME or AWAY side")
        if self.event_type in {
            MatchEventType.YELLOW_CARD,
            MatchEventType.RED_CARD,
            MatchEventType.SECOND_YELLOW,
        } and self.player_id is None:
            raise ValueError("Card events require a player")
        if self.assist_player_id is not None and self.event_type not in {
            MatchEventType.GOAL,
            MatchEventType.OWN_GOAL,
        }:
            raise ValueError("An assist can only be recorded for a goal")
        if self.is_penalty and self.event_type not in {
            MatchEventType.GOAL,
            MatchEventType.OWN_GOAL,
            MatchEventType.PENALTY_MISSED,
        }:
            raise ValueError("is_penalty is only valid for goal/penalty events")
        return self


class MatchEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: MatchSide | None = None
    player_id: UUID | None = None
    assist_player_id: UUID | None = None
    event_type: MatchEventType | None = None
    minute: int | None = Field(default=None, ge=0, le=130)
    added_time_minute: int | None = Field(default=None, ge=0, le=30)
    description: str | None = Field(default=None, max_length=1000)
    source: MatchEventSource | None = None
    is_penalty: bool | None = None

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_patch_fields(self) -> "MatchEventUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in {"side", "event_type", "minute", "source", "is_penalty"}
        ):
            raise ValueError("Required event fields cannot be null")
        return self


class MatchEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    side: MatchSide
    player_id: UUID | None
    assist_player_id: UUID | None
    related_player_id: UUID | None
    event_type: MatchEventType
    minute: int
    added_time_minute: int | None
    description: str | None
    source: MatchEventSource
    is_penalty: bool
    own_goal: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SubstitutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_out_id: UUID
    player_in_id: UUID
    minute: int = Field(ge=0, le=130)
    added_time_minute: int | None = Field(default=None, ge=0, le=30)
    reason: SubstitutionReason = SubstitutionReason.OTHER
    side: MatchSide | None = None

    @model_validator(mode="after")
    def players_must_differ(self) -> "SubstitutionCreate":
        if self.player_out_id == self.player_in_id:
            raise ValueError("player_out_id and player_in_id must differ")
        return self


class SubstitutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    player_out_id: UUID
    player_in_id: UUID
    event_id: UUID
    side: MatchSide
    minute: int
    added_time_minute: int | None
    reason: SubstitutionReason
    created_by: UUID
    created_at: datetime