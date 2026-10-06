"""Phase 08G vector-store tests. No Qdrant server required: a fake
in-memory store exercises the protocol, governance interaction, and
the retrieval boundary. Real-server coverage lives in
test_memory_vector_store_integration.py (skipped without a server)."""

import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.schemas.memory import MemoryIndexDocument
from app.services.memory_governance import redact_memory
from app.services.memory_retrieval import VectorRetrievalBackend, retrieve_memories
from app.services.memory_vector_store import (
    QdrantVectorStore,
    VectorDimensionMismatch,
    VectorHit,
    VectorSearchFilters,
    VectorStore,
    VectorStoreHealth,
    VectorStoreUnavailable,
    payload_for,
    point_id_for,
)
from tests.conftest import DatabaseFixture
from tests.test_memory_governance import make_user, record


class FakeVectorStore:
    """Deterministic in-memory VectorStore. No ranking: search returns
    insertion-ordered filter matches with score 0.0 (explicitly not a
    relevance signal)."""

    def __init__(self, vector_size: int = 4) -> None:
        self.vector_size = vector_size
        self.points: dict[str, tuple[list[float], dict[str, object]]] = {}
        self.fail: str | None = None

    def _guard(self) -> None:
        if self.fail == "unavailable":
            raise VectorStoreUnavailable("fake store is down")

    async def upsert(self, document, vector) -> None:  # type: ignore[no-untyped-def]
        from app.schemas.memory import MemoryIndexDocument as Doc

        assert isinstance(document, Doc)
        self._guard()
        items = list(vector)
        if len(items) != self.vector_size:
            raise VectorDimensionMismatch("fake dimension mismatch")
        self.points[point_id_for(document.index_key)] = (items, payload_for(document))

    async def delete(self, memory_id: UUID, index_key: str | None = None) -> bool:
        self._guard()
        if index_key is not None:
            self.points.pop(point_id_for(index_key), None)
            return True
        doomed = [
            point_id
            for point_id, (_, stored) in self.points.items()
            if stored.get("memory_id") == str(memory_id)
        ]
        for point_id in doomed:
            del self.points[point_id]
        return True

    async def search(self, vector, *, limit: int = 20, filters=None) -> list[VectorHit]:  # type: ignore[no-untyped-def]
        self._guard()
        items = list(vector)
        if len(items) != self.vector_size:
            raise VectorDimensionMismatch("fake dimension mismatch")
        hits: list[VectorHit] = []
        for _point_id, (_, stored) in self.points.items():
            if filters is not None and not self._matches(stored, filters):
                continue
            hits.append(
                VectorHit(
                    index_key=str(stored["index_key"]),
                    memory_id=UUID(str(stored["memory_id"])),
                    score=0.0,
                    payload=dict(stored),
                )
            )
            if len(hits) >= max(1, limit):
                break
        return hits

    @staticmethod
    def _matches(stored: dict[str, object], filters: VectorSearchFilters) -> bool:
        for key in ("memory_type", "sensitivity", "source_type", "source_id"):
            wanted = getattr(filters, key)
            if wanted is not None:
                raw = wanted.value if hasattr(wanted, "value") else wanted
                if stored.get(key) != raw:
                    return False
        return True

    async def health(self) -> VectorStoreHealth:
        if self.fail == "unavailable":
            return VectorStoreHealth(
                reachable=False, collection_exists=False, detail="fake store is down"
            )
        return VectorStoreHealth(reachable=True, collection_exists=True, detail="")


class StubProvider:
    model_id = "test-only-stub"
    embedding_version = "0-test"
    embedding_dim = 4

    async def embed(self, text: str) -> list[float]:
        assert text.strip()
        return [0.1, 0.2, 0.3, 0.4]


