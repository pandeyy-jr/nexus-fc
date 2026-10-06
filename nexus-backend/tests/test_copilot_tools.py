"""Phase 09A copilot tool tests: registry, execution boundary, RBAC,
read-only enforcement. No LLM involved — the boundary is tested directly."""

import json
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.ai.copilot.registry import (
    ToolDefinition,
    ToolErrorCategory,
    ToolExecutionContext,
    build_default_registry,
)
from app.ai.copilot.tools import PlayerRefInput
from app.core.football import PlayerPosition
from app.core.matches import MatchSide, MatchSquadStatus
from app.core.memory import MemorySensitivity, MemorySourceType, MemoryType
from app.core.roles import RoleName
from app.core.training import (
    AttendanceStatus,
    AvailabilityReasonCategory,
    AvailabilityStatus,
    TrainingSessionType,
)
from app.db.models.availability import PlayerAvailability
from app.db.models.match import Match, MatchSquad
from app.db.models.memory import EvidenceReference, MemoryRecord
from app.db.models.opponent import Opponent
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.models.training import TrainingParticipation, TrainingSession
from app.db.models.user import User
from app.schemas.memory import MemoryCreate
from app.services import club_memory
from tests.conftest import DatabaseFixture
from tests.factories import create_user


async def load_actor(database: DatabaseFixture, user_id: UUID) -> User:
    async with database.sessions() as session:
        user = await session.scalar(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )
        assert user is not None
        session.expunge(user)
        return user


async def seed_domain(database: DatabaseFixture, admin_id: UUID) -> dict[str, UUID]:
    """Team, two players (A linked later), match+squad, training,
    availability, one club memory. Returns ids."""
    async with database.sessions() as session:
        team = Team(
            name="Copilot Team",
            short_name="COP",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Copilot Opponent")
        session.add_all([team, opponent])
        await session.flush()
        player_a = Player(
            first_name="Ada",
            last_name="A",
            date_of_birth=date(2000, 1, 1),
            preferred_position=PlayerPosition.CM,
        )
        player_b = Player(
            first_name="Bo",
            last_name="B",
            date_of_birth=date(2001, 2, 2),
            preferred_position=PlayerPosition.ST,
        )
        session.add_all([player_a, player_b])
        await session.flush()
        match = Match(
            team_id=team.id,
            opponent_id=opponent.id,
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            home_away=MatchSide.HOME,
            created_by=admin_id,
        )
        session.add(match)
        await session.flush()
        session.add(
            MatchSquad(
                match_id=match.id,
                player_id=player_a.id,
                squad_status=MatchSquadStatus.SELECTED,
                starting=False,
                captain=False,
            )
        )
        training_session = TrainingSession(
            team_id=team.id,
            session_date=date(2026, 9, 20),
            start_time=time(10, 0),
            end_time=time(11, 30),
            session_type=TrainingSessionType.TECHNICAL,
            created_by=admin_id,
        )
        session.add(training_session)
        await session.flush()
        session.add(
            TrainingParticipation(
                training_session_id=training_session.id,
                player_id=player_a.id,
                attendance_status=AttendanceStatus.ATTENDED,
                recorded_at=datetime.now(UTC),
            )
        )
        session.add(
            PlayerAvailability(
                player_id=player_a.id,
                status=AvailabilityStatus.AVAILABLE,
                effective_from=datetime.now(UTC) - timedelta(days=1),
                reason_category=AvailabilityReasonCategory.COACHING,
                recorded_by=admin_id,
            )
        )
        await session.commit()
        return {
            "team_id": team.id,
            "player_a": player_a.id,
            "player_b": player_b.id,
            "match_id": match.id,
        }


async def link_player_user(
    database: DatabaseFixture, player_id: UUID, user_id: UUID
) -> None:
    async with database.sessions() as session:
        player = await session.get(Player, player_id)
        assert player is not None
        player.user_id = user_id
        await session.commit()


async def seed_memory(database: DatabaseFixture, actor: User) -> UUID:
    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            actor,
            MemoryCreate(
                memory_type=MemoryType.MATCH,
                title="Derby decided late",
                summary="Two goals in the final ten minutes.",
                occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
                source_type=MemorySourceType.HUMAN_RECORDED,
                source_id="note-copilot-1",
            ),
        )
        return view.id


async def make_context(
    database: DatabaseFixture, actor: User
) -> tuple[ToolExecutionContext, object]:
    session_cm = database.sessions()
    session = await session_cm.__aenter__()

    async def _close() -> None:
        await session_cm.__aexit__(None, None, None)

    return ToolExecutionContext(actor=actor, session=session), _close


