"""Phase 08F indexing tests. The embedding provider here is a
TEST-ONLY deterministic stub (model_id "test-only-dummy") — its
vectors prove plumbing, never retrieval quality. No cosine
similarity, no vector store, no external calls."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.services import club_memory
from app.services.memory_governance import redact_memory
from app.services.memory_indexing import (
    EmbeddingProvider,
    MemoryIndexingService,
    build_index_text,
    build_removal_request,
)
from tests.conftest import DatabaseFixture
from tests.test_memory_governance import make_user, payload, record


class TestOnlyDeterministicProvider:
    """Test double. Deterministic sha256-derived floats; obviously not a
    production embedding model and never used outside tests."""

    model_id = "test-only-dummy"
    embedding_version = "0-test"
    embedding_dim = 8

    async def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[: self.embedding_dim]]


def service() -> MemoryIndexingService:
    return MemoryIndexingService(TestOnlyDeterministicProvider())


async def test_eligible_memory_index_document(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        result = await service().index_memory(session, admin, view.id)
    document = result.document
    assert document.memory_id == view.id
    assert "Pressing triggers" in document.text
    assert "Mid-block triggers" in document.text
    assert document.memory_type is MemoryType.MATCH
    assert document.sensitivity is MemorySensitivity.CLUB_GENERAL
    assert document.source_type is MemorySourceType.HUMAN_RECORDED
    assert document.source_id == "note-gov-1"
    assert document.embedding_model == "test-only-dummy"
    assert document.embedding_version == "0-test"
    assert len(result.embedding) == 8
    assert result.embedding_dim == 8


async def test_redacted_memory_rejected(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-2@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        await redact_memory(session, admin, view.id)
        with pytest.raises(HTTPException) as exc:
            await service().index_memory(session, admin, view.id)
        assert exc.value.status_code == 403


async def test_expired_memory_rejected(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-3@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        stored = await session.get(MemoryRecord, view.id)
        assert stored is not None
        stored.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(HTTPException) as exc:
            await service().index_memory(session, admin, view.id)
        assert exc.value.status_code == 403


async def test_unauthorized_actor_rejected(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-4@example.com", RoleName.ADMIN)
    scout = await make_user(database, "idx-scout@example.com", RoleName.SCOUT)
    view = await record(database, admin, sensitivity=MemorySensitivity.TACTICAL)
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as exc:
            await service().index_memory(session, scout, view.id)
        assert exc.value.status_code == 403
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as absent:
            await service().index_memory(session, admin, uuid4())
        assert absent.value.status_code == 404


async def test_embedding_provider_failure(database: DatabaseFixture) -> None:
    class ExplodingProvider(TestOnlyDeterministicProvider):
        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("provider down")

    admin = await make_user(database, "idx-admin-5@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as exc:
            await MemoryIndexingService(ExplodingProvider()).index_memory(
                session, admin, view.id
            )
        assert exc.value.status_code == 502


async def test_embedding_dimension_validation(database: DatabaseFixture) -> None:
    class ShortProvider(TestOnlyDeterministicProvider):
        async def embed(self, text: str) -> list[float]:
            return [0.1, 0.2]

    class InfProvider(TestOnlyDeterministicProvider):
        async def embed(self, text: str) -> list[float]:
            return [float("inf")] * self.embedding_dim

    admin = await make_user(database, "idx-admin-6@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as short:
            await MemoryIndexingService(ShortProvider()).index_memory(
                session, admin, view.id
            )
        assert short.value.status_code == 500
        with pytest.raises(HTTPException) as nonfinite:
            await MemoryIndexingService(InfProvider()).index_memory(
                session, admin, view.id
            )
        assert nonfinite.value.status_code == 502


async def test_metadata_version_preservation(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-7@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        first = await service().index_memory(session, admin, view.id)
        second = await service().index_memory(session, admin, view.id)
    assert (
        first.document.embedding_model
        == second.document.embedding_model
        == "test-only-dummy"
    )
    assert (
        first.document.embedding_version
        == second.document.embedding_version
        == "0-test"
    )
    assert first.document.generated_at is not None
    assert first.document.source_content_hash
    assert isinstance(first, type(second))


async def test_deterministic_indexing_identity(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-8@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        first = await service().index_memory(session, admin, view.id)
        second = await service().index_memory(session, admin, view.id)
    assert first.document.index_key == second.document.index_key
    assert first.embedding == second.embedding


async def test_changed_version_produces_different_identity(
    database: DatabaseFixture,
) -> None:
    class V2Provider(TestOnlyDeterministicProvider):
        embedding_version = "1-test"

    admin = await make_user(database, "idx-admin-9@example.com", RoleName.ADMIN)
    view = await record(database, admin)
    async with database.sessions() as session:
        old = await service().index_memory(session, admin, view.id)
        new = await MemoryIndexingService(V2Provider()).index_memory(
            session, admin, view.id
        )
    assert old.document.index_key != new.document.index_key
    assert old.document.embedding_version != new.document.embedding_version


async def test_provenance_preservation(database: DatabaseFixture) -> None:
    from app.core.memory import MemoryEvidenceType
    from app.schemas.memory import EvidenceCreate

    admin = await make_user(database, "idx-admin-10@example.com", RoleName.ADMIN)
    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            admin,
            payload(source_id="note-idx-1"),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.HUMAN_RECORDED,
                    source_id="note-idx-1",
                    evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
                    excerpt="Left-side overload detail.",
                    match_id=None,
                )
            ],
        )
        result = await service().index_memory(session, admin, view.id)
    document = result.document
    assert len(document.evidence_ids) == 1
    assert document.evidence_ids[0] == view.evidence[0].id
    assert "Left-side overload detail." in document.text
    assert document.occurred_at == datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    removal = build_removal_request(document, "redacted")
    assert removal.memory_id == view.id
    assert removal.index_key == document.index_key
    assert removal.reason == "redacted"


async def test_sensitive_fields_excluded(database: DatabaseFixture) -> None:
    admin = await make_user(database, "idx-admin-11@example.com", RoleName.ADMIN)
    view = await record(
        database,
        admin,
        extra_data='{"internal": "do-not-embed"}',
        confidence=0.9,
    )
    async with database.sessions() as session:
        result = await service().index_memory(session, admin, view.id)
    dumped = result.document.model_dump()
    assert "do-not-embed" not in result.document.text
    assert "created_by" not in dumped
    assert "confidence" not in dumped
    assert "extra_data" not in dumped
    assert set(dumped) == {
        "index_key",
        "memory_id",
        "text",
        "memory_type",
        "sensitivity",
        "source_type",
        "source_id",
        "occurred_at",
        "evidence_ids",
        "match_ids",
        "video_ids",
        "embedding_model",
        "embedding_version",
        "source_content_hash",
        "generated_at",
    }


async def test_index_text_builder() -> None:
    assert build_index_text("T", "S", ["a", " ", "b"]) == "T\nS\na\nb"
    assert isinstance(TestOnlyDeterministicProvider(), EmbeddingProvider)


async def test_provider_contract_rejected() -> None:
    with pytest.raises(TypeError):
        MemoryIndexingService(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        MemoryIndexingService(_ZeroDimProvider())


class _ZeroDimProvider(TestOnlyDeterministicProvider):
    embedding_dim = 0  # type: ignore[assignment]

    async def embed(self, text: str) -> list[float]:
        return []
