from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory import (
    DecisionStatus,
    DecisionType,
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
    RedactionStatus,
)
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.repositories import memory
from app.schemas.memory import DecisionView, MemoryView

REDACTED_TITLE = "[Redacted]"
REDACTED_SUMMARY = "[Content redacted under governance policy]"
REDACTED_EXCERPT = "[Redacted]"

_ALL = frozenset(MemorySensitivity)
_COACHING = frozenset(
    {
        MemorySensitivity.CLUB_GENERAL,
        MemorySensitivity.PERFORMANCE,
        MemorySensitivity.PLAYER_DEVELOPMENT,
        MemorySensitivity.AVAILABILITY,
        MemorySensitivity.TACTICAL,
        MemorySensitivity.DECISION,
    }
)

# Central policy mapping: server-side RoleName -> allowed sensitivities.
# PLAYER sees CLUB_GENERAL only and is never a wildcard. RESTRICTED is
# ADMIN/DIRECTOR only. Conservative defaults; changes require review.
ROLE_ACCESS: dict[RoleName, frozenset[MemorySensitivity]] = {
    RoleName.ADMIN: _ALL,
    RoleName.DIRECTOR: _ALL,
    RoleName.HEAD_COACH: _COACHING,
    RoleName.ASSISTANT_COACH: _COACHING,
    RoleName.ANALYST: _COACHING,
    RoleName.SPORTS_SCIENTIST: frozenset(
        {
            MemorySensitivity.CLUB_GENERAL,
            MemorySensitivity.PERFORMANCE,
            MemorySensitivity.PLAYER_DEVELOPMENT,
            MemorySensitivity.AVAILABILITY,
        }
    ),
    RoleName.MEDICAL_STAFF: frozenset(
        {MemorySensitivity.CLUB_GENERAL, MemorySensitivity.AVAILABILITY}
    ),
    RoleName.SCOUT: frozenset(
        {MemorySensitivity.CLUB_GENERAL, MemorySensitivity.SCOUTING}
    ),
    RoleName.PLAYER: frozenset({MemorySensitivity.CLUB_GENERAL}),
}

# Redaction is a governance action, not a coaching one.
REDACT_ROLES = frozenset({RoleName.ADMIN, RoleName.DIRECTOR})


@dataclass(frozen=True)
class RetrievalDecision:
    allowed: bool
    reason: str


def _actor_role(actor: User) -> RoleName | None:
    role = getattr(actor, "role", None)
    name = getattr(role, "name", None)
    if not getattr(actor, "is_active", False) or name is None:
        return None
    try:
        return RoleName(name)
    except ValueError:
        return None


def evaluate_retrieval(actor: User, record: MemoryRecord) -> RetrievalDecision:
    """Pure deterministic policy check. Reads the server-side role only —
    client-supplied role strings are never consulted."""
    role = _actor_role(actor)
    if role is None:
        return RetrievalDecision(False, "inactive-or-unknown-actor")
    if record.redaction_status is RedactionStatus.REDACTED:
        return RetrievalDecision(False, "redacted")
    if is_expired(record):
        return RetrievalDecision(False, "retention-expired")
    if record.sensitivity not in ROLE_ACCESS.get(role, frozenset()):
        return RetrievalDecision(False, "insufficient-permissions")
    return RetrievalDecision(True, "allowed")


def can_retrieve(actor: User, record: MemoryRecord) -> bool:
    return evaluate_retrieval(actor, record).allowed


def require_retrieval(actor: User, record: MemoryRecord) -> None:
    """Enforcement entry point for REST, retrieval, RAG, and agents.

    RAG pipelines MUST call this (or filter_retrievable) before memory
    content enters model context — internal callers get no bypass.
    """
    decision = evaluate_retrieval(actor, record)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Memory is not available for retrieval: {decision.reason}",
        )


def filter_retrievable(actor: User, records: list[MemoryRecord]) -> list[MemoryRecord]:
    """Drop denied/expired/redacted records; preserves input order."""
    return [record for record in records if can_retrieve(actor, record)]


def is_expired(record: MemoryRecord, at: datetime | None = None) -> bool:
    if record.retention_until is None:
        return False
    moment = at or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment >= record.retention_until


