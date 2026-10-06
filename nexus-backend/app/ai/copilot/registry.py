"""Governed copilot tool registry and execution boundary (Phase 09A).

Only this module resolves tool names, checks permissions, and invokes
handlers. LLM input is untrusted data: arguments are validated, the
actor always comes from the server-side context, and permission is
evaluated here — never by the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.copilot.tools import BUILTIN_TOOLS, RegisteredTool, ToolDefinition
from app.db.models.user import User

_ERROR_MESSAGE_LIMIT = 300


class ToolErrorCategory(StrEnum):
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_NOT_AUTHORIZED = "TOOL_NOT_AUTHORIZED"
    TOOL_INVALID_INPUT = "TOOL_INVALID_INPUT"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: ToolErrorCategory
    message: str = Field(min_length=1, max_length=500)
    tool_name: str = Field(min_length=1, max_length=64)


class ToolExecutionRecord(BaseModel):
    """Internal execution record. Arguments are deliberately excluded —
    they may contain IDs the audit trail does not need to retain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1, max_length=64)
    actor_id: UUID
    request_id: UUID | None = None
    started_at: datetime
    completed_at: datetime
    success: bool
    error_category: ToolErrorCategory | None = None


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool
    data: dict | None = None
    error: ToolError | None = None
    record: ToolExecutionRecord

    @model_validator(mode="after")
    def check_consistency(self) -> ToolExecutionResult:
        if self.success and (self.data is None or self.error is not None):
            raise ValueError("successful results require data and no error")
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("failed results require an error and no data")
        if self.record.success != self.success:
            raise ValueError("record success must match result success")
        if (self.record.error_category is None) == (self.error is not None):
            raise ValueError("record error category must match result error")
        return self


@dataclass
class ToolExecutionContext:
    """Server-side invocation context. Constructed by NEXUS code only —
    actor identity never comes from tool arguments."""

    actor: User
    session: AsyncSession
    request_id: UUID | None = None
    extra: dict[str, str] = field(default_factory=dict)


def _categorize(name: str, exc: BaseException) -> ToolError:
    """Map handler failures to public categories without leaking internals."""
    if isinstance(exc, HTTPException):
        detail = str(exc.detail)[:_ERROR_MESSAGE_LIMIT]
        if exc.status_code == 403:
            return ToolError(
                category=ToolErrorCategory.TOOL_NOT_AUTHORIZED,
                message=detail,
                tool_name=name,
            )
        if exc.status_code == 503:
            return ToolError(
                category=ToolErrorCategory.TOOL_UNAVAILABLE,
                message=detail,
                tool_name=name,
            )
        return ToolError(
            category=ToolErrorCategory.TOOL_EXECUTION_FAILED,
            message=detail,
            tool_name=name,
        )
    return ToolError(
        category=ToolErrorCategory.TOOL_EXECUTION_FAILED,
        message="tool execution failed",
        tool_name=name,
    )


class ToolRegistry:
    """Name-keyed registry with server-side permission checks."""

    def __init__(self, tools: tuple[RegisteredTool, ...] = ()) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for tool in tools:
            self.register(tool.definition, tool.handler)

    def register(self, definition: ToolDefinition, handler) -> None:
        if not callable(handler):
            raise ValueError("tool handler must be callable")
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool name: {definition.name}")
        self._tools[definition.name] = RegisteredTool(
            definition=definition, handler=handler
        )

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool: {name}") from None

    def list_for_actor(self, actor: User) -> list[ToolDefinition]:
        """Deterministic (name-sorted) tool list filtered by server-side role."""
        role = actor.role.name
        names = sorted(self._tools)
        return [
            self._tools[name].definition
            for name in names
            if role in self._tools[name].definition.allowed_roles
        ]

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        started_at = datetime.now(UTC)

        def record(success: bool, error: ToolError | None) -> ToolExecutionRecord:
            return ToolExecutionRecord(
                tool_name=tool_name,
                actor_id=context.actor.id,
                request_id=context.request_id,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                success=success,
                error_category=error.category if error is not None else None,
            )

        def fail(error: ToolError) -> ToolExecutionResult:
            return ToolExecutionResult(
                success=False, error=error, record=record(False, error)
            )

        if not isinstance(context.actor, User) or not context.actor.is_active:
            error = ToolError(
                category=ToolErrorCategory.TOOL_NOT_AUTHORIZED,
                message="invalid actor context",
                tool_name=tool_name,
            )
            return fail(error)
        try:
            registered = self.get(tool_name)
        except KeyError:
            error = ToolError(
                category=ToolErrorCategory.TOOL_NOT_FOUND,
                message=f"unknown tool: {tool_name}",
                tool_name=tool_name,
            )
            return fail(error)
        definition = registered.definition
        if context.actor.role.name not in definition.allowed_roles:
            error = ToolError(
                category=ToolErrorCategory.TOOL_NOT_AUTHORIZED,
                message="actor role may not use this tool",
                tool_name=tool_name,
            )
            return fail(error)
        if not isinstance(arguments, dict):
            error = ToolError(
                category=ToolErrorCategory.TOOL_INVALID_INPUT,
                message="tool arguments must be an object",
                tool_name=tool_name,
            )
            return fail(error)
        try:
            validated = definition.input_model(**arguments)
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}".rstrip()
                for err in exc.errors()[:5]
            )[:_ERROR_MESSAGE_LIMIT]
            error = ToolError(
                category=ToolErrorCategory.TOOL_INVALID_INPUT,
                message=message or "invalid tool arguments",
                tool_name=tool_name,
            )
            return fail(error)
        try:
            output = await registered.handler(context.session, context.actor, validated)
            validated_output = definition.output_model.model_validate(
                output.model_dump() if isinstance(output, BaseModel) else output
            )
        except HTTPException as exc:
            error = _categorize(tool_name, exc)
            return fail(error)
        except Exception:
            error = ToolError(
                category=ToolErrorCategory.TOOL_EXECUTION_FAILED,
                message="tool execution failed",
                tool_name=tool_name,
            )
            return fail(error)
        return ToolExecutionResult(
            success=True,
            data=validated_output.model_dump(mode="json"),
            record=record(True, None),
        )


def build_default_registry() -> ToolRegistry:
    """Registry preloaded with the read-only builtin tools."""
    return ToolRegistry(BUILTIN_TOOLS)
