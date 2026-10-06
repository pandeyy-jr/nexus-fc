"""Phase 09D provider adapter tests. No network: every HTTP exchange
goes through httpx.MockTransport. No API keys, no live services."""

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.ai.copilot.openai_provider import OpenAIChatProvider, build_copilot_provider
from app.ai.copilot.provider import (
    ModelProviderError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
)
from app.ai.copilot.registry import build_default_registry
from app.ai.copilot.service import CopilotService
from app.core.config import Settings
from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_copilot_tools import load_actor

_TEST_KEY = "test-key-do-not-use-in-production-000"
_PLAYER_ID = "00000000-0000-0000-0000-000000000001"


def make_provider(handler, **overrides) -> OpenAIChatProvider:
    transport = httpx.MockTransport(handler)
    params: dict = {
        "model": "test-model",
        "api_key": SecretStr(_TEST_KEY),
        "base_url": "https://llm.test/v1",
        "timeout_seconds": 5.0,
        "max_output_tokens": 128,
        "transport": transport,
    }
    params.update(overrides)
    return OpenAIChatProvider(**params)


def chat_response(message: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": message}]})


async def test_valid_final_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return chat_response({"role": "assistant", "content": "Ada is available."})

    provider = make_provider(handler)
    response = await provider.complete("Who is available?", [], [])
    assert response.final_answer == "Ada is available."
    assert response.tool_calls == []
    assert len(seen) == 1
    assert seen[0].url.path == "/v1/chat/completions"


async def test_valid_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_player_status",
                            "arguments": f'{{"player_id": "{_PLAYER_ID}"}}',
                        },
                    }
                ],
            }
        )

    provider = make_provider(handler)
    response = await provider.complete("Tell me about Ada.", [], [])
    assert response.final_answer is None
    (call,) = response.tool_calls
    assert call.call_id == "call_1"
    assert call.tool_name == "get_player_status"
    assert call.arguments == {"player_id": _PLAYER_ID}


async def test_tool_schema_conversion() -> None:
    from app.ai.copilot.tools import BUILTIN_TOOLS

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode()))
        return chat_response({"role": "assistant", "content": "done."})

    provider = make_provider(handler)
    await provider.complete("Hi.", [tool.definition for tool in BUILTIN_TOOLS], [])
    functions = {tool["function"]["name"]: tool for tool in seen[0]["tools"]}
    assert len(functions) == 6
    status = functions["get_player_status"]
    assert status["type"] == "function"
    assert "player_id" in status["function"]["parameters"]["properties"]
    assert seen[0]["tool_choice"] == "auto"
    assert seen[0]["model"] == "test-model"
    assert seen[0]["max_tokens"] == 128


async def test_multiple_available_tools() -> None:
    from app.ai.copilot.tools import BUILTIN_TOOLS

    names = {tool.definition.name for tool in BUILTIN_TOOLS}
    assert names == {
        "get_player_status",
        "get_player_match_history",
        "get_training_summary",
        "get_player_availability",
        "get_match_summary",
        "search_club_memory",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": "not-a-dict"}]},
        {"choices": [{"message": {"role": "assistant"}}]},
        {"choices": [{"message": {"role": "assistant", "content": "   "}}]},
    ],
)
async def test_malformed_provider_response(payload: dict) -> None:
    provider = make_provider(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ModelProviderError):
        await provider.complete("Hi?", [], [])


@pytest.mark.parametrize(
    "arguments",
    ['{"player_id": ', "[1, 2]", '"just-a-string"', "null"],
)
async def test_malformed_tool_arguments(arguments: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_player_status",
                            "arguments": arguments,
                        },
                    }
                ],
            }
        )

    provider = make_provider(handler)
    with pytest.raises(ModelProviderError):
        await provider.complete("Hi?", [], [])


async def test_empty_provider_response() -> None:
    provider = make_provider(
        lambda request: chat_response({"role": "assistant", "content": None})
    )
    with pytest.raises(ModelProviderError):
        await provider.complete("Hi?", [], [])


async def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    provider = make_provider(handler)
    with pytest.raises(ModelProviderTimeout):
        await provider.complete("Hi?", [], [])


async def test_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = make_provider(handler)
    with pytest.raises(ModelProviderUnavailable):
        await provider.complete("Hi?", [], [])


async def test_authentication_failure_not_retried() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": "bad key"})

    provider = make_provider(handler)
    with pytest.raises(ModelProviderUnavailable):
        await provider.complete("Hi?", [], [])
    assert len(calls) == 1


async def test_rate_limit_retried_once() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return chat_response({"role": "assistant", "content": "recovered."})

    provider = make_provider(handler)
    response = await provider.complete("Hi?", [], [])
    assert response.final_answer == "recovered."
    assert len(calls) == 2


async def test_server_error_gives_up_after_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"error": "boom"})

    provider = make_provider(handler)
    with pytest.raises(ModelProviderError):
        await provider.complete("Hi?", [], [])
    assert len(calls) == 2


async def test_missing_credentials() -> None:
    settings = Settings(
        jwt_secret_key="x" * 32,
        copilot_api_key=None,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    with pytest.raises(ModelProviderUnavailable):
        build_copilot_provider(settings)
    blank = Settings(
        jwt_secret_key="x" * 32,
        copilot_api_key=SecretStr("   "),
        database_url="sqlite+aiosqlite:///:memory:",
    )
    with pytest.raises(ModelProviderUnavailable):
        build_copilot_provider(blank)


async def test_secret_never_written_to_logs(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_TEST_KEY}"
        return chat_response({"role": "assistant", "content": "ok."})

    provider = make_provider(handler)
    with caplog.at_level(logging.INFO, logger="app.ai.copilot.openai_provider"):
        await provider.complete("Hi?", [], [])
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert _TEST_KEY not in logged
    assert "Bearer" not in logged


@pytest.mark.asyncio
async def test_provider_cannot_bypass_registry(database: DatabaseFixture) -> None:
    """A model requesting an unauthorized tool is still denied by the
    existing registry — the adapter adds no authority of its own."""
    analyst_id, _ = await create_user(
        database, "copilot-provider-analyst@example.com", RoleName.ANALYST
    )
    actor = await load_actor(database, analyst_id)

    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_player_availability",
                            "arguments": f'{{"player_id": "{_PLAYER_ID}"}}',
                        },
                    }
                ],
            }
        )

    provider = make_provider(handler)
    service = CopilotService(build_default_registry(), provider)
    async with database.sessions() as session:
        from app.ai.copilot.models import CopilotRequest

        response = await service.ask(session, actor, CopilotRequest(question="Fit?"))
    assert response.tool_call_count == 1
    assert response.grounded is False
