"""Phase 07A — tactical state representation.

Converts Phase 06 :class:`VisionObservation` records into structured,
serializable football state without any tactical interpretation:

VisionObservation -> TacticalStateBuilder -> TacticalFrameState(s)
                                                 -> TacticalSequence

Hard rules:

- ``track_id`` is never a ``player_id``; ``player_id`` stays ``None``
  until a verified association exists (enforced by validators).
- ``team`` stays ``UNKNOWN`` unless explicitly supplied or verified;
  it is never inferred from position.
- Missing positions are ``None`` with validity ``MISSING`` — never
  silently ``(0, 0)``.
- Velocity is DERIVED (finite difference over real timestamps) or
  absent (``None``); never fabricated, never OBSERVED here.
- Domain objects only — no tensors, no torch, no numpy.

Units: positions are normalized pitch units (or metres when the source
space is METRIC); velocity is therefore units/second of that space.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.vision.schemas import (
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchSpace,
    VisionObservation,
)

MAX_PLAYERS_PER_FRAME = 32
MAX_SEQUENCE_FRAMES = 3600


class TacticalContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TeamAssociation(StrEnum):
    HOME = "HOME"
    AWAY = "AWAY"
    UNKNOWN = "UNKNOWN"


class PositionValidity(StrEnum):
    VALID = "VALID"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    MISSING = "MISSING"


class MotionSource(StrEnum):
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"


class Velocity2D(TacticalContract):
    """Finite-difference velocity with explicit provenance of derivation."""

    vx: float = Field(allow_inf_nan=False)
    vy: float = Field(allow_inf_nan=False)
    speed: float = Field(ge=0, allow_inf_nan=False)
    source: MotionSource = MotionSource.DERIVED
    delta_t_seconds: float = Field(gt=0, allow_inf_nan=False)


class TacticalPlayerState(TacticalContract):
    """One non-ball observation: position plus traceable provenance refs."""

    track_id: str = Field(min_length=1, max_length=100)
    player_id: UUID | None = None
    identity_verified: bool = False
    team: TeamAssociation = TeamAssociation.UNKNOWN
    object_class: ObjectClass
    pitch_x: float | None = Field(default=None, allow_inf_nan=False)
    pitch_y: float | None = Field(default=None, allow_inf_nan=False)
    validity: PositionValidity
    object_confidence: float = Field(ge=0, le=1)
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    match_id: UUID
    source_id: UUID
    velocity: Velocity2D | None = None
    mapping_point_type: MappingPointType | None = None
    coordinate_space: PitchSpace = PitchSpace.NORMALIZED
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)
    detector_name: str | None = Field(default=None, min_length=1, max_length=100)
    tracker_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_identity_association(self) -> TacticalPlayerState:
        if self.player_id is not None and not self.identity_verified:
            raise ValueError("Player identity requires a verified association")
        return self

    @model_validator(mode="after")
    def validate_position_presence(self) -> TacticalPlayerState:
        has_position = self.pitch_x is not None and self.pitch_y is not None
        if self.validity is PositionValidity.MISSING and has_position:
            raise ValueError("MISSING positions must not carry coordinates")
        if self.validity is not PositionValidity.MISSING and not has_position:
            raise ValueError("Non-missing positions require coordinates")
        return self


class TacticalBallState(TacticalContract):
    """The ball: same envelope as a player, no identity or team fields."""

    track_id: str = Field(min_length=1, max_length=100)
    object_class: ObjectClass = ObjectClass.BALL
    pitch_x: float | None = Field(default=None, allow_inf_nan=False)
    pitch_y: float | None = Field(default=None, allow_inf_nan=False)
    validity: PositionValidity
    object_confidence: float = Field(ge=0, le=1)
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    match_id: UUID
    source_id: UUID
    velocity: Velocity2D | None = None
    mapping_point_type: MappingPointType | None = None
    coordinate_space: PitchSpace = PitchSpace.NORMALIZED
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)
    detector_name: str | None = Field(default=None, min_length=1, max_length=100)
    tracker_name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_position_presence(self) -> TacticalBallState:
        has_position = self.pitch_x is not None and self.pitch_y is not None
        if self.validity is PositionValidity.MISSING and has_position:
            raise ValueError("MISSING positions must not carry coordinates")
        if self.validity is not PositionValidity.MISSING and not has_position:
            raise ValueError("Non-missing positions require coordinates")
        return self


class TacticalFrameState(TacticalContract):
    """The state of the pitch at one moment. ``ball=None`` means the ball
    was not observed — explicitly missing, never a fabricated position."""

    match_id: UUID
    source_id: UUID
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    players: list[TacticalPlayerState] = Field(max_length=MAX_PLAYERS_PER_FRAME)
    ball: TacticalBallState | None = None
    coordinate_space: PitchSpace = PitchSpace.NORMALIZED
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_frame_consistency(self) -> TacticalFrameState:
        for player in self.players:
            if (
                player.frame_index != self.frame_index
                or player.timestamp_seconds != self.timestamp_seconds
                or player.match_id != self.match_id
                or player.source_id != self.source_id
                or player.coordinate_space != self.coordinate_space
            ):
                raise ValueError("Player state must match its frame state")
        if self.ball is not None and (
            self.ball.frame_index != self.frame_index
            or self.ball.timestamp_seconds != self.timestamp_seconds
            or self.ball.match_id != self.match_id
            or self.ball.source_id != self.source_id
            or self.ball.coordinate_space != self.coordinate_space
        ):
            raise ValueError("Ball state must match its frame state")
        return self


class TacticalSequence(TacticalContract):
    """Chronologically ordered frames; future Transformer input domain."""

    frames: list[TacticalFrameState] = Field(
        min_length=1, max_length=MAX_SEQUENCE_FRAMES
    )

    @model_validator(mode="after")
    def validate_chronology(self) -> TacticalSequence:
        first = self.frames[0]
        for previous, current in zip(self.frames, self.frames[1:], strict=False):
            if current.frame_index <= previous.frame_index:
                raise ValueError("Frames must be strictly increasing in index")
            if current.timestamp_seconds < previous.timestamp_seconds:
                raise ValueError("Frames must not go backwards in time")
            if (
                current.match_id != first.match_id
                or current.source_id != first.source_id
                or current.coordinate_space != first.coordinate_space
            ):
                raise ValueError(
                    "Sequence frames must share match, video, and coordinate space"
                )
        return self


class BuilderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    derive_velocity: bool = True
    max_velocity_gap_seconds: float = Field(default=1.0, gt=0, le=60)


class InvalidTacticalInput(ValueError):
    """Observations cannot be converted to tactical state."""


def _validity_of(observation: VisionObservation) -> PositionValidity:
    if observation.pitch_coordinate is None:
        return PositionValidity.MISSING
    if observation.mapping_status is MappingStatus.FAILED:
        return PositionValidity.MISSING
    if observation.mapping_status is MappingStatus.OUT_OF_BOUNDS:
        return PositionValidity.OUT_OF_BOUNDS
    return PositionValidity.VALID


def _team_of(observation: VisionObservation) -> TeamAssociation:
    if observation.team_side is None:
        return TeamAssociation.UNKNOWN
    return TeamAssociation(observation.team_side.value)


def _player_state(observation: VisionObservation) -> TacticalPlayerState:
    coordinate = observation.pitch_coordinate
    return TacticalPlayerState(
        track_id=observation.tracking_id,
        player_id=observation.player_id,
        identity_verified=observation.identity_verified,
        team=_team_of(observation),
        object_class=observation.object_class,
        pitch_x=coordinate.x if coordinate is not None else None,
        pitch_y=coordinate.y if coordinate is not None else None,
        validity=_validity_of(observation),
        object_confidence=observation.detection_confidence,
        frame_index=observation.frame.frame_number,
        timestamp_seconds=observation.frame.timestamp_seconds,
        match_id=observation.match_id,
        source_id=observation.source_id,
        velocity=None,
        mapping_point_type=observation.mapping_point_type,
        coordinate_space=coordinate.space
        if coordinate is not None
        else PitchSpace.NORMALIZED,
        calibration_id=observation.calibration_id,
        detector_name=observation.detector_name,
        tracker_name=observation.tracker_name,
    )


def _ball_state(observation: VisionObservation) -> TacticalBallState:
    coordinate = observation.pitch_coordinate
    return TacticalBallState(
        track_id=observation.tracking_id,
        object_class=observation.object_class,
        pitch_x=coordinate.x if coordinate is not None else None,
        pitch_y=coordinate.y if coordinate is not None else None,
        validity=_validity_of(observation),
        object_confidence=observation.detection_confidence,
        frame_index=observation.frame.frame_number,
        timestamp_seconds=observation.frame.timestamp_seconds,
        match_id=observation.match_id,
        source_id=observation.source_id,
        velocity=None,
        mapping_point_type=observation.mapping_point_type,
        coordinate_space=coordinate.space
        if coordinate is not None
        else PitchSpace.NORMALIZED,
        calibration_id=observation.calibration_id,
        detector_name=observation.detector_name,
        tracker_name=observation.tracker_name,
    )


def _derive_velocity(
    previous_x: float,
    previous_y: float,
    current_x: float,
    current_y: float,
    delta_t: float,
) -> Velocity2D:
    vx = (current_x - previous_x) / delta_t
    vy = (current_y - previous_y) / delta_t
    return Velocity2D(
        vx=vx,
        vy=vy,
        speed=(vx**2 + vy**2) ** 0.5,
        source=MotionSource.DERIVED,
        delta_t_seconds=delta_t,
    )


class TacticalStateBuilder:
    """Stateless converter: observations in, tactical state out.

    Velocity is derived across consecutive sequence frames for identical
    track ids with valid positions and ``0 < dt <= max_gap``;
    otherwise velocity stays ``None`` (UNAVAILABLE, represented by absence).
    """

    def __init__(self, config: BuilderConfig | None = None) -> None:
        self.config = config or BuilderConfig()

    def build_frame(
        self, observations: Sequence[VisionObservation]
    ) -> TacticalFrameState:
        items = list(observations)
        if not items:
            raise InvalidTacticalInput("At least one observation is required")
        if any(not isinstance(item, VisionObservation) for item in items):
            raise InvalidTacticalInput("All items must be VisionObservation records")
        first = items[0]
        for item in items[1:]:
            if (
                item.frame != first.frame
                or item.match_id != first.match_id
                or item.source_id != first.source_id
            ):
                raise InvalidTacticalInput(
                    "A frame state requires one match/video/frame"
                )
        players = sorted(
            (
                _player_state(item)
                for item in items
                if item.object_class is not ObjectClass.BALL
            ),
            key=lambda player: player.track_id,
        )
        if len(players) > MAX_PLAYERS_PER_FRAME:
            raise InvalidTacticalInput("Too many player observations in one frame")
        balls = [
            _ball_state(item) for item in items if item.object_class is ObjectClass.BALL
        ]
        if len(balls) > 1:
            raise InvalidTacticalInput("At most one ball observation per frame")
        spaces = {player.coordinate_space for player in players} | {
            ball.coordinate_space
            for ball in balls
            if ball.validity is not PositionValidity.MISSING
        }
        if len(spaces) > 1:
            raise InvalidTacticalInput("Mixed coordinate spaces in one frame")
        return TacticalFrameState(
            match_id=first.match_id,
            source_id=first.source_id,
            frame_index=first.frame.frame_number,
            timestamp_seconds=first.frame.timestamp_seconds,
            players=players,
            ball=balls[0] if balls else None,
            coordinate_space=next(iter(spaces), PitchSpace.NORMALIZED),
            calibration_id=first.calibration_id,
        )

    def build_sequence(self, frames: Sequence[TacticalFrameState]) -> TacticalSequence:
        ordered = list(frames)
        if not ordered:
            raise InvalidTacticalInput("At least one frame state is required")
        if any(not isinstance(item, TacticalFrameState) for item in ordered):
            raise InvalidTacticalInput("All items must be TacticalFrameState records")
        sequence = TacticalSequence(frames=ordered)
        if self.config.derive_velocity:
            return self._with_velocities(sequence)
        return sequence

    def build_sequence_from_observations(
        self, observations: Sequence[VisionObservation]
    ) -> TacticalSequence:
        grouped: dict[int, list[VisionObservation]] = {}
        for item in observations:
            if not isinstance(item, VisionObservation):
                raise InvalidTacticalInput(
                    "All items must be VisionObservation records"
                )
            grouped.setdefault(item.frame.frame_number, []).append(item)
        frames = [self.build_frame(grouped[number]) for number in sorted(grouped)]
        return self.build_sequence(frames)

    def _with_velocities(self, sequence: TacticalSequence) -> TacticalSequence:
        previous: dict[str, TacticalPlayerState | TacticalBallState] = {}
        enriched: list[TacticalFrameState] = []
        for frame in sequence.frames:
            current: dict[str, TacticalPlayerState | TacticalBallState] = {}
            new_players = [
                self._attach_velocity(player, previous.get(player.track_id))
                for player in frame.players
            ]
            new_ball = (
                self._attach_velocity(frame.ball, previous.get(frame.ball.track_id))
                if frame.ball is not None
                else None
            )
            for state in (*new_players, *((new_ball,) if new_ball else ())):
                current[state.track_id] = state
            previous = current
            enriched.append(
                frame.model_copy(update={"players": new_players, "ball": new_ball})
            )
        return TacticalSequence(frames=enriched)

    def _attach_velocity(
        self,
        state: TacticalPlayerState | TacticalBallState,
        prior: TacticalPlayerState | TacticalBallState | None,
    ) -> TacticalPlayerState | TacticalBallState:
        if (
            prior is None
            or state.validity is PositionValidity.MISSING
            or prior.validity is PositionValidity.MISSING
            or state.pitch_x is None
            or state.pitch_y is None
            or prior.pitch_x is None
            or prior.pitch_y is None
        ):
            return state
        delta_t = state.timestamp_seconds - prior.timestamp_seconds
        if not 0 < delta_t <= self.config.max_velocity_gap_seconds:
            return state
        velocity = _derive_velocity(
            prior.pitch_x, prior.pitch_y, state.pitch_x, state.pitch_y, delta_t
        )
        return state.model_copy(update={"velocity": velocity})
