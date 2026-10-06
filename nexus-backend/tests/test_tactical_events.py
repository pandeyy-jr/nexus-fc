"""Phase 07F event tests: contracts, honest baselines, explicit
refusals. No trained models, no fabricated labels."""

from uuid import UUID

import pytest

from app.ai.tactics.events import (
    BaselineDetectorSuite,
    DetectionMethod,
    EventEvidence,
    EventType,
    InvalidEventInput,
    OverloadRegion,
    PlayerMovementDetector,
    PossessionChangeDetector,
    SpatialOverloadDetector,
    TacticalEvent,
    TacticalEventDetector,
    TeamCompactnessDetector,
)
from app.ai.tactics.state import TacticalSequence, TacticalStateBuilder
from app.ai.vision.schemas import (
    BoundingBox,
    FrameReference,
    ImagePoint,
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchCoordinate,
    TeamSide,
    VisionObservation,
)

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def frame(number: int, timestamp: float) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=timestamp,
        width=640,
        height=360,
    )


def observation(
    ref: FrameReference,
    tracking_id: str,
    pitch: tuple[float, float] | None,
    team_side: TeamSide | None = None,
) -> VisionObservation:
    return VisionObservation(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame=ref,
        tracking_id=tracking_id,
        object_class=ObjectClass.PLAYER,
        detection_confidence=0.8,
        bounding_box=BoundingBox(x_min=10, y_min=20, x_max=50, y_max=100),
        image_point=ImagePoint(x=30, y=100),
        mapping_point_type=MappingPointType.BOTTOM_CENTER,
        pitch_coordinate=(
            PitchCoordinate(x=pitch[0], y=pitch[1], coordinate_system="PITCH")
            if pitch is not None
            else None
        ),
        mapping_status=(
            MappingStatus.MAPPED if pitch is not None else MappingStatus.FAILED
        ),
        calibration_id="cal-1",
        detector_name="det",
        tracker_name="trk",
        team_side=team_side,
    )


def sequence(frames: list[list[VisionObservation]]) -> TacticalSequence:
    grouped: dict[int, list[VisionObservation]] = {}
    for item in frames:
        for obs in item:
            grouped.setdefault(obs.frame.frame_number, []).append(obs)
    builder = TacticalStateBuilder()
    states = [builder.build_frame(grouped[n]) for n in sorted(grouped)]
    return TacticalSequence(frames=states)


def track_run(track_id: str, points: list[tuple[int, float, float, float]]):
    return [observation(frame(n, t), track_id, (x, y)) for n, t, x, y in points]


# 1/2. Serialization + evidence preservation.
def test_event_serialization_and_evidence() -> None:
    seq = sequence([track_run("player-1", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.4, 0.3)])])
    (event,) = PlayerMovementDetector().detect(seq)
    dumped = event.model_dump()
    assert dumped["event_type"] == "PLAYER_MOVEMENT"
    assert dumped["match_id"] == MATCH_ID
    assert event.evidence.track_ids == ("player-1",)
    assert len(event.evidence.positions) == 2
    assert event.evidence.detector_name == "player-movement-rule"
    assert TacticalEvent(**dumped) == event


# 3. Movement baseline values.
def test_movement_measurements() -> None:
    seq = sequence([track_run("player-1", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.5, 0.3)])])
    (event,) = PlayerMovementDetector().detect(seq)
    assert event.start_frame == 0 and event.end_frame == 1
    assert event.start_timestamp == pytest.approx(0.0)
    assert event.end_timestamp == pytest.approx(0.5)
    assert event.metadata["distance"] == pytest.approx(0.3)
    assert event.metadata["mean_speed"] == pytest.approx(0.6)
    assert event.detection_method is DetectionMethod.RULE
    assert event.confidence is None  # 15. no invented confidence


