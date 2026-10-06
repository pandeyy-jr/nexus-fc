from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.repositories import memory
from app.schemas.memory import (
    IndexingResult,
    MemoryIndexDocument,
    VectorRemovalRequest,
)

# ---------------------------------------------------------------------------
# Indexing eligibility vs retrieval authorization.
#
# These are different concepts by design. A future system MAY build one
# club-wide vector index (indexing eligibility: not redacted, not
# expired). But retrieval MUST ALWAYS re-apply actor-specific governance
# (filter_retrievable / require_retrieval) before content reaches any
# caller. A vector hit is never, by itself, authorization to disclose.
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal embedding contract. Future OpenAI/Gemini/local providers
    implement ``embed``; nothing here knows about vector stores."""

    @property
    def model_id(self) -> str: ...

    @property
    def embedding_version(self) -> str: ...

    @property
    def embedding_dim(self) -> int: ...

    async def embed(self, text: str) -> list[float]: ...


def _content_hash(memory_id: UUID, text: str) -> str:
    return hashlib.sha256(f"{memory_id}|{text}".encode()).hexdigest()


def _index_key(memory_id: UUID, model_id: str, version: str, content_hash: str) -> str:
    return hashlib.sha256(
        "|".join((str(memory_id), model_id, version, content_hash)).encode("utf-8")
    ).hexdigest()


def build_index_text(title: str, summary: str, excerpts: list[str]) -> str:
    """Assemble the embeddable text. Title + summary + evidence excerpts
    only — see MemoryIndexDocument for the exclusion list."""
    parts = [title.strip(), summary.strip()]
    parts.extend(excerpt.strip() for excerpt in excerpts if excerpt.strip())
    return "\n".join(part for part in parts if part)


def build_removal_request(
    document: MemoryIndexDocument, reason: str, at: datetime | None = None
) -> VectorRemovalRequest:
    """Describe a stale vector for future Qdrant cleanup (redacted,
    expired, or source-deleted memories). No store interaction here."""
    moment = at or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return VectorRemovalRequest(
        index_key=document.index_key,
        memory_id=document.memory_id,
        reason=reason,
        requested_at=moment,
    )


class MemoryIndexingService:
    """Governed indexing: PostgreSQL stays authoritative; vectors are
    derived data. The actor passed here must satisfy the SAME governance
    boundary as retrieval — there is no 'AI indexing' bypass."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        if not isinstance(provider, EmbeddingProvider):
            raise TypeError("provider must implement EmbeddingProvider")
        if provider.embedding_dim < 1:
            raise ValueError("provider embedding_dim must be positive")
        self.provider = provider

    async def index_memory(
        self, session: AsyncSession, actor: User, memory_id: UUID
    ) -> IndexingResult:
        from app.services.memory_governance import require_retrieval

        record = await memory.get_memory(session, memory_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
            )
        require_retrieval(actor, record)
        document = self.build_document(record)
        try:
            vector = await self.provider.embed(document.text)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Embedding provider failed",
            ) from exc
        items = tuple(vector)
        if len(items) != self.provider.embedding_dim:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Embedding dimension mismatch",
            )
        if any(not isinstance(value, (int, float)) for value in items):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Embedding provider returned non-numeric values",
            )
        finite = tuple(float(value) for value in items)
        if any(not math.isfinite(value) for value in finite):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Embedding provider returned non-finite values",
            )
        return IndexingResult(
            document=document,
            embedding=finite,
            embedding_dim=self.provider.embedding_dim,
        )

    def build_document(self, record: MemoryRecord) -> MemoryIndexDocument:
        """Pure document construction (no provider call). Rejects redacted
        or expired records even before governance is consulted."""
        from app.services.memory_governance import is_eligible

        if not is_eligible(record):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Memory is not eligible for indexing",
            )
        excerpts = [
            reference.excerpt for reference in record.evidence if reference.excerpt
        ]
        text = build_index_text(record.title, record.summary, excerpts)
        if not text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Memory has no embeddable text",
            )
        content_hash = _content_hash(record.id, text)
        occurred = record.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        return MemoryIndexDocument(
            index_key=_index_key(
                record.id,
                self.provider.model_id,
                self.provider.embedding_version,
                content_hash,
            ),
            memory_id=record.id,
            text=text,
            memory_type=record.memory_type,
            sensitivity=record.sensitivity,
            source_type=record.source_type,
            source_id=record.source_id,
            occurred_at=occurred,
            evidence_ids=tuple(reference.id for reference in record.evidence),
            match_ids=tuple(
                reference.match_id
                for reference in record.evidence
                if reference.match_id is not None
            ),
            video_ids=tuple(
                reference.video_id
                for reference in record.evidence
                if reference.video_id is not None
            ),
            embedding_model=self.provider.model_id,
            embedding_version=self.provider.embedding_version,
            source_content_hash=content_hash,
            generated_at=datetime.now(UTC),
        )


__all__ = [
    "EmbeddingProvider",
    "MemoryIndexingService",
    "build_index_text",
    "build_removal_request",
]
