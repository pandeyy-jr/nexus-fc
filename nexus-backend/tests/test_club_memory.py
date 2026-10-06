"""Phase 08A Club Memory tests: persistence, provenance, integrity.
No RAG, no vectors, no LLM — domain tables only."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.matches import MatchSide
from app.core.memory import (
    DecisionStatus,
    DecisionType,
    MemoryEvidenceType,
    MemorySourceType,
    MemoryType,
)
from app.core.roles import RoleName
from app.db.models.match import Match
from app.db.models.memory import DecisionRecord, EvidenceReference, MemoryRecord
from app.db.models.opponent import Opponent
from app.db.models.team import Team
from app.db.models.video_source import VideoSourceRecord
from tests.conftest import DatabaseFixture
from tests.factories import create_user


async def seed_match(database: DatabaseFixture, creator_id: UUID) -> UUID:
    async with database.sessions() as session:
        team = Team(
            name="Memory Team",
            short_name="MEM",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Memory Opponent")
        session.add_all([team, opponent])
        await session.flush()
        match = Match(
            team_id=team.id,
            opponent_id=opponent.id,
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            home_away=MatchSide.HOME,
            created_by=creator_id,
        )
        session.add(match)
        await session.commit()
        return match.id


async def seed_video(
    database: DatabaseFixture, match_id: UUID, creator_id: UUID
) -> UUID:
    async with database.sessions() as session:
        source_id = uuid4()
        session.add(
            VideoSourceRecord(
                id=source_id,
                match_id=match_id,
                original_filename="memory.mp4",
                media_type="video/mp4",
                file_size_bytes=10,
                processing_status="READY",
                storage_reference=f"{source_id.hex}.mp4",
                created_by=creator_id,
            )
        )
        await session.commit()
        return source_id


def memory_kwargs(creator_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "memory_type": MemoryType.MATCH,
        "title": "Derby decided late",
        "summary": "Two goals in the final ten minutes turned the derby.",
        "occurred_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        "created_by": creator_id,
        "source_type": MemorySourceType.HUMAN_RECORDED,
        "source_id": "analyst-note-42",
        "confidence": 0.8,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_valid_memory_creation(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        session.add(MemoryRecord(**memory_kwargs(admin_id)))  # type: ignore[arg-type]
        await session.commit()
    async with database.sessions() as session:
        record = await session.scalar(
            select(MemoryRecord).where(MemoryRecord.title == "Derby decided late")
        )
        assert record is not None
        assert record.memory_type is MemoryType.MATCH
        assert record.source_type is MemorySourceType.HUMAN_RECORDED
        assert record.confidence == pytest.approx(0.8)
        assert record.created_by == admin_id
        assert record.created_at is not None


@pytest.mark.asyncio
async def test_missing_confidence_stays_null(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-2@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        session.add(
            MemoryRecord(**memory_kwargs(admin_id, confidence=None))  # type: ignore[arg-type]
        )
        await session.commit()
        record_id = (
            await session.execute(select(MemoryRecord.id).limit(1))
        ).scalar_one()
    async with database.sessions() as session:
        record = await session.get(MemoryRecord, record_id)
        assert record is not None
        assert record.confidence is None


@pytest.mark.asyncio
async def test_confidence_out_of_range_rejected(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-3@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        session.add(
            MemoryRecord(**memory_kwargs(admin_id, confidence=1.5))  # type: ignore[arg-type]
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_evidence_references(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-4@example.com", RoleName.ADMIN
    )
    match_id = await seed_match(database, admin_id)
    source_id = await seed_video(database, match_id, admin_id)
    async with database.sessions() as session:
        memory = MemoryRecord(
            **memory_kwargs(admin_id, source_type=MemorySourceType.VISION)  # type: ignore[arg-type]
        )
        session.add(memory)
        await session.flush()
        session.add(
            EvidenceReference(
                memory_record_id=memory.id,
                source_type=MemorySourceType.VISION,
                source_id="track-player-3",
                match_id=match_id,
                video_id=source_id,
                frame_number=120,
                timestamp_seconds=4.8,
                evidence_type=MemoryEvidenceType.FRAME_REFERENCE,
                excerpt="Player 3 holds width on the right touchline.",
                provenance="nexus-deterministic-iou/06E.1 cal-06F-1",
            )
        )
        await session.commit()
        memory_id = memory.id
    async with database.sessions() as session:
        record = await session.get(MemoryRecord, memory_id)
        assert record is not None
        assert len(record.evidence) == 1
        evidence = record.evidence[0]
        assert evidence.frame_number == 120
        assert evidence.timestamp_seconds == pytest.approx(4.8)
        assert evidence.provenance == "nexus-deterministic-iou/06E.1 cal-06F-1"
        assert evidence.match_id == match_id


@pytest.mark.asyncio
async def test_ai_origin_is_preserved(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-5@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        memory = MemoryRecord(
            **memory_kwargs(  # type: ignore[arg-type]
                admin_id,
                source_type=MemorySourceType.TACTICAL_ANALYSIS,
                source_id="fusion-run-9",
            )
        )
        session.add(memory)
        await session.commit()
        memory_id = memory.id
    async with database.sessions() as session:
        record = await session.get(MemoryRecord, memory_id)
        assert record is not None
        assert record.source_type is MemorySourceType.TACTICAL_ANALYSIS
        assert record.source_type is not MemorySourceType.HUMAN_RECORDED


@pytest.mark.asyncio
async def test_decision_record(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-6@example.com", RoleName.ADMIN
    )
    coach_id, _ = await create_user(
        database, "memory-coach@example.com", RoleName.HEAD_COACH
    )
    async with database.sessions() as session:
        memory = MemoryRecord(**memory_kwargs(admin_id))  # type: ignore[arg-type]
        session.add(memory)
        await session.flush()
        evidence = EvidenceReference(
            memory_record_id=memory.id,
            source_type=MemorySourceType.HUMAN_RECORDED,
            source_id="note-7",
            evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
            excerpt="Opponents overload our left side after 60 minutes.",
        )
        session.add(evidence)
        await session.flush()
        evidence_id = evidence.id
        session.add(
            DecisionRecord(
                decision_type=DecisionType.TACTICAL,
                summary="Shift to a back three for the final quarter.",
                context="Leading 1-0, left side overloaded.",
                rationale="Extra cover on the overloaded side preserves the lead.",
                decision_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
                decision_maker=coach_id,
                status=DecisionStatus.ACCEPTED,
                related_memory_id=memory.id,
                related_evidence_id=evidence_id,
                created_by=admin_id,
            )
        )
        await session.commit()
        decision_id = (
            await session.execute(select(DecisionRecord.id).limit(1))
        ).scalar_one()
    async with database.sessions() as session:
        decision = await session.get(DecisionRecord, decision_id)
        assert decision is not None
        assert decision.decision_maker == coach_id
        assert decision.created_by == admin_id
        assert decision.status is DecisionStatus.ACCEPTED
        assert decision.related_memory_id is not None


@pytest.mark.asyncio
async def test_invalid_references_rejected(database: DatabaseFixture) -> None:
    # NOTE: foreign-key RESTRICT/CASCADE-to-DB behavior is enforced by
    # PostgreSQL in production; SQLite test runs do not enforce FK pragmas.
    # These tests cover the constraints SQLite does enforce.
    admin_id, _ = await create_user(
        database, "memory-admin-7@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        session.add(
            EvidenceReference(
                memory_record_id=None,  # type: ignore[arg-type]
                source_type=MemorySourceType.HUMAN_RECORDED,
                source_id="orphan",
                evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    async with database.sessions() as session:
        memory = MemoryRecord(**memory_kwargs(admin_id))  # type: ignore[arg-type]
        session.add(memory)
        await session.flush()
        session.add(
            EvidenceReference(
                memory_record_id=memory.id,
                source_type=MemorySourceType.HUMAN_RECORDED,
                source_id="bad-frame",
                evidence_type=MemoryEvidenceType.FRAME_REFERENCE,
                frame_number=-1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_delete_memory_cascades_evidence(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(
        database, "memory-admin-8@example.com", RoleName.ADMIN
    )
    async with database.sessions() as session:
        memory = MemoryRecord(**memory_kwargs(admin_id))  # type: ignore[arg-type]
        session.add(memory)
        await session.flush()
        session.add(
            EvidenceReference(
                memory_record_id=memory.id,
                source_type=MemorySourceType.HUMAN_RECORDED,
                source_id="note-8",
                evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
            )
        )
        await session.commit()
        memory_id = memory.id
    async with database.sessions() as session:
        record = await session.get(MemoryRecord, memory_id)
        assert record is not None
        await session.delete(record)
        await session.commit()
    async with database.sessions() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(EvidenceReference)
        )
        assert remaining == 0


@pytest.mark.asyncio
async def test_extra_data_round_trip(database: DatabaseFixture) -> None:
    import json as json_module

    admin_id, _ = await create_user(
        database, "memory-admin-9@example.com", RoleName.ADMIN
    )
    payload = json_module.dumps({"formation": "4-3-3", "venue": "home"})
    async with database.sessions() as session:
        session.add(
            MemoryRecord(**memory_kwargs(admin_id, extra_data=payload))  # type: ignore[arg-type]
        )
        await session.commit()
    async with database.sessions() as session:
        record = await session.scalar(select(MemoryRecord).limit(1))
        assert record is not None
        assert json_module.loads(record.extra_data or "{}") == {
            "formation": "4-3-3",
            "venue": "home",
        }
