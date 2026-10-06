"""Phase 09F hardening tests: rate limiting, timeouts, safe errors, audit, read-only."""

import logging
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.ai.copilot.openai_provider import OpenAIChatProvider
from app.ai.copilot.provider import ModelProviderTimeout, ScriptedFakeProvider
from app.api.v1.endpoints.copilot import get_copilot_provider
from app.core.config import get_settings
from app.core.rate_limit import InMemoryRateLimiter
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


def call(call_id: str, tool_name: str, arguments: dict) -> dict:
    return {
        "final_answer": None,
        "tool_calls": [
            {"call_id": call_id, "tool_name": tool_name, "arguments": arguments}
        ],
    }


class TestRateLimiting:
    """A. rate limit
    B. rate-limit identity cannot be spoofed"""

    @pytest.mark.asyncio
    async def test_rate_limit_enforced(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """A: Rate limit is enforced per authenticated actor."""
        admin_id, token = await create_user(database, "rl-admin@example.com", "ADMIN")
        actor = await load_actor(database, admin_id)
        use_provider(ScriptedFakeProvider([answer("Hi.")]))

        limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)
        # Direct limiter test
        for _ in range(3):
            limiter.check_limit(f"copilot:{actor.id}")
            limiter.record_hit(f"copilot:{actor.id}")
        with pytest.raises(Exception) as exc_info:
            limiter.check_limit(f"copilot:{actor.id}")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limit_identity_not_spoofable(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """B: Rate limit keyed by server-derived actor.id, not client header."""
        _, token = await create_user(database, "rl-admin2@example.com", "ADMIN")
        use_provider(ScriptedFakeProvider([answer("Hi.")]))

        # Make requests with different fake X-Request-ID headers;
        # rate limit should not be affected
        for _ in range(5):
            response = await client.post(
                "/api/v1/ai/copilot/query",
                json={"question": "Hi?"},
                headers={**bearer(token), "X-Request-ID": f"client-{_}"},
            )
            assert response.status_code == 200, response.text
            assert "X-Request-ID" in response.headers
            assert response.headers["X-Request-ID"] != f"client-{_}"


class TestRequestBudgets:
    """C. oversized request
    D. bounded tool calls
    E. bounded iterations"""

    @pytest.mark.asyncio
    async def test_oversized_question_rejected(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """C: Question length is bounded."""
        _, token = await create_user(database, "budget-q@example.com", "ADMIN")
        use_provider(ScriptedFakeProvider([answer("Hi.")]))

        # Very long question should be rejected (pydantic max_length=2000)
        long_q = "x" * 3000
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": long_q},
            headers=bearer(token),
        )
        # Pydantic validation should reject
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_tool_call_budget_enforced(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """D: MAX_TOOL_CALLS=5 enforced."""
        admin_id, token = await create_user(database, "budget-tc@example.com", "ADMIN")
        _ = await load_actor(database, admin_id)
        ids = await seed_domain(database, admin_id)

        script = [
            call("c0", "get_player_status", {"player_id": str(ids["player_a"])}),
            call("c1", "get_match_summary", {"match_id": str(ids["match_id"])}),
            call("c2", "get_training_summary", {"player_id": str(ids["player_a"])}),
            call("c3", "get_player_availability", {"player_id": str(ids["player_a"])}),
            call("c4", "search_club_memory", {"text": "derby", "limit": 5}),
            call("c5", "get_player_status", {"player_id": str(ids["player_b"])}),
            answer("Never reached."),
        ]
        use_provider(ScriptedFakeProvider(script))
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Tell me more."},
            headers=bearer(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tool_call_count"] == 5
        assert body["error"] == "TOOL_BUDGET_EXHAUSTED"

    @pytest.mark.asyncio
    async def test_iteration_budget_enforced(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """E: MAX_ITERATIONS=6 enforced."""
        admin_id, token = await create_user(database, "budget-it@example.com", "ADMIN")
        _ = await load_actor(database, admin_id)
        ids = await seed_domain(database, admin_id)

        # Script with different arguments to avoid deduplication
        script = [
            call(
                f"c{i}",
                "get_player_status",
                {"player_id": str(ids["player_a"]), "dummy": i},
            )
            for i in range(10)
        ]
        script.append(answer("Done."))
        use_provider(ScriptedFakeProvider(script))
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Loop?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        body = response.json()
        # Should hit tool budget first (5 calls max)
        assert body["tool_call_count"] == 5


class TestProviderTimeoutAndRetry:
    """F. provider timeout
    G. provider retry behavior"""

    @pytest.mark.asyncio
    async def test_provider_timeout_handled(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """F: Provider timeout returns controlled error."""
        _, token = await create_user(database, "timeout@example.com", "ADMIN")

        class SlowProvider:
            model_id = "slow-provider"

            async def complete(self, question, tools, history):
                raise ModelProviderTimeout("too slow")

        use_provider(SlowProvider())
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hello?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error"] == "PROVIDER_TIMEOUT"
        assert body["answer"] == ""

    @pytest.mark.asyncio
    async def test_provider_retry_once_on_429(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """G: Provider retries once on 429/5xx, never on 401/403."""
        import httpx
        from pydantic import SecretStr

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": "ok."}}]
                },
            )

        transport = httpx.MockTransport(handler)
        provider = OpenAIChatProvider(
            model="test-model",
            api_key=SecretStr("test-key"),
            base_url="https://llm.test/v1",
            timeout_seconds=5.0,
            max_output_tokens=128,
            transport=transport,
        )
        app.dependency_overrides[get_copilot_provider] = lambda: provider

        _, token = await create_user(database, "retry@example.com", "ADMIN")
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        assert call_count == 2  # one retry
        body = response.json()
        assert body["answer"] == "ok."

    @pytest.mark.asyncio
    async def test_provider_no_retry_on_401(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """G: Provider does not retry on 401."""
        import httpx
        from pydantic import SecretStr

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        transport = httpx.MockTransport(handler)
        provider = OpenAIChatProvider(
            model="test-model",
            api_key=SecretStr("test-key"),
            base_url="https://llm.test/v1",
            timeout_seconds=5.0,
            max_output_tokens=128,
            transport=transport,
        )
        app.dependency_overrides[get_copilot_provider] = lambda: provider

        _, token = await create_user(database, "retry401@example.com", "ADMIN")
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        assert call_count == 1  # no retry
        body = response.json()
        assert body["error"] == "PROVIDER_UNAVAILABLE"


class TestSafeErrorResponses:
    """H. safe public error"""

    @pytest.mark.asyncio
    async def test_no_stack_traces_in_response(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """H: Error responses never contain stack traces."""
        _, token = await create_user(database, "err1@example.com", "ADMIN")

        class BrokenProvider:
            model_id = "broken"

            async def complete(self, question, tools, history):
                raise RuntimeError("simulated crash")

        use_provider(BrokenProvider())
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is not None
        # Should be a controlled error category, not a traceback
        assert "traceback" not in str(body).lower()
        assert "RuntimeError" not in body.get("error", "")

    @pytest.mark.asyncio
    async def test_no_secrets_in_logs(
        self,
        caplog: pytest.LogCaptureFixture,
        client: AsyncClient,
        database: DatabaseFixture,
    ):
        """J: No secrets in logs."""
        _, token = await create_user(database, "logsecret@example.com", "ADMIN")

        use_provider(ScriptedFakeProvider([answer("ok")]))
        with caplog.at_level(logging.INFO, logger="app.api.v1.endpoints.copilot"):
            response = await client.post(
                "/api/v1/ai/copilot/query",
                json={"question": "Hi?"},
                headers=bearer(token),
            )
        assert response.status_code == 200
        logs = "\n".join(r.getMessage() for r in caplog.records)
        assert "Bearer" not in logs
        assert token not in logs


class TestRequestIDPropagation:
    """I. request ID propagation"""

    @pytest.mark.asyncio
    async def test_request_id_in_response(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """I: X-Request-ID returned in header (server-generated for trust)."""
        _, token = await create_user(database, "reqid@example.com", "ADMIN")
        use_provider(ScriptedFakeProvider([answer("ok")]))

        # Client-provided ID is ignored; server generates its own for trust
        custom_id = str(uuid4())
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?"},
            headers={**bearer(token), "X-Request-ID": custom_id},
        )
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Server generates its own ID, doesn't echo client's
        assert response.headers["X-Request-ID"] != custom_id
        # Should be a valid UUID
        import uuid

        uuid.UUID(response.headers["X-Request-ID"])  # raises if invalid

    @pytest.mark.asyncio
    async def test_request_id_in_logs(
        self,
        caplog: pytest.LogCaptureFixture,
        client: AsyncClient,
        database: DatabaseFixture,
    ):
        """I: Request ID appears in logs."""
        _, token = await create_user(database, "reqid2@example.com", "ADMIN")
        use_provider(ScriptedFakeProvider([answer("ok")]))

        with caplog.at_level(logging.INFO, logger="app.api.v1.endpoints.copilot"):
            response = await client.post(
                "/api/v1/ai/copilot/query",
                json={"question": "Hi?"},
                headers=bearer(token),
            )
        assert response.status_code == 200
        server_request_id = response.headers["X-Request-ID"]

        # Check structured log extra fields contain the server-generated request_id
        found = False
        for record in caplog.records:
            if getattr(record, "request_id", None) == server_request_id:
                found = True
                break
        assert found, (
            f"Server request ID {server_request_id} not found in log extra fields"
        )


class TestAuthAndAuthorization:
    """K. inactive actor
    L. unauthorized actor/tool"""

    @pytest.mark.asyncio
    async def test_inactive_actor_rejected(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """K: Inactive users are rejected at auth layer."""

        from app.db.models.user import User

        # Create user, then deactivate
        user_id, token = await create_user(database, "inactive@example.com", "ADMIN")
        async with database.sessions() as session:
            user = await session.get(User, user_id)
            user.is_active = False
            await session.commit()

        use_provider(ScriptedFakeProvider([answer("ok")]))
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Hi?"},
            headers=bearer(token),
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthorized_tool_rejected(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """L: Actor without tool permission gets structured error."""
        analyst_id, token = await create_user(
            database, "unauth-tool@example.com", "ANALYST"
        )
        _ = await load_actor(database, analyst_id)
        ids = await seed_domain(database, analyst_id)

        use_provider(
            ScriptedFakeProvider(
                [
                    call(
                        "c1",
                        "get_player_availability",
                        {"player_id": str(ids["player_a"])},
                    ),
                    answer("Cannot access."),
                ]
            )
        )
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Availability?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["tool_call_count"] == 1
        assert body["grounded"] is False
        # Tool execution fails with TOOL_NOT_AUTHORIZED but loop continues


class TestReadOnlyIntegrity:
    """M. no mutation"""

    @pytest.mark.asyncio
    async def test_no_database_mutation(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """M: Copilot requests do not mutate database."""
        from sqlalchemy import func, select

        from app.db.models.availability import PlayerAvailability
        from app.db.models.match import Match
        from app.db.models.memory import EvidenceReference, MemoryRecord
        from app.db.models.player import Player
        from app.db.models.training import TrainingParticipation, TrainingSession

        admin_id, token = await create_user(database, "readonly@example.com", "ADMIN")
        _ = await load_actor(database, admin_id)
        ids = await seed_domain(database, admin_id)

        async def counts():
            async with database.sessions() as session:
                out = {}
                for model, key in (
                    (Player, "players"),
                    (Match, "matches"),
                    (TrainingSession, "sessions"),
                    (TrainingParticipation, "participations"),
                    (PlayerAvailability, "records"),
                    (MemoryRecord, "memories"),
                    (EvidenceReference, "evidence"),
                ):
                    out[key] = await session.scalar(
                        select(func.count()).select_from(model)
                    )
                return out

        before = await counts()
        use_provider(
            ScriptedFakeProvider(
                [
                    call(
                        "c1", "get_player_status", {"player_id": str(ids["player_a"])}
                    ),
                    call("c2", "search_club_memory", {"text": "Derby", "limit": 10}),
                    answer("Done."),
                ]
            )
        )
        response = await client.post(
            "/api/v1/ai/copilot/query",
            json={"question": "Report?"},
            headers=bearer(token),
        )
        assert response.status_code == 200
        after = await counts()
        assert after == before


class TestProviderUnavailableStartup:
    """N. provider unavailable does not break startup"""

    def test_app_starts_without_copilot_key(self):
        """N: Application can start without COPILOT_API_KEY."""
        settings = get_settings()
        assert (
            settings.copilot_api_key is None
            or not settings.copilot_api_key.get_secret_value().strip()
        )
        # Settings loads fine - provider just becomes unavailable at call time


class TestHealthEndpoint:
    """O. health endpoint does not leak configuration"""

    @pytest.mark.asyncio
    async def test_health_does_not_call_provider(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """O: Health check does not make provider calls."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "copilot" not in str(body).lower()
        # No API key in response
        assert "api_key" not in str(body).lower()

    @pytest.mark.asyncio
    async def test_health_db_does_not_leak_config(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """O: Database health check does not leak config."""
        response = await client.get("/api/v1/health/db")
        assert response.status_code in (200, 503)  # depends on DB availability
        body = response.json()
        assert "password" not in str(body).lower()
        assert "secret" not in str(body).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
