from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.repositories import memory
from app.schemas.memory import (
    MemoryView,
    RetrievalMatch,
    RetrievalQuery,
    RetrievalResponse,
    VectorRetrievalEvaluation,
)
from app.services.memory_governance import filter_retrievable
from app.services.memory_indexing import EmbeddingProvider
from app.services.memory_vector_store import VectorHit, VectorSearchFilters, VectorStore


@runtime_checkable
class RetrievalBackend(Protocol):
    """Fetch candidate records for a query. A future
    VectorRetrievalBackend implements this same method — callers
    (REST, agents, RAG) keep calling ``retrieve_memories`` unchanged."""

    async def fetch(
        self, session: AsyncSession, query: RetrievalQuery
    ) -> list[MemoryRecord]: ...


class DatabaseRetrievalBackend:
    """Deterministic SQLAlchemy retrieval: explicit filters only,
    repository ordering (occurred_at desc, id). No semantic matching."""

    source_label = "explicit-filters"

    async def fetch(
        self, session: AsyncSession, query: RetrievalQuery
    ) -> list[MemoryRecord]:
        return await memory.list_memories(
            session,
            memory_type=query.memory_type,
            source_type=query.source_type,
            source_id=query.source_id,
            occurred_from=query.occurred_from,
            occurred_to=query.occurred_to,
            has_confidence=query.has_confidence,
            min_confidence=query.min_confidence,
            max_confidence=query.max_confidence,
            limit=query.limit,
            offset=query.offset,
        )


def _match_reason(query: RetrievalQuery) -> str:
    active = [
        name
        for name in (
            "memory_type",
            "source_type",
            "source_id",
            "occurred_from",
            "occurred_to",
            "has_confidence",
            "min_confidence",
            "max_confidence",
        )
        if getattr(query, name) is not None
    ]
    if not active:
        return "unfiltered-bounded-scan"
    return "explicit-filters:" + ",".join(active)


def _build_match(
    record: MemoryRecord,
    reason: str,
    hit: VectorHit | None,
) -> RetrievalMatch:
    version = hit.payload.get("embedding_version") if hit is not None else None
    if hit is None or not isinstance(version, str) or not version:
        return RetrievalMatch(
            memory=MemoryView.model_validate(record),
            match_reason=reason,
            governance_status="allowed",
        )
    return RetrievalMatch(
        memory=MemoryView.model_validate(record),
        match_reason=reason,
        governance_status="allowed",
        similarity_score=hit.score,
        index_key=hit.index_key,
        embedding_version=version,
    )


async def retrieve_memories(
    session: AsyncSession,
    actor: User,
    query: RetrievalQuery,
    backend: RetrievalBackend | None = None,
) -> RetrievalResponse:
    """Single retrieval entry point for REST, agents, and future RAG.

    Backend fetches candidates; governance drops everything the actor
    may not see; only governed DTOs are returned. Read-only: memories
    are never modified, redacted, or created here.
    """
    active_backend = backend if backend is not None else DatabaseRetrievalBackend()
    records = await active_backend.fetch(session, query)
    label = getattr(active_backend, "source_label", "vector-search")
    reason = _match_reason(query) if label == "explicit-filters" else label
    describe = getattr(active_backend, "last_hit_for", None)
    results = [
        _build_match(
            record,
            reason,
            describe(record.id) if callable(describe) else None,
        )
        for record in filter_retrievable(actor, records)
    ]
    return RetrievalResponse(query=query, results=results, result_count=len(results))


