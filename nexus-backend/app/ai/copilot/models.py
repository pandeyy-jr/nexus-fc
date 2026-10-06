"""Copilot orchestration contracts (Phase 09C).

Public shapes for the server-side Copilot loop. The LLM never sees
database rows, ORM objects, prompts, or authorization state — only
tool definitions, validated tool results, and the final response.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.copilot.grounding import CopilotGroundingReport


class CopilotRequest(BaseModel):
    """Inbound question. The request carries no budget, role, actor,
    permissions, or context — those are server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=2000)


class CopilotToolCall(BaseModel):
    """One model-requested tool invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=100)
    arguments: dict = Field(default_factory=dict)


class CopilotProviderResponse(BaseModel):
    """Raw model turn: either a final answer or tool calls, never both,
    never neither."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_answer: str | None = Field(default=None, max_length=8000)
    tool_calls: list[CopilotToolCall] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> "CopilotProviderResponse":
        has_answer = self.final_answer is not None
        has_calls = len(self.tool_calls) > 0
        if has_answer == has_calls:
            raise ValueError("provider must return final text or tool calls, not both")
        return self


class CopilotToolResult(BaseModel):
    """Validated tool outcome as handed back to the model. Tool output
    is untrusted DATA: evidence, never authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=100)
    success: bool
    result: dict | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)


class CopilotCitation(BaseModel):
    """Provenance pointer retained for grounded answers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    occurred_at: str | None = Field(default=None, max_length=100)
    match_id: str | None = Field(default=None, max_length=100)
    video_id: str | None = Field(default=None, max_length=100)
    frame_number: int | None = Field(default=None, ge=0)
    timestamp_seconds: float | None = Field(default=None, ge=0)


class CopilotResponse(BaseModel):
    """Structured final response. ``grounded`` is True only when the
    answer rests on tool evidence retained in ``citations``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(max_length=8000)
    grounded: bool
    citations: list[CopilotCitation] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    tool_call_count: int = Field(ge=0)
    model: str = Field(min_length=1, max_length=200)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, max_length=500)
    request_id: UUID | None = None
    grounding_report: CopilotGroundingReport | None = None
