"""Phase 10E — decision replay finalization and integrity tests.

Covers: read-only API contract (no mutation methods), cross-table
immutability of replay/evidence/decision records under every replay
request, decision-time snapshot boundaries (immediately before / exact /
immediately after), edge cases (no evidence, no AI, no human decision,
no outcomes, identical outcome timestamps, malformed stored lists,
missing references, inaccessible evidence), error safety (controlled
404/422/401 bodies without internals), and deterministic repeated
requests across all replay endpoints.

Deterministic fixtures only: no network, no LLM, no Qdrant.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.memory import MemorySensitivity
from app.core.roles import RoleName
from app.db.models.memory import (
    DecisionRecord,
    EvidenceReference,
)
from app.db.models.memory import (
    DecisionReplay as DecisionReplayRecord,
)
from app.main import app
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_replay_evaluation import evaluate, read_replay_row
from tests.test_replay_outcome_linking import link_replay
from tests.test_replay_reconstruction import (
    bearer,
    build_full_replay,
    create_replay,
    load_actor,
    reconstruct,
    seed_evidence,
    set_evidence_time,
    ts,
)

BASE = "/api/v1/memory/decisions/replay"
DECISIONS = "/api/v1/memory/decisions"

# Substrings that must never appear in error bodies.
ERROR_LEAK_MARKERS = (
    "traceback",
    "sqlalchemy",
    "select ",
    "insert into",
    "update ",
    "password",
    "secret",
    "exception",
    "site-packages",
)


async def get_view(client: AsyncClient, token: str, replay_id: str) -> dict:
    response = await client.get(f"{BASE}/{replay_id}", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def get_list(client: AsyncClient, token: str) -> list:
    response = await client.get(BASE, headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def read_evidence_rows(
    database: DatabaseFixture, evidence_ids: list[UUID]
) -> dict[str, dict]:
    async with database.sessions() as session:
        rows: dict[str, dict] = {}
        for ev_id in evidence_ids:
            row = await session.get(EvidenceReference, ev_id)
            assert row is not None
            rows[str(ev_id)] = {
                column.name: getattr(row, column.name)
                for column in EvidenceReference.__table__.columns
            }
        return rows


async def read_decision_row(database: DatabaseFixture, decision_id: str) -> dict:
    async with database.sessions() as session:
        row = await session.get(DecisionRecord, UUID(decision_id))
        assert row is not None
        return {
            column.name: getattr(row, column.name)
            for column in DecisionRecord.__table__.columns
        }


def assert_no_leaks(response_text: str) -> None:
    lowered = response_text.lower()
    for marker in ERROR_LEAK_MARKERS:
        assert marker not in lowered, f"error body leaked '{marker}'"


class TestReadonlyContract:
    @pytest.mark.asyncio
    async def test_openapi_exposes_no_mutation_methods_on_replay(self):
        """The replay surface is read-only plus one append-only creation
        POST; no PATCH/PUT/DELETE exists anywhere under replay routes."""
        paths = app.openapi()["paths"]
        replay_paths = {
            path: methods
            for path, methods in paths.items()
            if "/decisions/replay" in path
        }
        assert replay_paths, "replay routes not found in OpenAPI"
        collection = f"{BASE}"
        for path, methods in replay_paths.items():
            allowed = {"get"} if path != collection else {"get", "post"}
            assert set(methods) == allowed, f"{path} exposes {set(methods)}"
        # The four read routes each exist and are GET-only
        assert "get" in replay_paths[f"{BASE}/{{replay_id}}"]
        assert "get" in replay_paths[f"{BASE}/{{replay_id}}/reconstruction"]
        assert "get" in replay_paths[f"{BASE}/{{replay_id}}/evaluation"]
        # IDs and timestamps are consistently typed across contracts
        schemas = app.openapi()["components"]["schemas"]
        eval_props = schemas["DecisionReplayEvaluation"]["properties"]
        assert eval_props["decision_id"]["format"] == "uuid"
        assert eval_props["decision_time"]["format"] == "date-time"
        assert eval_props["decision_maker"]["anyOf"][0]["format"] == "uuid"
        view_props = schemas["DecisionReplayView"]["properties"]
        assert view_props["id"]["format"] == "uuid"
        assert view_props["decision_at"]["format"] == "date-time"
        # Every replay schema is response-only/read-safe: no mutation verb
        # appears in any replay path definition
        for path in replay_paths:
            assert "delete" not in path and "update" not in path

    @pytest.mark.asyncio
    async def test_all_replay_requests_leave_records_untouched(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Every replay request (both roles, all read endpoints) leaves
        the replay row, its evidence rows, and a DecisionRecord row
        byte-identical — no mutation of history is possible."""
        admin_id, admin_token = await create_user(
            database, "ev10e-mut-admin@example.com", RoleName.ADMIN
        )
        _, analyst_token = await create_user(
            database, "ev10e-mut-analyst@example.com", RoleName.ANALYST
        )
        fixture = await build_full_replay(client, database, admin_id, admin_token)

        # An unrelated DecisionRecord also must never be touched
        decision_resp = await client.post(
            DECISIONS,
            json={
                "decision_type": "TACTICAL",
                "summary": "10E immutability sentinel decision",
                "rationale": "Recorded to prove replay never mutates it",
                "decision_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            },
            headers=bearer(admin_token),
        )
        assert decision_resp.status_code == 201, decision_resp.text
        decision_id = decision_resp.json()["id"]

        replay_id = fixture["replay_id"]
        evidence_ids = [fixture["dt_evidence_id"], fixture["out_evidence_id"]]

        replay_before = await read_replay_row(database, replay_id)
        evidence_before = await read_evidence_rows(database, evidence_ids)
        decision_before = await read_decision_row(database, decision_id)

        # Exercise every replay read endpoint as two different roles
        for token in (admin_token, analyst_token):
            await get_list(client, token)
            await get_view(client, token, replay_id)
            await reconstruct(client, token, replay_id)
            await evaluate(client, token, replay_id)
        # And the governed DecisionRecord read path
        decision_read = await client.get(
            f"{DECISIONS}/{decision_id}", headers=bearer(admin_token)
        )
        assert decision_read.status_code == 200

        assert await read_replay_row(database, replay_id) == replay_before
        assert await read_evidence_rows(database, evidence_ids) == evidence_before
        assert await read_decision_row(database, decision_id) == decision_before


class TestSnapshotBoundaries:
    """Decision-time snapshot integrity at exact temporal boundaries."""

    @pytest.mark.asyncio
    async def test_evidence_immediately_before_decision(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Evidence recorded one second before the decision is
        BEFORE_DECISION and part of the decision-time context."""
        admin_id, token = await create_user(
            database, "ev10e-before@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="BOUNDARY-BEFORE", summary="One second before"
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(seconds=1))
        fixture = await link_replay(client, token, decision_at, evidence_ids=(ev_id,))

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        item = next(i for i in recon["evidence"] if i["evidence_id"] == str(ev_id))
        assert item["temporal_relation"] == "BEFORE_DECISION"
        assert item["is_decision_time_evidence"] is True
        assert str(ev_id) in [e["evidence_id"] for e in body["decision_time_evidence"]]
        assert any(
            i["evidence_id"] == str(ev_id) and i["phase"] == "EVIDENCE"
            for i in recon["timeline"]
        )

    @pytest.mark.asyncio
    async def test_evidence_at_exact_decision_timestamp(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Evidence recorded at exactly the decision instant classifies
        AT_DECISION and remains part of the decision-time context."""
        admin_id, token = await create_user(
            database, "ev10e-at@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="BOUNDARY-AT", summary="Exactly at decision"
        )
        await set_evidence_time(database, ev_id, decision_at)
        fixture = await link_replay(client, token, decision_at, evidence_ids=(ev_id,))

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        item = next(i for i in recon["evidence"] if i["evidence_id"] == str(ev_id))
        assert item["temporal_relation"] == "AT_DECISION"
        assert item["is_decision_time_evidence"] is True
        dt_ids = [e["evidence_id"] for e in body["decision_time_evidence"]]
        assert str(ev_id) in dt_ids

    @pytest.mark.asyncio
    async def test_evidence_immediately_after_decision(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Even one second after the decision, evidence is AFTER_DECISION
        and can never appear as decision-time context — even when the
        stored record wrongly claims it was known at decision time."""
        admin_id, token = await create_user(
            database, "ev10e-after@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="BOUNDARY-AFTER", summary="One second after"
        )
        await set_evidence_time(database, ev_id, decision_at + timedelta(seconds=1))
        fixture = await link_replay(client, token, decision_at, evidence_ids=(ev_id,))

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        item = next(i for i in recon["evidence"] if i["evidence_id"] == str(ev_id))
        assert item["temporal_relation"] == "AFTER_DECISION"
        assert item["is_decision_time_evidence"] is False
        dt_ids = [e["evidence_id"] for e in body["decision_time_evidence"]]
        assert str(ev_id) not in dt_ids
        # It is neither decision-time context nor a linked outcome,
        # so it must not appear in the timeline at all.
        assert not [i for i in recon["timeline"] if i["evidence_id"] == str(ev_id)]
        assert any(
            "referenced as decision-time evidence" in w for w in recon["warnings"]
        )


class TestReplayEdgeCases:
    @pytest.mark.asyncio
    async def test_decision_with_no_evidence(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """A replay with no evidence returns safe empties everywhere —
        no fabricated items, no warnings, no error."""
        _, token = await create_user(database, "ev10e-noev@example.com", RoleName.ADMIN)
        fixture = await link_replay(client, token, datetime.now(UTC))

        recon = await reconstruct(client, token, fixture["id"])
        view = await get_view(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert recon["evidence"] == []
        assert recon["outcome_references"] == []
        assert recon["warnings"] == []
        phases = {item["phase"] for item in recon["timeline"]}
        assert "EVIDENCE" not in phases and "OUTCOME" not in phases
        assert view["evidence_ids"] is None
        assert body["decision_time_evidence"] == []
        assert body["status"] == "INSUFFICIENT_EVIDENCE"

    @pytest.mark.asyncio
    async def test_decision_with_no_ai_recommendation(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Absence of an AI recommendation is represented as None
        consistently across reconstruction and evaluation."""
        admin_id, token = await create_user(
            database, "ev10e-noai@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="NOAI-10E", summary="Context without AI"
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(minutes=4))
        fixture = await link_replay(client, token, decision_at, evidence_ids=(ev_id,))

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert recon["ai_recommendation"] is None
        assert body["ai_recommendation"] is None
        assert body["recommendation_relation"] == "NO_RECOMMENDATION_RECORDED"
        phases = {item["phase"] for item in recon["timeline"]}
        assert "AI_RECOMMENDATION" not in phases

    @pytest.mark.asyncio
    async def test_decision_with_no_human_decision_data(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """When no human decision data is recorded (allowed by the
        contract), the human field stays None, no human timeline event is
        invented, and the evaluation reports the absence factually."""
        admin_id, token = await create_user(
            database, "ev10e-nohuman@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="NOHUMAN-10E", summary="Context only"
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(minutes=4))
        fixture = await create_replay(
            client,
            token,
            decision_at=decision_at.isoformat(),
            ai_recommendation_text="Hold the current shape",
            ai_model="test-model",
            ai_recommendation_at=(decision_at - timedelta(minutes=20)).isoformat(),
            evidence_ids=[str(ev_id)],
        )

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert recon["human_decision"] is None
        assert body["human_decision"] is None
        phases = {item["phase"] for item in recon["timeline"]}
        assert "HUMAN_DECISION" not in phases
        # AI recommendation still present as its own separate field
        assert recon["ai_recommendation"] is not None
        assert body["ai_recommendation"] is not None
        assert body["recommendation_relation"] == "NO_HUMAN_DECISION_RECORDED"
        assert body["status"] == "PARTIALLY_EVALUABLE"

    @pytest.mark.asyncio
    async def test_decision_with_no_outcomes(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Decision-time evidence without outcomes yields empty outcome
        sets, not invented ones."""
        admin_id, token = await create_user(
            database, "ev10e-noout@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database, actor, excerpt="NOOUT-10E", summary="Decision-time only"
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(minutes=4))
        fixture = await link_replay(client, token, decision_at, evidence_ids=(ev_id,))

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert recon["outcome_references"] == []
        assert body["outcome_references"] == []
        assert "OUTCOME_EVIDENCE_ABSENT" in [o["code"] for o in body["observations"]]
        assert body["status"] == "EVALUABLE"
        phases = {item["phase"] for item in recon["timeline"]}
        assert "OUTCOME" not in phases

    @pytest.mark.asyncio
    async def test_multiple_outcomes_at_identical_timestamps(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Outcome ties fall back to evidence-ID ordering everywhere, and
        repeated reconstruction is deep-equal."""
        admin_id, token = await create_user(
            database, "ev10e-tie@example.com", RoleName.ADMIN
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        ids: list[UUID] = []
        for _ in range(3):
            _, ev_id = await seed_evidence(
                database,
                actor,
                excerpt=f"TIE-{uuid4().hex[:6]}",
                summary="Identical outcome timestamp",
            )
            ids.append(ev_id)
        tied_at = decision_at + timedelta(minutes=5)
        for ev_id in ids:
            await set_evidence_time(database, ev_id, tied_at)
        fixture = await link_replay(client, token, decision_at, outcome_ids=tuple(ids))

        first = await reconstruct(client, token, fixture["id"])
        second = await reconstruct(client, token, fixture["id"])

        assert first == second
        ref_ids = [r["evidence_id"] for r in first["outcome_references"]]
        assert ref_ids == sorted(str(i) for i in ids)
        timeline_outcomes = [
            i["evidence_id"] for i in first["timeline"] if i["phase"] == "OUTCOME"
        ]
        assert timeline_outcomes == sorted(timeline_outcomes)
        stamps = [ts(i["timestamp"]) for i in first["timeline"]]
        assert stamps == sorted(stamps)

    @pytest.mark.asyncio
    async def test_malformed_stored_evidence_lists(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Corrupt stored reference JSON degrades to controlled warnings
        and safe empties across every read endpoint — never a 500."""
        _, token = await create_user(
            database, "ev10e-corrupt@example.com", RoleName.ADMIN
        )
        fixture = await link_replay(client, token, datetime.now(UTC))
        async with database.sessions() as session:
            await session.execute(
                update(DecisionReplayRecord)
                .where(DecisionReplayRecord.id == UUID(fixture["id"]))
                .values(
                    evidence_ids="not-valid-json",
                    outcome_evidence_ids="also-not-valid",
                )
            )
            await session.commit()

        view = await get_view(client, token, fixture["id"])
        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert view["evidence_ids"] is None
        assert view["outcome_evidence_ids"] is None
        assert any("evidence references" in w for w in recon["warnings"])
        assert any("outcome evidence references" in w for w in recon["warnings"])
        assert recon["evidence"] == []
        assert body["status"] == "INSUFFICIENT_EVIDENCE"
        assert any("could not be parsed" in w for w in body["warnings"])

    @pytest.mark.asyncio
    async def test_missing_source_reference_is_controlled(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """A dangling reference warns identically at reconstruction and
        evaluation level; nothing is fabricated and nothing crashes."""
        _, token = await create_user(
            database, "ev10e-ghost@example.com", RoleName.ADMIN
        )
        ghost = uuid4()
        fixture = await link_replay(
            client, token, datetime.now(UTC), evidence_ids=(ghost,)
        )

        recon = await reconstruct(client, token, fixture["id"])
        body = await evaluate(client, token, fixture["id"])

        assert any(
            f"Evidence reference {ghost} not found" in w for w in recon["warnings"]
        )
        assert recon["evidence"] == []
        assert body["status"] == "PARTIALLY_EVALUABLE"
        missing = [
            o for o in body["observations"] if o["code"] == "MISSING_LINKED_REFERENCE"
        ]
        assert missing and missing[0]["evidence_ids"] == [str(ghost)]

    @pytest.mark.asyncio
    async def test_inaccessible_evidence_returns_no_content(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Restricted evidence keeps the replay readable for other
        actors while exposing no excerpt or provenance anywhere in the
        raw response text."""
        admin_id, admin_token = await create_user(
            database, "ev10e-restr-admin@example.com", RoleName.ADMIN
        )
        _, analyst_token = await create_user(
            database, "ev10e-restr-analyst@example.com", RoleName.ANALYST
        )
        actor = await load_actor(database, admin_id)
        decision_at = datetime.now(UTC) - timedelta(hours=1)
        _, ev_id = await seed_evidence(
            database,
            actor,
            excerpt="10E-RESTRICTED-EXCERPT hidden",
            summary="Hidden summary",
            sensitivity=MemorySensitivity.RESTRICTED,
            provenance="hidden-origin:5",
        )
        await set_evidence_time(database, ev_id, decision_at - timedelta(minutes=4))
        fixture = await link_replay(
            client, admin_token, decision_at, evidence_ids=(ev_id,)
        )

        # Raw response text must not contain restricted content
        response = await client.get(
            f"{BASE}/{fixture['id']}/reconstruction",
            headers=bearer(analyst_token),
        )
        assert response.status_code == 200
        lowered = response.text.lower()
        assert "10e-restricted-excerpt" not in lowered
        assert "hidden-origin" not in lowered
        assert "hidden summary" not in lowered

        recon = await reconstruct(client, analyst_token, fixture["id"])
        body = await evaluate(client, analyst_token, fixture["id"])
        assert recon["evidence"][0]["excerpt"] is None
        assert recon["evidence"][0]["provenance"] is None
        assert recon["evidence"][0]["governance_status"] == "inaccessible"
        assert any("unavailable" in w for w in recon["warnings"])
        assert body["decision_time_evidence"] == []


class TestErrorSafety:
    @pytest.mark.asyncio
    async def test_unknown_replay_returns_controlled_404(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Unknown replay IDs return a controlled 404 with a fixed detail
        and no internals on every read route."""
        _, token = await create_user(database, "ev10e-404@example.com", RoleName.ADMIN)
        missing = str(uuid4())
        for suffix in ("", "/reconstruction", "/evaluation"):
            response = await client.get(
                f"{BASE}/{missing}{suffix}", headers=bearer(token)
            )
            assert response.status_code == 404, response.text
            payload = response.json()
            assert set(payload) == {"detail"}
            assert payload["detail"] == "Decision replay not found"
            assert_no_leaks(response.text)

    @pytest.mark.asyncio
    async def test_malformed_replay_id_returns_validation_error(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Malformed UUID path segments are rejected by typed validation
        without exposing internals."""
        _, token = await create_user(database, "ev10e-422@example.com", RoleName.ADMIN)
        response = await client.get(
            f"{BASE}/not-a-uuid/reconstruction", headers=bearer(token)
        )
        assert response.status_code == 422, response.text
        assert_no_leaks(response.text)

    @pytest.mark.asyncio
    async def test_replay_endpoints_require_authentication(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Every replay route — read and create — rejects missing
        credentials with the project-standard 401."""
        _, token = await create_user(database, "ev10e-401@example.com", RoleName.ADMIN)
        fixture = await link_replay(client, token, datetime.now(UTC))
        replay_id = fixture["id"]
        cases = [
            ("GET", BASE, None),
            ("GET", f"{BASE}/{replay_id}", None),
            ("GET", f"{BASE}/{replay_id}/reconstruction", None),
            ("GET", f"{BASE}/{replay_id}/evaluation", None),
            (
                "POST",
                BASE,
                {
                    "decision_type": "TACTICAL",
                    "decision_at": datetime.now(UTC).isoformat(),
                },
            ),
        ]
        for method, path, json_body in cases:
            request = getattr(client, method.lower())
            kwargs = {"json": json_body} if json_body is not None else {}
            response = await request(path, **kwargs)
            assert response.status_code == 401, f"{method} {path}: {response.text}"
            payload = response.json()
            assert payload["detail"] == "Invalid or missing access token"
            assert_no_leaks(response.text)


class TestDeterministicReplay:
    @pytest.mark.asyncio
    async def test_repeated_replay_requests_equivalent(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """Every replay endpoint returns deep-equal results on repeated
        requests with identical underlying data."""
        admin_id, token = await create_user(
            database, "ev10e-repeat@example.com", RoleName.ADMIN
        )
        fixture = await build_full_replay(client, database, admin_id, token)
        replay_id = fixture["replay_id"]

        assert await get_list(client, token) == await get_list(client, token)
        assert await get_view(client, token, replay_id) == await get_view(
            client, token, replay_id
        )
        assert await reconstruct(client, token, replay_id) == await reconstruct(
            client, token, replay_id
        )
        assert await evaluate(client, token, replay_id) == await evaluate(
            client, token, replay_id
        )

    @pytest.mark.asyncio
    async def test_replay_list_ordering_is_stable(
        self, client: AsyncClient, database: DatabaseFixture
    ):
        """The list endpoint orders decision_at descending with an
        explicit id tie-break, identically across repeated requests."""
        _, token = await create_user(database, "ev10e-list@example.com", RoleName.ADMIN)
        shared = datetime.now(UTC) - timedelta(hours=1)
        earlier = shared - timedelta(minutes=30)
        await create_replay(
            client, token, decision_at=shared.isoformat(), human_decision="ACCEPTED"
        )
        await create_replay(
            client, token, decision_at=shared.isoformat(), human_decision="REJECTED"
        )
        await create_replay(
            client, token, decision_at=earlier.isoformat(), human_decision="MODIFIED"
        )

        first = await get_list(client, token)
        second = await get_list(client, token)

        assert first == second
        assert len(first) == 3
        stamps = [ts(item["decision_at"]) for item in first]
        assert stamps == sorted(stamps, reverse=True)
        # Equal timestamps fall back to ascending id order
        tied = [item for item in first if ts(item["decision_at"]) == shared]
        assert len(tied) == 2
        assert [item["id"] for item in tied] == sorted(item["id"] for item in tied)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
