"""Phase 07B-1 feature-encoder tests: numeric correctness, masks,
determinism, and source preservation. No model, no tensors."""

from uuid import UUID

import pytest

from app.ai.tactics.encoding import (
    ENCODER_VERSION,
    PLAYER_FEATURE_DIM,
    EncodedTacticalFrame,
    InvalidEncodingInput,
    TacticalFeatureEncoder,
)
from app.ai.tactics.state import (
    PositionValidity,
    TacticalFrameState,
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
    object_class: ObjectClass,
    pitch: tuple[float, float] | None,
    team_side: object = None,
) -> VisionObservation:
    return VisionObservation(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame=ref,
        tracking_id=tracking_id,
        object_class=object_class,
        detection_confidence=0.75,
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
        team_side=team_side,  # type: ignore[arg-type]
    )


def frame_state(
    number: int, timestamp: float, *items: VisionObservation
) -> TacticalFrameState:
    refs = {item.frame for item in items}
    assert len(refs) == 1, "helper builds single-frame states"
    return TacticalStateBuilder().build_frame(list(items))


def player_obs(
    ref: FrameReference, track_id: str, x: float, y: float
) -> VisionObservation:
    return observation(ref, track_id, ObjectClass.PLAYER, (x, y))


# 1. Correct position encoding.
def test_position_encoding() -> None:
    ref = frame(0, 0.0)
    state = frame_state(0, 0.0, player_obs(ref, "player-1", 0.25, 0.75))
    (player,) = TacticalFeatureEncoder().encode_frame(state).players
    assert len(player.features) == PLAYER_FEATURE_DIM
    assert player.features[0] == pytest.approx(0.25)
    assert player.features[1] == pytest.approx(0.75)
    assert player.features[5] == pytest.approx(0.75)
    assert player.has_position is True


# 2. Home/away/unknown encoding.
def test_team_encoding() -> None:
    from app.ai.vision.schemas import TeamSide

    ref = frame(0, 0.0)
    home = observation(ref, "p-h", ObjectClass.PLAYER, (0.2, 0.3), TeamSide.HOME)
    away = observation(ref, "p-a", ObjectClass.PLAYER, (0.4, 0.3), TeamSide.AWAY)
    unknown = observation(ref, "p-u", ObjectClass.PLAYER, (0.6, 0.3))
    encoded = TacticalFeatureEncoder().encode_frame(
        TacticalStateBuilder().build_frame([home, away, unknown])
    )
    by_id = {p.track_id: p for p in encoded.players}
    assert by_id["p-h"].features[6:9] == (1.0, 0.0, 0.0)
    assert by_id["p-a"].features[6:9] == (0.0, 1.0, 0.0)
    assert by_id["p-u"].features[6:9] == (0.0, 0.0, 1.0)


# 3. Missing position mask (never silently 0,0 without a flag).
def test_missing_position_mask() -> None:
    ref = frame(0, 0.0)
    missing = observation(ref, "player-1", ObjectClass.PLAYER, None)
    # A genuinely missing position at the origin must still read as missing.
    origin = observation(ref, "player-2", ObjectClass.PLAYER, (0.0, 0.0))
    encoded = TacticalFeatureEncoder().encode_frame(
        TacticalStateBuilder().build_frame([missing, origin])
    )
    by_id = {p.track_id: p for p in encoded.players}
    assert by_id["player-1"].has_position is False
    assert by_id["player-1"].features[0] == 0.0
    assert by_id["player-2"].has_position is True


# 4/5. Missing vs valid velocity.
def test_velocity_masks() -> None:
    states = TacticalStateBuilder().build_sequence_from_observations(
        [
            player_obs(frame(0, 0.0), "player-1", 0.2, 0.3),
            player_obs(frame(1, 0.5), "player-1", 0.3, 0.3),
        ]
    )
    first, second = TacticalFeatureEncoder().encode_sequence(states)
    assert first.players[0].has_velocity is False
    assert first.players[0].features[2:5] == (0.0, 0.0, 0.0)
    assert second.players[0].has_velocity is True
    assert second.players[0].features[2] == pytest.approx(0.2)
    assert second.players[0].features[4] == pytest.approx(0.2)
    assert first.delta_t_seconds is None
    assert second.delta_t_seconds == pytest.approx(0.5)


