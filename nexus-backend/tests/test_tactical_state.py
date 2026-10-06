"""Phase 07A tactical-state tests. No interpretation is tested here —
only representation, provenance, ordering, and honest derived motion."""

from uuid import UUID

import pytest

from app.ai.tactics.state import (
    BuilderConfig,
    InvalidTacticalInput,
    MotionSource,
    PositionValidity,
    TacticalBallState,
    TacticalPlayerState,
    TacticalSequence,
    TacticalStateBuilder,
    TeamAssociation,
)
from app.ai.vision.schemas import (
    BoundingBox,
    FrameReference,
    ImagePoint,
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchCoordinate,
    PitchSpace,
    VisionObservation,
)

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def frame(number: int, timestamp: float | None = None) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=0.04 * number if timestamp is None else timestamp,
        width=640,
        height=360,
    )


def observation(
    ref: FrameReference,
    tracking_id: str,
    object_class: ObjectClass,
    pitch: tuple[float, float] | None,
    status: MappingStatus = MappingStatus.MAPPED,
    confidence: float = 0.9,
) -> VisionObservation:
    return VisionObservation(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame=ref,
        tracking_id=tracking_id,
        object_class=object_class,
        detection_confidence=confidence,
        bounding_box=BoundingBox(x_min=10, y_min=20, x_max=50, y_max=100),
        image_point=ImagePoint(x=30, y=100),
        mapping_point_type=MappingPointType.BOTTOM_CENTER,
        pitch_coordinate=(
            PitchCoordinate(x=pitch[0], y=pitch[1], coordinate_system="PITCH")
            if pitch is not None
            else None
        ),
        mapping_status=status,
        calibration_id="cal-1",
        detector_name="det",
        tracker_name="trk",
    )


def builder(**kwargs: object) -> TacticalStateBuilder:
    return TacticalStateBuilder(
        BuilderConfig(**kwargs) if kwargs else BuilderConfig()  # type: ignore[arg-type]
    )


# 1. Single tactical frame.
def test_single_tactical_frame() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    assert state.frame_index == 0
    assert state.players[0].pitch_x == pytest.approx(0.2)
    assert state.ball is None  # missing ball is explicit, not fabricated


# 2. Multiple players, deterministic order.
def test_multiple_players() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [
            observation(ref, "player-2", ObjectClass.PLAYER, (0.7, 0.3)),
            observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3)),
        ]
    )
    assert [p.track_id for p in state.players] == ["player-1", "player-2"]


# 3. Ball + players.
def test_ball_and_players() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [
            observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3)),
            observation(ref, "ball-1", ObjectClass.BALL, (0.5, 0.5)),
        ]
    )
    assert isinstance(state.ball, TacticalBallState)
    assert state.ball.pitch_x == pytest.approx(0.5)
    assert len(state.players) == 1


# 4/13. Unknown team side by default, never inferred.
def test_team_side_unknown_unless_verified() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.9, 0.9))]
    )
    assert state.players[0].team is TeamAssociation.UNKNOWN


# 5/18. Missing player position is not (0, 0).
def test_missing_position_is_explicit() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, None, MappingStatus.FAILED)]
    )
    player = state.players[0]
    assert player.validity is PositionValidity.MISSING
    assert player.pitch_x is None and player.pitch_y is None
    assert (player.pitch_x, player.pitch_y) != (0.0, 0.0)


# 6. Missing ball.
def test_missing_ball_is_none() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    assert state.ball is None


# 7. Invalid (out-of-bounds) pitch coordinate preserved + flagged.
def test_out_of_bounds_preserved_and_flagged() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [
            observation(
                ref,
                "player-1",
                ObjectClass.PLAYER,
                (1.4, 0.5),
                MappingStatus.OUT_OF_BOUNDS,
            )
        ]
    )
    player = state.players[0]
    assert player.validity is PositionValidity.OUT_OF_BOUNDS
    assert player.pitch_x == pytest.approx(1.4)  # raw preserved, not clamped


# 8/9. Multiple frames, chronological ordering.
def test_sequence_ordering() -> None:
    observations = [
        observation(frame(n), "player-1", ObjectClass.PLAYER, (0.1 * n, 0.3))
        for n in range(3)
    ]
    sequence = builder().build_sequence_from_observations(observations)
    assert [f.frame_index for f in sequence.frames] == [0, 1, 2]
    assert sequence.frames[0].timestamp_seconds < sequence.frames[2].timestamp_seconds


# 10. Duplicate/invalid frame handling.
def test_duplicate_frame_index_rejected() -> None:
    ref = frame(0)
    first = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    with pytest.raises(ValueError):
        TacticalSequence(frames=[first, first])
    with pytest.raises(InvalidTacticalInput):
        builder().build_frame([])
    with pytest.raises(InvalidTacticalInput):
        builder().build_frame(["nope"])  # type: ignore[list-item]
    mixed = [
        observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3)),
        observation(frame(1), "player-2", ObjectClass.PLAYER, (0.4, 0.3)),
    ]
    with pytest.raises(InvalidTacticalInput):
        builder().build_frame(mixed)