# 4/5. Missing timestamps / coordinates break runs honestly.
def test_movement_invalid_time_or_missing_coords() -> None:
    flat_time = sequence(
        [
            [observation(frame(0, 1.0), "player-1", (0.2, 0.3))],
            [observation(frame(1, 1.0), "player-1", (0.5, 0.3))],
        ]
    )
    assert PlayerMovementDetector().detect(flat_time) == []
    gap_run = sequence(
        [
            [observation(frame(0, 0.0), "player-1", (0.2, 0.3))],
            [observation(frame(1, 0.5), "player-1", None)],
            [observation(frame(2, 1.0), "player-1", (0.5, 0.3))],
        ]
    )
    assert PlayerMovementDetector().detect(gap_run) == []


# 6. Compactness with known sides.
def test_compactness_change() -> None:
    home_wide = [
        observation(frame(0, 0.0), "h1", (0.1, 0.1), TeamSide.HOME),
        observation(frame(0, 0.0), "h2", (0.9, 0.9), TeamSide.HOME),
    ]
    home_narrow = [
        observation(frame(1, 0.5), "h1", (0.4, 0.4), TeamSide.HOME),
        observation(frame(1, 0.5), "h2", (0.6, 0.6), TeamSide.HOME),
    ]
    events = TeamCompactnessDetector(change_threshold=0.5).detect(
        sequence([home_wide, home_narrow])
    )
    assert len(events) == 1
    (event,) = events
    assert event.event_type is EventType.TEAM_COMPACTNESS_CHANGE
    assert event.metadata["team"] == "HOME"
    assert event.metadata["area_before"] == pytest.approx(0.64)
    assert event.metadata["area_after"] == pytest.approx(0.04)


def test_compactness_no_change_no_event() -> None:
    same = [
        observation(frame(0, 0.0), "h1", (0.1, 0.2), TeamSide.HOME),
        observation(frame(0, 0.0), "h2", (0.5, 0.6), TeamSide.HOME),
        observation(frame(1, 0.5), "h1", (0.1, 0.2), TeamSide.HOME),
        observation(frame(1, 0.5), "h2", (0.5, 0.6), TeamSide.HOME),
    ]
    assert TeamCompactnessDetector().detect(sequence([same[:2], same[2:]])) == []


# 7. Unknown sides yield nothing.
def test_compactness_unknown_sides_skipped() -> None:
    frames = [
        [observation(frame(0, 0.0), "p1", (0.1, 0.3))],
        [observation(frame(1, 0.5), "p1", (0.9, 0.3))],
    ]
    assert TeamCompactnessDetector().detect(sequence(frames)) == []


# 8/9. Overload with valid inputs; invalid region rejected.
def test_spatial_overload() -> None:
    region = OverloadRegion(x_min=0.0, x_max=0.5, y_min=0.0, y_max=1.0)
    attackers = [
        observation(frame(0, 0.0), "h1", (0.1, 0.2), TeamSide.HOME),
        observation(frame(0, 0.0), "h2", (0.2, 0.4), TeamSide.HOME),
        observation(frame(0, 0.0), "h3", (0.3, 0.6), TeamSide.HOME),
        observation(frame(0, 0.0), "a1", (0.4, 0.5), TeamSide.AWAY),
    ]
    events = SpatialOverloadDetector(region, min_advantage=2).detect(
        sequence([attackers])
    )
    assert len(events) == 1
    assert events[0].metadata["leader"] == "HOME"
    assert events[0].start_frame == events[0].end_frame == 0
    with pytest.raises(ValueError):
        OverloadRegion(x_min=0.6, x_max=0.5, y_min=0.0, y_max=1.0)


def test_overload_without_opposition_presence_skipped() -> None:
    region = OverloadRegion(x_min=0.0, x_max=0.5, y_min=0.0, y_max=1.0)
    alone = [
        observation(frame(0, 0.0), "h1", (0.1, 0.2), TeamSide.HOME),
        observation(frame(0, 0.0), "h2", (0.2, 0.4), TeamSide.HOME),
    ]
    assert (
        SpatialOverloadDetector(region, min_advantage=1).detect(sequence([alone])) == []
    )