def is_eligible(record: MemoryRecord, at: datetime | None = None) -> bool:
    """Retrieval eligibility ignoring role: ACTIVE and unexpired."""
    return record.redaction_status is RedactionStatus.ACTIVE and not is_expired(
        record, at
    )


def can_redact(actor: User) -> bool:
    role = _actor_role(actor)
    return role is not None and role in REDACT_ROLES


async def redact_memory(
    session: AsyncSession, actor: User, memory_id: UUID
) -> MemoryView:
    """Governance redaction: replaces content with markers, preserves the
    record, provenance, timestamps, and audit metadata. The row is never
    deleted; already-redacted memories conflict rather than re-run."""
    if not can_redact(actor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memory redaction requires ADMIN or DIRECTOR",
        )
    record = await memory.get_memory(session, memory_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )
    if record.redaction_status is RedactionStatus.REDACTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Memory is already redacted",
        )
    try:
        record.title = REDACTED_TITLE
        record.summary = REDACTED_SUMMARY
        record.extra_data = None
        record.confidence = None
        record.redaction_status = RedactionStatus.REDACTED
        record.redacted_at = datetime.now(UTC)
        record.redacted_by = actor.id
        references = list(record.evidence)
        for reference in references:
            reference.excerpt = (
                REDACTED_EXCERPT if reference.excerpt is not None else None
            )
        await session.flush()
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Memory could not be redacted",
        ) from exc
    await session.refresh(record)
    return MemoryView.model_validate(record)


async def get_governed_memory_view(
    session: AsyncSession, actor: User, memory_id: UUID
) -> MemoryView:
    """Fetch + enforce in one call for future REST/RAG layers."""
    record = await memory.get_memory(session, memory_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found"
        )
    require_retrieval(actor, record)
    return MemoryView.model_validate(record)


async def list_governed_memory_views(
    session: AsyncSession,
    actor: User,
    *,
    memory_type: MemoryType | None = None,
    source_type: MemorySourceType | None = None,
    source_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    has_confidence: bool | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryView]:
    """List through the single choke point: repository filters first,
    governance drops denied rows, DTOs map last. No alternate path."""
    records = await memory.list_memories(
        session,
        memory_type=memory_type,
        source_type=source_type,
        source_id=source_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        has_confidence=has_confidence,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        limit=limit,
        offset=offset,
    )
    return [
        MemoryView.model_validate(record)
        for record in filter_retrievable(actor, records)
    ]


async def get_governed_decision_view(
    session: AsyncSession, actor: User, decision_id: UUID
) -> DecisionView:
    """Decisions inherit the strictest linked-memory rule: when a decision
    references a memory the actor may not retrieve, the decision is
    withheld too. Unlinked decisions are visible to any active actor."""
    record = await memory.get_decision(session, decision_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found"
        )
    if record.related_memory_id is not None:
        linked = await memory.get_memory(session, record.related_memory_id)
        if linked is None or not can_retrieve(actor, linked):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Decision is not available for retrieval",
            )
    return DecisionView.model_validate(record)


async def list_governed_decision_views(
    session: AsyncSession,
    actor: User,
    *,
    decision_type: DecisionType | None = None,
    status: DecisionStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DecisionView]:
    records = await memory.list_decisions(
        session, decision_type=decision_type, status=status, limit=limit, offset=offset
    )
    visible: list[DecisionView] = []
    for record in records:
        if record.related_memory_id is not None:
            linked = await memory.get_memory(session, record.related_memory_id)
            if linked is None or not can_retrieve(actor, linked):
                continue
        visible.append(DecisionView.model_validate(record))
    return visible


__all__ = [
    "REDACT_ROLES",
    "ROLE_ACCESS",
    "RetrievalDecision",
    "can_redact",
    "can_retrieve",
    "evaluate_retrieval",
    "filter_retrievable",
    "get_governed_decision_view",
    "get_governed_memory_view",
    "is_eligible",
    "is_expired",
    "list_governed_decision_views",
    "list_governed_memory_views",
    "redact_memory",
    "require_retrieval",
]
