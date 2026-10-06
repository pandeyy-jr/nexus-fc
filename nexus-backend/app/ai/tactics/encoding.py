"""Phase 07B-1 — tactical feature encoder.

Converts :class:`TacticalFrameState` / :class:`TacticalSequence` into a
deterministic, serializable numerical representation for the future
temporal Transformer. Domain layer only: plain floats, no tensors,
no torch, no numpy.

Feature layout (versioned by ``ENCODER_VERSION``)::

    [x, y, vx, vy, speed, confidence, is_home, is_away, is_unknown]

Padding rule (the only place zeros stand in for absence, always gated
by explicit masks): missing positions encode as ``0.0`` with
``has_position=False``; missing velocity encodes as ``0.0`` with
``has_velocity=False``. Velocity is never computed here — only the
07A builder derives it. The ball uses the same width with team bits
zeroed and lives in its own field, never among players.
"""

from __future__ import annotations

from math import isfinite
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.tactics.state import (
    MAX_PLAYERS_PER_FRAME,
    PositionValidity,
    TacticalBallState,
    TacticalFrameState,
    TacticalPlayerState,
    TacticalSequence,
    TeamAssociation,
)
from app.ai.vision.schemas import ObjectClass, PitchSpace

ENCODER_VERSION = "07B-1.1"
PLAYER_FEATURE_DIM = 9


class EncodingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvalidEncodingInput(ValueError):
    """Tactical state cannot be encoded to features."""


class EncodedEntity(EncodingContract):
    """One tracked object as a fixed-width feature vector plus masks."""

    track_id: str = Field(min_length=1, max_length=100)
    object_class: ObjectClass
    features: tuple[float, ...]
    has_position: bool
    has_velocity: bool

    @model_validator(mode="after")
    def validate_vector_contract(self) -> EncodedEntity:
        if len(self.features) != PLAYER_FEATURE_DIM:
            raise ValueError(f"Feature vector must hold {PLAYER_FEATURE_DIM} values")
        if any(not isfinite(value) for value in self.features):
            raise ValueError("Feature values must be finite")
        x, y, vx, vy, speed = self.features[:5]
        if not self.has_position and (x != 0.0 or y != 0.0):
            raise ValueError("Masked-out positions must be zero-padded")
        if not self.has_velocity and (vx != 0.0 or vy != 0.0 or speed != 0.0):
            raise ValueError("Masked-out velocity must be zero-padded")
        return self


class EncodedTacticalFrame(EncodingContract):
    match_id: UUID
    source_id: UUID
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    delta_t_seconds: float | None = Field(default=None, ge=0)
    players: tuple[EncodedEntity, ...]
    ball: EncodedEntity | None = None
    coordinate_space: PitchSpace = PitchSpace.NORMALIZED
    encoder_version: str = ENCODER_VERSION


def _team_bits(team: TeamAssociation | None) -> tuple[float, float, float]:
    if team is TeamAssociation.HOME:
        return (1.0, 0.0, 0.0)
    if team is TeamAssociation.AWAY:
        return (0.0, 1.0, 0.0)
    return (0.0, 0.0, 1.0)


def _encode_entity(
    track_id: str,
    object_class: ObjectClass,
    x: float | None,
    y: float | None,
    validity: PositionValidity,
    confidence: float,
    team_bits: tuple[float, float, float],
    vx: float | None,
    vy: float | None,
    speed: float | None,
) -> EncodedEntity:
    has_position = (
        x is not None and y is not None and validity is not PositionValidity.MISSING
    )
    has_velocity = (
        has_position and vx is not None and vy is not None and speed is not None
    )
    features = (
        x if has_position and x is not None else 0.0,
        y if has_position and y is not None else 0.0,
        vx if has_velocity and vx is not None else 0.0,
        vy if has_velocity and vy is not None else 0.0,
        speed if has_velocity and speed is not None else 0.0,
        confidence,
        *team_bits,
    )
    return EncodedEntity(
        track_id=track_id,
        object_class=object_class,
        features=features,
        has_position=has_position,
        has_velocity=has_velocity,
    )


class TacticalFeatureEncoder:
    """Stateless encoder: tactical state in, feature frames out."""

    version = ENCODER_VERSION

    def encode_frame(self, state: TacticalFrameState) -> EncodedTacticalFrame:
        if not isinstance(state, TacticalFrameState):
            raise InvalidEncodingInput("A TacticalFrameState is required")
        if len(state.players) > MAX_PLAYERS_PER_FRAME:
            raise InvalidEncodingInput("Too many players in one frame")
        players = tuple(
            sorted(
                (self.encode_player(player) for player in state.players),
                key=lambda entity: entity.track_id,
            )
        )
        ball = self.encode_ball(state.ball) if state.ball is not None else None
        return EncodedTacticalFrame(
            match_id=state.match_id,
            source_id=state.source_id,
            frame_index=state.frame_index,
            timestamp_seconds=state.timestamp_seconds,
            delta_t_seconds=None,
            players=players,
            ball=ball,
            coordinate_space=state.coordinate_space,
            encoder_version=self.version,
        )

    def encode_sequence(
        self, sequence: TacticalSequence
    ) -> tuple[EncodedTacticalFrame, ...]:
        if not isinstance(sequence, TacticalSequence):
            raise InvalidEncodingInput("A TacticalSequence is required")
        encoded: list[EncodedTacticalFrame] = []
        previous_timestamp: float | None = None
        for frame in sequence.frames:
            current = self.encode_frame(frame)
            delta_t: float | None = None
            if previous_timestamp is not None:
                delta_t = current.timestamp_seconds - previous_timestamp
                if delta_t < 0:
                    raise InvalidEncodingInput("Sequence timestamps go backwards")
            previous_timestamp = current.timestamp_seconds
            encoded.append(current.model_copy(update={"delta_t_seconds": delta_t}))
        return tuple(encoded)

    @staticmethod
    def encode_player(player: TacticalPlayerState) -> EncodedEntity:
        if not isinstance(player, TacticalPlayerState):
            raise InvalidEncodingInput("A TacticalPlayerState is required")
        velocity = player.velocity
        return _encode_entity(
            track_id=player.track_id,
            object_class=player.object_class,
            x=player.pitch_x,
            y=player.pitch_y,
            validity=player.validity,
            confidence=player.object_confidence,
            team_bits=_team_bits(player.team),
            vx=velocity.vx if velocity else None,
            vy=velocity.vy if velocity else None,
            speed=velocity.speed if velocity else None,
        )

    @staticmethod
    def encode_ball(ball: TacticalBallState) -> EncodedEntity:
        if not isinstance(ball, TacticalBallState):
            raise InvalidEncodingInput("A TacticalBallState is required")
        velocity = ball.velocity
        return _encode_entity(
            track_id=ball.track_id,
            object_class=ball.object_class,
            x=ball.pitch_x,
            y=ball.pitch_y,
            validity=ball.validity,
            confidence=ball.object_confidence,
            team_bits=(0.0, 0.0, 0.0),
            vx=velocity.vx if velocity else None,
            vy=velocity.vy if velocity else None,
            speed=velocity.speed if velocity else None,
        )
