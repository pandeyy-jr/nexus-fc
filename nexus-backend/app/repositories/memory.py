from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.memory import DecisionStatus, DecisionType, MemorySourceType, MemoryType
from app.db.models.memory import (
    DecisionRecord,
    DecisionReplay,
    EvidenceReference,
    MemoryRecord,
)

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


async def add_memory(session: AsyncSession, fields: dict) -> MemoryRecord:
    record = MemoryRecord(**fields)
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return record


async def add_evidence(
    session: AsyncSession, memory_id: UUID, fields: dict
) -> EvidenceReference:
    reference = EvidenceReference(memory_record_id=memory_id, **fields)
    session.add(reference)
    await session.flush()
    await session.refresh(reference)
    return reference


async def add_decision(session: AsyncSession, fields: dict) -> DecisionRecord:
    record = DecisionRecord(**fields)
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return record


async def get_memory(session: AsyncSession, memory_id: UUID) -> MemoryRecord | None:
    result = await session.execute(
        select(MemoryRecord)
        .options(selectinload(MemoryRecord.evidence))
        .where(MemoryRecord.id == memory_id)
    )
    return result.scalar_one_or_none()


async def list_memories(
    session: AsyncSession,
    *,
    memory_type: MemoryType | None = None,
    source_type: MemorySourceType | None = None,
    source_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    has_confidence: bool | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> list[MemoryRecord]:
    statement = select(MemoryRecord).options(selectinload(MemoryRecord.evidence))
    if memory_type is not None:
        statement = statement.where(MemoryRecord.memory_type == memory_type)
    if source_type is not None:
        statement = statement.where(MemoryRecord.source_type == source_type)
    if source_id is not None:
        statement = statement.where(MemoryRecord.source_id == source_id)
    if occurred_from is not None:
        statement = statement.where(MemoryRecord.occurred_at >= occurred_from)
    if occurred_to is not None:
        statement = statement.where(MemoryRecord.occurred_at < occurred_to)
    if has_confidence is True:
        statement = statement.where(MemoryRecord.confidence.is_not(None))
    elif has_confidence is False:
        statement = statement.where(MemoryRecord.confidence.is_(None))
    if min_confidence is not None:
        statement = statement.where(MemoryRecord.confidence >= min_confidence)
    if max_confidence is not None:
        statement = statement.where(MemoryRecord.confidence <= max_confidence)
    statement = statement.order_by(MemoryRecord.occurred_at.desc(), MemoryRecord.id)
    bounded = max(1, min(limit, _MAX_LIMIT))
    result = await session.execute(statement.limit(bounded).offset(max(0, offset)))
    return list(result.scalars().all())


async def get_evidence(
    session: AsyncSession, evidence_id: UUID
) -> EvidenceReference | None:
    return await session.get(EvidenceReference, evidence_id)


async def get_decision(
    session: AsyncSession, decision_id: UUID
) -> DecisionRecord | None:
    return await session.get(DecisionRecord, decision_id)


async def list_decisions(
    session: AsyncSession,
    *,
    decision_type: DecisionType | None = None,
    status: DecisionStatus | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> list[DecisionRecord]:
    statement = select(DecisionRecord)
    if decision_type is not None:
        statement = statement.where(DecisionRecord.decision_type == decision_type)
    if status is not None:
        statement = statement.where(DecisionRecord.status == status)
    statement = statement.order_by(DecisionRecord.decision_at.desc(), DecisionRecord.id)
    bounded = max(1, min(limit, _MAX_LIMIT))
    result = await session.execute(statement.limit(bounded).offset(max(0, offset)))
    return list(result.scalars().all())


async def add_decision_replay(session: AsyncSession, fields: dict) -> DecisionReplay:
    record = DecisionReplay(**fields)
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return record


async def get_decision_replay(
    session: AsyncSession, replay_id: UUID
) -> DecisionReplay | None:
    return await session.get(DecisionReplay, replay_id)


async def list_decision_replays(
    session: AsyncSession,
    *,
    decision_type: DecisionType | None = None,
    match_id: UUID | None = None,
    player_id: UUID | None = None,
    decision_from: datetime | None = None,
    decision_to: datetime | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> list[DecisionReplay]:
    statement = select(DecisionReplay)
    if decision_type is not None:
        statement = statement.where(DecisionReplay.decision_type == decision_type)
    if match_id is not None:
        statement = statement.where(DecisionReplay.match_id == match_id)
    if player_id is not None:
        statement = statement.where(DecisionReplay.player_id == player_id)
    if decision_from is not None:
        statement = statement.where(DecisionReplay.decision_at >= decision_from)
    if decision_to is not None:
        statement = statement.where(DecisionReplay.decision_at < decision_to)
    statement = statement.order_by(DecisionReplay.decision_at.desc(), DecisionReplay.id)
    bounded = max(1, min(limit, _MAX_LIMIT))
    result = await session.execute(statement.limit(bounded).offset(max(0, offset)))
    return list(result.scalars().all())
