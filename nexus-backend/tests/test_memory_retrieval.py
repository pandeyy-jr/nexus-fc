"""Phase 08E retrieval tests: governed deterministic retrieval only.
No vectors, no scores, no LLM — database backend plus choke points."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.schemas.memory import MemoryView, RetrievalQuery
from app.services import memory_retrieval
from app.services.memory_governance import redact_memory
from app.services.memory_retrieval import (
    DatabaseRetrievalBackend,
    RetrievalBackend,
    retrieve_memories,
)
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_memory_governance import make_user, record


async def test_authorized_retrieval(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin@example.com", RoleName.ADMIN)
    await record(database, admin)
    async with database.sessions() as session:
        response = await retrieve_memories(
            session, admin, RetrievalQuery(memory_type=MemoryType.MATCH)
        )
    assert response.result_count == 1
    (match,) = response.results
    assert isinstance(match.memory, MemoryView)
    assert match.memory.memory_type is MemoryType.MATCH
    assert match.governance_status == "allowed"
    assert "memory_type" in match.match_reason
    assert response.query.limit == 20


async def test_unauthorized_retrieval_excluded(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-2@example.com", RoleName.ADMIN)
    scout = await make_user(database, "ret-scout@example.com", RoleName.SCOUT)
    await record(database, admin, sensitivity=MemorySensitivity.TACTICAL)
    async with database.sessions() as session:
        response = await retrieve_memories(session, scout, RetrievalQuery())
    assert response.result_count == 0
    assert response.results == []


async def test_player_isolation(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-3@example.com", RoleName.ADMIN)
    player = await make_user(database, "ret-player@example.com", RoleName.PLAYER)
    await record(database, admin, sensitivity=MemorySensitivity.CLUB_GENERAL)
    await record(
        database,
        admin,
        sensitivity=MemorySensitivity.PERFORMANCE,
        source_id="note-ret-p",
    )
    async with database.sessions() as session:
        response = await retrieve_memories(session, player, RetrievalQuery())
    assert response.result_count == 1
    assert response.results[0].memory.sensitivity is MemorySensitivity.CLUB_GENERAL


async def test_restricted_sensitivity(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-4@example.com", RoleName.ADMIN)
    coach = await make_user(database, "ret-coach@example.com", RoleName.HEAD_COACH)
    await record(database, admin, sensitivity=MemorySensitivity.RESTRICTED)
    async with database.sessions() as session:
        assert (
            await retrieve_memories(session, coach, RetrievalQuery())
        ).result_count == 0
        assert (
            await retrieve_memories(session, admin, RetrievalQuery())
        ).result_count == 1


async def test_redacted_memories_excluded(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-5@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        await redact_memory(session, admin, view.id)
        response = await retrieve_memories(session, admin, RetrievalQuery())
    assert response.result_count == 0


async def test_expired_memories_excluded(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-6@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        stored = await session.get(MemoryRecord, view.id)
        assert stored is not None
        from datetime import timedelta

        stored.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        response = await retrieve_memories(session, admin, RetrievalQuery())
    assert response.result_count == 0


async def test_explicit_filters(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-7@example.com", RoleName.ADMIN)
    await record(database, admin, source_id="note-a")
    await record(
        database,
        admin,
        memory_type=MemoryType.TRAINING,
        source_id="note-b",
        source_type=MemorySourceType.TRAINING_RECORD,
    )
    async with database.sessions() as session:
        by_type = await retrieve_memories(
            session, admin, RetrievalQuery(memory_type=MemoryType.TRAINING)
        )
        assert by_type.result_count == 1
        by_source = await retrieve_memories(
            session, admin, RetrievalQuery(source_id="note-a")
        )
        assert by_source.result_count == 1
        assert by_source.results[0].memory.source_id == "note-a"
        ranged = await retrieve_memories(
            session,
            admin,
            RetrievalQuery(
                occurred_from=datetime(2026, 9, 1, tzinfo=UTC),
                occurred_to=datetime(2026, 9, 2, tzinfo=UTC),
            ),
        )
        assert ranged.result_count == 2


async def test_deterministic_ordering(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-8@example.com", RoleName.ADMIN)
    for index in range(3):
        await record(database, admin, source_id=f"note-ord-{index}")
    async with database.sessions() as session:
        first = await retrieve_memories(session, admin, RetrievalQuery())
        second = await retrieve_memories(session, admin, RetrievalQuery())
    assert [r.memory.id for r in first.results] == [r.memory.id for r in second.results]
    assert first == second


async def test_provenance_preservation(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-9@example.com", RoleName.ADMIN)
    await record(database, admin)
    async with database.sessions() as session:
        (match,) = (await retrieve_memories(session, admin, RetrievalQuery())).results
    memory = match.memory
    assert memory.id is not None
    assert memory.source_type is MemorySourceType.HUMAN_RECORDED
    assert memory.source_id == "note-gov-1"
    assert memory.occurred_at == datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


async def test_bounded_limits(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-10@example.com", RoleName.ADMIN)
    for index in range(3):
        await record(database, admin, source_id=f"note-lim-{index}")
    async with database.sessions() as session:
        assert (
            await retrieve_memories(session, admin, RetrievalQuery(limit=1))
        ).result_count == 1
        assert (
            await retrieve_memories(session, admin, RetrievalQuery(limit=100))
        ).result_count == 3
    with pytest.raises(ValidationError):
        RetrievalQuery(limit=0)
    with pytest.raises(ValidationError):
        RetrievalQuery(limit=101)


async def test_empty_results(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-11@example.com", RoleName.ADMIN)
    async with database.sessions() as session:
        response = await retrieve_memories(
            session, admin, RetrievalQuery(source_id="note-missing")
        )
    assert response.result_count == 0
    assert response.results == []


async def test_backend_interface_compatibility(database: DatabaseFixture) -> None:
    """A future VectorRetrievalBackend plugs in via the same Protocol."""

    class StubBackend:
        async def fetch(
            self, session: AsyncSession, query: memory_retrieval.RetrievalQuery
        ) -> list[MemoryRecord]:
            assert isinstance(query, memory_retrieval.RetrievalQuery)
            return []

    assert isinstance(StubBackend(), RetrievalBackend)
    admin = await make_user(database, "ret-admin-12@example.com", RoleName.ADMIN)
    await record(database, admin)
    async with database.sessions() as session:
        stubbed = await retrieve_memories(
            session, admin, RetrievalQuery(), backend=StubBackend()
        )
        assert stubbed.result_count == 0
        assert stubbed.results == []
        assert isinstance(
            await retrieve_memories(
                session, admin, RetrievalQuery(), backend=DatabaseRetrievalBackend()
            ),
            memory_retrieval.RetrievalResponse,
        )


async def test_no_orm_or_scores_exposed(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-13@example.com", RoleName.ADMIN)
    await record(database, admin)
    async with database.sessions() as session:
        (match,) = (await retrieve_memories(session, admin, RetrievalQuery())).results
    assert type(match.memory) is MemoryView
    assert "_sa_instance_state" not in match.memory.__dict__
    assert "_sa_instance_state" not in match.__dict__
    dumped = match.model_dump()
    assert "relevance" not in dumped
    assert "score" not in dumped
    assert "similarity" not in dumped
    assert "confidence" not in dumped or isinstance(
        dumped["memory"].get("confidence"), (float, type(None))
    )


async def test_query_text_accepted_but_not_matched(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-14@example.com", RoleName.ADMIN)
    await record(database, admin)
    async with database.sessions() as session:
        response = await retrieve_memories(
            session, admin, RetrievalQuery(text="pressing triggers derby")
        )
    # Accepted for future compatibility; matching stays filter-based.
    assert response.query.text == "pressing triggers derby"
    with pytest.raises(ValidationError):
        RetrievalQuery(text="x" * 501)
    with pytest.raises(ValidationError):
        RetrievalQuery(limit=5, unknown_field=True)  # type: ignore[call-arg]


async def test_invalid_actor_denied(database: DatabaseFixture) -> None:
    admin = await make_user(database, "ret-admin-15@example.com", RoleName.ADMIN)
    await record(database, admin)
    user_id, _ = await create_user(database, "ret-inactive@example.com", RoleName.ADMIN)
    async with database.sessions() as session:
        from app.db.models.user import User

        stored = await session.get(User, user_id)
        assert stored is not None
        stored.is_active = False
        await session.commit()
        idle = await session.get(User, user_id)
        assert idle is not None
        response = await retrieve_memories(session, idle, RetrievalQuery())
    assert response.result_count == 0
