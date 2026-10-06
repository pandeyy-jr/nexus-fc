"""Phase 10C — decision replay outcome linking tests.

Covers: outcome representation (source/timestamp/provenance/temporal
relation), before/at/after classification, temporal integrity (post-
decision evidence never shown as decision-time context), governance of
unauthorized outcome evidence, AI/human/outcome separation, deterministic
ordering, empty/multiple/missing outcome sets, and absence of causal or
judgment language.

Deterministic fixtures only: no network, no LLM, no Qdrant.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.memory import MemorySensitivity
from app.core.roles import RoleName
from app.db.models.memory import DecisionReplay
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_replay_reconstruction import (
    JUDGMENT_WORDS,
    build_full_replay,
    create_replay,
    load_actor,
    reconstruct,
    seed_evidence,
    set_evidence_time,
    ts,
)

BASE = "/api/v1/memory/decisions/replay"

OUTCOME_REF_KEYS = {
    "evidence_id",
    "source_type",
    "source_id",
    "timestamp",
    "description",
    "temporal_relation",
    "provenance",
}


async def link_replay(
    client: AsyncClient,
    token: str,
    decision_at: datetime,
    *,
    evidence_ids: tuple[UUID, ...] = (),
    outcome_ids: tuple[UUID, ...] = (),
    **overrides: object,
) -> dict:
    """Create a replay whose human decision sits just before ``decision_at``."""
    payload: dict = {
        "decision_at": decision_at.isoformat(),
        "human_decision": "ACCEPTED",
        "human_decision_at": (decision_at - timedelta(minutes=5)).isoformat(),
        "evidence_ids": [str(e) for e in evidence_ids] or None,
        "outcome_evidence_ids": [str(o) for o in outcome_ids] or None,
    }
    payload.update(overrides)
    return await create_replay(client, token, **payload)


class TestOutcomeRepresentation:
    """Outcome item preserves source, timestamp, ID, description,
    provenance, and before/after classification. Empty and multiple
    outcome sets behave correctly."""

    @pytest.mark.asyncio
    async def test_outcome_evidence_is_after_decision(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """1: Every linked outcome is classified AFTER_DECISION and its
        timestamp is later than the decision."""
        admin_id, token = await create_user(
            database, "oc-after@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        assert body["outcome_references"], "outcome reference expected"
        decision_time = ts(body["decision_time"])
        for ref in body["outcome_references"]:
            assert set(ref) == OUTCOME_REF_KEYS
            assert ref["temporal_relation"] == "AFTER_DECISION"
            assert ts(ref["timestamp"]) > decision_time
        out_item = next(
            i
            for i in body["evidence"]
            if i["evidence_id"] == str(fixture["out_evidence_id"])
        )
        assert out_item["temporal_relation"] == "AFTER_DECISION"
        assert out_item["is_outcome_evidence"] is True

    @pytest.mark.asyncio
    async def test_provenance_preserved_on_outcome(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """4: Evidence provenance survives linking into the outcome view."""
        admin_id, token = await create_user(
            database, "oc-prov@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="OUTCOME-PROV-EXCERPT second half chance",
            summary="Outcome with provenance",
            timestamp_seconds=3000.0,
            provenance="clip-annotation:v3",
        )
        await set_evidence_time(database, ev_id, decision_at + timedelta(minutes=4))
        fixture = await link_replay(client, token, decision_at, outcome_ids=(ev_id,))

        body = await reconstruct(client, token, fixture["id"])

        ref = body["outcome_references"][0]
        assert ref["provenance"] == "clip-annotation:v3"
        item = body["evidence"][0]
        assert item["provenance"] == "clip-annotation:v3"
        assert item["source_type"] == "HUMAN_RECORDED"
        assert item["source_id"]
        assert ts(ref["timestamp"]) == decision_at + timedelta(minutes=4)

    @pytest.mark.asyncio
    async def test_empty_outcome_set(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """8: A replay with no linked outcomes returns an empty outcome set
        with no fabricated events and no warnings."""
        _, token = await create_user(database, "oc-empty@example.com", RoleName.ADMIN)
        fixture = await link_replay(client, token, datetime.now(UTC))

        body = await reconstruct(client, token, fixture["id"])

        assert body["outcome_references"] == []
        assert body["evidence"] == []
        assert not [i for i in body["timeline"] if i["phase"] == "OUTCOME"]
        assert body["warnings"] == []

    @pytest.mark.asyncio
    async def test_multiple_outcomes_all_present_and_ordered(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """9: Multiple linked outcomes are all returned in timestamp order."""
        admin_id, token = await create_user(
            database, "oc-multi@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=2)

        outcome_ids: list[UUID] = []
        for offset in (10, 5, 20):  # deliberately unsorted input order
            _, ev_id = await seed_evidence(
                database,
                actor,
                excerpt=f"MULTI-OUTCOME-{offset}",
                summary=f"Outcome recorded at +{offset} minutes",
                timestamp_seconds=float(offset * 60),
            )
            await set_evidence_time(
                database, ev_id, decision_at + timedelta(minutes=offset)
            )
            outcome_ids.append(ev_id)

        fixture = await link_replay(
            client,
            token,
            decision_at,
            outcome_ids=(outcome_ids[0], outcome_ids[1], outcome_ids[2]),
        )

        body = await reconstruct(client, token, fixture["id"])

        refs = body["outcome_references"]
        assert len(refs) == 3
        stamps = [ts(r["timestamp"]) for r in refs]
        assert stamps == sorted(stamps)
        assert stamps == [
            decision_at + timedelta(minutes=5),
            decision_at + timedelta(minutes=10),
            decision_at + timedelta(minutes=20),
        ]
        assert all(r["temporal_relation"] == "AFTER_DECISION" for r in refs)
        outcome_events = [i for i in body["timeline"] if i["phase"] == "OUTCOME"]
        assert len(outcome_events) == 3


class TestTemporalIntegrity:
    """before/at/after classification; post-decision evidence is never
    presented as decision-time context."""

    @pytest.mark.asyncio
    async def test_before_at_after_classification(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """2: Evidence is classified BEFORE_DECISION / AT_DECISION /
        AFTER_DECISION purely from timestamps."""
        admin_id, token = await create_user(
            database, "oc-classify@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)

        _, before_ev = await seed_evidence(
            database, actor, excerpt="BEFORE-EXCERPT", summary="Known earlier"
        )
        _, at_ev = await seed_evidence(
            database, actor, excerpt="AT-EXCERPT", summary="At the decision"
        )
        _, after_ev = await seed_evidence(
            database, actor, excerpt="AFTER-EXCERPT", summary="Observed later"
        )
        await set_evidence_time(database, before_ev, decision_at - timedelta(minutes=9))
        await set_evidence_time(database, at_ev, decision_at)
        await set_evidence_time(database, after_ev, decision_at + timedelta(minutes=3))

        fixture = await link_replay(
            client,
            token,
            decision_at,
            evidence_ids=(before_ev, at_ev),
            outcome_ids=(after_ev,),
        )

        body = await reconstruct(client, token, fixture["id"])
        by_id = {i["evidence_id"]: i for i in body["evidence"]}

        assert by_id[str(before_ev)]["temporal_relation"] == "BEFORE_DECISION"
        assert by_id[str(at_ev)]["temporal_relation"] == "AT_DECISION"
        assert by_id[str(after_ev)]["temporal_relation"] == "AFTER_DECISION"
        # Decision-time context keeps before/at items; the outcome is after
        assert by_id[str(before_ev)]["is_decision_time_evidence"] is True
        assert by_id[str(at_ev)]["is_decision_time_evidence"] is True
        assert by_id[str(after_ev)]["is_outcome_evidence"] is True
        # The single linked outcome is classified after the decision
        assert body["outcome_references"][0]["temporal_relation"] == "AFTER_DECISION"
        # Timeline phases mirror the classification
        phases = {
            i["evidence_id"]: i["phase"]
            for i in body["timeline"]
            if i["evidence_id"] is not None
        }
        assert phases[str(before_ev)] == "EVIDENCE"
        assert phases[str(at_ev)] == "EVIDENCE"
        assert phases[str(after_ev)] == "OUTCOME"

    @pytest.mark.asyncio
    async def test_post_decision_evidence_never_in_decision_context(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """3: Even when the stored record wrongly links a post-decision
        record as decision-time evidence, reconstruction classifies it
        AFTER_DECISION, never shows it as known at decision time, and
        warns about the contradiction."""
        admin_id, token = await create_user(
            database, "oc-late@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, late_ev = await seed_evidence(
            database, actor, excerpt="LATE-EXCERPT", summary="Recorded too late"
        )
        await set_evidence_time(database, late_ev, decision_at + timedelta(minutes=7))

        fixture = await link_replay(client, token, decision_at, evidence_ids=(late_ev,))

        body = await reconstruct(client, token, fixture["id"])

        item = body["evidence"][0]
        assert item["temporal_relation"] == "AFTER_DECISION"
        assert item["is_decision_time_evidence"] is False
        assert item["is_outcome_evidence"] is False  # not a linked outcome either
        # Absent from the timeline entirely: neither known-at-decision nor outcome
        assert not [i for i in body["timeline"] if i["evidence_id"] == str(late_ev)]
        assert any(
            "referenced as decision-time evidence" in w for w in body["warnings"]
        )
        # Global invariant: nothing classified AFTER is decision-time context
        decision_time = ts(body["decision_time"])
        for ev in body["evidence"]:
            if ev["temporal_relation"] == "AFTER_DECISION":
                assert ev["is_decision_time_evidence"] is False
        for item in body["timeline"]:
            if item["is_decision_time_evidence"]:
                assert ts(item["timestamp"]) <= decision_time


class TestAiHumanOutcomeSeparation:
    @pytest.mark.asyncio
    async def test_ai_human_and_outcome_remain_distinct(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """5: AI recommendation, human decision, and observed outcome stay in
        separate fields; the later outcome never rewrites the human act."""
        admin_id, token = await create_user(
            database, "oc-separate@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        ai = body["ai_recommendation"]
        human = body["human_decision"]
        outcomes = body["outcome_references"]
        assert ai and human and outcomes

        assert set(ai) == {
            "text",
            "model",
            "model_version",
            "timestamp",
            "request_id",
            "grounded",
            "cited_evidence_ids",
        }
        assert set(human) == {"decision", "timestamp", "rationale", "decision_maker"}
        # Human decision is unchanged by the later outcome
        assert human["decision"] == "ACCEPTED"
        assert human["rationale"] == "Wide overloads were being neutralised"
        assert "OUTCOME" not in str(human).upper()
        # Outcome references carry no AI or human fields
        for ref in outcomes:
            assert set(ref) == OUTCOME_REF_KEYS
            assert "decision" not in ref
            assert "model" not in ref
        # AI recommendation carries no outcome verdict
        assert "success" not in str(ai).lower()


class TestOutcomeGovernance:
    @pytest.mark.asyncio
    async def test_unauthorized_outcome_evidence_withheld(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """6: A user who may not retrieve the underlying evidence receives
        no outcome entry, no outcome timeline event, no excerpt and no
        provenance — while the authorized admin sees the full outcome."""
        admin_id, admin_token = await create_user(
            database, "oc-owner@example.com", RoleName.ADMIN
        )
        _, analyst_token = await create_user(
            database, "oc-analyst@example.com", RoleName.ANALYST
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="OUTCOME-RESTRICTED-EXCERPT welfare follow-up",
            summary="Restricted outcome summary",
            sensitivity=MemorySensitivity.RESTRICTED,
            provenance="restricted-note:123",
        )
        await set_evidence_time(database, ev_id, decision_at + timedelta(minutes=6))
        fixture = await link_replay(
            client, admin_token, decision_at, outcome_ids=(ev_id,)
        )

        analyst_body = await reconstruct(client, analyst_token, fixture["id"])
        admin_body = await reconstruct(client, admin_token, fixture["id"])

        # Authorized admin sees the full outcome
        assert admin_body["outcome_references"][0]["temporal_relation"] == (
            "AFTER_DECISION"
        )
        assert (
            admin_body["outcome_references"][0]["provenance"] == "restricted-note:123"
        )

        # Analyst gets no outcome presentation at all
        assert analyst_body["outcome_references"] == []
        assert not [i for i in analyst_body["timeline"] if i["phase"] == "OUTCOME"]
        placeholder = analyst_body["evidence"][0]
        assert placeholder["governance_status"] == "inaccessible"
        assert placeholder["excerpt"] is None
        assert placeholder["provenance"] is None
        serialized = str(analyst_body)
        assert "OUTCOME-RESTRICTED-EXCERPT" not in serialized
        assert "restricted-note:123" not in serialized
        assert any("unavailable" in w for w in analyst_body["warnings"])
        assert any(
            "outcome reference(s) were withheld" in w for w in analyst_body["warnings"]
        )
        # Reason for restriction is never disclosed
        assert "restricted" not in str(analyst_body["warnings"]).lower()


class TestDeterministicOrdering:
    @pytest.mark.asyncio
    async def test_equal_timestamps_ordered_by_evidence_id(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """6/7: Equal timestamps fall back to stable evidence-ID ordering;
        repeated reads are identical."""
        admin_id, token = await create_user(
            database, "oc-deterministic@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)

        ids: list[UUID] = []
        for _ in range(3):
            _, ev_id = await seed_evidence(
                database,
                actor,
                excerpt=f"SAME-TS-{uuid4().hex[:6]}",
                summary="Outcome sharing one timestamp",
            )
            ids.append(ev_id)
        same_ts = decision_at + timedelta(minutes=5)
        for ev_id in ids:
            await set_evidence_time(database, ev_id, same_ts)

        fixture = await link_replay(client, token, decision_at, outcome_ids=tuple(ids))

        first = await reconstruct(client, token, fixture["id"])
        second = await reconstruct(client, token, fixture["id"])

        assert first == second
        got = [r["evidence_id"] for r in first["outcome_references"]]
        expected = sorted(str(i) for i in ids)
        assert got == expected
        # Deterministic tie-break: timestamp, then evidence ID
        keys = [
            (ts(r["timestamp"]), r["evidence_id"]) for r in first["outcome_references"]
        ]
        assert keys == sorted(keys)


class TestMissingAndInvalidReferences:
    @pytest.mark.asyncio
    async def test_missing_outcome_reference_warns(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """10a: A dangling outcome reference warns and is never fabricated."""
        _, token = await create_user(database, "oc-missing@example.com", RoleName.ADMIN)
        ghost = uuid4()
        fixture = await link_replay(
            client,
            token,
            datetime.now(UTC),
            outcome_ids=(ghost,),
        )

        body = await reconstruct(client, token, fixture["id"])

        assert any("not found" in w for w in body["warnings"])
        assert body["outcome_references"] == []
        assert body["evidence"] == []
        assert not [i for i in body["timeline"] if i["phase"] == "OUTCOME"]

    @pytest.mark.asyncio
    async def test_invalid_stored_reference_list_warns(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """10b: Corrupt stored reference JSON warns instead of failing or
        silently pretending the links never existed."""
        _, token = await create_user(database, "oc-invalid@example.com", RoleName.ADMIN)
        fixture = await link_replay(client, token, datetime.now(UTC))
        async with database.sessions() as session:
            await session.execute(
                update(DecisionReplay)
                .where(DecisionReplay.id == UUID(fixture["id"]))
                .values(outcome_evidence_ids="not-valid-json")
            )
            await session.commit()

        body = await reconstruct(client, token, fixture["id"])

        assert any(
            "Stored outcome evidence references could not be parsed" in w
            for w in body["warnings"]
        )
        assert body["outcome_references"] == []


class TestNoJudgmentLanguage:
    @pytest.mark.asyncio
    async def test_no_causal_or_judgment_language(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """11: The service generates no causality, success/failure, or
        quality judgment when outcomes are linked."""
        admin_id, token = await create_user(
            database, "oc-judgment@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await reconstruct(client, token, fixture["replay_id"])

        serialized = str(body).lower()
        for word in JUDGMENT_WORDS:
            assert word not in serialized, f"judgment word found: {word}"
        for ref in body["outcome_references"]:
            assert ref["description"].startswith("Outcome")
            assert "caused" not in ref["description"].lower()
        # No verdict-shaped fields anywhere in the response
        assert "verdict" not in serialized
        assert "causality" not in serialized


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
