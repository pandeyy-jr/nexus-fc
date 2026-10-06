"""OpenAI-compatible chat provider adapter (Phase 09D).

One concrete ``ModelProvider`` speaking the OpenAI chat-completions
dialect over plain HTTPS via httpx. No vendor SDK is installed or
required; any OpenAI-compatible endpoint works.

Isolation rules enforced here:
- Only ``question``, tool schemas, and prior tool *results* leave the
  process. Never JWTs, password hashes, sessions, ORM objects, Qdrant
  credentials, authorization state, or unrestricted memory rows.
- The API key is read from configuration at call time and never logged.
- Logs carry provider/model/latency/counts/error categories only.
"""

import json
import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from app.ai.copilot.models import (
    CopilotProviderResponse,
    CopilotToolCall,
    CopilotToolResult,
)
from app.ai.copilot.provider import (
    ModelProviderError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
    tool_json_schema,
)
from app.ai.copilot.tools import ToolDefinition
from app.core.config import Settings

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTIONS = (
    "You are the NEXUS FC club assistant. Answer only from the evidence "
    "returned by tools. Never invent players, matches, statistics, medical "
    "facts, or tactical events. If evidence is insufficient, say so."
)


def build_copilot_provider(settings: Settings) -> "OpenAIChatProvider":
    """Construct the configured provider, or raise unavailable when no
    credential is configured. Never crashes merely because the key is
    absent — callers map this to a controlled 503."""
    key = settings.copilot_api_key
    if key is None or not key.get_secret_value().strip():
        raise ModelProviderUnavailable("Copilot LLM credential is not configured")
    return OpenAIChatProvider(
        model=settings.copilot_model,
        api_key=key,
        base_url=settings.copilot_base_url,
        timeout_seconds=settings.copilot_timeout_seconds,
        max_output_tokens=settings.copilot_max_output_tokens,
    )


class OpenAIChatProvider:
    """Stateless OpenAI-dialect chat adapter."""

    def __init__(
        self,
        *,
        model: str,
        api_key: SecretStr | str,
        base_url: str,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model or not model.strip():
            raise ValueError("model must not be blank")
        if not base_url or not base_url.strip():
            raise ValueError("base_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._model = model.strip()
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._transport = transport

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(
        self,
        question: str,
        tools: Sequence[ToolDefinition],
        history: Sequence[CopilotToolResult],
    ) -> CopilotProviderResponse:
        started = time.perf_counter()
        payload = self._request_payload(question, tools, history)
        try:
            data = await self._post_with_retry(payload)
        except (ModelProviderTimeout, ModelProviderUnavailable):
            raise
        except ModelProviderError:
            raise
        except Exception as exc:
            raise ModelProviderError(
                f"provider request failed: {type(exc).__name__}"
            ) from exc
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "copilot provider call completed",
                extra={
                    "provider": "openai-compatible",
                    "model": self._model,
                    "latency_ms": round(elapsed_ms, 1),
                    "tool_count": len(tools),
                    "history_count": len(history),
                },
            )
        return self._parse_response(data)

    def _request_payload(
        self,
        question: str,
        tools: Sequence[ToolDefinition],
        history: Sequence[CopilotToolResult],
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": question},
        ]
        rendered = self._render_history(history)
        if rendered:
            messages.append({"role": "user", "content": rendered})
        return {
            "model": self._model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": schema["name"],
                        "description": schema["description"],
                        "parameters": schema["parameters"],
                    },
                }
                for schema in (tool_json_schema(tool) for tool in tools)
            ],
            "tool_choice": "auto",
            "max_tokens": self._max_output_tokens,
        }

    @staticmethod
    def _render_history(history: Sequence[CopilotToolResult]) -> str:
        """Prior tool outcomes as plain data text. Never authority."""
        lines = []
        for item in history:
            if item.success:
                lines.append(f"{item.tool_name} succeeded: {json.dumps(item.result)}")
            else:
                lines.append(f"{item.tool_name} failed: {item.error_code}")
        return "Previous tool results:\n" + "\n".join(lines)

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """At most one retry, only for transient statuses. Auth and
        client errors are never retried."""
        key = (
            self._api_key.get_secret_value()
            if isinstance(self._api_key, SecretStr)
            else self._api_key
        )
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            attempts = 0
            while True:
                attempts += 1
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                except httpx.TimeoutException as exc:
                    raise ModelProviderTimeout("provider request timed out") from exc
                except (httpx.ConnectError, httpx.NetworkError) as exc:
                    raise ModelProviderUnavailable(
                        f"provider unreachable: {type(exc).__name__}"
                    ) from exc
                except Exception as exc:
                    raise ModelProviderError(
                        f"provider request failed: {type(exc).__name__}"
                    ) from exc
                if response.status_code in (401, 403):
                    raise ModelProviderUnavailable(
                        "provider rejected credentials; not retried"
                    )
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempts < 2:
                        continue
                    raise ModelProviderError(
                        f"provider error after retry: HTTP {response.status_code}"
                    )
                if response.status_code != 200:
                    raise ModelProviderError(
                        f"provider error: HTTP {response.status_code}"
                    )
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ModelProviderError(
                        "provider returned malformed JSON"
                    ) from exc
                if not isinstance(data, dict):
                    raise ModelProviderError("provider returned malformed JSON")
                return data

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> CopilotProviderResponse:
        """Convert one chat-completions payload into the 09C contract.
        Anything unexpected is a malformed-response error, never a guess."""
        try:
            choices = data["choices"]
            message = choices[0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelProviderError("provider response has no usable choice") from exc
        if not isinstance(message, dict):
            raise ModelProviderError("provider response has no usable choice")
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ModelProviderError("malformed tool calls in provider response")
        calls: list[CopilotToolCall] = []
        for raw_call in raw_calls:
            try:
                function = raw_call["function"]
                name = function["name"]
                raw_arguments = function.get("arguments", "{}")
            except (KeyError, TypeError) as exc:
                raise ModelProviderError(
                    "malformed tool call in provider response"
                ) from exc
            if not isinstance(name, str) or not name.strip():
                raise ModelProviderError("malformed tool call in provider response")
            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except (ValueError, TypeError) as exc:
                raise ModelProviderError(
                    "malformed tool arguments in provider response"
                ) from exc
            if not isinstance(arguments, dict):
                raise ModelProviderError(
                    "malformed tool arguments in provider response"
                )
            call_id = raw_call.get("id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise ModelProviderError("malformed tool call in provider response")
            calls.append(
                CopilotToolCall(call_id=call_id, tool_name=name, arguments=arguments)
            )
        content = message.get("content")
        if calls:
            return CopilotProviderResponse(final_answer=None, tool_calls=calls)
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError("provider returned an empty response")
        return CopilotProviderResponse(final_answer=content, tool_calls=[])