async def retrieve_with_evaluation(
    session: AsyncSession,
    actor: User,
    query: RetrievalQuery,
    backend: VectorRetrievalBackend,
) -> tuple[RetrievalResponse, VectorRetrievalEvaluation]:
    """Instrumented vector pass: candidate/resolved/stale/authorized
    counts plus wall-clock latency. No Recall@K/Precision@K — those need
    ground-truth relevance labels, which do not exist."""
    import time

    if not isinstance(backend, VectorRetrievalBackend):
        raise TypeError("backend must be a VectorRetrievalBackend")
    started = time.perf_counter()
    hits = await backend.search_hits(query)
    resolved: list[tuple[VectorHit, MemoryRecord]] = []
    stale = 0
    for hit in hits:
        if not backend.is_fresh(hit):
            stale += 1
            continue
        record = await memory.get_memory(session, hit.memory_id)
        if record is None:
            stale += 1
            continue
        resolved.append((hit, record))
    kept = filter_retrievable(actor, [record for _, record in resolved])
    kept_ids = {record.id for record in kept}
    latency_ms = (time.perf_counter() - started) * 1000.0
    response = RetrievalResponse(
        query=query,
        results=[
            _build_match(record, "vector-search", hit)
            for hit, record in resolved
            if record.id in kept_ids
        ],
        result_count=len(kept),
    )
    evaluation = VectorRetrievalEvaluation(
        candidate_count=len(hits),
        resolved_count=len(resolved),
        stale_count=stale,
        authorized_count=len(kept),
        filtered_count=len(resolved) - len(kept),
        returned_count=len(kept),
        latency_ms=latency_ms,
        embedding_model=backend.provider.model_id,
        embedding_version=backend.provider.embedding_version,
    )
    return response, evaluation


__all__ = [
    "DatabaseRetrievalBackend",
    "RetrievalBackend",
    "VectorRetrievalBackend",
    "retrieve_memories",
    "retrieve_with_evaluation",
]


class VectorRetrievalBackend:
    """Vector search behind the same retrieval contract. Hits resolve to
    authoritative PostgreSQL records; missing sources are skipped, and
    governance (redacted/expired/unauthorized) still applies downstream
    in ``retrieve_memories``. A vector hit is never authorization."""

    source_label = "vector-search"

    def __init__(
        self,
        store: VectorStore,
        provider: EmbeddingProvider,
        expected_embedding: tuple[str, str] | None = None,
    ) -> None:
        if not isinstance(store, VectorStore):
            raise TypeError("store must implement VectorStore")
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("provider must implement EmbeddingProvider")
        self.store = store
        self.provider = provider
        self.expected_embedding = expected_embedding
        self.last_hits: dict[str, VectorHit] = {}

    def last_hit_for(self, memory_id: object) -> VectorHit | None:
        """Most recent hit for a memory id (single-flight per fetch)."""
        return self.last_hits.get(str(memory_id))

    def is_fresh(self, hit: VectorHit) -> bool:
        """Payload model/version must match the expected embedding when
        configured; otherwise any well-formed hit is fresh."""
        if self.expected_embedding is None:
            return True
        model, version = self.expected_embedding
        payload = hit.payload
        return (
            payload.get("embedding_model") == model
            and payload.get("embedding_version") == version
        )

    async def search_hits(self, query: RetrievalQuery) -> list[VectorHit]:
        """Embed + vector search with deterministic tie-breaks (score
        desc, then memory id). No governance here — callers apply it."""
        text = (query.text or "").strip()
        if not text:
            self.last_hits = {}
            return []
        try:
            vector = await self.provider.embed(text)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Embedding provider failed",
            ) from exc
        hits = await self.store.search(
            vector,
            limit=query.limit,
            filters=VectorSearchFilters(
                memory_type=query.memory_type,
                source_type=query.source_type,
                source_id=query.source_id,
            ),
        )
        ordered = sorted(hits, key=lambda hit: (-hit.score, str(hit.memory_id)))
        self.last_hits = {str(hit.memory_id): hit for hit in ordered}
        return ordered

    async def fetch(
        self, session: AsyncSession, query: RetrievalQuery
    ) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for hit in await self.search_hits(query):
            if not self.is_fresh(hit):
                continue
            record = await memory.get_memory(session, hit.memory_id)
            if record is None:
                continue
            records.append(record)
        return records
