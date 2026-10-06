import asyncio
import math
import uuid
from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.schemas.memory import MemoryIndexDocument

# Point IDs must be deterministic so re-upserts are idempotent.
_POINT_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# Payload schema (metadata only — content stays in PostgreSQL):
#   index_key, memory_id, memory_type, sensitivity, source_type, source_id,
#   occurred_at (ISO), occurred_ts (float, range filtering),
#   evidence_ids, match_ids, video_ids (string lists),
#   embedding_model, embedding_version, source_content_hash.


class VectorStoreError(Exception):
    """Base class for explicit vector-store failures."""


class VectorStoreUnavailable(VectorStoreError):
    """Qdrant unreachable, collection missing, or client failure."""


class VectorDimensionMismatch(VectorStoreError):
    """A vector does not match the store's configured dimension."""


class VectorSearchFilters(BaseModel):
    """Exact-match prefilters; no semantic content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_type: MemoryType | None = None
    sensitivity: MemorySensitivity | None = None
    source_type: MemorySourceType | None = None
    source_id: str | None = Field(default=None, max_length=100)


class VectorHit(BaseModel):
    """One engine hit: identifiers plus engine-reported score.

    ``score`` is Qdrant's raw similarity for the query — informational
    only, never a claim about tactical relevance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    index_key: str = Field(min_length=1, max_length=128)
    memory_id: UUID
    score: float
    payload: dict[str, object] = Field(default_factory=dict)


class VectorStoreHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reachable: bool
    collection_exists: bool
    detail: str = Field(default="", max_length=500)


@runtime_checkable
class VectorStore(Protocol):
    """Replaceable vector-storage contract. Qdrant is one backend;
    tests use an in-memory fake behind this same interface."""

    async def upsert(
        self, document: MemoryIndexDocument, vector: Sequence[float]
    ) -> None: ...

    async def delete(self, memory_id: UUID, index_key: str | None = None) -> bool: ...

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int = 20,
        filters: VectorSearchFilters | None = None,
    ) -> list[VectorHit]: ...

    async def health(self) -> VectorStoreHealth: ...


def point_id_for(index_key: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, index_key))


def payload_for(document: MemoryIndexDocument) -> dict[str, object]:
    return {
        "index_key": document.index_key,
        "memory_id": str(document.memory_id),
        "memory_type": document.memory_type.value,
        "sensitivity": document.sensitivity.value,
        "source_type": document.source_type.value,
        "source_id": document.source_id,
        "occurred_at": document.occurred_at.isoformat(),
        "occurred_ts": document.occurred_at.timestamp(),
        "evidence_ids": [str(value) for value in document.evidence_ids],
        "match_ids": [str(value) for value in document.match_ids],
        "video_ids": [str(value) for value in document.video_ids],
        "embedding_model": document.embedding_model,
        "embedding_version": document.embedding_version,
        "source_content_hash": document.source_content_hash,
    }


def _require_qdrant() -> object:
    try:
        import qdrant_client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VectorStoreUnavailable(
            "qdrant-client is not installed; vector storage is unavailable"
        ) from exc
    return qdrant_client


