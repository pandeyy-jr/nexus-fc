from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.ai.vision.pipeline import VisionPipeline
from app.ai.vision.schemas import (
    BoundingBox,
    Detection,
    FrameReference,
    ObjectClass,
    PitchCoordinate,
    PitchPosition,
    TrackedObject,
    TrackingFrame,
    VideoProcessingStatus,
    VideoSource,
)
from app.ai.vision.types import FramePacket


def sample_frame() -> FrameReference:
    return FrameReference(
        source_id=UUID(int=1),
        frame_number=0,
        timestamp_seconds=0.0,
        width=1920,
        height=1080,
    )


def test_detection_validates_box_and_tracking_identity_is_distinct() -> None:
    frame = sample_frame()
    detection = Detection(
        frame=frame,
        object_class=ObjectClass.PLAYER,
        confidence=0.95,
        bounding_box=BoundingBox(x_min=10, y_min=20, x_max=30, y_max=60),
    )
    assert detection.frame.frame_number == 0

    with pytest.raises(ValueError):
        BoundingBox(x_min=40, y_min=20, x_max=30, y_max=60)
    with pytest.raises(ValueError):
        Detection(
            frame=frame,
            object_class=ObjectClass.BALL,
            confidence=1.1,
            bounding_box=BoundingBox(x_min=0, y_min=0, x_max=20, y_max=20),
        )
    with pytest.raises(ValueError):
        TrackedObject(
            frame=frame,
            object_class=ObjectClass.PLAYER,
            confidence=0.9,
            bounding_box=BoundingBox(x_min=0, y_min=0, x_max=20, y_max=20),
            tracking_id="track-1",
            player_id=UUID(int=2),
        )


def test_pipeline_composes_stages_lazily() -> None:
    frame = sample_frame()
    video = VideoSource(
        source_id=frame.source_id,
        match_id=UUID(int=2),
        original_filename="match.mp4",
        media_type="video/mp4",
        file_size_bytes=100,
        ingested_at=datetime(2026, 9, 29, tzinfo=UTC),
        processing_status=VideoProcessingStatus.READY,
        storage_reference=f"{frame.source_id.hex}.mp4",
    )
    box = BoundingBox(x_min=1, y_min=2, x_max=10, y_max=20)
    called: list[str] = []

    class Extractor:
        def extract(self, source: VideoSource) -> Iterable[FramePacket[bytes]]:
            called.append("extract")
            yield FramePacket(reference=frame, payload=b"frame")

    class Detector:
        def detect(self, packet: FramePacket[bytes]) -> Sequence[Detection]:
            called.append("detect")
            return [
                Detection(
                    frame=packet.reference,
                    object_class=ObjectClass.BALL,
                    confidence=0.8,
                    bounding_box=box,
                )
            ]

    class Tracker:
        def track(
            self, reference: FrameReference, detections: Sequence[Detection]
        ) -> TrackingFrame:
            called.append("track")
            return TrackingFrame(
                frame=reference,
                tracks=[
                    TrackedObject(
                        frame=reference,
                        object_class=ObjectClass.BALL,
                        confidence=detections[0].confidence,
                        bounding_box=detections[0].bounding_box,
                        tracking_id="ball-1",
                    )
                ],
            )

    class Mapper:
        def map(self, tracking: TrackingFrame) -> Sequence[PitchPosition]:
            called.append("map")
            return [
                PitchPosition(
                    frame=tracking.frame,
                    tracking_id=tracking.tracks[0].tracking_id,
                    coordinate=PitchCoordinate(x=20.0, y=30.0),
                )
            ]

    results = VisionPipeline(Extractor(), Detector(), Tracker(), Mapper()).run(video)
    assert called == []
    result = next(results)
    assert called == ["extract", "detect", "track", "map"]
    assert result.tracking.tracks[0].tracking_id == "ball-1"
    assert result.pitch_positions[0].coordinate.coordinate_system == "PITCH"
