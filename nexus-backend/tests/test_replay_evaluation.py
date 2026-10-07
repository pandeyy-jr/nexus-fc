"""Phase 10D — decision replay evaluation tests.

Covers: the typed evaluation contract, evidence-based factual comparison,
structured evaluation statuses, temporal integrity (post-decision
evidence never enters the decision-time set), governance (unauthorized
evidence cannot influence the evaluation), provenance traceability,
deterministic ordering, repeated-evaluation equivalence, unknown
confidence remaining unknown, absence of causal/judgment language, and
read-only behavior (stored record never mutated).

Deterministic fixtures only: no network, no LLM, no Qdrant.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.memory import MemorySensitivity
from app.core.roles import RoleName
from app.db.models.memory import DecisionReplay as DecisionReplayRecord
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_replay_outcome_linking import link_replay
from tests.test_replay_reconstruction import (
    JUDGMENT_WORDS,
    bearer,
    build_full_replay,
    load_actor,
    seed_evidence,
    set_evidence_time,
    ts,
)

BASE = "/api/v1/memory/decisions/replay"

# Extra causal/hindsight phrasing beyond JUDGMENT_WORDS that the
# evaluation service must never produce.
CAUSAL_PHRASES = (
    "would have",
    "led to",
    "due to",
    "blame",
    "fault",
    "wrong",
    "wisely",
    "poorly",
    "responsible for",
    "at fault",
)

EVALUATION_KEYS = {
    "decision_id",
    "decision_type",
    "decision_time",
    "decision_maker",
    "status",
    "recommendation_relation",
    "ai_recommendation",
    "human_decision",
    "decision_time_evidence",
    "outcome_references",
    "observations",
    "metadata",
    "provenance",
    "warnings",
}

METADATA_KEYS = {"method", "basis", "llm_used", "confidence"}
OBSERVATION_KEYS = {"code", "detail", "evidence_ids"}


async def evaluate(client: AsyncClient, token: str, replay_id: str) -> dict:
    response = await client.get(f"{BASE}/{replay_id}/evaluation", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


def codes(body: dict) -> list[str]:
    return [obs["code"] for obs in body["observations"]]


async def read_replay_row(database: DatabaseFixture, replay_id: str) -> dict:
    """Snapshot every column of the stored replay record."""
    async with database.sessions() as session:
        row = await session.get(DecisionReplayRecord, UUID(replay_id))
        assert row is not None
        return {
            column.name: getattr(row, column.name)
            for column in DecisionReplayRecord.__table__.columns
        }


class TestCompleteEvaluation:
    """1. complete replay  2. no AI recommendation  3. human differs"""

    @pytest.mark.asyncio
    async def test_complete_replay_is_evaluable(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """1: Full replay (AI + human + outcomes) yields EVALUABLE with
        every contract field present and the three parts kept separate."""
        admin_id, token = await create_user(
            database, "ev-full@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await evaluate(client, token, fixture["replay_id"])

        assert set(body) == EVALUATION_KEYS
        assert body["decision_id"] == fixture["replay_id"]
        assert body["decision_type"] == "TACTICAL"
        assert ts(body["decision_time"]) == fixture["decision_at"]
        assert body["decision_maker"] == str(admin_id)
        assert body["status"] == "EVALUABLE"
        assert body["recommendation_relation"] == "RECOMMENDATION_ACCEPTED"

        # The three parts are separate top-level fields, never merged
        ai = body["ai_recommendation"]
        human = body["human_decision"]
        outcomes = body["outcome_references"]
        assert ai is not None and ai["model"] == "test-model"
        assert human is not None and human["decision"] == "ACCEPTED"
        assert outcomes and outcomes[0]["evidence_id"] == str(
            fixture["out_evidence_id"]
        )
        # Each part carries only its own fields: no human fields inside
        # the AI record, no AI fields inside the human record
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
        assert set(outcomes[0]) == {
            "evidence_id",
            "source_type",
            "source_id",
            "timestamp",
            "description",
            "temporal_relation",
            "provenance",
        }
        # Separate moments, separate values
        assert ts(ai["timestamp"]) != ts(human["timestamp"])

        # Evidence at decision time is governed, classified, traceable
        dt_items = body["decision_time_evidence"]
        assert [e["evidence_id"] for e in dt_items] == [str(fixture["dt_evidence_id"])]
        assert dt_items[0]["temporal_relation"] == "BEFORE_DECISION"
        assert dt_items[0]["governance_status"] == "allowed"
        assert outcomes[0]["temporal_relation"] == "AFTER_DECISION"

        # Factual observations with traceable evidence IDs
        assert "DECISION_TIME_EVIDENCE_PRESENT" in codes(body)
        assert "OUTCOME_EVIDENCE_PRESENT" in codes(body)
        for obs in body["observations"]:
            assert set(obs) == OBSERVATION_KEYS
        assert body["warnings"] == []
        assert body["provenance"]["source"] == "decision_replays"
        assert body["provenance"]["replay_id"] == fixture["replay_id"]

    @pytest.mark.asyncio
    async def test_no_ai_recommendation(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """2: A replay without an AI recommendation stays evaluable and
        reports the absence factually instead of inventing a comparison."""
        admin_id, token = await create_user(
            database, "ev-noai@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, dt_ev = await seed_evidence(
            database, actor, excerpt="NOAI-EXCERPT context", summary="Context"
        )
        await set_evidence_time(database, dt_ev, decision_at - timedelta(minutes=8))
        fixture = await link_replay(client, token, decision_at, evidence_ids=(dt_ev,))

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "EVALUABLE"
        assert body["ai_recommendation"] is None
        assert body["recommendation_relation"] == "NO_RECOMMENDATION_RECORDED"
        assert body["human_decision"]["decision"] == "ACCEPTED"
        assert "DECISION_TIME_EVIDENCE_PRESENT" in codes(body)
        assert "OUTCOME_EVIDENCE_ABSENT" in codes(body)

    @pytest.mark.asyncio
    async def test_human_decision_differs_from_recommendation(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """3: A recorded human rejection of the recommendation is
        reported as a factual relation — never as a verdict on either."""
        admin_id, token = await create_user(
            database, "ev-reject@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, dt_ev = await seed_evidence(
            database, actor, excerpt="REJECT-EXCERPT context", summary="Context"
        )
        await set_evidence_time(database, dt_ev, decision_at - timedelta(minutes=8))
        fixture = await link_replay(
            client,
            token,
            decision_at,
            evidence_ids=(dt_ev,),
            ai_recommendation_text="Switch to a back four",
            ai_model="test-model",
            ai_model_version="1.0",
            ai_recommendation_at=(decision_at - timedelta(minutes=20)).isoformat(),
            human_decision="REJECTED",
        )

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "EVALUABLE"
        assert body["recommendation_relation"] == "RECOMMENDATION_REJECTED"
        assert body["ai_recommendation"]["text"] == "Switch to a back four"
        assert body["human_decision"]["decision"] == "REJECTED"
        # The stored human act is preserved verbatim
        assert body["human_decision"]["rationale"] is None or isinstance(
            body["human_decision"]["rationale"], str
        )


class TestEvaluationStatus:
    """4. insufficient  5. conflicting  10. missing outcome  11. missing evidence"""

    @pytest.mark.asyncio
    async def test_insufficient_evidence(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """4: With no evidence links at all, no evaluation is
        manufactured — status says INSUFFICIENT_EVIDENCE."""
        _, token = await create_user(database, "ev-none@example.com", RoleName.ADMIN)
        fixture = await link_replay(client, token, datetime.now(UTC))

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "INSUFFICIENT_EVIDENCE"
        assert "NO_USABLE_EVIDENCE" in codes(body)
        assert "DECISION_TIME_EVIDENCE_ABSENT" in codes(body)
        assert "OUTCOME_EVIDENCE_ABSENT" in codes(body)
        assert body["decision_time_evidence"] == []
        assert body["outcome_references"] == []
        # The bare decision facts are still present and separated
        assert body["decision_id"] == fixture["id"]
        assert body["human_decision"]["decision"] == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_conflicting_outcome_evidence(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """5: An outcome link whose record time is not after the decision
        is reported as a factual conflict — never resolved by guessing."""
        admin_id, token = await create_user(
            database, "ev-conflict@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="CONFLICT-EXCERPT", summary="Contradiction"
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(minutes=10))
        fixture = await link_replay(client, token, decision_at, outcome_ids=(ev_id,))

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "CONFLICTING_EVIDENCE"
        conflict_obs = [
            o
            for o in body["observations"]
            if o["code"] == "CONFLICTING_OUTCOME_EVIDENCE"
        ]
        assert conflict_obs and conflict_obs[0]["evidence_ids"] == [str(ev_id)]
        # Temporal truth wins: the contradicted item is not shown as an outcome
        assert body["outcome_references"] == []
        assert any("after the decision time" in w for w in body["warnings"])

    @pytest.mark.asyncio
    async def test_missing_outcome_reference(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """10: A dangling outcome reference is reported as missing and
        makes the evaluation partial; nothing is fabricated for it."""
        _, token = await create_user(
            database, "ev-ghost-out@example.com", RoleName.ADMIN
        )
        ghost = uuid4()
        fixture = await link_replay(
            client, token, datetime.now(UTC), outcome_ids=(ghost,)
        )

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "PARTIALLY_EVALUABLE"
        assert "MISSING_LINKED_REFERENCE" in codes(body)
        missing = [
            o for o in body["observations"] if o["code"] == "MISSING_LINKED_REFERENCE"
        ]
        assert missing and [str(ghost)] == missing[0]["evidence_ids"]
        assert body["outcome_references"] == []

    @pytest.mark.asyncio
    async def test_missing_decision_time_evidence_reference(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """11: A dangling decision-time evidence reference is reported as
        missing; status is partial, not a manufactured complete result."""
        _, token = await create_user(
            database, "ev-ghost-dt@example.com", RoleName.ADMIN
        )
        ghost = uuid4()
        fixture = await link_replay(
            client, token, datetime.now(UTC), evidence_ids=(ghost,)
        )

        body = await evaluate(client, token, fixture["id"])

        assert body["status"] == "PARTIALLY_EVALUABLE"
        assert "MISSING_LINKED_REFERENCE" in codes(body)
        assert "DECISION_TIME_EVIDENCE_ABSENT" in codes(body)
        assert body["decision_time_evidence"] == []


class TestEvaluationTemporalIntegrity:
    @pytest.mark.asyncio
    async def test_post_decision_evidence_stays_post_decision(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """6: Before/at/after classification is preserved; post-decision
        evidence is never fed backward into the decision-time set."""
        admin_id, token = await create_user(
            database, "ev-temporal@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, before_ev = await seed_evidence(
            database, actor, excerpt="EV-BEFORE", summary="Known earlier"
        )
        _, at_ev = await seed_evidence(
            database, actor, excerpt="EV-AT", summary="At the decision"
        )
        _, after_ev = await seed_evidence(
            database, actor, excerpt="EV-AFTER", summary="Observed later"
        )
        await set_evidence_time(database, before_ev, decision_at - timedelta(minutes=9))
        await set_evidence_time(database, at_ev, decision_at)
        await set_evidence_time(database, after_ev, decision_at + timedelta(minutes=4))
        fixture = await link_replay(
            client,
            token,
            decision_at,
            evidence_ids=(before_ev, at_ev),
            outcome_ids=(after_ev,),
        )

        body = await evaluate(client, token, fixture["id"])

        dt_ids = [e["evidence_id"] for e in body["decision_time_evidence"]]
        assert set(dt_ids) == {str(before_ev), str(at_ev)}
        for item in body["decision_time_evidence"]:
            assert item["temporal_relation"] in ("BEFORE_DECISION", "AT_DECISION")
        outcome_ids = [r["evidence_id"] for r in body["outcome_references"]]
        assert outcome_ids == [str(after_ev)]
        assert body["outcome_references"][0]["temporal_relation"] == "AFTER_DECISION"
        # The after item is never decision-time context, and before/at
        # items never appear as outcomes.
        assert str(after_ev) not in dt_ids
        assert not ({str(before_ev), str(at_ev)} & set(outcome_ids))


class TestEvaluationGovernance:
    @pytest.mark.asyncio
    async def test_unauthorized_outcome_cannot_influence_evaluation(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """7: Evidence the actor may not retrieve cannot influence any
        observation, is counted as unavailable without disclosing the
        reason, and leaks neither excerpt nor provenance."""
        admin_id, admin_token = await create_user(
            database, "ev-owner@example.com", RoleName.ADMIN
        )
        _, analyst_token = await create_user(
            database, "ev-analyst@example.com", RoleName.ANALYST
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="EVAL-RESTRICTED-EXCERPT welfare note",
            summary="Restricted outcome",
            sensitivity=MemorySensitivity.RESTRICTED,
            provenance="restricted-note:77",
        )
        await set_evidence_time(database, ev_id, decision_at + timedelta(minutes=6))
        fixture = await link_replay(
            client, admin_token, decision_at, outcome_ids=(ev_id,)
        )

        admin_body = await evaluate(client, admin_token, fixture["id"])
        analyst_body = await evaluate(client, analyst_token, fixture["id"])

        # Authorized admin sees the factual outcome
        assert admin_body["status"] == "EVALUABLE"
        assert "OUTCOME_EVIDENCE_PRESENT" in codes(admin_body)
        assert admin_body["outcome_references"][0]["provenance"] == "restricted-note:77"

        # Analyst: outcome cannot influence the evaluation
        assert analyst_body["status"] == "PARTIALLY_EVALUABLE"
        assert analyst_body["outcome_references"] == []
        assert "OUTCOME_EVIDENCE_ABSENT" in codes(analyst_body)
        assert "LINKED_EVIDENCE_UNAVAILABLE" in codes(analyst_body)
        serialized = str(analyst_body)
        assert "EVAL-RESTRICTED-EXCERPT" not in serialized
        assert "restricted-note:77" not in serialized
        assert any("unavailable" in w for w in analyst_body["warnings"])
        # The restriction reason is never disclosed
        assert "restricted" not in str(analyst_body["warnings"]).lower()
        assert "restricted" not in serialized.lower()


class TestEvaluationProvenanceAndDeterminism:
    @pytest.mark.asyncio
    async def test_provenance_preserved(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """8: Evaluation claims trace back to replay, evidence, source,
        and timestamp — no duplicate evidence storage is introduced."""
        admin_id, token = await create_user(
            database, "ev-prov@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, dt_ev = await seed_evidence(
            database,
            actor,
            excerpt="PROV-EXCERPT",
            summary="With provenance",
            provenance="clip-annotation:9x",
        )
        _, out_ev = await seed_evidence(
            database,
            actor,
            excerpt="PROV-OUT-EXCERPT",
            summary="Outcome with provenance",
            provenance="match-log:42",
        )
        await set_evidence_time(database, dt_ev, decision_at - timedelta(minutes=9))
        await set_evidence_time(database, out_ev, decision_at + timedelta(minutes=7))
        fixture = await link_replay(
            client,
            token,
            decision_at,
            evidence_ids=(dt_ev,),
            outcome_ids=(out_ev,),
        )

        body = await evaluate(client, token, fixture["id"])

        assert body["provenance"]["replay_id"] == fixture["id"]
        assert body["provenance"]["source"] == "decision_replays"
        assert body["provenance"]["created_by"]
        dt_item = body["decision_time_evidence"][0]
        assert dt_item["provenance"] == "clip-annotation:9x"
        outcome = body["outcome_references"][0]
        assert outcome["provenance"] == "match-log:42"
        assert outcome["source_type"] and outcome["source_id"]
        assert ts(outcome["timestamp"]) == decision_at + timedelta(minutes=7)
        # Every observation evidence ID resolves to returned evidence
        known = {e["evidence_id"] for e in body["decision_time_evidence"]} | {
            r["evidence_id"] for r in body["outcome_references"]
        }
        for obs in body["observations"]:
            for eid in obs["evidence_ids"]:
                assert str(eid) in known

    @pytest.mark.asyncio
    async def test_deterministic_ordering(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """9: Evidence is ordered timestamp → evidence ID, including a
        stable tie-break for equal timestamps."""
        admin_id, token = await create_user(
            database, "ev-order@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)

        ids: list[UUID] = []
        for offset in (5, 5, 20):  # first two share one timestamp
            _, ev_id = await seed_evidence(
                database,
                actor,
                excerpt=f"ORDER-{uuid4().hex[:6]}",
                summary="Ordering fixture",
            )
            await set_evidence_time(
                database,
                ev_id,
                decision_at + timedelta(minutes=offset) - timedelta(minutes=15),
            )
            ids.append(ev_id)

        fixture = await link_replay(client, token, decision_at, evidence_ids=tuple(ids))

        body = await evaluate(client, token, fixture["id"])

        keys = [
            (ts(e["created_at"]), e["evidence_id"])
            for e in body["decision_time_evidence"]
        ]
        assert keys == sorted(keys)
        assert [k[1] for k in keys[:2]] == sorted(k[1] for k in keys[:2])
        # The +20m record is post-decision, so it is not decision-time context
        assert len(keys) == 2

    @pytest.mark.asyncio
    async def test_repeated_evaluation_equivalent(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """15: Same input produces the same structured evaluation."""
        admin_id, token = await create_user(
            database, "ev-repeat@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        first = await evaluate(client, token, fixture["replay_id"])
        second = await evaluate(client, token, fixture["replay_id"])

        assert first == second


class TestEvaluationIntegrity:
    @pytest.mark.asyncio
    async def test_unknown_confidence_remains_unknown(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """12: No confidence score is fabricated; unknown stays unknown
        and no LLM is used."""
        admin_id, token = await create_user(
            database, "ev-conf@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await evaluate(client, token, fixture["replay_id"])

        metadata = body["metadata"]
        assert set(metadata) == METADATA_KEYS
        assert metadata["confidence"] is None
        assert metadata["llm_used"] is False
        assert metadata["method"] == "deterministic-structured-comparison"
        assert metadata["basis"] == "decision_replay_reconstruction"

    @pytest.mark.asyncio
    async def test_no_causal_or_judgment_language(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """13: The evaluation never emits causal, verdict, or hindsight
        phrasing anywhere in its response."""
        admin_id, token = await create_user(
            database, "ev-lang@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)

        body = await evaluate(client, token, fixture["replay_id"])

        serialized = str(body).lower()
        for word in JUDGMENT_WORDS:
            assert word not in serialized, f"judgment word found: {word}"
        for phrase in CAUSAL_PHRASES:
            assert phrase not in serialized, f"causal phrase found: {phrase}"
        # Observation details are plain factual statements
        for obs in body["observations"]:
            assert obs["detail"]
            assert not obs["detail"].endswith(".")  # no verdict-style phrasing
        assert body["metadata"]["llm_used"] is False

    @pytest.mark.asyncio
    async def test_evaluation_does_not_mutate_stored_record(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """14: Evaluation is read-only — every stored column of the
        decision replay record is byte-identical before and after."""
        admin_id, token = await create_user(
            database, "ev-mutate@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)
        replay_id = fixture["replay_id"]

        before = await read_replay_row(database, replay_id)
        await evaluate(client, token, replay_id)
        await evaluate(client, token, replay_id)
        after = await read_replay_row(database, replay_id)

        assert before == after


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
