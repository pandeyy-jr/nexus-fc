from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.ai.vision.storage import LocalVideoStorage
from app.api.v1.endpoints.videos import get_video_storage
from app.core.matches import MatchSide
from app.core.roles import RoleName
from app.db.models.match import Match
from app.db.models.opponent import Opponent
from app.db.models.team import Team
from app.main import app
from tests.conftest import DatabaseFixture
from tests.factories import create_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def video_headers(filename: str = "training.mp4") -> dict[str, str]:
    return {"X-Filename": filename, "Content-Type": "video/mp4"}


async def create_match(database: DatabaseFixture, creator_id: UUID) -> UUID:
    async with database.sessions() as session:
        team = Team(
            name="Video Team",
            short_name="VID",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Video Opponent")
        session.add_all([team, opponent])
        await session.flush()
        match = Match(
            team_id=team.id,
            opponent_id=opponent.id,
            scheduled_at=datetime(2026, 10, 1, tzinfo=UTC),
            home_away=MatchSide.HOME,
            created_by=creator_id,
        )
        session.add(match)
        await session.commit()
        return match.id


@pytest.mark.asyncio
async def test_ingests_video_to_generated_storage_reference(
    client: AsyncClient,
    database: DatabaseFixture,
    tmp_path: Path,
) -> None:
    admin_id, token = await create_user(
        database, "video-admin@example.com", RoleName.ADMIN
    )
    match_id = await create_match(database, admin_id)
    storage = LocalVideoStorage(tmp_path / "videos")
    app.dependency_overrides[get_video_storage] = lambda: storage
    body = b"\x00\x00\x00\x18ftypisom0000"

    response = await client.post(
        f"/api/v1/matches/{match_id}/videos",
        content=body,
        headers={**video_headers("Team Session.mp4"), **bearer(token)},
    )

    assert response.status_code == 201, response.text
    source = response.json()
    assert source["match_id"] == str(match_id)
    assert source["original_filename"] == "Team Session.mp4"
    assert source["media_type"] == "video/mp4"
    assert source["file_size_bytes"] == len(body)
    assert source["processing_status"] == "READY"
    assert "/" not in source["storage_reference"]
    stored_path = tmp_path / "videos" / source["storage_reference"]
    assert stored_path.read_bytes() == body


@pytest.mark.asyncio
async def test_video_upload_rejects_unauthorized_missing_match_and_unsafe_input(
    client: AsyncClient,
    database: DatabaseFixture,
    tmp_path: Path,
) -> None:
    admin_id, admin_token = await create_user(
        database, "video-admin-2@example.com", RoleName.ADMIN
    )
    _, player_token = await create_user(
        database, "video-player@example.com", RoleName.PLAYER
    )
    match_id = await create_match(database, admin_id)
    storage = LocalVideoStorage(tmp_path / "videos")
    app.dependency_overrides[get_video_storage] = lambda: storage
    body = b"\x00\x00\x00\x18ftypisom0000"
    route = f"/api/v1/matches/{match_id}/videos"

    forbidden = await client.post(
        route,
        content=body,
        headers={**video_headers(), **bearer(player_token)},
    )
    unauthenticated = await client.post(route, content=body, headers=video_headers())
    missing_match = await client.post(
        f"/api/v1/matches/{UUID(int=0)}/videos",
        content=body,
        headers={**video_headers(), **bearer(admin_token)},
    )
    unsafe_name = await client.post(
        route,
        content=body,
        headers={**video_headers("..\\outside.mp4"), **bearer(admin_token)},
    )
    unsupported_extension = await client.post(
        route,
        content=body,
        headers={**video_headers("training.exe"), **bearer(admin_token)},
    )
    wrong_type = await client.post(
        route,
        content=body,
        headers={
            **video_headers(),
            "Content-Type": "video/webm",
            **bearer(admin_token),
        },
    )
    invalid_signature = await client.post(
        route,
        content=b"not a video",
        headers={**video_headers(), **bearer(admin_token)},
    )

    assert forbidden.status_code == 403
    assert unauthenticated.status_code == 401
    assert missing_match.status_code == 404
    assert unsafe_name.status_code == 422
    assert unsupported_extension.status_code == 422
    assert wrong_type.status_code == 422
    assert invalid_signature.status_code == 422
    assert list((tmp_path / "videos").glob("*")) == []


@pytest.mark.asyncio
async def test_video_upload_enforces_size_limit(
    client: AsyncClient,
    database: DatabaseFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import video_ingestion

    admin_id, token = await create_user(
        database, "video-admin-3@example.com", RoleName.ADMIN
    )
    match_id = await create_match(database, admin_id)
    storage = LocalVideoStorage(tmp_path / "videos")
    app.dependency_overrides[get_video_storage] = lambda: storage
    monkeypatch.setattr(video_ingestion, "MAX_VIDEO_SIZE_BYTES", 12)

    response = await client.post(
        f"/api/v1/matches/{match_id}/videos",
        content=b"\x00\x00\x00\x18ftypisom0000",
        headers={**video_headers(), **bearer(token)},
    )

    assert response.status_code == 413
    assert list((tmp_path / "videos").glob("*")) == []
