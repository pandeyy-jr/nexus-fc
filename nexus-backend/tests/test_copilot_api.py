"""Phase 09C API tests: auth, injection resistance, provider states.

Uses ScriptedFakeProvider via dependency override — no network, no keys."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.ai.copilot.provider import ScriptedFakeProvider
from app.api.v1.endpoints.copilot import get_copilot_provider
from app.core.roles import RoleName
from app.main import app
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_copilot_tools import load_actor, seed_domain


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def use_provider(provider) -> None:
    app.dependency_overrides[get_copilot_provider] = lambda: provider


def answer(text: str) -> dict:
    return {"final_answer": text, "tool_calls": []}


@pytest.mark.asyncio
async def test_unauthenticated_rejected(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    del database
    response = await client.post(
        "/api/v1/ai/copilot/query", json={"question": "Hello?"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_grounded_flow_via_api(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    admin_id, token = await create_user(
        database, "copilot-admin@example.com", RoleName.ADMIN
    )
    actor = await load_actor(database, admin_id)
    ids = await seed_domain(database, admin_id)
    use_provider(
        ScriptedFakeProvider(
            [
                {
                    "final_answer": None,
                    "tool_calls": [
                        {
                            "call_id": "c1",
                            "tool_name": "get_player_status",
                            "arguments": {"player_id": str(ids["player_a"])},
                        }
                    ],
                },
                answer("Ada A is active."),
            ]
        )
    )
    assert actor.id == admin_id
    response = await client.post(
        "/api/v1/ai/copilot/query",
        json={"question": "Tell me about Ada."},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Ada A is active."
    assert body["grounded"] is True
    assert body["tool_call_count"] == 1
    assert body["tools_used"] == ["get_player_status"]
    assert body["error"] is None
    assert len(body["citations"]) == 1
    assert body["citations"][0]["source_id"] == str(ids["player_a"])


@pytest.mark.asyncio
async def test_provider_unconfigured_gives_503(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, token = await create_user(database, "copilot-a2@example.com", RoleName.ADMIN)
    response = await client.post(
        "/api/v1/ai/copilot/query",
        json={"question": "Hello?"},
        headers=bearer(token),
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_copilot_unknown_fields_rejected(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, token = await create_user(database, "copilot-a3@example.com", RoleName.ADMIN)
    use_provider(ScriptedFakeProvider([answer("Hi.")]))
    for injected in (
        {"role": "ADMIN"},
        {"actor_id": str(uuid4())},
        {"max_tool_calls": 100},
        {"tools": ["get_player_status"]},
    ):
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?", **injected},
            headers=bearer(token),
        )
        assert response.status_code == 422, injected


@pytest.mark.asyncio
async def test_blank_question_rejected(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, token = await create_user(database, "copilot-a4@example.com", RoleName.ADMIN)
    use_provider(ScriptedFakeProvider([answer("Hi.")]))
    assert (
        await client.post(
            "/api/v1/ai/copilot/query", json={"question": ""}, headers=bearer(token)
        )
    ).status_code == 422


def scripted_provider(player_id: str) -> ScriptedFakeProvider:
    return ScriptedFakeProvider(
        [
            {
                "final_answer": None,
                "tool_calls": [
                    {
                        "call_id": "c1",
                        "tool_name": "get_player_status",
                        "arguments": {"player_id": player_id},
                    }
                ],
            },
            answer("Ada A is active."),
        ]
    )


@pytest.mark.asyncio
async def test_end_to_end_governed_chain(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    admin_id, admin_token = await create_user(
        database, "copilot-admin-e2e@example.com", RoleName.ADMIN
    )
    _, player_token = await create_user(
        database, "copilot-player-e2e@example.com", RoleName.PLAYER
    )
    ids = await seed_domain(database, admin_id)
    use_provider(scripted_provider(str(ids["player_a"])))
    admin_response = await client.post(
        "/api/v1/ai/copilot/query",
        json={"question": "Tell me about Ada."},
        headers=bearer(admin_token),
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json()["grounded"] is True

    # Same question, unprivileged actor: identical contract shape,
    # governed content only.
    use_provider(scripted_provider(str(ids["player_a"])))
    player_response = await client.post(
        "/api/v1/ai/copilot/query",
        json={"question": "Tell me about Ada."},
        headers=bearer(player_token),
    )
    assert player_response.status_code == 200, player_response.text
    body = player_response.json()
    assert set(body) == {
        "answer",
        "grounded",
        "citations",
        "tools_used",
        "tool_call_count",
        "model",
        "warnings",
        "error",
        "request_id",
        "grounding_report",
    }
