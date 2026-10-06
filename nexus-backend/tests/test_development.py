from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.roles import RoleName
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.phase04_helpers import bearer, create_domain_context


def goal_payload(**changes: object) -> dict[str, object]:
    return {
        "title": "Improve scanning before receiving",
        "description": "Documented technical development focus",
        "category": "TECHNICAL",
        "target_date": (date.today() + timedelta(days=30)).isoformat(),
        "priority": "HIGH",
        **changes,
    }


def assessment_payload(**changes: object) -> dict[str, object]:
    return {
        "progress_status": "IN_PROGRESS",
        "assessment_note": "Coach documented progress during review",
        "next_action": "Review again next month",
        **changes,
    }


@pytest.mark.asyncio
async def test_goals_assessments_keep_human_attribution_and_history(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    coach_headers = bearer(context.coach_token)
    goal_path = f"/api/v1/players/{context.player_id}/development/goals"
    assessment_path = f"/api/v1/players/{context.player_id}/development/assessments"

    created = await client.post(
        goal_path,
        headers=coach_headers,
        json=goal_payload(team_id=str(context.team_id)),
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]
    assert created.json()["created_by"] == str(context.coach_id)

    updated = await client.patch(
        f"{goal_path}/{goal_id}",
        headers=coach_headers,
        json={"status": "IN_PROGRESS"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == goal_payload()["title"]
    assert updated.json()["status"] == "IN_PROGRESS"

    spoofed = await client.post(
        assessment_path,
        headers=coach_headers,
        json={
            **assessment_payload(goal_id=goal_id),
            "assessor_id": str(context.player_user_id),
        },
    )
    first_assessment = await client.post(
        assessment_path,
        headers=coach_headers,
        json=assessment_payload(goal_id=goal_id),
    )
    second_assessment = await client.post(
        assessment_path,
        headers=coach_headers,
        json=assessment_payload(
            goal_id=goal_id,
            assessment_date=(date.today() - timedelta(days=1)).isoformat(),
            progress_status="COMPLETED",
        ),
    )
    assert spoofed.status_code == 422
    assert first_assessment.status_code == 201, first_assessment.text
    assert first_assessment.json()["assessor_id"] == str(context.coach_id)
    assert second_assessment.status_code == 201
    first_id = first_assessment.json()["id"]

    patch_assessment = await client.patch(
        f"{assessment_path}/{first_id}",
        headers=coach_headers,
        json={"assessment_note": "Updated human note"},
    )
    assessment_history = await client.get(assessment_path, headers=coach_headers)
    assert patch_assessment.status_code == 200
    assert patch_assessment.json()["assessment_note"] == "Updated human note"
    assert len(assessment_history.json()) == 2

    cancelled = await client.delete(f"{goal_path}/{goal_id}", headers=coach_headers)
    goal_after_cancel = await client.get(
        f"{goal_path}/{goal_id}", headers=coach_headers
    )
    assessments_after_cancel = await client.get(assessment_path, headers=coach_headers)
    assert cancelled.status_code == 204
    assert goal_after_cancel.status_code == 200
    assert goal_after_cancel.json()["status"] == "CANCELLED"
    assert len(assessments_after_cancel.json()) == 2

    player_goal_read = await client.get(goal_path, headers=bearer(context.player_token))
    player_assessment_read = await client.get(
        assessment_path, headers=bearer(context.player_token)
    )
    player_goal_write = await client.post(
        goal_path, headers=bearer(context.player_token), json=goal_payload()
    )
    player_assessment_write = await client.post(
        assessment_path,
        headers=bearer(context.player_token),
        json=assessment_payload(),
    )
    assert player_goal_read.status_code == 200
    assert player_assessment_read.status_code == 200
    assert player_goal_write.status_code == 403
    assert player_assessment_write.status_code == 403


@pytest.mark.asyncio
async def test_development_access_is_scoped_and_medical_staff_is_not_overprivileged(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    _, medical_token = await create_user(
        database, "phase4-medical-development@example.com", RoleName.MEDICAL_STAFF
    )
    _, scout_token = await create_user(
        database, "phase4-scout@example.com", RoleName.SCOUT
    )
    goals_path = f"/api/v1/players/{context.player_id}/development/goals"
    cross_player = f"/api/v1/players/{uuid4()}/development/goals"

    created = await client.post(
        goals_path, headers=bearer(context.coach_token), json=goal_payload()
    )
    assert created.status_code == 201
    player_read = await client.get(goals_path, headers=bearer(context.player_token))
    other_player_read = await client.get(
        cross_player, headers=bearer(context.player_token)
    )
    medical_read = await client.get(goals_path, headers=bearer(medical_token))
    scout_read = await client.get(goals_path, headers=bearer(scout_token))
    scout_write = await client.post(
        goals_path, headers=bearer(scout_token), json=goal_payload()
    )

    assert player_read.status_code == 200 and len(player_read.json()) == 1
    assert other_player_read.status_code == 404
    assert medical_read.status_code == 403
    assert scout_read.status_code == 200
    assert scout_write.status_code == 403


@pytest.mark.asyncio
async def test_goal_team_relation_and_development_validation(
    client: AsyncClient, database: DatabaseFixture
) -> None:
    context = await create_domain_context(database)
    headers = bearer(context.coach_token)
    goals_path = f"/api/v1/players/{context.player_id}/development/goals"
    foreign_team = await client.post(
        "/api/v1/teams",
        headers=headers,
        json={
            "name": "Unrelated Team",
            "short_name": "UT",
            "age_group": "U21",
            "gender_category": "Open",
            "season": "2026/27",
        },
    )
    invalid_category = await client.post(
        goals_path, headers=headers, json=goal_payload(category="PSYCHIC")
    )
    unrelated_team = await client.post(
        goals_path,
        headers=headers,
        json=goal_payload(team_id=foreign_team.json()["id"]),
    )
    bad_goal_id = await client.post(
        goals_path,
        headers=headers,
        json={**goal_payload(), "created_by": str(context.player_user_id)},
    )
    bad_assessment_date = await client.post(
        f"/api/v1/players/{context.player_id}/development/assessments",
        headers=headers,
        json=assessment_payload(
            assessment_date=(date.today() + timedelta(days=1)).isoformat()
        ),
    )
    missing_player = await client.post(
        f"/api/v1/players/{uuid4()}/development/goals",
        headers=headers,
        json=goal_payload(),
    )

    assert invalid_category.status_code == 422
    assert unrelated_team.status_code == 409
    assert bad_goal_id.status_code == 422
    assert bad_assessment_date.status_code == 422
    assert missing_player.status_code == 404
