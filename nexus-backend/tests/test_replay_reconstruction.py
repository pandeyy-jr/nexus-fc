"""Phase 10B — read-only decision replay reconstruction tests.

Covers: chronological reconstruction, decision-time vs outcome evidence
separation, AI/human separation, provenance, governance (restricted and
redacted evidence), missing data warnings, deterministic ordering,
read-only API surface, and the absence of hindsight judgment.

Deterministic fixtures only: no network, no LLM, no Qdrant.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.memory import (
    MemoryEvidenceType,
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
)
from app.core.roles import RoleName
from app.db.models.memory import DecisionReplay, EvidenceReference, MemoryRecord
from app.db.models.user import User
from app.schemas.memory import EvidenceCreate, MemoryCreate
from app.services import club_memory, memory_governance
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_club_memory import seed_match, seed_video

BASE = "/api/v1/memory/decisions/replay"

# Substrings that would indicate hindsight judgment. None may appear in a
# reconstruction response.
JUDGMENT_WORDS = (
    "success",
    "failure",
    "failed",
    "caused",
    "because of",
    "correct",
    "incorrect",
    "optimal",
    "should have",
    "quality",
    "rating",
    "better",
    "worse",
)

TOP_LEVEL_KEYS = {
    "decision_id",
    "decision_type",
    "decision_status",
    "decision_time",
    "decision_maker",
    "match_id",
    "player_id",
    "ai_recommendation",
    "human_decision",
    "timeline",
    "evidence",
    "outcome_references",
    "provenance",
    "warnings",
}

TIMELINE_KEYS = {
    "timestamp",
    "phase",
    "description",
    "source_type",
    "source_id",
    "evidence_id",
    "is_decision_time_evidence",
    "is_outcome_evidence",
}

EVIDENCE_KEYS = {
    "evidence_id",
    "source_type",
    "source_id",
    "evidence_type",
    "excerpt",
    "match_id",
    "video_id",
    "frame_number",
    "timestamp_seconds",
    "created_at",
    "governance_status",
    "temporal_relation",
    "provenance",
    "is_decision_time_evidence",
    "is_outcome_evidence",
}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


async def load_actor(database: DatabaseFixture, user_id: UUID) -> User:
    async with database.sessions() as session:
        user = await session.get(User, user_id)
        assert user is not None
        _ = user.role.name  # load role before detaching
        session.expunge(user)
        return user


async def seed_evidence(
    database: DatabaseFixture,
    actor: User,
    *,
    excerpt: str,
    summary: str,
    sensitivity: MemorySensitivity = MemorySensitivity.CLUB_GENERAL,
    match_id: UUID | None = None,
    video_id: UUID | None = None,
    timestamp_seconds: float | None = 402.5,
    frame_number: int | None = 120,
    provenance: str | None = None,
) -> tuple[UUID, UUID]:
    """Record a memory with one evidence reference.

    Returns (memory_id, evidence_id)."""
    async with database.sessions() as session:
        view = await club_memory.record_memory(
            session,
            actor,
            MemoryCreate(
                memory_type=MemoryType.MATCH,
                title=f"Replay fixture {uuid4().hex[:8]}",
                summary=summary,
                occurred_at=datetime.now(UTC) - timedelta(hours=3),
                source_type=MemorySourceType.HUMAN_RECORDED,
                source_id=f"fixture-{uuid4().hex[:8]}",
                sensitivity=sensitivity,
            ),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.HUMAN_RECORDED,
                    source_id=f"fixture-ev-{uuid4().hex[:8]}",
                    match_id=match_id,
                    video_id=video_id,
                    frame_number=frame_number,
                    timestamp_seconds=timestamp_seconds,
                    evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
                    excerpt=excerpt,
                    provenance=provenance,
                )
            ],
        )
    assert len(view.evidence) == 1
    return view.id, view.evidence[0].id


async def set_evidence_time(
    database: DatabaseFixture, evidence_id: UUID, when: datetime
) -> None:
    async with database.sessions() as session:
        await session.execute(
            update(EvidenceReference)
            .where(EvidenceReference.id == evidence_id)
            .values(created_at=when)
        )
        await session.commit()


async def create_replay(client: AsyncClient, token: str, **overrides: object) -> dict:
    payload: dict = {
        "decision_type": "TACTICAL",
        "decision_at": datetime.now(UTC).isoformat(),
    }
    payload.update(overrides)
    response = await client.post(f"{BASE}", json=payload, headers=bearer(token))
    assert response.status_code == 201, response.text
    return response.json()


async def reconstruct(client: AsyncClient, token: str, replay_id: str) -> dict:
    response = await client.get(
        f"{BASE}/{replay_id}/reconstruction", headers=bearer(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def build_full_replay(
    client: AsyncClient, database: DatabaseFixture, admin_id: UUID, token: str
) -> dict:
    """Full fixture: decision-time evidence, AI rec, human decision,
    and a later outcome — all with controlled, deterministic timestamps."""
    actor = await load_actor(database, admin_id)
    match_id = await seed_match(database, admin_id)
    video_id = await seed_video(database, match_id, admin_id)

    _, dt_ev = await seed_evidence(
        database,
        actor,
        excerpt="DT-EVIDENCE-EXCERPT right flank overload",
        summary="Decision-time context summary",
        match_id=match_id,
        video_id=video_id,
    )
    _, out_ev = await seed_evidence(
        database,
        actor,
        excerpt="OUTCOME-EVIDENCE-EXCERPT substitution on 74 minutes",
        summary="Outcome context summary",
        match_id=match_id,
        video_id=video_id,
        timestamp_seconds=4532.0,
        frame_number=900,
    )

    decision_at = datetime.now(UTC) - timedelta(hours=1)
    ai_at = decision_at - timedelta(minutes=20)
    human_at = decision_at - timedelta(minutes=10)
    await set_evidence_time(database, dt_ev, decision_at - timedelta(minutes=30))
    await set_evidence_time(database, out_ev, decision_at + timedelta(minutes=6))

    body = await create_replay(
        client,
        token,
        decision_at=decision_at.isoformat(),
        decision_maker=str(admin_id),
        ai_recommendation_text="Shift to a back three after the hour mark",
        ai_model="test-model",
        ai_model_version="1.0",
        ai_recommendation_at=ai_at.isoformat(),
        ai_request_id=str(uuid4()),
        ai_grounded=True,
        ai_cited_evidence_ids=[str(dt_ev)],
        human_decision="ACCEPTED",
        human_decision_at=human_at.isoformat(),
        rationale="Wide overloads were being neutralised",
        evidence_ids=[str(dt_ev)],
        outcome_evidence_ids=[str(out_ev)],
    )
    return {
        "replay_id": body["id"],
        "decision_at": decision_at,
        "ai_at": ai_at,
        "human_at": human_at,
        "dt_evidence_id": dt_ev,
        "out_evidence_id": out_ev,
        "match_id": match_id,
        "video_id": video_id,
    }


class TestReplayReconstruction:
    """1. reconstruction 6. provenance 11. deterministic ordering"""

    @pytest.mark.asyncio
    async def test_reconstruction_returns_complete_replay(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """1: Read-only reconstruction returns the full replay contract."""
        admin_id, token = await create_user(
            database, "rb-full@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        assert set(body) == TOP_LEVEL_KEYS
        assert body["decision_id"] == fixture["replay_id"]
        assert body["decision_type"] == "TACTICAL"
        assert ts(body["decision_time"]) == fixture["decision_at"]
        assert body["decision_maker"] == str(admin_id)
        assert isinstance(body["timeline"], list) and body["timeline"]
        assert isinstance(body["evidence"], list) and body["evidence"]
        assert isinstance(body["outcome_references"], list)
        assert body["provenance"]["source"] == "decision_replays"
        assert body["provenance"]["replay_id"] == fixture["replay_id"]
        # Deterministic fixture must not emit spurious warnings
        assert body["warnings"] == []
        for item in body["timeline"]:
            assert set(item) == TIMELINE_KEYS
        for item in body["evidence"]:
            assert set(item) == EVIDENCE_KEYS

    @pytest.mark.asyncio
    async def test_evidence_provenance_preserved(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """6: Source IDs, evidence IDs, match/video/frame references and
        record timestamps survive reconstruction."""
        admin_id, token = await create_user(
            database, "rb-prov@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        by_id = {item["evidence_id"]: item for item in body["evidence"]}
        dt_item = by_id[str(fixture["dt_evidence_id"])]
        assert dt_item["source_type"] == "HUMAN_RECORDED"
        assert dt_item["source_id"]
        assert dt_item["evidence_type"] == "TEXT_EXCERPT"
        assert dt_item["excerpt"] == "DT-EVIDENCE-EXCERPT right flank overload"
        assert dt_item["match_id"] == str(fixture["match_id"])
        assert dt_item["video_id"] == str(fixture["video_id"])
        assert dt_item["frame_number"] == 120
        assert dt_item["timestamp_seconds"] == 402.5
        assert dt_item["created_at"]
        assert dt_item["governance_status"] == "allowed"

        out_item = by_id[str(fixture["out_evidence_id"])]
        assert out_item["frame_number"] == 900
        assert out_item["timestamp_seconds"] == 4532.0

    @pytest.mark.asyncio
    async def test_deterministic_ordering(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """11: Repeated reads return identical, deterministically ordered
        timelines (timestamp, phase, stable evidence ID)."""
        admin_id, token = await create_user(
            database, "rb-det@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        first = await reconstruct(client, token, fixture["replay_id"])
        second = await reconstruct(client, token, fixture["replay_id"])

        assert first == second
        stamps = [ts(item["timestamp"]) for item in first["timeline"]]
        assert stamps == sorted(stamps)
        # Phase ordering within the same second is stable
        phases = [item["phase"] for item in first["timeline"]]
        assert phases == sorted(phases) or len(set(stamps)) == len(stamps)


class TestChronology:
    """2. chronological ordering
    3. decision-time vs outcome separation"""

    @pytest.mark.asyncio
    async def test_timeline_is_chronological(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """2: Timeline is sorted by timestamp ascending."""
        admin_id, token = await create_user(
            database, "rb-chrono@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        stamps = [ts(item["timestamp"]) for item in body["timeline"]]
        assert stamps == sorted(stamps)

    @pytest.mark.asyncio
    async def test_decision_time_and_outcome_evidence_separated(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """3: Evidence known at decision time is never presented as outcome
        evidence and vice versa; later evidence is never shown as known."""
        admin_id, token = await create_user(
            database, "rb-sep@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])
        decision_time = ts(body["decision_time"])

        dt_items = [i for i in body["timeline"] if i["phase"] == "EVIDENCE"]
        outcome_items = [i for i in body["timeline"] if i["phase"] == "OUTCOME"]
        assert dt_items and outcome_items

        for item in dt_items:
            assert item["is_decision_time_evidence"] is True
            assert item["is_outcome_evidence"] is False
            assert ts(item["timestamp"]) < decision_time
        for item in outcome_items:
            assert item["is_outcome_evidence"] is True
            assert item["is_decision_time_evidence"] is False
            assert ts(item["timestamp"]) > decision_time

        evidence_flags = {i["evidence_id"]: i for i in body["evidence"]}
        assert (
            evidence_flags[str(fixture["dt_evidence_id"])]["is_decision_time_evidence"]
            is True
        )
        assert (
            evidence_flags[str(fixture["out_evidence_id"])]["is_outcome_evidence"]
            is True
        )
        assert (
            evidence_flags[str(fixture["out_evidence_id"])]["is_decision_time_evidence"]
            is False
        )


class TestAiHumanSeparation:
    """4. AI recommendation preserved separately
    5. human decision preserved separately"""

    @pytest.mark.asyncio
    async def test_ai_recommendation_preserved_separately(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """4: The AI recommendation keeps model/provider metadata, time,
        request ID and citations in its own field."""
        admin_id, token = await create_user(
            database, "rb-ai@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        ai = body["ai_recommendation"]
        assert ai is not None
        assert ai["text"] == "Shift to a back three after the hour mark"
        assert ai["model"] == "test-model"
        assert ai["model_version"] == "1.0"
        assert ts(ai["timestamp"]) == fixture["ai_at"]
        assert ai["request_id"] is not None
        assert ai["grounded"] is True
        assert ai["cited_evidence_ids"] == [str(fixture["dt_evidence_id"])]
        ai_phases = [i for i in body["timeline"] if i["phase"] == "AI_RECOMMENDATION"]
        assert len(ai_phases) == 1
        # AI output is never merged into the human decision field
        assert body["human_decision"] is not None
        assert "text" not in body["human_decision"]

    @pytest.mark.asyncio
    async def test_human_decision_preserved_separately(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """5: The human decision keeps decision maker, timestamp, structured
        action and rationale — never merged with the AI output."""
        admin_id, token = await create_user(
            database, "rb-human@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        human = body["human_decision"]
        assert human is not None
        assert human["decision"] == "ACCEPTED"
        assert human["decision_maker"] == str(admin_id)
        assert ts(human["timestamp"]) == fixture["human_at"]
        assert human["rationale"] == "Wide overloads were being neutralised"
        human_phases = [i for i in body["timeline"] if i["phase"] == "HUMAN_DECISION"]
        assert len(human_phases) == 1
        # No field judges the human act
        assert "correct" not in human
        assert "score" not in human
        # AI recommendation and human decision are distinct objects
        assert body["ai_recommendation"] is not None
        assert set(body["ai_recommendation"]) != set(human)

    @pytest.mark.asyncio
    async def test_missing_ai_timestamp_warns(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """10: A missing AI recommendation timestamp produces a warning and
        no chronology is invented for it."""
        admin_id, token = await create_user(
            database, "rb-noai-ts@example.com", RoleName.ADMIN
        )
        fixture = await create_replay(
            client,
            token,
            ai_recommendation_text="Consider a double pivot",
            human_decision="MODIFIED",
            human_decision_at=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        )

        body = await reconstruct(client, token, fixture["id"])

        assert any("AI recommendation timestamp missing" in w for w in body["warnings"])
        assert body["ai_recommendation"]["timestamp"] is None
        assert body["ai_recommendation"]["text"] == "Consider a double pivot"


class TestGovernance:
    """7. restricted evidence remains inaccessible
    8. redacted evidence remains governed
    15. player cannot access another player's restricted replay"""

    @pytest.mark.asyncio
    async def test_restricted_evidence_governed_by_role(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """7: Restricted-memory evidence hydrates for authorized roles and
        is withheld (content only, IDs preserved) for everyone else."""
        admin_id, admin_token = await create_user(
            database, "rb-restricted@example.com", RoleName.ADMIN
        )
        analyst_id, analyst_token = await create_user(
            database, "rb-analyst@example.com", RoleName.ANALYST
        )
        actor = await load_actor(database, admin_id)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="RESTRICTED-EXCERPT internal contract clause",
            summary="RESTRICTED-SUMMARY board-only note",
            sensitivity=MemorySensitivity.RESTRICTED,
        )
        fixture = await create_replay(
            client,
            admin_token,
            human_decision="DEFERRED",
            human_decision_at=datetime.now(UTC).isoformat(),
            evidence_ids=[str(ev_id)],
        )

        admin_body = await reconstruct(client, admin_token, fixture["id"])
        analyst_body = await reconstruct(client, analyst_token, fixture["id"])

        admin_item = admin_body["evidence"][0]
        assert admin_item["governance_status"] == "allowed"
        assert admin_item["excerpt"] == "RESTRICTED-EXCERPT internal contract clause"

        analyst_item = analyst_body["evidence"][0]
        assert analyst_item["governance_status"] == "inaccessible"
        assert analyst_item["excerpt"] is None
        # Identity (IDs) preserved so the replay stays intact...
        assert analyst_item["evidence_id"] == str(ev_id)
        # ...but contents and the reason for restriction never leak
        assert "RESTRICTED-EXCERPT" not in str(analyst_body)
        assert "RESTRICTED-SUMMARY" not in str(analyst_body)
        assert any("unavailable" in w for w in analyst_body["warnings"])
        assert "restricted" not in str(analyst_body["warnings"]).lower()
        assert "permission" not in str(analyst_body["warnings"]).lower()

    @pytest.mark.asyncio
    async def test_redacted_evidence_remains_governed(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """8: Evidence whose parent memory was redacted stays withheld even
        for ADMIN — redaction is never reversed by reconstruction."""
        admin_id, token = await create_user(
            database, "rb-redact@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        memory_id, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="REDACTED-EXCERPT sensitive welfare note",
            summary="REDACTED-SUMMARY welfare summary",
        )
        async with database.sessions() as session:
            await memory_governance.redact_memory(session, actor, memory_id)

        fixture = await create_replay(
            client,
            token,
            human_decision="NO_ACTION",
            human_decision_at=datetime.now(UTC).isoformat(),
            evidence_ids=[str(ev_id)],
        )
        body = await reconstruct(client, token, fixture["id"])

        item = body["evidence"][0]
        assert item["governance_status"] == "inaccessible"
        assert item["excerpt"] is None
        assert "REDACTED-EXCERPT" not in str(body)
        assert "REDACTED-SUMMARY" not in str(body)
        assert any("unavailable" in w for w in body["warnings"])

    @pytest.mark.asyncio
    async def test_player_cannot_view_restricted_replay_content(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """15: A PLAYER cannot read another person's restricted (availability)
        replay content; the replay itself stays safely available."""
        admin_id, admin_token = await create_user(
            database, "rb-owner@example.com", RoleName.ADMIN
        )
        _, player_token = await create_user(
            database, "rb-other-player@example.com", RoleName.PLAYER
        )
        actor = await load_actor(database, admin_id)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="AVAIL-CONFIDENTIAL-DETAIL return-to-play progression",
            summary="AVAIL-CONFIDENTIAL-SUMMARY",
            sensitivity=MemorySensitivity.AVAILABILITY,
        )
        fixture = await create_replay(
            client,
            admin_token,
            human_decision="ACCEPTED",
            human_decision_at=datetime.now(UTC).isoformat(),
            evidence_ids=[str(ev_id)],
        )

        body = await reconstruct(client, player_token, fixture["id"])

        # Replay structure survives, restricted content does not
        assert body["decision_id"] == fixture["id"]
        assert body["evidence"][0]["governance_status"] == "inaccessible"
        assert body["evidence"][0]["excerpt"] is None
        assert "AVAIL-CONFIDENTIAL-DETAIL" not in str(body)
        assert "AVAIL-CONFIDENTIAL-SUMMARY" not in str(body)
        assert any("unavailable" in w for w in body["warnings"])


class TestMissingData:
    """9. missing evidence reference
    10. missing timestamp warning"""

    @pytest.mark.asyncio
    async def test_missing_evidence_reference_handled_safely(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """9: A dangling evidence reference warns instead of fabricating an
        event or failing the read."""
        admin_id, token = await create_user(
            database, "rb-missing@example.com", RoleName.ADMIN
        )
        ghost = uuid4()
        fixture = await create_replay(
            client,
            token,
            human_decision="ACCEPTED",
            human_decision_at=datetime.now(UTC).isoformat(),
            evidence_ids=[str(ghost)],
            outcome_evidence_ids=[str(uuid4())],
        )

        body = await reconstruct(client, token, fixture["id"])

        assert any("not found" in w for w in body["warnings"])
        # Nothing fabricated: no ghost evidence, no ghost timeline event
        assert body["evidence"] == []
        ghost_refs = [i for i in body["timeline"] if i["evidence_id"] in {str(ghost)}]
        assert ghost_refs == []
        assert body["outcome_references"] == []

    @pytest.mark.asyncio
    async def test_missing_video_timestamp_warns_in_description(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """10: Evidence without an event timestamp is ordered by record time
        and says so — chronology is not silently invented."""
        admin_id, token = await create_user(
            database, "rb-no-ts@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="NO-TS-EXCERPT",
            summary="Evidence without a video timestamp",
            timestamp_seconds=None,
            frame_number=None,
        )
        fixture = await create_replay(
            client,
            token,
            human_decision="ACCEPTED",
            human_decision_at=datetime.now(UTC).isoformat(),
            evidence_ids=[str(ev_id)],
        )

        body = await reconstruct(client, token, fixture["id"])

        evidence_events = [i for i in body["timeline"] if i["phase"] == "EVIDENCE"]
        assert len(evidence_events) == 1
        assert "no video timestamp" in evidence_events[0]["description"]
        assert "ordered by record time" in evidence_events[0]["description"]
        assert body["evidence"][0]["timestamp_seconds"] is None


class TestReadOnlyApi:
    """12. no PATCH endpoint
    13. no DELETE endpoint
    14. unauthorized replay access
    16. no mutation during replay reads"""

    @pytest.mark.asyncio
    async def test_no_patch_endpoint(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """12: Reconstruction exposes no write methods."""
        admin_id, token = await create_user(
            database, "rb-patch@example.com", RoleName.ADMIN
        )
        fixture = await create_replay(client, token)

        response = await client.patch(
            f"{BASE}/{fixture['id']}/reconstruction",
            json={"warnings": []},
            headers=bearer(token),
        )
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_no_delete_endpoint(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """13: Reconstruction exposes no delete methods."""
        admin_id, token = await create_user(
            database, "rb-del@example.com", RoleName.ADMIN
        )
        fixture = await create_replay(client, token)

        response = await client.delete(
            f"{BASE}/{fixture['id']}/reconstruction", headers=bearer(token)
        )
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_unauthenticated_access_denied(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """14: Reconstruction requires authentication."""
        admin_id, token = await create_user(
            database, "rb-unauth@example.com", RoleName.ADMIN
        )
        fixture = await create_replay(client, token)

        response = await client.get(f"{BASE}/{fixture['id']}/reconstruction")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_reconstruction_does_not_mutate(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """16: Reads never mutate the replay, its evidence, or memories."""
        admin_id, token = await create_user(
            database, "rb-mutate@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        async def snapshot() -> tuple[dict, int, int, int]:
            async with database.sessions() as session:
                record = await session.get(DecisionReplay, UUID(fixture["replay_id"]))
                assert record is not None
                columns = {
                    "decision_at": record.decision_at,
                    "human_decision": record.human_decision,
                    "rationale": record.rationale,
                    "evidence_ids": record.evidence_ids,
                    "outcome_evidence_ids": record.outcome_evidence_ids,
                    "created_at": record.created_at,
                }
                memories = len(
                    list((await session.execute(select(MemoryRecord))).scalars())
                )
                evidence = len(
                    list((await session.execute(select(EvidenceReference))).scalars())
                )
                replays = len(
                    list((await session.execute(select(DecisionReplay))).scalars())
                )
            return columns, memories, evidence, replays

        before = await snapshot()
        await reconstruct(client, token, fixture["replay_id"])
        await reconstruct(client, token, fixture["replay_id"])
        after = await snapshot()

        assert before == after


class TestNoHindsightJudgment:
    """17. no fabricated outcome
    18. no causality/quality judgment"""

    @pytest.mark.asyncio
    async def test_no_fabricated_outcome(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """17: Outcomes are descriptive references only — no success,
        failure, or causality is computed or returned."""
        admin_id, token = await create_user(
            database, "rb-outcome@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        assert body["outcome_references"], "outcome reference expected"
        for ref in body["outcome_references"]:
            assert set(ref) == {
                "evidence_id",
                "source_type",
                "source_id",
                "timestamp",
                "description",
                "temporal_relation",
                "provenance",
            }
            assert ref["description"].startswith("Outcome")
            assert ref["temporal_relation"] == "AFTER_DECISION"
        # No field anywhere claims an outcome verdict
        assert "success" not in str(body).lower()
        assert "failure" not in str(body).lower()

    @pytest.mark.asyncio
    async def test_no_causality_or_quality_judgment(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """18: The reconstruction never ranks, scores, or attributes causality
        to the human decision or the AI recommendation."""
        admin_id, token = await create_user(
            database, "rb-judge@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        serialized = str(body).lower()
        for word in JUDGMENT_WORDS:
            assert word not in serialized, f"judgment word found: {word}"
        # No score/rating fields on any contract
        for item in body["timeline"] + body["evidence"] + body["outcome_references"]:
            assert not any(
                key in item for key in ("score", "rating", "quality", "verdict")
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
