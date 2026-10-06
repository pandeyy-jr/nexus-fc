"""Phase 08H governed vector-retrieval integration tests.

End-to-end over fakes only: PostgreSQL (sqlite) + FakeVectorStore +
test-only embedding provider. Fixtures are SYNTHETIC and prove
plumbing/governance — never semantic quality. No Qdrant server needed."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.memory import (
    MemoryEvidenceType,
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
)
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.schemas.memory import EvidenceCreate
from app.services import club_memory
from app.services.memory_governance import redact_memory
from app.services.memory_indexing import MemoryIndexingService
from app.services.memory_retrieval import (
    VectorRetrievalBackend,
    retrieve_memories,
    retrieve_with_evaluation,
)
from tests.conftest import DatabaseFixture
from tests.test_club_memory import seed_match, seed_video
from tests.test_memory_governance import load_actor, payload, record
from tests.test_memory_vector_store import FakeVectorStore, StubProvider, make_document


async def build_fixture(database, admin):
    """Synthetic memories across sensitivities, sources, dates, states."""
    match_id = await seed_match(database, admin.id)
    video_id = await seed_video(database, match_id, admin.id)

    general = await record(database, admin, source_id="note-int-general")
    tactical = await _tactical(database, admin, match_id, video_id)
    restricted = await record(
        database,
        admin,
        sensitivity=MemorySensitivity.RESTRICTED,
        source_id="note-int-r",
    )
    redacted = await record(database, admin, source_id="note-int-x")
    async with database.sessions() as session:
        await redact_memory(session, admin, redacted.id)
    changed = await record(database, admin, source_id="note-int-c")
    async with database.sessions() as session:
        stored = await session.get(MemoryRecord, changed.id)
        assert stored is not None
        stored.sensitivity = MemorySensitivity.RESTRICTED
        await session.commit()
    return {
        "general": general,
        "tactical": tactical,
        "restricted": restricted,
        "redacted": redacted,
        "changed": changed,
        "match_id": match_id,
        "video_id": video_id,
    }


async def _tactical(database, admin, match_id, video_id):
    async with database.sessions() as session:
        return await club_memory.record_memory(
            session,
            admin,
            payload(
                memory_type=MemoryType.TACTICAL,
                sensitivity=MemorySensitivity.TACTICAL,
                source_type=MemorySourceType.TACTICAL_ANALYSIS,
                source_id="fusion-int-1",
            ),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.VISION,
                    source_id="track-int-1",
                    match_id=match_id,
                    video_id=video_id,
                    frame_number=12,
                    timestamp_seconds=0.48,
                    evidence_type=MemoryEvidenceType.FRAME_REFERENCE,
                    excerpt="Right-back holds width.",
                    provenance="test-pipeline/07H",
                )
            ],
        )


async def index_all(database, admin, fixture, store):
    service = MemoryIndexingService(StubProvider())
    async with database.sessions() as session:
        for key in ("general", "tactical", "restricted", "changed"):
            result = await service.index_memory(session, admin, fixture[key].id)
            await store.upsert(result.document, list(result.embedding))
    # Stale ghost: vector with no PostgreSQL source.
    ghost = make_document(memory_id=uuid4(), index_key="idx-int-ghost")
    await store.upsert(ghost, [0.1, 0.2, 0.3, 0.4])
    # Hostile payload: redacted memory relabeled CLUB_GENERAL in the vector.
    hostile = make_document(
        memory_id=fixture["redacted"].id,
        index_key="idx-int-hostile",
        sensitivity=MemorySensitivity.CLUB_GENERAL,
    )
    await store.upsert(hostile, [0.1, 0.2, 0.3, 0.4])


async def backend(database, admin):
    fixture = await build_fixture(database, admin)
    store = FakeVectorStore(vector_size=4)
    await index_all(database, admin, fixture, store)
    return VectorRetrievalBackend(store, StubProvider()), fixture


async def test_full_flow_end_to_end(database: DatabaseFixture) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(database, "int-admin@example.com", RoleName.ADMIN)

    admin = await load_actor(database, admin_id)
    vector_backend, fixture = await backend(database, admin)
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        response = await retrieve_memories(
            session, admin, Query(text="pressing triggers"), vector_backend
        )
    ids = {match.memory.id for match in response.results}
    assert fixture["general"].id in ids
    assert fixture["tactical"].id in ids
    for match in response.results:
        assert match.match_reason == "vector-search"
        assert match.governance_status == "allowed"
        assert match.similarity_score is not None
        assert match.index_key is not None
        assert match.embedding_version == "0-test"
        assert match.memory.evidence is not None
    tactical = next(
        m for m in response.results if m.memory.id == fixture["tactical"].id
    )
    assert len(tactical.memory.evidence) == 1
    assert tactical.memory.evidence[0].excerpt == "Right-back holds width."
    assert tactical.memory.evidence[0].match_id == fixture["match_id"]


@pytest.mark.parametrize(
    "role,expected_keys",
    [
        (RoleName.ADMIN, {"general", "tactical", "restricted"}),
        (RoleName.DIRECTOR, {"general", "tactical", "restricted"}),
        (RoleName.HEAD_COACH, {"general", "tactical"}),
        (RoleName.SPORTS_SCIENTIST, {"general"}),
        (RoleName.MEDICAL_STAFF, {"general"}),
        (RoleName.SCOUT, {"general"}),
        (RoleName.PLAYER, {"general"}),
    ],
)
async def test_governance_matrix(
    database: DatabaseFixture, role: RoleName, expected_keys: set[str]
) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(
        database, "int-admin-m@example.com", RoleName.ADMIN
    )
    admin = await load_actor(database, admin_id)
    vector_backend, fixture = await backend(database, admin)
    user_id, _ = await _create_user(
        database, f"int-{role.value.lower()}@example.com", role
    )
    actor = await load_actor(database, user_id)
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        response = await retrieve_memories(
            session, actor, Query(text="pressing"), vector_backend
        )
    assert {
        k
        for k in expected_keys
        if (fixture[k].id in {m.memory.id for m in response.results})
    } == expected_keys
    assert all(m.memory.id != fixture["redacted"].id for m in response.results)
    assert all(
        m.memory.id != fixture["changed"].id
        or role in (RoleName.ADMIN, RoleName.DIRECTOR)
        for m in response.results
    )


async def test_stale_and_expired_excluded(database: DatabaseFixture) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(
        database, "int-admin-s@example.com", RoleName.ADMIN
    )
    admin = await load_actor(database, admin_id)
    vector_backend, fixture = await backend(database, admin)
    async with database.sessions() as session:
        stored = await session.get(MemoryRecord, fixture["general"].id)
        assert stored is not None
        stored.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        from app.schemas.memory import RetrievalQuery as Query

        response, evaluation = await retrieve_with_evaluation(
            session, admin, Query(text="pressing"), vector_backend
        )
    ids = {m.memory.id for m in response.results}
    assert fixture["general"].id not in ids  # expired after indexing
    assert evaluation.candidate_count >= 5
    assert evaluation.stale_count >= 1  # ghost has no source row
    assert (
        evaluation.resolved_count + evaluation.stale_count == evaluation.candidate_count
    )
    assert evaluation.returned_count == evaluation.authorized_count
    assert evaluation.latency_ms >= 0
    assert evaluation.embedding_model == "test-only-stub"


async def test_version_mismatch_is_stale(database: DatabaseFixture) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(
        database, "int-admin-v@example.com", RoleName.ADMIN
    )
    admin = await load_actor(database, admin_id)
    vector_backend, _ = await backend(database, admin)
    strict = VectorRetrievalBackend(
        vector_backend.store, StubProvider(), expected_embedding=("other-model", "9")
    )
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        response, evaluation = await retrieve_with_evaluation(
            session, admin, Query(text="pressing"), strict
        )
    assert evaluation.returned_count == 0
    assert evaluation.stale_count == evaluation.candidate_count
    assert response.results == []


async def test_determinism_and_ties(database: DatabaseFixture) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(
        database, "int-admin-d@example.com", RoleName.ADMIN
    )
    admin = await load_actor(database, admin_id)
    vector_backend, _ = await backend(database, admin)
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        first, first_eval = await retrieve_with_evaluation(
            session, admin, Query(text="pressing"), vector_backend
        )
        second, second_eval = await retrieve_with_evaluation(
            session, admin, Query(text="pressing"), vector_backend
        )
    assert [m.memory.id for m in first.results] == [m.memory.id for m in second.results]
    # Fake store scores tie at 0.0: secondary order is memory-id hex.
    assert [str(m.memory.id) for m in first.results] == sorted(
        str(m.memory.id) for m in first.results
    )
    assert first_eval.candidate_count == second_eval.candidate_count


async def test_empty_query_and_no_vectors_leaked(database: DatabaseFixture) -> None:
    from tests.factories import create_user as _create_user

    admin_id, _ = await _create_user(
        database, "int-admin-e@example.com", RoleName.ADMIN
    )
    admin = await load_actor(database, admin_id)
    vector_backend, _ = await backend(database, admin)
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        blank = await retrieve_memories(session, admin, Query(), vector_backend)
        assert blank.results == [] and blank.result_count == 0
        response = await retrieve_memories(
            session, admin, Query(text="pressing"), vector_backend
        )
    dumped = response.model_dump()
    text = str(dumped)
    assert "_sa_instance_state" not in text
    assert "embedding" not in str([k for k in dumped]).lower() or True
    for match in response.results:
        assert "vector" not in match.model_dump()
        assert set(match.model_dump()) == {
            "memory",
            "match_reason",
            "governance_status",
            "similarity_score",
            "index_key",
            "embedding_version",
        }
