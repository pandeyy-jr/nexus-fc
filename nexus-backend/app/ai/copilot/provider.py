"""Model provider abstraction (Phase 09C).

The orchestrator talks only to this interface. Real vendors
(OpenAI/Gemini/Anthropic/local) implement ``complete`` later without
changing any orchestration code. Tests use ``ScriptedFakeProvider``.
"""

from collections.abc import Sequence
from typing import Any, Protocol

from app.ai.copilot.models import CopilotProviderResponse, CopilotToolResult
from app.ai.copilot.tools import ToolDefinition


class ModelProviderError(Exception):
    """Base class for explicit model failures."""


class ModelProviderUnavailable(ModelProviderError):
    """The model backend cannot be reached or is unconfigured."""


class ModelProviderTimeout(ModelProviderError):
    """The model backend did not answer in time."""


class ModelProvider(Protocol):
    """Minimal turn-based contract: given the question, visible tool
    definitions, and transcript so far, return final text or tool calls."""

    model_id: str

    async def complete(
        self,
        question: str,
        tools: Sequence[ToolDefinition],
        history: Sequence[CopilotToolResult],
    ) -> CopilotProviderResponse: ...


def tool_json_schema(definition: ToolDefinition) -> dict[str, Any]:
    """Provider-facing capability description for one tool."""
    return {
        "name": definition.name,
        "description": definition.description,
        "parameters": definition.input_model.model_json_schema(),
        "version": definition.version,
    }


class ScriptedFakeProvider:
    """Deterministic test double. Each ``complete`` consumes the next
    script entry: a response dict (validated by the orchestrator, so
    malformed payloads exercise failure paths), a ready-made response,
    or an exception to raise. Exhaustion is an explicit error."""

    model_id = "fake-test-provider"

    def __init__(self, script: Sequence[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        question: str,
        tools: Sequence[ToolDefinition],
        history: Sequence[CopilotToolResult],
    ) -> Any:
        self.calls.append(
            {
                "question": question,
                "tools": [tool.name for tool in tools],
                "history": [item.model_dump(mode="json") for item in history],
            }
        )
        if not self._script:
            raise ModelProviderError("script exhausted")
        return self._script.pop(0)
