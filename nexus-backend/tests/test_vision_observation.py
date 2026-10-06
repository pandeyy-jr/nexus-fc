"""Phase 06G vision-observation tests (service + API).

Uses injected fake extraction/detection with the real deterministic
tracker and mapper, so no YOLO weights, GPU, or footage are required.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.ai.vision.pitch_mapping import HomographyMapper, MapperConfig
from app.ai.vision.schemas import (
    BoundingBox,
    CalibrationCorrespondence,
    Detection,
    FrameReference,
    ImagePoint,
    MappingStatus,
    ObjectClass,
    PitchCalibration,
    PitchCoordinate,
    TrackingFrame,
    VideoProcessingStatus,
    VisionJobStatus,
    VisionProcessingRequest,
)
from app.ai.vision.tracking import DeterministicIoUTracker
from app.ai.vision.types import FramePacket
from app.core.matches import MatchSide
from app.core.roles import RoleName
from app.db.models.match import Match
from app.db.models.opponent import Opponent
from app.db.models.team import Team
from app.db.models.user import User
from app.db.models.video_source import VideoSourceRecord
from app.services.vision_processing import (
    VisionComponents,
    clear_vision_jobs,
    request_vision_processing,
)
from tests.conftest import DatabaseFixture
from tests.factories import create_user
from tests.test_video_ingestion import bearer

SOURCE_WIDTH = 640
SOURCE_HEIGHT = 360


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterable[None]:
    clear_vision_jobs()
    yield
    clear_vision_jobs()


def rect_calibration(calibration_id: str = "cal-06G-1") -> PitchCalibration:
    return PitchCalibration(
        calibration_id=calibration_id,
        correspondences=[
            CalibrationCorrespondence(
                image=ImagePoint(x=x, y=y),
                pitch=PitchCoordinate(x=xp, y=yp, coordinate_system="PITCH"),
            )
            for (x, y), (xp, yp) in (
                ((0, 0), (0, 0)),
                ((640, 0), (1, 0)),
                ((640, 360), (1, 1)),
                ((0, 360), (0, 1)),
            )
        ],
    )


def make_request(**kwargs: object) -> VisionProcessingRequest:
    payload: dict[str, object] = {"calibration": rect_calibration()}
    payload.update(kwargs)
    return VisionProcessingRequest(**payload)  # type: ignore[arg-type]


class FakeExtractor:
    def __init__(self, source_id: UUID, frame_count: int = 3) -> None:
        self.source_id = source_id
        self.frame_count = frame_count

    def extract(self, source: object) -> Iterable[FramePacket[object]]:
        for number in range(self.frame_count):
            yield FramePacket(
                reference=FrameReference(
                    source_id=self.source_id,
                    frame_number=number,
                    timestamp_seconds=0.04 * number,
                    width=SOURCE_WIDTH,
                    height=SOURCE_HEIGHT,
                ),
                payload=object(),
            )


class FakeDetector:
    def __init__(self, misses_frame: int | None = None) -> None:
        self.misses_frame = misses_frame

    def detect(self, packet: FramePacket[object]) -> list[Detection]:
        number = packet.reference.frame_number
        if self.misses_frame == number:
            return []
        shift = 2.0 * number
        return [
            Detection(
                frame=packet.reference,
                object_class=ObjectClass.PLAYER,
                confidence=0.9,
                bounding_box=BoundingBox(
                    x_min=10 + shift, y_min=20, x_max=50 + shift, y_max=100
                ),
            ),
            Detection(
                frame=packet.reference,
                object_class=ObjectClass.BALL,
                confidence=0.8,
                bounding_box=BoundingBox(x_min=300, y_min=150, x_max=312, y_max=162),
            ),
        ]


class FailingDetector(FakeDetector):
    def detect(self, packet: FramePacket[object]) -> list[Detection]:
        raise RuntimeError("inference exploded")


class FailingTracker(DeterministicIoUTracker):
    def track(self, frame: FrameReference, detections: object) -> TrackingFrame:
        raise RuntimeError("tracker exploded")


class EmptyMapper:
    def map(self, tracking: TrackingFrame) -> list[object]:
        return []


def calibrated_mapper() -> HomographyMapper:
    mapper = HomographyMapper(MapperConfig())
    mapper.calibrate(rect_calibration())
    return mapper


def components(
    source_id: UUID,
    detector: object | None = None,
    tracker: object | None = None,
    mapper: object | None = None,
    frame_count: int = 3,
) -> VisionComponents:
    extractor = FakeExtractor(source_id, frame_count)
    return VisionComponents(
        extractor_factory=extractor.extract,
        detector=detector or FakeDetector(),  # type: ignore[arg-type]
        tracker=tracker or DeterministicIoUTracker(),  # type: ignore[arg-type]
        mapper=mapper or calibrated_mapper(),  # type: ignore[arg-type]
        detector_name="fake-detector",
        detector_version="test-1",
        tracker_name="fake-tracker",
        tracker_version="test-1",
    )


async def seed_match_video(
    database: DatabaseFixture, creator_id: UUID
) -> tuple[UUID, UUID]:
    async with database.sessions() as session:
        team = Team(
            name="Vision Team",
            short_name="VIS",
            age_group="Senior",
            gender_category="Open",
            season="2026/27",
        )
        opponent = Opponent(name="Vision Opponent")
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
        await session.flush()
        source_id = uuid4()
        session.add(
            VideoSourceRecord(
                id=source_id,
                match_id=match.id,
                original_filename="session.mp4",
                media_type="video/mp4",
                file_size_bytes=10,
                processing_status=VideoProcessingStatus.READY.value,
                storage_reference=f"{source_id.hex}.mp4",
                created_by=creator_id,
            )
        )
        await session.commit()
        return match.id, source_id


async def load_actor(database: DatabaseFixture, user_id: UUID) -> User:
    async with database.sessions() as session:
        user = await session.scalar(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )
        assert user is not None
        session.expunge(user)
        return user


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_processing_preserves_evidence(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)
    request = make_request()
    snapshot = request.model_dump()

    async with database.sessions() as session:
        job = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=request,
            components=components(source_id),
        )

    assert job.status is VisionJobStatus.COMPLETED
    assert job.completed_at is not None
    assert job.frames_processed == 3
    assert job.match_id == match_id
    assert job.source_id == source_id
    assert job.calibration_id == "cal-06G-1"
    assert request.model_dump() == snapshot

    player_obs = [o for o in job.observations if o.tracking_id == "player-1"]
    ball_obs = [o for o in job.observations if o.tracking_id == "ball-1"]
    assert len(player_obs) == 3
    assert len(ball_obs) == 3
    first = player_obs[0]
    assert first.match_id == match_id
    assert first.source_id == source_id
    assert first.frame.frame_number == 0
    assert first.bounding_box.x_min == 10
    assert first.detection_confidence == 0.9
    assert first.mapping_status is MappingStatus.MAPPED
    assert first.pitch_coordinate is not None
    assert first.pitch_coordinate.x == pytest.approx(30 / 640)
    assert first.image_point.y == 100  # bottom-center preserved separately
    assert first.player_id is None
    assert first.identity_verified is False
    assert first.team_side is None
    assert first.detector_name == "fake-detector"
    assert first.tracker_name == "fake-tracker"


@pytest.mark.asyncio
async def test_mapping_failure_is_explicit_not_fabricated(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin-2@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)

    async with database.sessions() as session:
        job = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=make_request(),
            components=components(source_id, mapper=EmptyMapper()),
        )

    assert job.status is VisionJobStatus.COMPLETED
    assert job.observations
    assert all(o.pitch_coordinate is None for o in job.observations)
    assert all(o.mapping_status is MappingStatus.FAILED for o in job.observations)
    assert all(o.bounding_box.x_min >= 0 for o in job.observations)


@pytest.mark.asyncio
async def test_detector_failure_marks_job_failed(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin-3@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)

    async with database.sessions() as session:
        job = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=make_request(),
            components=components(source_id, detector=FailingDetector()),
        )

    assert job.status is VisionJobStatus.FAILED
    assert job.completed_at is not None
    assert job.error
    assert "frame 0" in job.error


@pytest.mark.asyncio
async def test_tracker_failure_marks_job_failed(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin-4@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)

    async with database.sessions() as session:
        job = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=make_request(),
            components=components(source_id, tracker=FailingTracker()),
        )

    assert job.status is VisionJobStatus.FAILED
    assert job.error


@pytest.mark.asyncio
async def test_idempotent_repeat_returns_same_job(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin-5@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)
    body = make_request()

    async with database.sessions() as session:
        first = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=body,
            components=components(source_id),
        )
    async with database.sessions() as session:
        second = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=body,
            components=components(source_id),
        )

    assert first.job_id == second.job_id
    assert first.observations == second.observations


@pytest.mark.asyncio
async def test_missing_or_unready_video_errors(
    database: DatabaseFixture,
) -> None:
    from fastapi import HTTPException

    admin_id, _ = await create_user(
        database, "vision-admin-6@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)

    async with database.sessions() as session:
        with pytest.raises(HTTPException) as missing:
            await request_vision_processing(
                session,
                object(),  # type: ignore[arg-type]
                match_id=match_id,
                source_id=uuid4(),
                actor=actor,
                request=make_request(),
                components=components(source_id),
            )
        assert missing.value.status_code == 404

        record = await session.get(VideoSourceRecord, source_id)
        assert record is not None
        record.processing_status = VideoProcessingStatus.FAILED.value
        await session.commit()
        with pytest.raises(HTTPException) as conflict:
            await request_vision_processing(
                session,
                object(),  # type: ignore[arg-type]
                match_id=match_id,
                source_id=source_id,
                actor=actor,
                request=make_request(),
                components=components(source_id),
            )
        assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_max_frames_bounds_processing(
    database: DatabaseFixture,
) -> None:
    admin_id, _ = await create_user(
        database, "vision-admin-7@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    actor = await load_actor(database, admin_id)

    async with database.sessions() as session:
        job = await request_vision_processing(
            session,
            object(),  # type: ignore[arg-type]
            match_id=match_id,
            source_id=source_id,
            actor=actor,
            request=make_request(max_frames=2),
            components=components(source_id, frame_count=5),
        )

    assert job.status is VisionJobStatus.COMPLETED
    assert job.frames_processed == 2
    assert {o.frame.frame_number for o in job.observations} == {0, 1}


def test_invalid_processing_request_rejected() -> None:
    with pytest.raises(ValidationError):
        make_request(max_frames=0)
    with pytest.raises(ValidationError):
        make_request(max_frames=301)
    with pytest.raises(ValidationError):
        VisionProcessingRequest(sample_every_n_frames=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


def api_request_body() -> dict[str, object]:
    return {
        "max_frames": 2,
        "sample_every_n_frames": 1,
        "detector_confidence_threshold": 0.25,
        "calibration": {
            "calibration_id": "cal-06G-1",
            "correspondences": [
                {
                    "image": {"x": x, "y": y},
                    "pitch": {"x": xp, "y": yp, "coordinate_system": "PITCH"},
                }
                for (x, y), (xp, yp) in (
                    ((0, 0), (0, 0)),
                    ((640, 0), (1, 0)),
                    ((640, 360), (1, 1)),
                    ((0, 360), (0, 1)),
                )
            ],
        },
    }


@pytest.mark.asyncio
async def test_api_post_and_get_processing_job(
    client: AsyncClient,
    database: DatabaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.endpoints.videos as videos_module

    admin_id, token = await create_user(
        database, "vision-api-admin@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    monkeypatch.setattr(
        videos_module,
        "build_vision_components",
        lambda storage, body: components(source_id, frame_count=2),
    )

    post = await client.post(
        f"/api/v1/matches/{match_id}/videos/{source_id}/vision-processing",
        json=api_request_body(),
        headers=bearer(token),
    )
    assert post.status_code == 200, post.text
    job = post.json()
    assert job["status"] == "COMPLETED"
    assert job["match_id"] == str(match_id)
    assert job["source_id"] == str(source_id)
    assert job["frames_processed"] == 2
    assert job["observations"]
    observation = job["observations"][0]
    assert observation["player_id"] is None
    assert observation["team_side"] is None
    assert observation["pitch_coordinate"] is not None

    get = await client.get(
        f"/api/v1/matches/{match_id}/videos/{source_id}"
        f"/vision-processing/{job['job_id']}",
        headers=bearer(token),
    )
    assert get.status_code == 200
    assert get.json()["job_id"] == job["job_id"]

    scoped = await client.get(
        f"/api/v1/matches/{uuid4()}/videos/{source_id}"
        f"/vision-processing/{job['job_id']}",
        headers=bearer(token),
    )
    assert scoped.status_code in (403, 404)
    unknown = await client.get(
        f"/api/v1/matches/{match_id}/videos/{source_id}/vision-processing/{uuid4()}",
        headers=bearer(token),
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_api_rbac_and_invalid_requests(
    client: AsyncClient,
    database: DatabaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.endpoints.videos as videos_module

    admin_id, admin_token = await create_user(
        database, "vision-api-admin-2@example.com", RoleName.ADMIN
    )
    _, player_token = await create_user(
        database, "vision-api-player@example.com", RoleName.PLAYER
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    monkeypatch.setattr(
        videos_module,
        "build_vision_components",
        lambda storage, body: components(source_id, frame_count=1),
    )
    route = f"/api/v1/matches/{match_id}/videos/{source_id}/vision-processing"

    forbidden = await client.post(
        route, json=api_request_body(), headers=bearer(player_token)
    )
    assert forbidden.status_code == 403
    unauthenticated = await client.post(route, json=api_request_body())
    assert unauthenticated.status_code == 401
    invalid = await client.post(
        route, json={"max_frames": 2}, headers=bearer(admin_token)
    )
    assert invalid.status_code == 422
    missing_video = await client.post(
        f"/api/v1/matches/{match_id}/videos/{uuid4()}/vision-processing",
        json=api_request_body(),
        headers=bearer(admin_token),
    )
    assert missing_video.status_code == 404


@pytest.mark.asyncio
async def test_api_model_unavailable_returns_503(
    client: AsyncClient,
    database: DatabaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.endpoints.videos as videos_module
    from app.services.vision_processing import DetectorUnavailableError

    admin_id, admin_token = await create_user(
        database, "vision-api-admin-3@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)

    def raise_unavailable(storage: object, body: object) -> object:
        raise DetectorUnavailableError("Vision model is unavailable")

    monkeypatch.setattr(videos_module, "build_vision_components", raise_unavailable)
    response = await client.post(
        f"/api/v1/matches/{match_id}/videos/{source_id}/vision-processing",
        json=api_request_body(),
        headers=bearer(admin_token),
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_api_inference_failure_is_explicit(
    client: AsyncClient,
    database: DatabaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.endpoints.videos as videos_module

    admin_id, admin_token = await create_user(
        database, "vision-api-admin-4@example.com", RoleName.ADMIN
    )
    match_id, source_id = await seed_match_video(database, admin_id)
    monkeypatch.setattr(
        videos_module,
        "build_vision_components",
        lambda storage, body: components(
            source_id, detector=FailingDetector(), frame_count=1
        ),
    )
    response = await client.post(
        f"/api/v1/matches/{match_id}/videos/{source_id}/vision-processing",
        json=api_request_body(),
        headers=bearer(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["error"]
