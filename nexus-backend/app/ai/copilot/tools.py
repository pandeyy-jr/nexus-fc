"""Copilot tool definitions and handlers (Phase 09A, read-only).

Every handler calls an existing application service with the
server-side actor — never SQLAlchemy, PostgreSQL, or Qdrant directly.
Inputs are strict Pydantic models (unknown fields rejected); outputs
reuse existing public response DTOs plus small explicit wrappers.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domain_roles import (
    AVAILABILITY_READ_ROLES,
    MATCH_READ_ROLES,
    PLAYER_VIEW_ROLES,
    TRAINING_READ_ROLES,
)
from app.core.memory import MemorySourceType, MemoryType
from app.core.roles import RoleName
from app.db.models.user import User
from app.schemas import availability as availability_schemas
from app.schemas import matches as matches_schemas
from app.schemas import memory as memory_schemas
from app.schemas import players as players_schemas
from app.schemas import training as training_schemas
from app.services import (
    availability as availability_service,
)
from app.services import (
    matches as matches_service,
)
from app.services import (
    players as players_service,
)
from app.services import (
    training as training_service,
)
from app.services.memory_retrieval import retrieve_memories

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

# Handler contract: validated input in, explicit DTO out.
ToolHandler = Callable[..., Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolDefinition:
    """Public contract for one copilot tool."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_roles: tuple[RoleName, ...]
    version: str = "1.0"
    read_only: bool = True

    def __post_init__(self) -> None:
        if not _TOOL_NAME_PATTERN.match(self.name):
            raise ValueError(f"invalid tool name: {self.name!r}")
        if not (20 <= len(self.description) <= 2000):
            raise ValueError("tool description must be 20-2000 characters")
        for label, model in (
            ("input", self.input_model),
            ("output", self.output_model),
        ):
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                raise ValueError(f"tool {label} must be a Pydantic model")
        if self.input_model.model_config.get("extra") != "forbid":
            raise ValueError("tool input models must forbid extra fields")
        if not self.allowed_roles:
            raise ValueError("tool must allow at least one role")
        if not (1 <= len(self.version) <= 32):
            raise ValueError("tool version must be 1-32 characters")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlayerRefInput(StrictInput):
    player_id: UUID


class PagedPlayerInput(StrictInput):
    player_id: UUID
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class MatchRefInput(StrictInput):
    match_id: UUID


