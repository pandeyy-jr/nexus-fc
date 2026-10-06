"""Phase 08B service tests: atomic writes, filters, invariants.
No REST, no RAG, no vectors — application boundary only."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.memory import (
    DecisionStatus,
    DecisionType,
    MemoryEvidenceType,
    MemorySourceType,
    MemoryType,
)
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.schemas.memory import DecisionCreate, EvidenceCreate, MemoryCreate, MemoryView
from app.services import club_memory
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_club_memory import seed_match, seed_video


def memory_payload(**overrides: object) -> MemoryCreate:
    payload: dict[str, object] = {
        "memory_type": MemoryType.MATCH,
        "title": "Late winner",
        "summary": "A stoppage-time goal settled a tight match.",
        "occurred_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        "source_type": MemorySourceType.HUMAN_RECORDED,
        "source_id": "note-1",
        "confidence": 0.7,
    }
    payload.update(overrides)
    return MemoryCreate(**payload)  # type: ignore[arg-type]


def evidence_payload(**overrides: object) -> EvidenceCreate:
    payload: dict[str, object] = {
        "source_type": MemorySourceType.HUMAN_RECORDED,
        "source_id": "note-1",
        "evidence_type": MemoryEvidenceType.TEXT_EXCERPT,
        "excerpt": "Right flank overload created the chance.",
    }
    payload.update(overrides)
    return EvidenceCreate(**payload)  # type: ignore[arg-type]


async def load_actor(database: DatabaseFixture, user_id: UUID) -> User:
    async with database.sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        session.expunge(user)
        return user


async def memory_count(database: DatabaseFixture) -> int:
    async with database.sessions() as session:
        return int(
            await session.scalar(select(func.count()).select_from(MemoryRecord)) or 0
        )


@pytest.mark.asyncio
async def test_atomic_memory_with_evidence(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            actor,
            memory_payload(),
            [evidence_payload(), evidence_payload(source_id="note-2")],
        )
    assert isinstance(view, MemoryView)
    assert view.created_by == admin_id
    assert len(view.evidence) == 2
    assert all(e.memory_record_id == view.id for e in view.evidence)
    assert "__sa_instance_state__" not in view.model_dump()

    async with database.sessions() as session:
        fetched = await club_memory.get_memory_view(session, view.id)
        assert fetched == view
        with pytest.raises(HTTPException) as missing:
            await club_memory.get_memory_view(session, uuid4())
        assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_rollback_on_failed_evidence(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-2@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    bad = evidence_payload(match_id=uuid4())
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as exc:
            await club_memory.record_memory(session, actor, memory_payload(), [bad])
        assert exc.value.status_code == 404
    assert await memory_count(database) == 0


@pytest.mark.asyncio
async def test_evidence_video_reference_checked(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-3@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as exc:
            await club_memory.record_memory(
                session,
                actor,
                memory_payload(),
                [evidence_payload(video_id=uuid4())],
            )
        assert exc.value.status_code == 404
    assert await memory_count(database) == 0


@pytest.mark.asyncio
async def test_filters_and_deterministic_ordering(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-4@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    stamps = [
        datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    ]
    async with database.sessions() as session:
        await club_memory.record_memory(
            session, actor, memory_payload(occurred_at=stamps[0])
        )
        await club_memory.record_memory(
            session,
            actor,
            memory_payload(
                occurred_at=stamps[1],
                memory_type=MemoryType.TACTICAL,
                source_type=MemorySourceType.TACTICAL_ANALYSIS,
                source_id="fusion-1",
                confidence=None,
            ),
        )
        await club_memory.record_memory(
            session,
            actor,
            memory_payload(
                occurred_at=stamps[2],
                memory_type=MemoryType.TRAINING,
                source_id="session-9",
                confidence=0.4,
            ),
        )
    async with database.sessions() as session:
        ordered = await club_memory.list_memory_views(session)
        assert [m.occurred_at for m in ordered] == sorted(
            [m.occurred_at for m in ordered], reverse=True
        )
        again = await club_memory.list_memory_views(session)
        assert [m.id for m in ordered] == [m.id for m in again]

        by_type = await club_memory.list_memory_views(
            session, memory_type=MemoryType.TACTICAL
        )
        assert len(by_type) == 1
        assert by_type[0].source_type is MemorySourceType.TACTICAL_ANALYSIS

        by_source = await club_memory.list_memory_views(session, source_id="session-9")
        assert len(by_source) == 1

        ranged = await club_memory.list_memory_views(
            session,
            occurred_from=datetime(2026, 9, 2, tzinfo=UTC),
            occurred_to=datetime(2026, 9, 4, tzinfo=UTC),
        )
        assert len(ranged) == 2

        confident = await club_memory.list_memory_views(session, has_confidence=True)
        assert len(confident) == 2
        unconfident = await club_memory.list_memory_views(session, has_confidence=False)
        assert len(unconfident) == 1

        strong = await club_memory.list_memory_views(session, min_confidence=0.5)
        assert len(strong) == 1
        weak = await club_memory.list_memory_views(session, max_confidence=0.5)
        assert len(weak) == 1


@pytest.mark.asyncio
async def test_same_timestamp_order_is_stable(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-5@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    stamp = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    async with database.sessions() as session:
        for index in range(3):
            await club_memory.record_memory(
                session,
                actor,
                memory_payload(occurred_at=stamp, source_id=f"note-{index}"),
            )
    async with database.sessions() as session:
        first = [m.id for m in await club_memory.list_memory_views(session)]
        second = [m.id for m in await club_memory.list_memory_views(session)]
        assert first == second
        assert len(first) == 3


@pytest.mark.asyncio
async def test_provenance_preserved(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-6@example.com", RoleName.ADMIN)
    match_id = await seed_match(database, admin_id)
    video_id = await seed_video(database, match_id, admin_id)
    actor = await load_actor(database, admin_id)
    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            actor,
            memory_payload(
                source_type=MemorySourceType.VISION,
                source_id="track-9",
                confidence=None,
            ),
            [
                evidence_payload(
                    source_type=MemorySourceType.VISION,
                    source_id="track-9",
                    match_id=match_id,
                    video_id=video_id,
                    frame_number=45,
                    timestamp_seconds=1.8,
                    evidence_type=MemoryEvidenceType.FRAME_REFERENCE,
                    provenance="yolo11n/06D deterministic-iou/06E.1",
                )
            ],
        )
    assert view.source_type is MemorySourceType.VISION
    assert view.confidence is None
    (evidence,) = view.evidence
    assert evidence.match_id == match_id
    assert evidence.video_id == video_id
    assert evidence.provenance == "yolo11n/06D deterministic-iou/06E.1"


@pytest.mark.asyncio
async def test_invalid_confidence_rejected() -> None:
    with pytest.raises(ValidationError):
        memory_payload(confidence=1.5)
    with pytest.raises(ValidationError):
        evidence_payload(frame_number=-1)


@pytest.mark.asyncio
async def test_decision_creation_and_separation(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-7@example.com", RoleName.ADMIN)
    coach_id, _ = await create_user(
        database, "svc-coach@example.com", RoleName.HEAD_COACH
    )
    recorder = await load_actor(database, admin_id)
    async with database.sessions() as session:
        memory = await club_memory.record_memory(
            session,
            recorder,
            memory_payload(
                source_type=MemorySourceType.TACTICAL_ANALYSIS, source_id="fusion-2"
            ),
            [evidence_payload(source_type=MemorySourceType.TACTICAL_ANALYSIS)],
        )
        decision = await club_memory.record_decision(
            session,
            recorder,
            DecisionCreate(
                decision_type=DecisionType.TACTICAL,
                summary="Hold a higher line in the second half.",
                rationale="The offside trap worked three times.",
                decision_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
                decision_maker=coach_id,
                status=DecisionStatus.ACCEPTED,
                related_memory_id=memory.id,
                related_evidence_id=memory.evidence[0].id,
            ),
        )
    assert decision.decision_maker == coach_id
    assert decision.created_by == admin_id
    assert decision.related_memory_id == memory.id
    assert memory.source_type is MemorySourceType.TACTICAL_ANALYSIS

    async with database.sessions() as session:
        fetched = await club_memory.get_decision_view(session, decision.id)
        assert fetched == decision
        listed = await club_memory.list_decision_views(
            session, status=DecisionStatus.ACCEPTED
        )
        assert [d.id for d in listed] == [decision.id]
        with pytest.raises(HTTPException):
            await club_memory.get_decision_view(session, uuid4())
    with pytest.raises(ValidationError):
        DecisionCreate(
            decision_type=DecisionType.TACTICAL,
            summary="",
            rationale="Because.",
            decision_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
            related_memory_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_decision_missing_links_rejected(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "svc-admin-8@example.com", RoleName.ADMIN)
    recorder = await load_actor(database, admin_id)
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as exc:
            await club_memory.record_decision(
                session,
                recorder,
                DecisionCreate(
                    decision_type=DecisionType.SELECTION,
                    summary="Start the youth keeper.",
                    rationale="Form in training.",
                    decision_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
                    related_memory_id=uuid4(),
                ),
            )
        assert exc.value.status_code == 404
