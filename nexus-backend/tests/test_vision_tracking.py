from uuid import UUID

import pytest

from app.ai.vision.pipeline import VisionPipeline
from app.ai.vision.schemas import (
    BoundingBox,
    Detection,
    FrameReference,
    ObjectClass,
)
from app.ai.vision.tracking import (
    BoTSORTAdapter,
    ByteTrackAdapter,
    DeterministicIoUTracker,
    InvalidTrackInput,
    ObservationKind,
    StreamConfig,
    TrackerConfig,
    TrackerLimitExceeded,
    TrackerUnavailable,
    TrackLifecycle,
    build_tracker,
)

SOURCE_ID = UUID(int=1)
WIDTH = 640
HEIGHT = 360


def frame(number: int, timestamp: float | None = None) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=0.04 * number if timestamp is None else timestamp,
        width=WIDTH,
        height=HEIGHT,
    )


def detection(
    frame_ref: FrameReference,
    object_class: ObjectClass,
    box: tuple[float, float, float, float],
    confidence: float = 0.9,
) -> Detection:
    return Detection(
        frame=frame_ref,
        object_class=object_class,
        confidence=confidence,
        bounding_box=BoundingBox(
            x_min=box[0], y_min=box[1], x_max=box[2], y_max=box[3]
        ),
    )


def player_box(x: float) -> tuple[float, float, float, float]:
    return (x, 100.0, x + 40.0, 200.0)


# 1. Empty detection sequence.
def test_empty_sequence_yields_empty_tracks() -> None:
    tracker = DeterministicIoUTracker()
    result = tracker.update(frame(0), [])
    assert result.tracks == []
    assert result.frame.frame_number == 0


# 2. One player across multiple frames keeps its track id.
def test_single_player_keeps_track_id() -> None:
    tracker = DeterministicIoUTracker()
    first = tracker.update(
        frame(0), [detection(frame(0), ObjectClass.PLAYER, player_box(10))]
    )
    second = tracker.update(
        frame(1), [detection(frame(1), ObjectClass.PLAYER, player_box(12))]
    )
    assert len(first.tracks) == len(second.tracks) == 1
    assert first.tracks[0].tracking_id == second.tracks[0].tracking_id


# 3. Multiple players keep distinct track ids.
def test_multiple_players_keep_distinct_ids() -> None:
    tracker = DeterministicIoUTracker()
    refs = [frame(0), frame(1)]
    first = tracker.update(
        refs[0],
        [
            detection(refs[0], ObjectClass.PLAYER, player_box(10)),
            detection(refs[0], ObjectClass.PLAYER, player_box(300)),
        ],
    )
    second = tracker.update(
        refs[1],
        [
            detection(refs[1], ObjectClass.PLAYER, player_box(12)),
            detection(refs[1], ObjectClass.PLAYER, player_box(302)),
        ],
    )
    ids_first = {t.tracking_id for t in first.tracks}
    ids_second = {t.tracking_id for t in second.tracks}
    assert len(ids_first) == 2
    assert ids_first == ids_second


# 4. Temporary missed detection within max_age continues the track.
def test_missed_detection_within_max_age_continues() -> None:
    tracker = DeterministicIoUTracker(
        TrackerConfig(player=StreamConfig(max_missed_frames=2))
    )
    ref0, ref2 = frame(0), frame(2)
    first = tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    tracker.update(frame(1), [])
    third = tracker.update(ref2, [detection(ref2, ObjectClass.PLAYER, player_box(12))])
    assert third.tracks[0].tracking_id == first.tracks[0].tracking_id


def test_missed_detection_beyond_max_age_starts_new_track() -> None:
    tracker = DeterministicIoUTracker(
        TrackerConfig(player=StreamConfig(max_missed_frames=1))
    )
    ref0 = frame(0)
    first = tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    tracker.update(frame(1), [])
    tracker.update(frame(2), [])
    ref3 = frame(3)
    fourth = tracker.update(ref3, [detection(ref3, ObjectClass.PLAYER, player_box(12))])
    assert fourth.tracks[0].tracking_id != first.tracks[0].tracking_id


# 5. New player entering the scene gets a new track id.
def test_new_player_gets_new_track_id() -> None:
    tracker = DeterministicIoUTracker()
    ref0, ref1 = frame(0), frame(1)
    first = tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    second = tracker.update(
        ref1,
        [
            detection(ref1, ObjectClass.PLAYER, player_box(12)),
            detection(ref1, ObjectClass.PLAYER, player_box(400)),
        ],
    )
    ids = {t.tracking_id for t in second.tracks}
    assert first.tracks[0].tracking_id in ids
    assert len(ids) == 2