# 11/12. Track ID preserved; player ID stays None.
def test_identity_rules() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-9", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    assert state.players[0].track_id == "player-9"
    assert state.players[0].player_id is None
    with pytest.raises(ValueError):
        TacticalPlayerState(
            track_id="x",
            object_class=ObjectClass.PLAYER,
            pitch_x=0.1,
            pitch_y=0.1,
            validity=PositionValidity.VALID,
            object_confidence=0.9,
            frame_index=0,
            timestamp_seconds=0.0,
            match_id=MATCH_ID,
            source_id=SOURCE_ID,
            player_id=UUID(int=1),
        )


# 14/15. Provenance + identifiers preserved.
def test_provenance_and_identifiers() -> None:
    ref = frame(0)
    state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    player = state.players[0]
    assert state.match_id == MATCH_ID == player.match_id
    assert state.source_id == SOURCE_ID == player.source_id
    assert player.calibration_id == "cal-1"
    assert player.detector_name == "det"
    assert player.tracker_name == "trk"
    assert player.mapping_point_type is MappingPointType.BOTTOM_CENTER
    assert player.coordinate_space is PitchSpace.NORMALIZED
    assert player.object_confidence == pytest.approx(0.9)


# 16. Derived velocity with valid timestamps.
def test_derived_velocity() -> None:
    observations = [
        observation(
            frame(0, timestamp=0.0), "player-1", ObjectClass.PLAYER, (0.2, 0.3)
        ),
        observation(
            frame(1, timestamp=0.5), "player-1", ObjectClass.PLAYER, (0.3, 0.3)
        ),
    ]
    sequence = builder().build_sequence_from_observations(observations)
    first, second = sequence.frames
    assert first.players[0].velocity is None
    velocity = second.players[0].velocity
    assert velocity is not None
    assert velocity.source is MotionSource.DERIVED
    assert velocity.vx == pytest.approx(0.2)
    assert velocity.vy == pytest.approx(0.0)
    assert velocity.speed == pytest.approx(0.2)
    assert velocity.delta_t_seconds == pytest.approx(0.5)


# 17. Velocity unavailable on bad timestamps/gaps.
def test_velocity_unavailable_without_valid_dt() -> None:
    same_time = [
        observation(
            frame(0, timestamp=1.0), "player-1", ObjectClass.PLAYER, (0.2, 0.3)
        ),
        observation(
            frame(1, timestamp=1.0), "player-1", ObjectClass.PLAYER, (0.3, 0.3)
        ),
    ]
    sequence = builder().build_sequence_from_observations(same_time)
    assert sequence.frames[1].players[0].velocity is None

    wide_gap = [
        observation(
            frame(0, timestamp=0.0), "player-1", ObjectClass.PLAYER, (0.2, 0.3)
        ),
        observation(
            frame(5, timestamp=10.0), "player-1", ObjectClass.PLAYER, (0.3, 0.3)
        ),
    ]
    sequence = builder().build_sequence_from_observations(wide_gap)
    assert sequence.frames[1].players[0].velocity is None

    missing_first = [
        observation(
            frame(0), "player-1", ObjectClass.PLAYER, None, MappingStatus.FAILED
        ),
        observation(frame(1), "player-1", ObjectClass.PLAYER, (0.3, 0.3)),
    ]
    sequence = builder().build_sequence_from_observations(missing_first)
    assert sequence.frames[1].players[0].velocity is None


# 19. Deterministic output.
def test_deterministic_output() -> None:
    ref = frame(0)
    items = [
        observation(ref, "player-2", ObjectClass.PLAYER, (0.7, 0.3)),
        observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3)),
        observation(ref, "ball-1", ObjectClass.BALL, (0.5, 0.5)),
    ]
    first = builder().build_frame(items).model_dump()
    second = builder().build_frame(list(reversed(items))).model_dump()
    assert first == second


# 20. Source observations not mutated.
def test_source_observations_not_mutated() -> None:
    items = [
        observation(frame(n), "player-1", ObjectClass.PLAYER, (0.1 * n, 0.3))
        for n in range(3)
    ]
    snapshot = [item.model_dump() for item in items]
    builder().build_sequence_from_observations(items)
    assert [item.model_dump() for item in items] == snapshot


def test_mixed_coordinate_space_rejected() -> None:
    ref = frame(0)
    normal = observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))
    metric = observation(ref, "player-2", ObjectClass.PLAYER, (21.0, 20.4))
    metric = metric.model_copy(
        update={
            "pitch_coordinate": PitchCoordinate(
                x=21.0, y=20.4, coordinate_system="PITCH", space=PitchSpace.METRIC
            )
        }
    )
    with pytest.raises(InvalidTacticalInput):
        builder().build_frame([normal, metric])


def test_sequence_bounds_and_types() -> None:
    with pytest.raises(InvalidTacticalInput):
        builder().build_sequence([])
    with pytest.raises(InvalidTacticalInput):
        builder().build_sequence_from_observations([])
    ref = frame(0)
    frame_state = builder().build_frame(
        [observation(ref, "player-1", ObjectClass.PLAYER, (0.2, 0.3))]
    )
    sequence = builder(derive_velocity=False).build_sequence([frame_state])
    assert len(sequence.frames) == 1
    assert sequence.frames[0].players[0].velocity is None