class QdrantVectorStore:
    """Qdrant adapter. All client calls stay inside this class; only
    VectorStoreError subclasses escape. Never authorizes — callers
    apply governance to resolved PostgreSQL records."""

    def __init__(
        self,
        url: str,
        collection: str,
        vector_size: int,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not url or not collection:
            raise ValueError("Qdrant url and collection are required")
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        qdrant_client = _require_qdrant()
        try:
            self._client = qdrant_client.QdrantClient(
                url=url, api_key=api_key, timeout=timeout_seconds
            )
        except Exception as exc:
            raise VectorStoreUnavailable(f"Qdrant client failed: {exc}") from exc
        self.collection = collection
        self.vector_size = vector_size

    def _checked_vector(self, vector: Sequence[float]) -> list[float]:
        items = list(vector)
        if len(items) != self.vector_size:
            raise VectorDimensionMismatch(
                f"expected {self.vector_size} dimensions, got {len(items)}"
            )
        if any(not isinstance(value, (int, float)) for value in items):
            raise VectorStoreError("Vector holds non-numeric values")
        if any(not math.isfinite(float(value)) for value in items):
            raise VectorStoreError("Vector holds non-finite values")
        return [float(value) for value in items]

    async def _collection_exists(self) -> bool:
        try:
            return bool(
                await asyncio.to_thread(self._client.collection_exists, self.collection)
            )
        except Exception as exc:
            raise VectorStoreUnavailable(
                f"Qdrant reachable check failed: {exc}"
            ) from exc

    async def ensure_collection(self) -> None:
        """Create the collection when absent; validate dimension when present."""
        qdrant_client = _require_qdrant()
        try:
            exists = await asyncio.to_thread(
                self._client.collection_exists, self.collection
            )
            if not exists:
                await asyncio.to_thread(
                    self._client.create_collection,
                    collection_name=self.collection,
                    vectors_config=qdrant_client.models.VectorParams(
                        size=self.vector_size,
                        distance=qdrant_client.models.Distance.COSINE,
                    ),
                )
                return
            info = await asyncio.to_thread(self._client.get_collection, self.collection)
            params = info.config.params.vectors
            existing = params.size if hasattr(params, "size") else None
            if existing is not None and existing != self.vector_size:
                raise VectorDimensionMismatch(
                    f"collection has {existing} dimensions, "
                    f"configured for {self.vector_size}"
                )
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreUnavailable(
                f"Qdrant collection setup failed: {exc}"
            ) from exc

    async def upsert(
        self, document: MemoryIndexDocument, vector: Sequence[float]
    ) -> None:
        qdrant_client = _require_qdrant()
        items = self._checked_vector(vector)
        if not await self._collection_exists():
            raise VectorStoreUnavailable(
                f"Collection '{self.collection}' is missing; "
                "run ensure_collection first"
            )
        try:
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self.collection,
                points=[
                    qdrant_client.models.PointStruct(
                        id=point_id_for(document.index_key),
                        vector=items,
                        payload=payload_for(document),
                    )
                ],
            )
        except Exception as exc:
            raise VectorStoreUnavailable(f"Qdrant upsert failed: {exc}") from exc

    async def delete(self, memory_id: UUID, index_key: str | None = None) -> bool:
        """Delete vectors only — the PostgreSQL MemoryRecord is untouched."""
        qdrant_client = _require_qdrant()
        if not await self._collection_exists():
            raise VectorStoreUnavailable(f"Collection '{self.collection}' is missing")
        try:
            if index_key is not None:
                selector = qdrant_client.models.PointIdsList(
                    points=[point_id_for(index_key)]
                )
            else:
                selector = qdrant_client.models.FilterSelector(
                    filter=qdrant_client.models.Filter(
                        must=[
                            qdrant_client.models.FieldCondition(
                                key="memory_id",
                                match=qdrant_client.models.MatchValue(
                                    value=str(memory_id)
                                ),
                            )
                        ]
                    )
                )
            await asyncio.to_thread(
                self._client.delete,
                collection_name=self.collection,
                points_selector=selector,
            )
            return True
        except Exception as exc:
            raise VectorStoreUnavailable(f"Qdrant delete failed: {exc}") from exc

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int = 20,
        filters: VectorSearchFilters | None = None,
    ) -> list[VectorHit]:
        qdrant_client = _require_qdrant()
        items = self._checked_vector(vector)
        bounded = max(1, min(limit, 100))
        if not await self._collection_exists():
            raise VectorStoreUnavailable(f"Collection '{self.collection}' is missing")
        query_filter = self._build_filter(qdrant_client, filters)
        try:
            response = await asyncio.to_thread(
                self._client.query_points,
                collection_name=self.collection,
                query=items,
                query_filter=query_filter,
                limit=bounded,
                with_payload=True,
            )
        except Exception as exc:
            raise VectorStoreUnavailable(f"Qdrant search failed: {exc}") from exc
        hits: list[VectorHit] = []
        for point in response.points:
            payload = dict(point.payload or {})
            try:
                hits.append(
                    VectorHit(
                        index_key=str(payload["index_key"]),
                        memory_id=UUID(str(payload["memory_id"])),
                        score=float(point.score),
                        payload=payload,
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return hits

    @staticmethod
    def _build_filter(
        qdrant_client: object, filters: VectorSearchFilters | None
    ) -> object | None:
        if filters is None:
            return None
        conditions: list[object] = []
        for key, value in (
            ("memory_type", filters.memory_type),
            ("sensitivity", filters.sensitivity),
            ("source_type", filters.source_type),
            ("source_id", filters.source_id),
        ):
            if value is not None:
                raw = value.value if hasattr(value, "value") else value
                conditions.append(
                    qdrant_client.models.FieldCondition(  # type: ignore[union-attr]
                        key=key,
                        match=qdrant_client.models.MatchValue(value=raw),  # type: ignore[union-attr]
                    )
                )
        if not conditions:
            return None
        return qdrant_client.models.Filter(must=conditions)  # type: ignore[union-attr]

    async def health(self) -> VectorStoreHealth:
        try:
            await asyncio.to_thread(self._client.get_collections)
        except Exception as exc:
            return VectorStoreHealth(
                reachable=False, collection_exists=False, detail=str(exc)[:500]
            )
        try:
            exists = await self._collection_exists()
        except VectorStoreUnavailable as exc:
            return VectorStoreHealth(
                reachable=True, collection_exists=False, detail=str(exc)[:500]
            )
        return VectorStoreHealth(reachable=True, collection_exists=exists, detail="")


__all__ = [
    "QdrantVectorStore",
    "VectorDimensionMismatch",
    "VectorHit",
    "VectorSearchFilters",
    "VectorStore",
    "VectorStoreError",
    "VectorStoreHealth",
    "VectorStoreUnavailable",
    "payload_for",
    "point_id_for",
]