class MemorySearchInput(StrictInput):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    memory_type: MemoryType | None = None
    source_type: MemorySourceType | None = None
    limit: int = Field(default=20, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class MatchHistoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    player_id: UUID
    matches: list[matches_schemas.MatchResponse]


class TrainingSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    player_id: UUID
    entries: list[training_schemas.PlayerTrainingHistoryResponse]


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    player_id: UUID
    records: list[availability_schemas.PlayerAvailabilityResponse]


async def _get_player_status(
    session: AsyncSession, actor: User, args: PlayerRefInput
) -> players_schemas.PlayerResponse:
    player = await players_service.get_player(session, args.player_id, actor)
    return players_schemas.PlayerResponse.model_validate(player)


async def _get_player_match_history(
    session: AsyncSession, actor: User, args: PagedPlayerInput
) -> MatchHistoryResult:
    found = await matches_service.list_player_match_history(
        session, args.player_id, actor, args.limit, args.offset
    )
    return MatchHistoryResult(
        player_id=args.player_id,
        matches=[matches_schemas.MatchResponse.model_validate(item) for item in found],
    )


async def _get_training_summary(
    session: AsyncSession, actor: User, args: PagedPlayerInput
) -> TrainingSummaryResult:
    player, records = await training_service.get_player_training_history(
        session, args.player_id, actor, args.limit, args.offset
    )
    return TrainingSummaryResult(
        player_id=player.id,
        entries=[
            training_schemas.PlayerTrainingHistoryResponse.model_validate(item)
            for item in records
        ],
    )


async def _get_player_availability(
    session: AsyncSession, actor: User, args: PagedPlayerInput
) -> AvailabilityResult:
    records = await availability_service.list_availability(
        session, args.player_id, actor, args.limit, args.offset
    )
    return AvailabilityResult(
        player_id=args.player_id,
        records=[
            availability_schemas.PlayerAvailabilityResponse.model_validate(item)
            for item in records
        ],
    )


async def _get_match_summary(
    session: AsyncSession, actor: User, args: MatchRefInput
) -> matches_schemas.MatchResponse:
    found = await matches_service.get_match_for_actor(session, args.match_id, actor)
    return matches_schemas.MatchResponse.model_validate(found)


async def _search_club_memory(
    session: AsyncSession, actor: User, args: MemorySearchInput
) -> memory_schemas.RetrievalResponse:
    query = memory_schemas.RetrievalQuery(
        text=args.text,
        memory_type=args.memory_type,
        source_type=args.source_type,
        limit=args.limit,
        offset=args.offset,
    )
    return await retrieve_memories(session, actor, query)


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler
    extra: dict[str, Any] = field(default_factory=dict)


def _player_roles(*role_groups: tuple[RoleName, ...]) -> tuple[RoleName, ...]:
    """Union role groups plus scoped PLAYER access (services enforce self-only)."""
    ordered = dict.fromkeys([role for group in role_groups for role in group])
    ordered.setdefault(RoleName.PLAYER, None)
    return tuple(ordered)


BUILTIN_TOOLS: tuple[RegisteredTool, ...] = (
    RegisteredTool(
        ToolDefinition(
            name="get_player_status",
            description=(
                "Return a player's profile and current status by player ID. "
                "Returns profile fields only; no training, availability, or "
                "match data. Staff roles may read any player; PLAYER role "
                "may read only their own linked profile."
            ),
            input_model=PlayerRefInput,
            output_model=players_schemas.PlayerResponse,
            allowed_roles=_player_roles(PLAYER_VIEW_ROLES),
        ),
        _get_player_status,
    ),
    RegisteredTool(
        ToolDefinition(
            name="get_player_match_history",
            description=(
                "Return paginated matches for a player ID. Returns match "
                "summaries only, not events or squad details. Staff roles "
                "may read any player; PLAYER role may read only their own history."
            ),
            input_model=PagedPlayerInput,
            output_model=MatchHistoryResult,
            allowed_roles=_player_roles(MATCH_READ_ROLES),
        ),
        _get_player_match_history,
    ),
    RegisteredTool(
        ToolDefinition(
            name="get_training_summary",
            description=(
                "Return paginated training participation history for a player "
                "ID. Returns session attendance and load fields only. Staff "
                "roles may read any player; PLAYER role may read only their own."
            ),
            input_model=PagedPlayerInput,
            output_model=TrainingSummaryResult,
            allowed_roles=_player_roles(TRAINING_READ_ROLES),
        ),
        _get_training_summary,
    ),
    RegisteredTool(
        ToolDefinition(
            name="get_player_availability",
            description=(
                "Return paginated availability records for a player ID. "
                "Returns status windows only, never medical diagnoses. Staff "
                "roles may read any player; PLAYER role may read only their own."
            ),
            input_model=PagedPlayerInput,
            output_model=AvailabilityResult,
            allowed_roles=_player_roles(AVAILABILITY_READ_ROLES),
        ),
        _get_player_availability,
    ),
    RegisteredTool(
        ToolDefinition(
            name="get_match_summary",
            description=(
                "Return one match by match ID. Returns the match record only, "
                "not squad, events, or video data. PLAYER role may read only "
                "matches they participate in."
            ),
            input_model=MatchRefInput,
            output_model=matches_schemas.MatchResponse,
            allowed_roles=_player_roles(MATCH_READ_ROLES),
        ),
        _get_match_summary,
    ),
    RegisteredTool(
        ToolDefinition(
            name="search_club_memory",
            description=(
                "Search governed club memories by text and explicit filters. "
                "Returns only memories the caller is authorized to retrieve; "
                "restricted, redacted, and expired memories are excluded by "
                "governance, never by the tool. Returns memory DTOs only, "
                "never vectors, embeddings, or ORM objects."
            ),
            input_model=MemorySearchInput,
            output_model=memory_schemas.RetrievalResponse,
            allowed_roles=tuple(RoleName),
        ),
        _search_club_memory,
    ),
)