# 10. Possession declines explicitly.
def test_possession_detector_declines() -> None:
    seq = sequence([track_run("player-1", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.21, 0.3)])])
    detector = PossessionChangeDetector()
    assert detector.unsupported_reason
    assert detector.detect(seq) == []


# 11/12. Frame preservation + determinism.
def test_frames_and_determinism() -> None:
    frames = [
        track_run("player-1", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.5, 0.3)]),
        track_run("player-2", [(0, 0.0, 0.7, 0.3), (1, 0.5, 0.6, 0.3)]),
    ]
    seq = sequence(frames)
    first = [e.model_dump() for e in BaselineDetectorSuite().detect(seq)]
    second = [e.model_dump() for e in BaselineDetectorSuite().detect(seq)]
    assert first == second
    for event in BaselineDetectorSuite().detect(seq):
        assert event.start_frame <= event.end_frame
        assert event.match_id == MATCH_ID


# 13/14. No fabricated IDs or sides.
def test_no_fabricated_identity() -> None:
    seq = sequence([track_run("player-9", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.5, 0.3)])])
    (event,) = PlayerMovementDetector().detect(seq)
    assert event.evidence.track_ids == ("player-9",)
    assert (
        "team" not in event.metadata or isinstance(event.metadata["team"], str) is False
    )
    assert all("player_id" not in key for key in event.metadata)


# 16. Sources not mutated.
def test_sources_not_mutated() -> None:
    builder = TacticalStateBuilder()
    obs = track_run("player-1", [(0, 0.0, 0.2, 0.3), (1, 0.5, 0.5, 0.3)])
    snapshot = [o.model_dump() for o in obs]
    states = builder.build_sequence_from_observations(obs)
    state_snapshot = states.model_dump()
    BaselineDetectorSuite().detect(states)
    assert [o.model_dump() for o in obs] == snapshot
    assert states.model_dump() == state_snapshot


# 17/18. Empty/single-frame input.
def test_empty_and_insufficient_input() -> None:
    with pytest.raises(InvalidEventInput):
        PlayerMovementDetector().detect("nope")  # type: ignore[arg-type]
    single = sequence([[observation(frame(0, 0.0), "player-1", (0.2, 0.3))]])
    assert PlayerMovementDetector().detect(single) == []
    assert TeamCompactnessDetector().detect(single) == []
    assert (
        SpatialOverloadDetector(
            OverloadRegion(x_min=0, x_max=1, y_min=0, y_max=1)
        ).detect(single)
        == []
    )
    assert BaselineDetectorSuite().detect(single) == []


def test_human_verified_confidence_rule() -> None:
    base = dict(
        event_type=EventType.PLAYER_MOVEMENT,
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        start_frame=0,
        end_frame=1,
        start_timestamp=0.0,
        end_timestamp=0.5,
        detection_method=DetectionMethod.HUMAN_VERIFIED,
        evidence=EventEvidence(
            track_ids=("player-1",),
            start_frame=0,
            end_frame=1,
            detector_name="human",
        ),
    )
    assert TacticalEvent(**base).confidence is None
    with pytest.raises(ValueError):
        TacticalEvent(**{**base, "confidence": 0.9})


def test_detector_interface_and_bad_config() -> None:
    assert issubclass(PlayerMovementDetector, TacticalEventDetector)
    with pytest.raises(InvalidEventInput):
        PlayerMovementDetector(min_distance=0.0)
    with pytest.raises(InvalidEventInput):
        TeamCompactnessDetector(min_players=1)
    with pytest.raises(InvalidEventInput):
        SpatialOverloadDetector(
            OverloadRegion(x_min=0, x_max=1, y_min=0, y_max=1), min_advantage=0
        )
