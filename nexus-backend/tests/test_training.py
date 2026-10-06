from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.phase04_helpers import bearer, create_domain_context


def session_payload(team_id: str, **changes: object) -> dict[str, object]:
    return {
        "team_id": team_id,
        "session_date": date.today().isoformat(),
        "start_time": "10:00:00",
        "end_time": "11:30:00",
        "session_type": "TECHNICAL",
        "objective": "Passing patterns",
        "planned_intensity": 6,
        "planned_duration_minutes": 90,
        **changes,
    }


@pytest.mark.asyncio
async def test_training_session_crud_and_session_validation(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    headers = bearer(context.coach_token)

    created = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(str(context.team_id)),
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    assert created.json()["created_by"] == str(context.coach_id)

    listing = await client.get(
        f"/api/v1/training/sessions?team_id={context.team_id}", headers=headers
    )
    profile = await client.get(
        f"/api/v1/training/sessions/{session_id}", headers=headers
    )
    updated = await client.patch(
        f"/api/v1/training/sessions/{session_id}",
        headers=headers,
        json={"objective": "Pressing triggers"},
    )
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert profile.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["objective"] == "Pressing triggers"
    assert updated.json()["session_type"] == "TECHNICAL"

    invalid_team = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(str(uuid4())),
    )
    invalid_type = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(str(context.team_id), session_type="GYMNASTICS"),
    )
    invalid_times = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(
            str(context.team_id), start_time="12:00:00", end_time="11:00:00"
        ),
    )
    assert invalid_team.status_code == 404
    assert invalid_type.status_code == 422
    assert invalid_times.status_code == 422

    unauthorized = await client.get(f"/api/v1/training/sessions/{uuid4()}")
    missing = await client.get(f"/api/v1/training/sessions/{uuid4()}", headers=headers)
    assert unauthorized.status_code == 401
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_participation_unique_team_scoped_and_player_history_safe(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    coach_headers = bearer(context.coach_token)
    session = await client.post(
        "/api/v1/training/sessions",
        headers=coach_headers,
        json=session_payload(str(context.team_id)),
    )
    session_id = session.json()["id"]
    participation_path = f"/api/v1/training/sessions/{session_id}/players"
    payload = {
        "player_id": str(context.player_id),
        "attendance_status": "PLANNED",
        "planned_load": 7.5,
        "player_response": "Normal readiness",
        "coach_note": "Focus on first touch",
    }
    added = await client.post(participation_path, headers=coach_headers, json=payload)
    duplicate = await client.post(
        participation_path, headers=coach_headers, json=payload
    )
    assert added.status_code == 201, added.text
    assert duplicate.status_code == 409
    participation = added.json()

    player_history = await client.get(
        f"/api/v1/players/{context.player_id}/training",
        headers=bearer(context.player_token),
    )
    assert player_history.status_code == 200
    assert len(player_history.json()) == 1
    assert "coach_note" not in player_history.text
    assert "Focus on first touch" not in player_history.text
    assert (
        await client.get(
            f"/api/v1/players/{uuid4()}/training", headers=bearer(context.player_token)
        )
    ).status_code == 404

    updated = await client.patch(
        f"/api/v1/training/sessions/{session_id}/players/{context.player_id}",
        headers=coach_headers,
        json={"attendance_status": "PARTIAL", "actual_load": 8.25},
    )
    assert updated.status_code == 200
    assert updated.json()["actual_load"] == 8.25
    assert updated.json()["attendance_status"] == "PARTIAL"
    assert updated.json()["player_id"] == participation["player_id"]

    player_write = await client.patch(
        f"/api/v1/training/sessions/{session_id}/players/{context.player_id}",
        headers=bearer(context.player_token),
        json={"actual_load": 0},
    )
    assert player_write.status_code == 403

    listed = await client.get(participation_path, headers=coach_headers)
    assert listed.status_code == 200 and len(listed.json()) == 1
    blocked_delete = await client.delete(
        f"/api/v1/training/sessions/{session_id}", headers=coach_headers
    )
    assert blocked_delete.status_code == 409

    removed = await client.delete(
        f"/api/v1/training/sessions/{session_id}/players/{context.player_id}",
        headers=coach_headers,
    )
    deleted_session = await client.delete(
        f"/api/v1/training/sessions/{session_id}", headers=coach_headers
    )
    assert removed.status_code == 204
    assert deleted_session.status_code == 204


@pytest.mark.asyncio
async def test_training_requires_membership_on_the_session_date(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    left_at = datetime.now(UTC) - timedelta(days=1)
    context = await create_domain_context(
        database,
        player_email="historical-training-player@example.com",
        membership_left_at=left_at,
    )
    old_date = (date.today() - timedelta(days=2)).isoformat()
    session = await client.post(
        "/api/v1/training/sessions",
        headers=bearer(context.coach_token),
        json=session_payload(str(context.team_id), session_date=old_date),
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    historical = await client.post(
        f"/api/v1/training/sessions/{session_id}/players",
        headers=bearer(context.coach_token),
        json={"player_id": str(context.player_id), "attendance_status": "ATTENDED"},
    )
    assert historical.status_code == 201, historical.text

    invalid_reschedule = await client.patch(
        f"/api/v1/training/sessions/{session_id}",
        headers=bearer(context.coach_token),
        json={"session_date": date.today().isoformat()},
    )
    assert invalid_reschedule.status_code == 409

    new_session = await client.post(
        "/api/v1/training/sessions",
        headers=bearer(context.coach_token),
        json=session_payload(str(context.team_id)),
    )
    not_member = await client.post(
        f"/api/v1/training/sessions/{new_session.json()['id']}/players",
        headers=bearer(context.coach_token),
        json={"player_id": str(context.player_id)},
    )
    invalid_player = await client.post(
        f"/api/v1/training/sessions/{new_session.json()['id']}/players",
        headers=bearer(context.coach_token),
        json={"player_id": str(uuid4())},
    )
    assert not_member.status_code == 409
    assert invalid_player.status_code == 404


@pytest.mark.asyncio
async def test_analyst_reads_training_but_cannot_modify_it(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    _, analyst_token = await create_user(
        database, "phase4-analyst@example.com", RoleName.ANALYST
    )
    session = await client.post(
        "/api/v1/training/sessions",
        headers=bearer(context.coach_token),
        json=session_payload(str(context.team_id)),
    )
    headers = bearer(analyst_token)

    read = await client.get(
        f"/api/v1/training/sessions/{session.json()['id']}", headers=headers
    )
    write = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(str(context.team_id)),
    )
    assert read.status_code == 200
    assert write.status_code == 403


@pytest.mark.asyncio
async def test_sports_scientist_can_update_load_but_not_attendance_or_roster(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    _, scientist_token = await create_user(
        database, "phase4-scientist@example.com", RoleName.SPORTS_SCIENTIST
    )
    headers = bearer(context.coach_token)
    created_session = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(str(context.team_id)),
    )
    session_id = created_session.json()["id"]
    path = f"/api/v1/training/sessions/{session_id}/players/{context.player_id}"
    participation = await client.post(
        f"/api/v1/training/sessions/{session_id}/players",
        headers=headers,
        json={"player_id": str(context.player_id)},
    )
    scientist_headers = bearer(scientist_token)

    load_update = await client.patch(
        path, headers=scientist_headers, json={"actual_load": 8.5}
    )
    attendance_update = await client.patch(
        path, headers=scientist_headers, json={"attendance_status": "ABSENT"}
    )
    create_participation = await client.post(
        f"/api/v1/training/sessions/{session_id}/players",
        headers=scientist_headers,
        json={"player_id": str(context.player_id)},
    )
    delete_participation = await client.delete(path, headers=scientist_headers)

    assert participation.status_code == 201
    assert load_update.status_code == 200
    assert load_update.json()["actual_load"] == 8.5
    assert attendance_update.status_code == 403
    assert create_participation.status_code == 403
    assert delete_participation.status_code == 403


@pytest.mark.asyncio
async def test_team_with_training_history_cannot_be_deleted(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    headers = bearer(context.coach_token)
    unrelated_team = await client.post(
        "/api/v1/teams",
        headers=headers,
        json={
            "name": "Training Only Team",
            "short_name": "TOT",
            "age_group": "Senior",
            "gender_category": "Open",
            "season": "2026/27",
        },
    )
    session = await client.post(
        "/api/v1/training/sessions",
        headers=headers,
        json=session_payload(unrelated_team.json()["id"]),
    )
    _, director_token = await create_user(
        database, "phase4-training-director@example.com", RoleName.DIRECTOR
    )

    delete_team = await client.delete(
        f"/api/v1/teams/{unrelated_team.json()['id']}",
        headers=bearer(director_token),
    )

    assert session.status_code == 201
    assert delete_team.status_code == 409