def make_document(**overrides: object) -> MemoryIndexDocument:

    base: dict[str, object] = {
        "index_key": "idx-key-1",
        "memory_id": uuid4(),
        "text": "Pressing triggers in the mid-block.",
        "memory_type": MemoryType.MATCH,
        "sensitivity": MemorySensitivity.CLUB_GENERAL,
        "source_type": MemorySourceType.HUMAN_RECORDED,
        "source_id": "note-1",
        "occurred_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        "embedding_model": "test-only-stub",
        "embedding_version": "0-test",
        "source_content_hash": "abc123",
        "generated_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return MemoryIndexDocument(**base)  # type: ignore[arg-type]


async def test_upsert_and_search() -> None:
    store = FakeVectorStore()
    document = make_document()
    await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
    hits = await store.search([0.1, 0.2, 0.3, 0.4])
    assert len(hits) == 1
    assert hits[0].memory_id == document.memory_id
    assert hits[0].index_key == document.index_key
    assert hits[0].payload["sensitivity"] == "CLUB_GENERAL"
    assert hits[0].payload["embedding_model"] == "test-only-stub"
    assert "summary" not in hits[0].payload
    assert isinstance(store, VectorStore)


async def test_idempotent_upsert() -> None:
    store = FakeVectorStore()
    document = make_document()
    await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
    await store.upsert(document, [0.4, 0.3, 0.2, 0.1])
    assert len(store.points) == 1
    hits = await store.search([0.4, 0.3, 0.2, 0.1])
    assert len(hits) == 1


async def test_delete_keeps_postgres_record(database: DatabaseFixture) -> None:
    admin = await make_user(database, "vec-admin@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    store = FakeVectorStore()
    document = make_document(memory_id=view.id, index_key="idx-del-1")
    await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
    assert await store.delete(view.id, "idx-del-1") is True
    assert await store.search([0.1, 0.2, 0.3, 0.4]) == []
    async with database.sessions() as session:
        assert await session.get(MemoryRecord, view.id) is not None
    await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
    assert await store.delete(view.id) is True
    assert await store.search([0.1, 0.2, 0.3, 0.4]) == []


async def test_dimension_validation() -> None:
    store = FakeVectorStore(vector_size=4)
    with pytest.raises(VectorDimensionMismatch):
        await store.upsert(make_document(), [0.1, 0.2])
    with pytest.raises(VectorDimensionMismatch):
        await store.search([0.1])
    adapter = QdrantVectorStore(
        url="http://localhost:9", collection="test", vector_size=4
    )
    assert isinstance(adapter, VectorStore)
    with pytest.raises(VectorDimensionMismatch):
        await adapter.upsert(make_document(), [0.1])
    with pytest.raises(ValueError):
        QdrantVectorStore(url="http://localhost:9", collection="test", vector_size=0)
    with pytest.raises(ValueError):
        QdrantVectorStore(url="", collection="test", vector_size=4)


async def test_metadata_preservation() -> None:
    document = make_document()
    stored = payload_for(document)
    for key in (
        "memory_id",
        "index_key",
        "memory_type",
        "sensitivity",
        "source_type",
        "source_id",
        "occurred_at",
        "embedding_model",
        "embedding_version",
        "source_content_hash",
    ):
        assert key in stored
    assert point_id_for("idx-key-1") == point_id_for("idx-key-1")
    assert point_id_for("idx-key-1") != point_id_for("idx-key-2")


async def test_store_failure_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeVectorStore()
    store.fail = "unavailable"
    with pytest.raises(VectorStoreUnavailable):
        await store.upsert(make_document(), [0.1, 0.2, 0.3, 0.4])
    with pytest.raises(VectorStoreUnavailable):
        await store.search([0.1, 0.2, 0.3, 0.4])
    with pytest.raises(VectorStoreUnavailable):
        await store.delete(uuid4())
    health = await store.health()
    assert health.reachable is False

    unreachable = QdrantVectorStore(
        url="http://localhost:9", collection="missing", vector_size=4
    )
    health = await unreachable.health()
    assert health.reachable is False
    with pytest.raises(VectorStoreUnavailable):
        await unreachable.upsert(make_document(), [0.1, 0.2, 0.3, 0.4])
    with pytest.raises(VectorStoreUnavailable):
        await unreachable.search([0.1, 0.2, 0.3, 0.4])
    with pytest.raises(VectorStoreUnavailable):
        await unreachable.delete(uuid4())

    monkeypatch.setitem(sys.modules, "qdrant_client", None)
    with pytest.raises(VectorStoreUnavailable):
        QdrantVectorStore(url="http://localhost:9", collection="x", vector_size=4)


async def test_stale_reference_skipped(database: DatabaseFixture) -> None:
    store = FakeVectorStore()
    ghost = make_document(index_key="idx-ghost")
    await store.upsert(ghost, [0.1, 0.2, 0.3, 0.4])
    backend = VectorRetrievalBackend(store, StubProvider())
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery

        assert await backend.fetch(session, RetrievalQuery(text="pressing")) == []


async def test_redacted_expired_unauthorized_filtered(
    database: DatabaseFixture,
) -> None:

    from app.services.memory_retrieval import VectorRetrievalBackend, retrieve_memories

    admin = await make_user(database, "vec-admin-3@example.com", RoleName.ADMIN)
    scout = await make_user(database, "vec-scout@example.com", RoleName.SCOUT)
    from datetime import UTC, datetime

    keeper = await record(database, admin, source_id="note-keep")
    gone = await record(database, admin, source_id="note-gone")
    store = FakeVectorStore()
    for view, key in ((keeper, "idx-keep"), (gone, "idx-gone")):
        await store.upsert(make_document(memory_id=view.id, index_key=key), [0.1] * 4)
    backend = VectorRetrievalBackend(store, StubProvider())
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery

        assert (
            await retrieve_memories(session, scout, RetrievalQuery(text="x"), backend)
        ).result_count == 2
        await redact_memory(session, admin, gone.id)
        from app.db.models.memory import MemoryRecord as Record

        kept = await session.get(Record, keeper.id)
        assert kept is not None
        kept.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        assert (
            await retrieve_memories(session, admin, RetrievalQuery(text="x"), backend)
        ).result_count == 0


async def test_unauthorized_result_filtered(database: DatabaseFixture) -> None:

    admin = await make_user(database, "vec-admin-4@example.com", RoleName.ADMIN)
    scout = await make_user(database, "vec-scout-2@example.com", RoleName.SCOUT)
    view = await record(database, admin, sensitivity=MemorySensitivity.TACTICAL)
    store = FakeVectorStore()
    await store.upsert(make_document(memory_id=view.id, index_key="idx-tac"), [0.1] * 4)
    backend = VectorRetrievalBackend(store, StubProvider())
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery

        denied = await retrieve_memories(
            session, scout, RetrievalQuery(text="x"), backend
        )
        assert denied.result_count == 0
        allowed = await retrieve_memories(
            session, admin, RetrievalQuery(text="x"), backend
        )
        assert allowed.result_count == 1
        assert allowed.results[0].memory.id == view.id
        assert "vector-search" in allowed.results[0].match_reason


async def test_fake_compatible_with_retrieval_service(
    database: DatabaseFixture,
) -> None:

    admin = await make_user(database, "vec-admin-5@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    store = FakeVectorStore()
    await store.upsert(make_document(memory_id=view.id, index_key="idx-ok"), [0.1] * 4)
    backend = VectorRetrievalBackend(store, StubProvider())
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery

        response = await retrieve_memories(
            session, admin, RetrievalQuery(text="pressing"), backend
        )
        assert response.result_count == 1
        memory = response.results[0].memory
        assert memory.id == view.id
        assert "_sa_instance_state" not in memory.__dict__
        blank = await retrieve_memories(session, admin, RetrievalQuery(), backend)
        assert blank.result_count == 0
