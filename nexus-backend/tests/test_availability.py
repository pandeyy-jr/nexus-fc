from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.phase04_helpers import bearer, create_domain_context


def availability_payload(
    start: datetime, end: datetime | None = None, **changes: object
) -> dict[str, object]:
    return {
        "status": "LIMITED",
        "effective_from": start.isoformat(),
        "effective_until": end.isoformat() if end is not None else None,
        "reason_category": "MEDICAL_RESTRICTION",
        "note": "Operational restriction only",
        **changes,
    }


@pytest.mark.asyncio
async def test_availability_history_current_update_and_end(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    headers = bearer(context.coach_token)
    now = datetime.now(UTC)
    start = now - timedelta(hours=1)
    end = now + timedelta(days=1)

    created = await client.post(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
        json=availability_payload(start, end),
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    assert created.json()["recorded_by"] == str(context.coach_id)
    assert "diagnosis" not in created.text.lower()

    current = await client.get(
        f"/api/v1/players/{context.player_id}/availability/current",
        headers=bearer(context.player_token),
    )
    history = await client.get(
        f"/api/v1/players/{context.player_id}/availability",
        headers=bearer(context.player_token),
    )
    assert current.status_code == 200 and current.json()["id"] == record_id
    assert history.status_code == 200 and len(history.json()) == 1

    overlap = await client.post(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
        json=availability_payload(now, now + timedelta(days=2)),
    )
    assert overlap.status_code == 409

    update = await client.patch(
        f"/api/v1/players/{context.player_id}/availability/{record_id}",
        headers=headers,
        json={"status": "AVAILABLE"},
    )
    invalid_merged_range = await client.patch(
        f"/api/v1/players/{context.player_id}/availability/{record_id}",
        headers=headers,
        json={"effective_from": (end + timedelta(days=1)).isoformat()},
    )
    assert update.status_code == 200 and update.json()["status"] == "AVAILABLE"
    assert invalid_merged_range.status_code == 422

    ended = await client.delete(
        f"/api/v1/players/{context.player_id}/availability/{record_id}",
        headers=headers,
    )
    current_after_end = await client.get(
        f"/api/v1/players/{context.player_id}/availability/current",
        headers=headers,
    )
    history_after_end = await client.get(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
    )
    assert ended.status_code == 200 and ended.json()["effective_until"] is not None
    assert current_after_end.status_code == 200 and current_after_end.json() is None
    assert history_after_end.status_code == 200 and len(history_after_end.json()) == 1

    next_period = await client.post(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
        json=availability_payload(
            datetime.now(UTC) + timedelta(seconds=1),
            status="AVAILABLE",
            reason_category="REST",
            note=None,
        ),
    )
    assert next_period.status_code == 201


@pytest.mark.asyncio
async def test_availability_rejects_bad_periods_and_duplicate_end(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    headers = bearer(context.coach_token)
    now = datetime.now(UTC)
    invalid = await client.post(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
        json=availability_payload(now + timedelta(days=1), now),
    )
    assert invalid.status_code == 422

    created = await client.post(
        f"/api/v1/players/{context.player_id}/availability",
        headers=headers,
        json=availability_payload(now - timedelta(days=1)),
    )
    assert created.status_code == 201
    record_id = created.json()["id"]
    end_path = f"/api/v1/players/{context.player_id}/availability/{record_id}"
    assert (await client.delete(end_path, headers=headers)).status_code == 200
    assert (await client.delete(end_path, headers=headers)).status_code == 409


@pytest.mark.asyncio
async def test_availability_access_is_scoped_and_medical_staff_is_not_overprivileged(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    _, medical_token = await create_user(
        database, "phase4-medical@example.com", RoleName.MEDICAL_STAFF
    )
    _, analyst_token = await create_user(
        database, "phase4-analyst@example.com", RoleName.ANALYST
    )
    path = f"/api/v1/players/{context.player_id}/availability"
    body = availability_payload(datetime.now(UTC))

    no_auth = await client.get(path)
    analyst_read = await client.get(path, headers=bearer(analyst_token))
    player_read = await client.get(path, headers=bearer(context.player_token))
    player_write = await client.post(
        path, headers=bearer(context.player_token), json=body
    )
    medical_write = await client.post(path, headers=bearer(medical_token), json=body)
    other_player = await client.get(
        f"/api/v1/players/{uuid4()}/availability",
        headers=bearer(context.player_token),
    )

    assert no_auth.status_code == 401
    assert analyst_read.status_code == 403
    assert player_read.status_code == 200 and player_read.json() == []
    assert player_write.status_code == 403
    assert medical_write.status_code == 201
    assert other_player.status_code == 404

    medical_training = await client.get(
        "/api/v1/training/sessions", headers=bearer(medical_token)
    )
    medical_development = await client.get(
        f"/api/v1/players/{context.player_id}/development/goals",
        headers=bearer(medical_token),
    )
    assert medical_training.status_code == 403
    assert medical_development.status_code == 403


@pytest.mark.asyncio
async def test_player_with_availability_history_cannot_be_deleted(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    _, director_token = await create_user(
        database, "phase4-availability-director@example.com", RoleName.DIRECTOR
    )
    player_response = await client.post(
        "/api/v1/players",
        headers=bearer(context.coach_token),
        json={
            "first_name": "Unassigned",
            "last_name": "Player",
            "date_of_birth": "2000-01-01",
            "preferred_position": "CM",
        },
    )
    player_id = player_response.json()["id"]
    availability = await client.post(
        f"/api/v1/players/{player_id}/availability",
        headers=bearer(context.coach_token),
        json=availability_payload(datetime.now(UTC)),
    )
    deleted = await client.delete(
        f"/api/v1/players/{player_id}", headers=bearer(director_token)
    )

    assert player_response.status_code == 201
    assert availability.status_code == 201
    assert deleted.status_code == 409
