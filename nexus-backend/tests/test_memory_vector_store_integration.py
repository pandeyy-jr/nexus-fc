"""Qdrant integration tests — SKIPPED unless QDRANT_INTEGRATION_URL is set.

Requires a running Qdrant server plus qdrant-client installed. Never runs
in the normal suite; run explicitly, e.g.::

    QDRANT_INTEGRATION_URL=http://localhost:6333 pytest \\
        tests/test_memory_vector_store_integration.py -q
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.schemas.memory import MemoryIndexDocument
from app.services.memory_vector_store import (
    QdrantVectorStore,
    VectorDimensionMismatch,
    VectorSearchFilters,
    VectorStoreHealth,
)

COLLECTION = os.environ.get("QDRANT_INTEGRATION_COLLECTION", "nexus_memory_test")
pytestmark = pytest.mark.skipif(
    not os.environ.get("QDRANT_INTEGRATION_URL"),
    reason="QDRANT_INTEGRATION_URL is not set",
)


def make_store(vector_size: int = 4) -> QdrantVectorStore:
    return QdrantVectorStore(
        url=os.environ["QDRANT_INTEGRATION_URL"],
        collection=COLLECTION,
        vector_size=vector_size,
    )


def make_document(index_key: str) -> MemoryIndexDocument:
    return MemoryIndexDocument(
        index_key=index_key,
        memory_id=uuid4(),
        text="Pressing triggers in the mid-block.",
        memory_type=MemoryType.MATCH,
        sensitivity=MemorySensitivity.CLUB_GENERAL,
        source_type=MemorySourceType.HUMAN_RECORDED,
        source_id="note-int-1",
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        embedding_model="integration-probe",
        embedding_version="0-test",
        source_content_hash="int-hash",
        generated_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


async def test_health_reachable() -> None:
    health = await make_store().health()
    assert isinstance(health, VectorStoreHealth)
    assert health.reachable is True
    assert health.collection_exists in (True, False)


async def test_upsert_search_delete_roundtrip() -> None:
    store = make_store()
    await store.ensure_collection()
    document = make_document("idx-int-roundtrip")
    try:
        await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
        await store.upsert(document, [0.1, 0.2, 0.3, 0.4])
        hits = await store.search(
            [0.1, 0.2, 0.3, 0.4],
            limit=10,
            filters=VectorSearchFilters(memory_type=MemoryType.MATCH),
        )
        assert any(hit.index_key == document.index_key for hit in hits)
        assert any(hit.memory_id == document.memory_id for hit in hits)
        assert await store.delete(document.memory_id, document.index_key) is True
        remaining = await store.search([0.1, 0.2, 0.3, 0.4], limit=10)
        assert all(hit.index_key != document.index_key for hit in remaining)
    finally:
        await store.delete(document.memory_id, document.index_key)


async def test_collection_dimension_guard() -> None:
    store = make_store()
    await store.ensure_collection()
    other = make_store(vector_size=8)
    with pytest.raises(VectorDimensionMismatch):
        await other.ensure_collection()