# 6. Player leaving terminates the track after configured rules.
def test_departed_player_track_terminates() -> None:
    tracker = DeterministicIoUTracker(
        TrackerConfig(player=StreamConfig(max_missed_frames=1))
    )
    ref0 = frame(0)
    tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    assert tracker.update(frame(1), []).tracks == []
    assert tracker.update(frame(2), []).tracks == []
    assert tracker.summaries() == []


# 7. Ball tracking continuity.
def test_ball_tracking_continuity() -> None:
    tracker = DeterministicIoUTracker()
    ref0, ref1 = frame(0), frame(1)
    ball = (300.0, 150.0, 312.0, 162.0)
    moved = (302.0, 151.0, 314.0, 163.0)
    first = tracker.update(ref0, [detection(ref0, ObjectClass.BALL, ball)])
    second = tracker.update(ref1, [detection(ref1, ObjectClass.BALL, moved)])
    assert first.tracks[0].tracking_id == second.tracks[0].tracking_id
    assert second.tracks[0].tracking_id.startswith("ball-")


# 8. Player and ball simultaneously keep separate namespaces.
def test_player_and_ball_simultaneously() -> None:
    tracker = DeterministicIoUTracker()
    ref = frame(0)
    result = tracker.update(
        ref,
        [
            detection(ref, ObjectClass.PLAYER, player_box(10)),
            detection(ref, ObjectClass.BALL, (300.0, 150.0, 312.0, 162.0)),
        ],
    )
    ids = {t.tracking_id for t in result.tracks}
    assert len(ids) == 2
    assert any(i.startswith("player-") for i in ids)
    assert any(i.startswith("ball-") for i in ids)


# 9. Track ids remain distinct from club player ids.
def test_track_ids_distinct_from_player_ids() -> None:
    tracker = DeterministicIoUTracker()
    ref = frame(0)
    result = tracker.update(ref, [detection(ref, ObjectClass.PLAYER, player_box(10))])
    track = result.tracks[0]
    assert isinstance(track.tracking_id, str)
    assert track.player_id is None
    assert track.identity_verified is False
    with pytest.raises(ValueError):
        UUID(track.tracking_id)


# 10. Reset behavior.
def test_reset_clears_state() -> None:
    tracker = DeterministicIoUTracker()
    ref0 = frame(0)
    first = tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    tracker.reset()
    ref1 = frame(1)
    second = tracker.update(ref1, [detection(ref1, ObjectClass.PLAYER, player_box(12))])
    assert tracker.active_track_ids() == [second.tracks[0].tracking_id]
    assert (
        first.tracks[0].tracking_id == second.tracks[0].tracking_id
    )  # counters restart
    assert tracker.summaries()[0].hits == 1


# 11. Malformed / invalid detections.
def test_frame_mismatch_rejected() -> None:
    tracker = DeterministicIoUTracker()
    with pytest.raises(InvalidTrackInput):
        tracker.update(
            frame(1), [detection(frame(0), ObjectClass.PLAYER, player_box(10))]
        )
    with pytest.raises(InvalidTrackInput):
        tracker.update(frame(0), ["not-a-detection"])  # type: ignore[list-item]
    with pytest.raises(InvalidTrackInput):
        tracker.update("frame", [])  # type: ignore[arg-type]


# 12. Deterministic behavior.
def test_deterministic_replay() -> None:
    def run() -> list[str]:
        tracker = DeterministicIoUTracker()
        ids: list[str] = []
        for number in range(4):
            ref = frame(number)
            boxes = [player_box(10 + 2 * number), player_box(300 - number)]
            result = tracker.update(
                ref, [detection(ref, ObjectClass.PLAYER, box) for box in boxes]
            )
            ids.extend(sorted(t.tracking_id for t in result.tracks))
        return ids

    assert run() == run()


# 13. Tracker unavailable / failure behavior.
def test_external_adapters_raise_tracker_unavailable() -> None:
    with pytest.raises(TrackerUnavailable):
        ByteTrackAdapter()
    with pytest.raises(TrackerUnavailable):
        BoTSORTAdapter()
    with pytest.raises(InvalidTrackInput):
        build_tracker("unknown-backend")
    assert isinstance(build_tracker("deterministic"), DeterministicIoUTracker)


