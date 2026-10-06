"""Phase 08C governance tests: policy matrix, redaction, eligibility.
No REST, no RAG — policy layer only."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.memory import (
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
    RedactionStatus,
)
from app.core.roles import RoleName
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.schemas.memory import MemoryCreate
from app.services import club_memory, memory_governance
from app.services.memory_governance import (
    RetrievalDecision,
    evaluate_retrieval,
    filter_retrievable,
    is_eligible,
    is_expired,
    require_retrieval,
)
from tests.conftest import DatabaseFixture
from tests.factories import create_user


async def load_actor(database: DatabaseFixture, user_id: UUID) -> User:
    async with database.sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        session.expunge(user)
        return user


async def make_user(database: DatabaseFixture, email: str, role: RoleName) -> User:
    user_id, _ = await create_user(database, email, role)
    return await load_actor(database, user_id)


def payload(**overrides: object) -> MemoryCreate:
    base: dict[str, object] = {
        "memory_type": MemoryType.MATCH,
        "title": "Pressing triggers",
        "summary": "Mid-block triggers on backward passes.",
        "occurred_at": datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        "source_type": MemorySourceType.HUMAN_RECORDED,
        "source_id": "note-gov-1",
    }
    base.update(overrides)
    return MemoryCreate(**base)  # type: ignore[arg-type]


async def record(database: DatabaseFixture, actor: User, **overrides: object):
    async with database.sessions() as session:
        return await club_memory.record_memory(session, actor, payload(**overrides))


@pytest.mark.asyncio
async def test_allowed_combinations(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin@example.com", RoleName.ADMIN)
    analyst = await make_user(database, "gov-analyst@example.com", RoleName.ANALYST)
    medic = await make_user(database, "gov-medic@example.com", RoleName.MEDICAL_STAFF)
    view = await record(database, admin, sensitivity=MemorySensitivity.AVAILABILITY)
    async with database.sessions() as session:
        record_orm = await session.get(MemoryRecord, view.id)
        assert record_orm is not None
        assert evaluate_retrieval(admin, record_orm) == RetrievalDecision(
            True, "allowed"
        )
        assert evaluate_retrieval(analyst, record_orm).allowed is True
        assert evaluate_retrieval(medic, record_orm).allowed is True
        assert record_orm.sensitivity is MemorySensitivity.AVAILABILITY


@pytest.mark.asyncio
async def test_denied_and_restricted(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-2@example.com", RoleName.ADMIN)
    scout = await make_user(database, "gov-scout@example.com", RoleName.SCOUT)
    analyst = await make_user(database, "gov-analyst-2@example.com", RoleName.ANALYST)
    tactical = await record(database, admin, sensitivity=MemorySensitivity.TACTICAL)
    restricted = await record(
        database, admin, sensitivity=MemorySensitivity.RESTRICTED, source_id="note-r"
    )
    async with database.sessions() as session:
        tactical_orm = await session.get(MemoryRecord, tactical.id)
        restricted_orm = await session.get(MemoryRecord, restricted.id)
        assert tactical_orm is not None and restricted_orm is not None
        assert evaluate_retrieval(scout, tactical_orm).allowed is False
        assert evaluate_retrieval(analyst, restricted_orm).allowed is False
        assert evaluate_retrieval(admin, restricted_orm).allowed is True
        with pytest.raises(HTTPException) as exc:
            require_retrieval(scout, tactical_orm)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_player_isolation(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-3@example.com", RoleName.ADMIN)
    player = await make_user(database, "gov-player@example.com", RoleName.PLAYER)
    general = await record(database, admin, sensitivity=MemorySensitivity.CLUB_GENERAL)
    perf = await record(
        database, admin, sensitivity=MemorySensitivity.PERFORMANCE, source_id="note-p"
    )
    async with database.sessions() as session:
        general_orm = await session.get(MemoryRecord, general.id)
        perf_orm = await session.get(MemoryRecord, perf.id)
        assert general_orm is not None and perf_orm is not None
        kept = filter_retrievable(player, [perf_orm, general_orm])
        assert [r.id for r in kept] == [general_orm.id]
        assert evaluate_retrieval(player, perf_orm).allowed is False


@pytest.mark.asyncio
async def test_redaction_flow(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-4@example.com", RoleName.ADMIN)
    coach = await make_user(database, "gov-coach@example.com", RoleName.HEAD_COACH)
    from app.core.memory import MemoryEvidenceType
    from app.schemas.memory import EvidenceCreate

    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            admin,
            payload(sensitivity=MemorySensitivity.DECISION),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.HUMAN_RECORDED,
                    source_id="note-gov-1",
                    evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
                    excerpt="Sensitive lineup detail.",
                )
            ],
        )
    async with database.sessions() as session:
        with pytest.raises(HTTPException) as forbidden:
            await memory_governance.redact_memory(session, coach, view.id)
        assert forbidden.value.status_code == 403
        redacted = await memory_governance.redact_memory(session, admin, view.id)
    assert redacted.redaction_status is RedactionStatus.REDACTED
    assert redacted.summary != "Mid-block triggers on backward passes."
    assert redacted.extra_data is None
    assert redacted.confidence is None
    assert redacted.redacted_by == admin.id
    assert redacted.redacted_at is not None
    # Provenance survives: ids, source, timestamps intact.
    assert redacted.id == view.id
    assert redacted.source_type is MemorySourceType.HUMAN_RECORDED
    assert redacted.source_id == "note-gov-1"
    assert redacted.occurred_at == view.occurred_at
    assert redacted.evidence[0].provenance == view.evidence[0].provenance
    async with database.sessions() as session:
        record_orm = await session.get(MemoryRecord, view.id)
        assert record_orm is not None
        assert evaluate_retrieval(admin, record_orm).allowed is False
        assert filter_retrievable(admin, [record_orm]) == []
        with pytest.raises(HTTPException) as conflict:
            await memory_governance.redact_memory(session, admin, view.id)
        assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_expired_eligibility(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-5@example.com", RoleName.ADMIN)
    future = datetime.now(UTC) + timedelta(days=30)
    view = await record(database, admin, retention_until=future)
    async with database.sessions() as session:
        record_orm = await session.get(MemoryRecord, view.id)
        assert record_orm is not None
        assert is_expired(record_orm) is False
        assert is_eligible(record_orm) is True
        assert is_expired(record_orm, at=future + timedelta(seconds=1)) is True
        assert is_eligible(record_orm, at=future + timedelta(seconds=1)) is False
        assert evaluate_retrieval(admin, record_orm).allowed is True
    # The row itself is never deleted by expiry.
    async with database.sessions() as session:
        assert await session.get(MemoryRecord, view.id) is not None


@pytest.mark.asyncio
async def test_retention_must_be_future() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        payload(retention_until=datetime(2020, 1, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_policy_determinism(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-6@example.com", RoleName.ADMIN)
    player = await make_user(database, "gov-player-2@example.com", RoleName.PLAYER)
    view = await record(database, admin)
    async with database.sessions() as session:
        record_orm = await session.get(MemoryRecord, view.id)
        assert record_orm is not None
        first = [evaluate_retrieval(a, record_orm) for a in (admin, player)]
        second = [evaluate_retrieval(a, record_orm) for a in (admin, player)]
        assert first == second
        assert filter_retrievable(player, [record_orm] * 3) == [record_orm] * 3


@pytest.mark.asyncio
async def test_governed_fetch(database: DatabaseFixture) -> None:
    admin = await make_user(database, "gov-admin-7@example.com", RoleName.ADMIN)
    player = await make_user(database, "gov-player-3@example.com", RoleName.PLAYER)
    view = await record(database, admin, sensitivity=MemorySensitivity.TACTICAL)
    async with database.sessions() as session:
        fetched = await memory_governance.get_governed_memory_view(
            session, admin, view.id
        )
        assert fetched.id == view.id
        with pytest.raises(HTTPException) as denied:
            await memory_governance.get_governed_memory_view(session, player, view.id)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as missing:
            await memory_governance.get_governed_memory_view(
                session, admin, UUID(int=0)
            )
        assert missing.value.status_code == 404