@pytest.mark.asyncio
async def test_registry_lists_deterministically(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-list@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    names = [tool.name for tool in build_default_registry().list_for_actor(actor)]
    assert names == sorted(names)
    assert len(names) == 6


@pytest.mark.asyncio
async def test_duplicate_and_unknown_rejected() -> None:
    registry = build_default_registry()
    existing = registry.get("get_player_status")
    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(existing.definition, existing.handler)
    with pytest.raises(KeyError):
        registry.get("no_such_tool")


@pytest.mark.asyncio
async def test_tool_definition_contract() -> None:
    from pydantic import BaseModel

    with pytest.raises(ValueError, match="invalid tool name"):
        ToolDefinition(
            name="Bad Name!",
            description="x" * 30,
            input_model=PlayerRefInput,
            output_model=PlayerRefInput,
            allowed_roles=(RoleName.ADMIN,),
        )
    with pytest.raises(ValueError, match="at least one role"):
        ToolDefinition(
            name="valid_name",
            description="x" * 30,
            input_model=PlayerRefInput,
            output_model=PlayerRefInput,
            allowed_roles=(),
        )

    class NotStrict(BaseModel):
        anything: str = "x"

    with pytest.raises(ValueError, match="forbid extra fields"):
        ToolDefinition(
            name="valid_name",
            description="x" * 30,
            input_model=NotStrict,
            output_model=PlayerRefInput,
            allowed_roles=(RoleName.ADMIN,),
        )
    with pytest.raises(ValueError, match="must be callable"):
        build_default_registry().register(
            ToolDefinition(
                name="fine_name",
                description="x" * 30,
                input_model=PlayerRefInput,
                output_model=PlayerRefInput,
                allowed_roles=(RoleName.ADMIN,),
            ),
            "not-callable",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_execute_unknown_tool(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    context, close = await make_context(database, actor)
    try:
        result = await build_default_registry().execute("missing_tool", {}, context)
    finally:
        await close()
    assert result.success is False
    assert result.error is not None
    assert result.error.category is ToolErrorCategory.TOOL_NOT_FOUND
    assert result.data is None
    assert result.record.success is False


@pytest.mark.asyncio
async def test_input_validation(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin2@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        bad_uuid = await registry.execute(
            "get_player_status", {"player_id": "not-a-uuid"}, context
        )
        assert bad_uuid.error is not None
        assert bad_uuid.error.category is ToolErrorCategory.TOOL_INVALID_INPUT

        extra_field = await registry.execute(
            "get_player_status",
            {"player_id": str(uuid4()), "actor": "ADMIN", "role": "ADMIN"},
            context,
        )
        assert extra_field.error is not None
        assert extra_field.error.category is ToolErrorCategory.TOOL_INVALID_INPUT

        not_a_dict = await registry.execute("get_player_status", ["x"], context)  # type: ignore[arg-type]
        assert not_a_dict.error is not None
        assert not_a_dict.error.category is ToolErrorCategory.TOOL_INVALID_INPUT

        oversized = await registry.execute(
            "get_player_match_history",
            {"player_id": str(uuid4()), "limit": 5000},
            context,
        )
        assert oversized.error is not None
        assert oversized.error.category is ToolErrorCategory.TOOL_INVALID_INPUT
    finally:
        await close()


@pytest.mark.asyncio
async def test_authorized_execution_and_output_shape(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin3@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    ids = await seed_domain(database, admin_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        status = await registry.execute(
            "get_player_status", {"player_id": str(ids["player_a"])}, context
        )
        assert status.success is True
        assert status.data is not None
        assert status.data["id"] == str(ids["player_a"])
        assert status.error is None
        assert status.record.actor_id == admin_id
        assert status.record.success is True

        history = await registry.execute(
            "get_player_match_history",
            {"player_id": str(ids["player_a"]), "limit": 10},
            context,
        )
        assert history.success is True
        assert history.data is not None
        assert len(history.data["matches"]) == 1

        summary = await registry.execute(
            "get_match_summary", {"match_id": str(ids["match_id"])}, context
        )
        assert summary.success is True
        assert summary.data is not None
        assert summary.data["id"] == str(ids["match_id"])

        training = await registry.execute(
            "get_training_summary", {"player_id": str(ids["player_a"])}, context
        )
        assert training.success is True
        assert training.data is not None
        assert len(training.data["entries"]) == 1

        availability = await registry.execute(
            "get_player_availability", {"player_id": str(ids["player_a"])}, context
        )
        assert availability.success is True
        assert availability.data is not None
        assert len(availability.data["records"]) == 1
    finally:
        await close()


@pytest.mark.asyncio
async def test_unauthorized_tool_use(database: DatabaseFixture) -> None:
    _, _ = await create_user(database, "cop-admin4@example.com", RoleName.ADMIN)
    analyst_id, _ = await create_user(
        database, "cop-analyst@example.com", RoleName.ANALYST
    )
    actor = await load_actor(database, analyst_id)
    context, close = await make_context(database, actor)
    try:
        # ANALYST is outside AVAILABILITY_READ_ROLES: registry gate denies.
        result = await build_default_registry().execute(
            "get_player_availability", {"player_id": str(uuid4())}, context
        )
    finally:
        await close()
    assert result.success is False
    assert result.error is not None
    assert result.error.category is ToolErrorCategory.TOOL_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_player_isolation(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin5@example.com", RoleName.ADMIN)
    player_a_id, _ = await create_user(database, "cop-pa@example.com", RoleName.PLAYER)
    player_b_id, _ = await create_user(database, "cop-pb@example.com", RoleName.PLAYER)
    ids = await seed_domain(database, admin_id)
    await link_player_user(database, ids["player_a"], player_a_id)
    await link_player_user(database, ids["player_b"], player_b_id)
    actor_a = await load_actor(database, player_a_id)
    context, close = await make_context(database, actor_a)
    registry = build_default_registry()
    try:
        own = await registry.execute(
            "get_player_status", {"player_id": str(ids["player_a"])}, context
        )
        assert own.success is True

        other = await registry.execute(
            "get_player_status", {"player_id": str(ids["player_b"])}, context
        )
        assert other.success is False
        assert other.error is not None
        assert other.error.category is ToolErrorCategory.TOOL_EXECUTION_FAILED
        assert str(ids["player_b"]) not in json.dumps(other.model_dump(mode="json"))

        history = await registry.execute(
            "get_player_match_history", {"player_id": str(ids["player_b"])}, context
        )
        assert history.success is False

        other_training = await registry.execute(
            "get_training_summary", {"player_id": str(ids["player_b"])}, context
        )
        assert other_training.success is False
    finally:
        await close()


@pytest.mark.asyncio
async def test_search_club_memory_governed(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin6@example.com", RoleName.ADMIN)
    player_id, _ = await create_user(database, "cop-p6@example.com", RoleName.PLAYER)
    actor = await load_actor(database, admin_id)
    memory_id = await seed_memory(database, actor)
    player = await load_actor(database, player_id)
    admin_context, close_admin = await make_context(database, actor)
    player_context, close_player = await make_context(database, player)
    registry = build_default_registry()
    try:
        found = await registry.execute(
            "search_club_memory", {"text": "Derby", "limit": 10}, admin_context
        )
        assert found.success is True
        assert found.data is not None
        assert found.data["result_count"] == 1

        as_player = await registry.execute(
            "search_club_memory", {"text": "Derby", "limit": 10}, player_context
        )
        assert as_player.success is True
        assert as_player.data is not None
        # CLUB_GENERAL sensitivity is visible to PLAYER in this fixture.
        assert as_player.data["result_count"] == 1
        assert str(memory_id) in {
            item["memory"]["id"] for item in as_player.data["results"]
        }
    finally:
        await close_admin()
        await close_player()


@pytest.mark.asyncio
async def test_read_only_enforcement(database: DatabaseFixture) -> None:
    from app.ai.copilot.registry import build_default_registry as build

    for tool in build().list_for_actor(
        await load_actor(
            database,
            (await create_user(database, "cop-admin7@example.com", RoleName.ADMIN))[0],
        )
    ):
        assert tool.read_only is True

    admin_id, _ = await create_user(database, "cop-admin8@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    ids = await seed_domain(database, admin_id)
    memory_id = await seed_memory(database, actor)

    async def counts() -> dict[str, int]:
        async with database.sessions() as session:
            out = {}
            for model, key in (
                (Player, "players"),
                (Match, "matches"),
                (TrainingSession, "sessions"),
                (TrainingParticipation, "participations"),
                (PlayerAvailability, "records"),
                (MemoryRecord, "memories"),
                (EvidenceReference, "evidence"),
            ):
                out[key] = await session.scalar(select(func.count()).select_from(model))
            return out

    before = await counts()
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        for name, args in (
            ("get_player_status", {"player_id": str(ids["player_a"])}),
            (
                "get_player_match_history",
                {"player_id": str(ids["player_a"])},
            ),
            ("get_training_summary", {"player_id": str(ids["player_a"])}),
            ("get_player_availability", {"player_id": str(ids["player_a"])}),
            ("get_match_summary", {"match_id": str(ids["match_id"])}),
            ("search_club_memory", {"limit": 10}),
        ):
            result = await registry.execute(name, args, context)
            assert result.success is True, (name, result.error)
    finally:
        await close()
    assert await counts() == before
    assert memory_id is not None


@pytest.mark.asyncio
async def test_no_orm_leakage_and_determinism(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin9@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    ids = await seed_domain(database, admin_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        first = await registry.execute(
            "get_player_status", {"player_id": str(ids["player_a"])}, context
        )
        second = await registry.execute(
            "get_player_status", {"player_id": str(ids["player_a"])}, context
        )
        assert first.success and second.success
        assert first.data == second.data
        blob = json.dumps(first.model_dump(mode="json"))
        assert "_sa_instance_state" not in blob
        listed_first = [t.name for t in registry.list_for_actor(actor)]
        listed_second = [t.name for t in registry.list_for_actor(actor)]
        assert listed_first == listed_second == sorted(listed_first)
    finally:
        await close()


@pytest.mark.asyncio
async def test_server_side_actor_enforcement(database: DatabaseFixture) -> None:
    coach_id, _ = await create_user(
        database, "cop-coach@example.com", RoleName.HEAD_COACH
    )
    actor = await load_actor(database, coach_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        names = {tool.name for tool in registry.list_for_actor(actor)}
        assert "get_player_status" in names
        # A scout must not see availability tooling at all.
        scout_id, _ = await create_user(
            database, "cop-scout@example.com", RoleName.SCOUT
        )
        scout = await load_actor(database, scout_id)
        scout_names = {tool.name for tool in registry.list_for_actor(scout)}
        assert "get_player_availability" not in scout_names
        assert "search_club_memory" in scout_names
    finally:
        await close()


@pytest.mark.asyncio
async def test_execution_failure_mapping(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin10@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        missing = await registry.execute(
            "get_match_summary", {"match_id": str(uuid4())}, context
        )
        assert missing.success is False
        assert missing.error is not None
        assert missing.error.category is ToolErrorCategory.TOOL_EXECUTION_FAILED
        assert "Traceback" not in missing.error.message
    finally:
        await close()


@pytest.mark.asyncio
async def test_player_availability_and_match_isolation(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(database, "cop-admin11@example.com", RoleName.ADMIN)
    player_a_id, _ = await create_user(
        database, "cop-pa11@example.com", RoleName.PLAYER
    )
    ids = await seed_domain(database, admin_id)
    await link_player_user(database, ids["player_a"], player_a_id)
    actor_a = await load_actor(database, player_a_id)
    context, close = await make_context(database, actor_a)
    registry = build_default_registry()
    try:
        own_availability = await registry.execute(
            "get_player_availability", {"player_id": str(ids["player_a"])}, context
        )
        assert own_availability.success is True
        assert own_availability.data is not None
        assert len(own_availability.data["records"]) == 1

        other_availability = await registry.execute(
            "get_player_availability", {"player_id": str(ids["player_b"])}, context
        )
        assert other_availability.success is False
        assert other_availability.error is not None
        assert (
            other_availability.error.category is ToolErrorCategory.TOOL_EXECUTION_FAILED
        )

        own_match = await registry.execute(
            "get_match_summary", {"match_id": str(ids["match_id"])}, context
        )
        assert own_match.success is True

        async with database.sessions() as session:
            other_match = Match(
                team_id=ids["team_id"],
                opponent_id=(
                    await session.scalar(select(Opponent.id).order_by(Opponent.id))
                ),
                scheduled_at=datetime(2026, 11, 1, tzinfo=UTC),
                home_away=MatchSide.AWAY,
                created_by=admin_id,
            )
            session.add(other_match)
            await session.commit()
            other_match_id = other_match.id
        outsider = await registry.execute(
            "get_match_summary", {"match_id": str(other_match_id)}, context
        )
        assert outsider.success is False
        assert outsider.error is not None
        assert outsider.error.category is ToolErrorCategory.TOOL_EXECUTION_FAILED
        blob = json.dumps(outsider.model_dump(mode="json"))
        assert "Traceback" not in blob
    finally:
        await close()


@pytest.mark.asyncio
async def test_restricted_memory_search(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin12@example.com", RoleName.ADMIN)
    analyst_id, _ = await create_user(
        database, "cop-analyst12@example.com", RoleName.ANALYST
    )
    actor = await load_actor(database, admin_id)
    analyst = await load_actor(database, analyst_id)
    async with database.sessions() as session:
        await club_memory.record_memory(
            session,
            actor,
            MemoryCreate(
                memory_type=MemoryType.TACTICAL,
                title="Restricted shape notes",
                summary="Shape details for staff only.",
                occurred_at=datetime(2026, 9, 2, 15, 0, tzinfo=UTC),
                source_type=MemorySourceType.TACTICAL_ANALYSIS,
                source_id="note-restricted-1",
                sensitivity=MemorySensitivity.RESTRICTED,
            ),
        )
    admin_context, close_admin = await make_context(database, actor)
    analyst_context, close_analyst = await make_context(database, analyst)
    registry = build_default_registry()
    try:
        visible = await registry.execute(
            "search_club_memory", {"text": "shape", "limit": 10}, admin_context
        )
        assert visible.success is True
        assert visible.data is not None
        assert visible.data["result_count"] == 1

        hidden = await registry.execute(
            "search_club_memory", {"text": "shape", "limit": 10}, analyst_context
        )
        assert hidden.success is True
        assert hidden.data is not None
        assert hidden.data["result_count"] == 0
        assert "Restricted shape notes" not in json.dumps(
            hidden.model_dump(mode="json")
        )
    finally:
        await close_admin()
        await close_analyst()


@pytest.mark.asyncio
async def test_inactive_user_denied(database: DatabaseFixture) -> None:
    user_id, _ = await create_user(
        database, "cop-inactive@example.com", RoleName.ADMIN, is_active=False
    )
    actor = await load_actor(database, user_id)
    context, close = await make_context(database, actor)
    try:
        result = await build_default_registry().execute(
            "get_player_status", {"player_id": str(uuid4())}, context
        )
    finally:
        await close()
    assert result.success is False
    assert result.error is not None
    assert result.error.category is ToolErrorCategory.TOOL_NOT_AUTHORIZED


@pytest.mark.asyncio
async def test_memory_search_input_bounds(database: DatabaseFixture) -> None:
    admin_id, _ = await create_user(database, "cop-admin13@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        oversized = await registry.execute("search_club_memory", {"limit": 21}, context)
        assert oversized.error is not None
        assert oversized.error.category is ToolErrorCategory.TOOL_INVALID_INPUT

        bad_enum = await registry.execute(
            "search_club_memory", {"memory_type": "NOPE"}, context
        )
        assert bad_enum.error is not None
        assert bad_enum.error.category is ToolErrorCategory.TOOL_INVALID_INPUT

        injected = await registry.execute(
            "search_club_memory",
            {"limit": 10, "sensitivity": "CLUB_GENERAL", "role": "ADMIN"},
            context,
        )
        assert injected.error is not None
        assert injected.error.category is ToolErrorCategory.TOOL_INVALID_INPUT
    finally:
        await close()


@pytest.mark.asyncio
async def test_per_tool_output_contracts(database: DatabaseFixture) -> None:
    from app.ai.copilot.tools import BUILTIN_TOOLS

    admin_id, _ = await create_user(database, "cop-admin14@example.com", RoleName.ADMIN)
    actor = await load_actor(database, admin_id)
    ids = await seed_domain(database, admin_id)
    await seed_memory(database, actor)
    context, close = await make_context(database, actor)
    registry = build_default_registry()
    try:
        calls = {
            "get_player_status": {"player_id": str(ids["player_a"])},
            "get_player_match_history": {"player_id": str(ids["player_a"])},
            "get_training_summary": {"player_id": str(ids["player_a"])},
            "get_player_availability": {"player_id": str(ids["player_a"])},
            "get_match_summary": {"match_id": str(ids["match_id"])},
            "search_club_memory": {"limit": 10},
        }
        by_name = {tool.definition.name: tool.definition for tool in BUILTIN_TOOLS}
        assert set(calls) == set(by_name)
        for name, args in calls.items():
            result = await registry.execute(name, args, context)
            assert result.success is True, (name, result.error)
            assert result.data is not None
            by_name[name].output_model.model_validate(result.data)
            json.dumps(result.model_dump(mode="json"))
    finally:
        await close()