def test_track_capacity_is_bounded() -> None:
    tracker = DeterministicIoUTracker(TrackerConfig(player=StreamConfig(max_tracks=1)))
    ref = frame(0)
    tracker.update(ref, [detection(ref, ObjectClass.PLAYER, player_box(10))])
    with pytest.raises(TrackerLimitExceeded):
        tracker.update(
            ref,
            [
                detection(ref, ObjectClass.PLAYER, player_box(10)),
                detection(ref, ObjectClass.PLAYER, player_box(400)),
            ],
        )


# 14. Bounding box / frame provenance remains intact.
def test_provenance_preserved() -> None:
    tracker = DeterministicIoUTracker()
    ref = frame(7, timestamp=0.28)
    source = detection(
        ref, ObjectClass.PLAYER, (10.0, 20.0, 50.0, 90.0), confidence=0.77
    )
    result = tracker.update(ref, [source])
    track = result.tracks[0]
    assert track.frame == ref
    assert track.bounding_box == source.bounding_box
    assert track.confidence == source.confidence
    assert track.object_class == ObjectClass.PLAYER
    assert tracker.provenance.observation == ObservationKind.OBSERVED
    assert tracker.provenance.tracker_name


# 15. No accidental mutation of source detections.
def test_source_detections_not_mutated() -> None:
    tracker = DeterministicIoUTracker()
    ref = frame(0)
    sources = [detection(ref, ObjectClass.PLAYER, player_box(10))]
    snapshot = [item.model_dump() for item in sources]
    tracker.update(ref, sources)
    ref_next = frame(1)
    tracker.update(ref_next, [detection(ref_next, ObjectClass.PLAYER, player_box(12))])
    assert [item.model_dump() for item in sources] == snapshot


def test_tentative_tracks_withheld_until_confirmed() -> None:
    tracker = DeterministicIoUTracker(TrackerConfig(player=StreamConfig(min_hits=2)))
    ref0, ref1 = frame(0), frame(1)
    assert (
        tracker.update(
            ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))]
        ).tracks
        == []
    )
    second = tracker.update(ref1, [detection(ref1, ObjectClass.PLAYER, player_box(12))])
    assert len(second.tracks) == 1
    assert tracker.summaries()[0].state == TrackLifecycle.CONFIRMED


def test_lost_tracks_emit_no_predicted_boxes() -> None:
    tracker = DeterministicIoUTracker(
        TrackerConfig(player=StreamConfig(max_missed_frames=3))
    )
    ref0 = frame(0)
    tracker.update(ref0, [detection(ref0, ObjectClass.PLAYER, player_box(10))])
    assert tracker.update(frame(1), []).tracks == []
    assert tracker.summaries()[0].state == TrackLifecycle.LOST


def test_ball_stream_uses_distinct_configuration() -> None:
    config = TrackerConfig()
    assert config.ball != config.player
    assert config.ball.max_missed_frames > config.player.max_missed_frames
    assert config.ball.iou_threshold < config.player.iou_threshold


def test_pipeline_integration_with_deterministic_tracker() -> None:
    from collections.abc import Iterable, Sequence
    from datetime import UTC, datetime

    from app.ai.vision.schemas import TrackingFrame, VideoProcessingStatus, VideoSource
    from app.ai.vision.types import FramePacket

    tracker = DeterministicIoUTracker()
    ref = frame(0)
    video = VideoSource(
        source_id=SOURCE_ID,
        match_id=UUID(int=2),
        original_filename="match.mp4",
        media_type="video/mp4",
        file_size_bytes=100,
        ingested_at=datetime(2026, 9, 29, tzinfo=UTC),
        processing_status=VideoProcessingStatus.READY,
        storage_reference=f"{SOURCE_ID.hex}.mp4",
    )

    class Extractor:
        def extract(self, source: VideoSource) -> Iterable[FramePacket[bytes]]:
            yield FramePacket(reference=ref, payload=b"frame")

    class Detector:
        def detect(self, packet: FramePacket[bytes]) -> Sequence[Detection]:
            return [detection(packet.reference, ObjectClass.PLAYER, player_box(10))]

    class Mapper:
        def map(self, tracking: TrackingFrame) -> Sequence[object]:
            return []

    [result] = list(
        VisionPipeline(Extractor(), Detector(), tracker, Mapper()).run(video)
    )
    assert len(result.tracking.tracks) == 1
    assert result.tracking.tracks[0].player_id is None
    assert result.detections[0].bounding_box == result.tracking.tracks[0].bounding_box
