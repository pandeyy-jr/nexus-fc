"""Phase 08D memory API tests: auth, governance choke points, safety.
No RAG, no vectors — REST boundary only."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def memory_body(
    overlay: dict[str, object] | None = None, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "memory": {
            "memory_type": "MATCH",
            "title": "Derby decided late",
            "summary": "Two goals in the final ten minutes.",
            "occurred_at": "2026-09-01T15:00:00Z",
            "source_type": "HUMAN_RECORDED",
            "source_id": "note-api-1",
            "confidence": 0.8,
        },
        "evidence": [
            {
                "source_type": "HUMAN_RECORDED",
                "source_id": "note-api-1",
                "evidence_type": "TEXT_EXCERPT",
                "excerpt": "Right flank overload.",
            }
        ],
    }
    body.update(overrides)
    if overlay:
        body.update(overlay)
    return body


@pytest.mark.asyncio
async def test_authenticated_creation_and_governed_retrieval(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, token = await create_user(database, "api-admin@example.com", RoleName.ADMIN)
    created = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(token)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] != "note-api-1"
    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["source_id"] == "note-api-1"
    assert "hashed_password" not in str(body)

    fetched = await client.get(f"/api/v1/memory/{body['id']}", headers=bearer(token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    listed = await client.get("/api/v1/memory", headers=bearer(token))
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json())


@pytest.mark.asyncio
async def test_unauthenticated_access_denied(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    assert (await client.post("/api/v1/memory", json=memory_body())).status_code == 401
    assert (await client.get("/api/v1/memory")).status_code == 401
    assert (await client.get(f"/api/v1/memory/{uuid4()}")).status_code == 401


@pytest.mark.asyncio
async def test_role_based_write_denial(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, player_token = await create_user(
        database, "api-player@example.com", RoleName.PLAYER
    )
    denied = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(player_token)
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_restricted_memory_and_player_isolation(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(
        database, "api-admin-2@example.com", RoleName.ADMIN
    )
    _, player_token = await create_user(
        database, "api-player-2@example.com", RoleName.PLAYER
    )
    restricted = await client.post(
        "/api/v1/memory",
        json=memory_body(
            {
                "memory": {
                    **memory_body()["memory"],  # type: ignore[index]
                    "source_id": "note-restricted",
                    "sensitivity": "RESTRICTED",
                }
            }
        ),
        headers=bearer(admin_token),
    )
    assert restricted.status_code == 201, restricted.text
    memory_id = restricted.json()["id"]

    assert (
        await client.get(f"/api/v1/memory/{memory_id}", headers=bearer(player_token))
    ).status_code == 403
    listed = await client.get("/api/v1/memory", headers=bearer(player_token))
    assert listed.status_code == 200
    assert all(item["id"] != memory_id for item in listed.json())


@pytest.mark.asyncio
async def test_redacted_and_expired_denial(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(
        database, "api-admin-3@example.com", RoleName.ADMIN
    )
    created = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(admin_token)
    )
    memory_id = created.json()["id"]
    redacted = await client.post(
        f"/api/v1/memory/{memory_id}/redact", headers=bearer(admin_token)
    )
    assert redacted.status_code == 200
    assert redacted.json()["redaction_status"] == "REDACTED"
    assert (
        await client.get(f"/api/v1/memory/{memory_id}", headers=bearer(admin_token))
    ).status_code == 403

    again = await client.post(
        f"/api/v1/memory/{memory_id}/redact", headers=bearer(admin_token)
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_redact_requires_elevated_role(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(
        database, "api-admin-4@example.com", RoleName.ADMIN
    )
    _, coach_token = await create_user(
        database, "api-coach@example.com", RoleName.HEAD_COACH
    )
    created = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(admin_token)
    )
    memory_id = created.json()["id"]
    assert (
        await client.post(
            f"/api/v1/memory/{memory_id}/redact", headers=bearer(coach_token)
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_evidence_creation_and_provenance(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(
        database, "api-admin-5@example.com", RoleName.ADMIN
    )
    created = await client.post(
        "/api/v1/memory",
        json=memory_body({"evidence": []}),
        headers=bearer(admin_token),
    )
    memory_id = created.json()["id"]
    added = await client.post(
        f"/api/v1/memory/{memory_id}/evidence",
        json={
            "source_type": "VISION",
            "source_id": "track-9",
            "evidence_type": "FRAME_REFERENCE",
            "frame_number": 45,
            "provenance": "yolo11n/06D",
        },
        headers=bearer(admin_token),
    )
    assert added.status_code == 201, added.text
    assert added.json()["source_id"] == "track-9"
    assert added.json()["memory_record_id"] == memory_id
    missing = await client.post(
        f"/api/v1/memory/{uuid4()}/evidence",
        json={
            "source_type": "VISION",
            "source_id": "track-9",
            "evidence_type": "FRAME_REFERENCE",
        },
        headers=bearer(admin_token),
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_decision_lifecycle_and_maker_validation(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    admin_id, admin_token = await create_user(
        database, "api-admin-6@example.com", RoleName.ADMIN
    )
    coach_id, _ = await create_user(
        database, "api-coach-2@example.com", RoleName.HEAD_COACH
    )
    created = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(admin_token)
    )
    memory_id = created.json()["id"]
    decision = await client.post(
        "/api/v1/memory/decisions",
        json={
            "decision_type": "TACTICAL",
            "summary": "Hold a higher line.",
            "rationale": "Offside trap worked.",
            "decision_at": "2026-09-01T16:00:00Z",
            "decision_maker": str(coach_id),
            "status": "ACCEPTED",
            "related_memory_id": memory_id,
        },
        headers=bearer(admin_token),
    )
    assert decision.status_code == 201, decision.text
    assert decision.json()["decision_maker"] == str(coach_id)
    assert decision.json()["created_by"] == str(admin_id)

    fetched = await client.get(
        f"/api/v1/memory/decisions/{decision.json()['id']}",
        headers=bearer(admin_token),
    )
    assert fetched.status_code == 200
    listed = await client.get("/api/v1/memory/decisions", headers=bearer(admin_token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    ghost = await client.post(
        "/api/v1/memory/decisions",
        json={
            "decision_type": "TACTICAL",
            "summary": "Ghost decision.",
            "rationale": "No such user.",
            "decision_at": "2026-09-01T16:00:00Z",
            "decision_maker": str(uuid4()),
        },
        headers=bearer(admin_token),
    )
    assert ghost.status_code == 404


@pytest.mark.asyncio
async def test_invalid_payload_and_pagination(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    _, admin_token = await create_user(
        database, "api-admin-7@example.com", RoleName.ADMIN
    )
    bad_confidence = memory_body()
    bad_confidence["memory"] = {**bad_confidence["memory"], "confidence": 9.0}  # type: ignore[index]
    assert (
        await client.post(
            "/api/v1/memory", json=bad_confidence, headers=bearer(admin_token)
        )
    ).status_code == 422
    unknown_field = memory_body()
    unknown_field["memory"] = {**unknown_field["memory"], "created_by": str(uuid4())}  # type: ignore[index]
    assert (
        await client.post(
            "/api/v1/memory", json=unknown_field, headers=bearer(admin_token)
        )
    ).status_code == 422
    assert (
        await client.get("/api/v1/memory?limit=101", headers=bearer(admin_token))
    ).status_code == 422
    assert (
        await client.get(f"/api/v1/memory/{uuid4()}", headers=bearer(admin_token))
    ).status_code == 404


@pytest.mark.asyncio
async def test_no_orm_leakage(client: AsyncClient, database: DatabaseFixture) -> None:
    _, admin_token = await create_user(
        database, "api-admin-8@example.com", RoleName.ADMIN
    )
    created = await client.post(
        "/api/v1/memory", json=memory_body(), headers=bearer(admin_token)
    )
    text = created.text
    for leaked in ("_sa_instance_state", "hashed_password", "SELECT ", "Traceback"):
        assert leaked not in text