# 6. Ball encoding stays separate with zeroed team bits.
def test_ball_encoding() -> None:
    ref = frame(0, 0.0)
    state = frame_state(
        0,
        0.0,
        player_obs(ref, "player-1", 0.2, 0.3),
        observation(ref, "ball-1", ObjectClass.BALL, (0.5, 0.5)),
    )
    encoded = TacticalFeatureEncoder().encode_frame(state)
    assert encoded.ball is not None
    assert encoded.ball.track_id == "ball-1"
    assert encoded.ball.object_class is ObjectClass.BALL
    assert encoded.ball.features[0] == pytest.approx(0.5)
    assert encoded.ball.features[6:9] == (0.0, 0.0, 0.0)
    assert all(p.object_class is not ObjectClass.BALL for p in encoded.players)


# 7/8. Multiple players + track ID preservation.
def test_multiple_players_track_ids() -> None:
    ref = frame(0, 0.0)
    state = frame_state(
        0,
        0.0,
        player_obs(ref, "player-2", 0.7, 0.3),
        player_obs(ref, "player-1", 0.2, 0.3),
    )
    encoded = TacticalFeatureEncoder().encode_frame(state)
    assert [p.track_id for p in encoded.players] == ["player-1", "player-2"]
    assert encoded.frame_index == 0
    assert encoded.encoder_version == ENCODER_VERSION


# 9. Deterministic output.
def test_deterministic_output() -> None:
    ref = frame(0, 0.0)
    items = [
        player_obs(ref, "player-2", 0.7, 0.3),
        player_obs(ref, "player-1", 0.2, 0.3),
        observation(ref, "ball-1", ObjectClass.BALL, (0.5, 0.5)),
    ]
    first = TacticalFeatureEncoder().encode_frame(
        TacticalStateBuilder().build_frame(items)
    )
    second = TacticalFeatureEncoder().encode_frame(
        TacticalStateBuilder().build_frame(list(reversed(items)))
    )
    assert first.model_dump() == second.model_dump()
    assert isinstance(first, EncodedTacticalFrame)


# 10. No mutation of source TacticalFrameState.
def test_source_state_not_mutated() -> None:
    ref = frame(0, 0.0)
    state = frame_state(0, 0.0, player_obs(ref, "player-1", 0.2, 0.3))
    snapshot = state.model_dump()
    TacticalFeatureEncoder().encode_frame(state)
    TacticalSequence(frames=[state])
    assert state.model_dump() == snapshot


def test_invalid_inputs_rejected() -> None:
    encoder = TacticalFeatureEncoder()
    with pytest.raises(InvalidEncodingInput):
        encoder.encode_frame("nope")  # type: ignore[arg-type]
    with pytest.raises(InvalidEncodingInput):
        encoder.encode_sequence("nope")  # type: ignore[arg-type]
    with pytest.raises(InvalidEncodingInput):
        encoder.encode_player("nope")  # type: ignore[arg-type]
    with pytest.raises(InvalidEncodingInput):
        encoder.encode_ball("nope")  # type: ignore[arg-type]


def test_metadata_preserved() -> None:
    ref = frame(3, 0.12)
    state = frame_state(3, 0.12, player_obs(ref, "player-1", 0.2, 0.3))
    encoded = TacticalFeatureEncoder().encode_frame(state)
    assert encoded.match_id == MATCH_ID
    assert encoded.source_id == SOURCE_ID
    assert encoded.timestamp_seconds == pytest.approx(0.12)
    assert encoded.coordinate_space.value == "NORMALIZED"
    assert all(p.has_velocity is False for p in encoded.players)
    assert TeamAssociation.UNKNOWN is not None
    assert PositionValidity.VALID is not None
