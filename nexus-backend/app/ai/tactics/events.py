"""Phase 07F — tactical event detection foundation.

Contracts plus deterministic RULE baselines over :class:`TacticalSequence`:

TacticalSequence -> TacticalEventDetector -> list[TacticalEvent]

Honesty rules:

- RULE baselines compute only what the inputs actually support.
- ML predictions are unwired: the models are untrained, so no neural
  classifier is connected. ``DetectionMethod.MODEL`` exists for the
  future trained classifier only.
- Confidence is method-aware: RULE baselines that lack a defined
  rule-confidence emit ``confidence=None``; HUMAN_VERIFIED events
  must never carry invented confidence (enforced).
- POSSESSION_CHANGE has a contract and an interface but no baseline:
  the available data cannot support it, so the detector explicitly
  declines instead of fabricating possession labels.

Every event carries evidence back to match/video/frames/tracks/coords.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.tactics.state import (
    PositionValidity,
    TacticalFrameState,
    TacticalPlayerState,
    TacticalSequence,
    TeamAssociation,
)

EVENT_DETECTOR_VERSION = "07F.1"
_EVENT_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class TacticalContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvalidEventInput(ValueError):
    """A sequence or configuration cannot yield tactical events."""


class EventType(StrEnum):
    POSSESSION_CHANGE = "POSSESSION_CHANGE"
    PLAYER_MOVEMENT = "PLAYER_MOVEMENT"
    TEAM_COMPACTNESS_CHANGE = "TEAM_COMPACTNESS_CHANGE"
    SPATIAL_OVERLOAD = "SPATIAL_OVERLOAD"


class DetectionMethod(StrEnum):
    RULE = "RULE"
    MODEL = "MODEL"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"


class PositionSample(TacticalContract):
    track_id: str = Field(min_length=1, max_length=100)
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    pitch_x: float = Field(allow_inf_nan=False)
    pitch_y: float = Field(allow_inf_nan=False)


class EventEvidence(TacticalContract):
    """Traceable backing for one event: frames, tracks, positions, origin."""

    track_ids: tuple[str, ...]
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    positions: tuple[PositionSample, ...] = ()
    detector_name: str = Field(min_length=1, max_length=100)
    detector_version: str = Field(default=EVENT_DETECTOR_VERSION, max_length=50)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_frame_order(self) -> EventEvidence:
        if self.end_frame < self.start_frame:
            raise ValueError("Evidence end frame must not precede start frame")
        return self


class TacticalEvent(TacticalContract):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    match_id: UUID
    source_id: UUID
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    start_timestamp: float = Field(ge=0, allow_inf_nan=False)
    end_timestamp: float = Field(ge=0, allow_inf_nan=False)
    confidence: float | None = Field(default=None, ge=0, le=1)
    detection_method: DetectionMethod
    evidence: EventEvidence
    metadata: dict[str, float | str | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_temporal_order(self) -> TacticalEvent:
        if self.end_frame < self.start_frame:
            raise ValueError("Event end frame must not precede start frame")
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("Event end time must not precede start time")
        return self

    @model_validator(mode="after")
    def validate_confidence_honesty(self) -> TacticalEvent:
        if self.detection_method is DetectionMethod.HUMAN_VERIFIED:
            if self.confidence is not None:
                raise ValueError("HUMAN_VERIFIED events must not invent confidence")
        return self


class TacticalEventDetector:
    """Interface: tactical state in, evidence-backed events out."""

    name: str = "base-detector"

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        raise NotImplementedError


def _deterministic_id(*parts: object) -> UUID:
    """Content-derived event IDs so identical inputs yield identical events."""
    from uuid import uuid5

    return uuid5(_EVENT_NAMESPACE, "|".join(str(part) for part in parts))


def _frames_of(sequence: TacticalSequence) -> list[TacticalFrameState]:
    if not isinstance(sequence, TacticalSequence):
        raise InvalidEventInput("A TacticalSequence is required")
    return list(sequence.frames)


def _player_positions(
    frame: TacticalFrameState,
) -> dict[str, TacticalPlayerState]:
    return {player.track_id: player for player in frame.players}


def _valid_sample(player: TacticalPlayerState) -> PositionSample | None:
    if (
        player.validity is PositionValidity.MISSING
        or player.pitch_x is None
        or player.pitch_y is None
    ):
        return None
    return PositionSample(
        track_id=player.track_id,
        frame_index=player.frame_index,
        timestamp_seconds=player.timestamp_seconds,
        pitch_x=player.pitch_x,
        pitch_y=player.pitch_y,
    )


class PlayerMovementDetector(TacticalEventDetector):
    """RULE baseline: maximal runs of consecutive valid positions with
    ``dt > 0`` per track; emits when travelled distance >= min_distance."""

    name = "player-movement-rule"

    def __init__(self, min_distance: float = 0.01) -> None:
        if not min_distance > 0:
            raise InvalidEventInput("min_distance must be positive")
        self.min_distance = min_distance

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        frames = _frames_of(sequence)
        by_track: dict[str, list[TacticalPlayerState]] = {}
        for frame in frames:
            for track_id, player in sorted(_player_positions(frame).items()):
                by_track.setdefault(track_id, []).append(player)
        events: list[TacticalEvent] = []
        for track_id in sorted(by_track):
            run: list[PositionSample] = []
            previous: PositionSample | None = None
            distance = 0.0
            for state in by_track[track_id]:
                sample = _valid_sample(state)
                if sample is None:
                    events.extend(self._flush(frames, track_id, run, distance))
                    run, distance, previous = [], 0.0, None
                    continue
                if previous is None:
                    run, previous = [sample], sample
                    continue
                delta_t = sample.timestamp_seconds - previous.timestamp_seconds
                if delta_t <= 0:
                    events.extend(self._flush(frames, track_id, run, distance))
                    run, distance, previous = [sample], 0.0, sample
                    continue
                distance += math.dist(
                    (previous.pitch_x, previous.pitch_y),
                    (sample.pitch_x, sample.pitch_y),
                )
                run.append(sample)
                previous = sample
            events.extend(self._flush(frames, track_id, run, distance))
        events.sort(key=lambda e: (e.start_frame, e.end_frame, e.event_id.hex))
        return events

    def _flush(
        self,
        frames: list[TacticalFrameState],
        track_id: str,
        run: list[PositionSample],
        distance: float,
    ) -> list[TacticalEvent]:
        if len(run) < 2 or distance < self.min_distance:
            return []
        first, last = run[0], run[-1]
        duration = last.timestamp_seconds - first.timestamp_seconds
        match_id = frames[0].match_id
        source_id = frames[0].source_id
        return [
            TacticalEvent(
                event_id=_deterministic_id(
                    EventType.PLAYER_MOVEMENT.value,
                    match_id,
                    source_id,
                    first.frame_index,
                    last.frame_index,
                    self.name,
                    track_id,
                    round(distance, 9),
                ),
                event_type=EventType.PLAYER_MOVEMENT,
                match_id=match_id,
                source_id=source_id,
                start_frame=first.frame_index,
                end_frame=last.frame_index,
                start_timestamp=first.timestamp_seconds,
                end_timestamp=last.timestamp_seconds,
                confidence=None,
                detection_method=DetectionMethod.RULE,
                evidence=EventEvidence(
                    track_ids=(track_id,),
                    start_frame=first.frame_index,
                    end_frame=last.frame_index,
                    positions=tuple(run),
                    detector_name=self.name,
                ),
                metadata={
                    "distance": distance,
                    "duration_seconds": duration,
                    "mean_speed": distance / duration if duration > 0 else 0.0,
                    "samples": float(len(run)),
                },
            )
        ]


class TeamCompactnessDetector(TacticalEventDetector):
    """RULE baseline: per-team width/depth/area/centroid per frame; emits
    when a known side's area changes relatively by >= threshold across
    consecutive frames. Frames without enough known-side players yield
    nothing — never fabricated."""

    name = "team-compactness-rule"

    def __init__(self, change_threshold: float = 0.5, min_players: int = 2) -> None:
        if not 0 < change_threshold:
            raise InvalidEventInput("change_threshold must be positive")
        if min_players < 2:
            raise InvalidEventInput("min_players must be at least 2")
        self.change_threshold = change_threshold
        self.min_players = min_players

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        frames = _frames_of(sequence)
        metrics = [self._frame_metrics(frame) for frame in frames]
        events: list[TacticalEvent] = []
        for first, second, first_m, second_m in zip(
            frames, frames[1:], metrics, metrics[1:], strict=False
        ):
            for team in (TeamAssociation.HOME, TeamAssociation.AWAY):
                before = first_m.get(team)
                after = second_m.get(team)
                if before is None or after is None:
                    continue
                change = abs(after["area"] - before["area"]) / max(before["area"], 1e-9)
                if change < self.change_threshold:
                    continue
                events.append(
                    TacticalEvent(
                        event_id=_deterministic_id(
                            EventType.TEAM_COMPACTNESS_CHANGE.value,
                            first.match_id,
                            first.source_id,
                            first.frame_index,
                            second.frame_index,
                            self.name,
                            team.value,
                            round(change, 9),
                        ),
                        event_type=EventType.TEAM_COMPACTNESS_CHANGE,
                        match_id=first.match_id,
                        source_id=first.source_id,
                        start_frame=first.frame_index,
                        end_frame=second.frame_index,
                        start_timestamp=first.timestamp_seconds,
                        end_timestamp=second.timestamp_seconds,
                        confidence=None,
                        detection_method=DetectionMethod.RULE,
                        evidence=EventEvidence(
                            track_ids=tuple(sorted(before["tracks"] | after["tracks"])),
                            start_frame=first.frame_index,
                            end_frame=second.frame_index,
                            detector_name=self.name,
                            notes=f"team={team.value}",
                        ),
                        metadata={
                            "team": team.value,
                            "area_before": before["area"],
                            "area_after": after["area"],
                            "relative_change": change,
                            "width_after": after["width"],
                            "depth_after": after["depth"],
                        },
                    )
                )
        events.sort(key=lambda e: (e.start_frame, e.end_frame, e.event_id.hex))
        return events

    def _frame_metrics(
        self, frame: TacticalFrameState
    ) -> dict[TeamAssociation, dict[str, object]]:
        grouped: dict[TeamAssociation, list[TacticalPlayerState]] = {}
        for player in frame.players:
            if player.team not in (TeamAssociation.HOME, TeamAssociation.AWAY):
                continue
            sample = _valid_sample(player)
            if sample is None:
                continue
            grouped.setdefault(player.team, []).append(player)
        out: dict[TeamAssociation, dict[str, object]] = {}
        for team, players in grouped.items():
            if len(players) < self.min_players:
                continue
            xs = [p.pitch_x for p in players if p.pitch_x is not None]
            ys = [p.pitch_y for p in players if p.pitch_y is not None]
            width = max(xs) - min(xs)
            depth = max(ys) - min(ys)
            out[team] = {
                "width": width,
                "depth": depth,
                "area": width * depth,
                "centroid_x": sum(xs) / len(xs),
                "centroid_y": sum(ys) / len(ys),
                "tracks": {p.track_id for p in players},
            }
        return out


class OverloadRegion(BaseModel):
    """Explicit normalized-pitch region for overload measurement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_region(self) -> OverloadRegion:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Region maximums must exceed minimums")
        return self

    def contains(self, x: float, y: float) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


class SpatialOverloadDetector(TacticalEventDetector):
    """RULE baseline: per frame, count known-side valid players inside the
    region; when the leader outnumbers the trailer by >= min_advantage
    (and the trailer fields >= 1), the frame is an overload frame.
    Consecutive frames with the same leader merge into one event. A pure
    headcount — never a claim of 'successful' overload."""

    name = "spatial-overload-rule"

    def __init__(
        self,
        region: OverloadRegion,
        min_advantage: int = 2,
    ) -> None:
        if min_advantage < 1:
            raise InvalidEventInput("min_advantage must be at least 1")
        self.region = region
        self.min_advantage = min_advantage

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        frames = _frames_of(sequence)
        events: list[TacticalEvent] = []
        run: list[tuple[TacticalFrameState, TeamAssociation, int, int]] = []
        leader: TeamAssociation | None = None
        for frame in frames:
            counts = self._count(frame)
            current: TeamAssociation | None = None
            home = counts.get(TeamAssociation.HOME, 0)
            away = counts.get(TeamAssociation.AWAY, 0)
            if home - away >= self.min_advantage and away >= 1:
                current = TeamAssociation.HOME
            elif away - home >= self.min_advantage and home >= 1:
                current = TeamAssociation.AWAY
            if current is None or current is not leader:
                events.extend(self._flush_run(run, leader))
                run = []
                leader = current
            if current is not None:
                run.append((frame, current, home, away))
        events.extend(self._flush_run(run, leader))
        events.sort(key=lambda e: (e.start_frame, e.end_frame, e.event_id.hex))
        return events

    def _count(self, frame: TacticalFrameState) -> dict[TeamAssociation, int]:
        counts: dict[TeamAssociation, int] = {}
        for player in frame.players:
            if player.team not in (TeamAssociation.HOME, TeamAssociation.AWAY):
                continue
            sample = _valid_sample(player)
            if sample is None:
                continue
            if self.region.contains(sample.pitch_x, sample.pitch_y):
                counts[player.team] = counts.get(player.team, 0) + 1
        return counts

    def _flush_run(
        self,
        run: list[tuple[TacticalFrameState, TeamAssociation, int, int]],
        leader: TeamAssociation | None,
    ) -> list[TacticalEvent]:
        if not run or leader is None:
            return []
        first = run[0][0]
        last = run[-1][0]
        return [
            TacticalEvent(
                event_id=_deterministic_id(
                    EventType.SPATIAL_OVERLOAD.value,
                    first.match_id,
                    first.source_id,
                    first.frame_index,
                    last.frame_index,
                    self.name,
                    leader.value,
                    len(run),
                ),
                event_type=EventType.SPATIAL_OVERLOAD,
                match_id=first.match_id,
                source_id=first.source_id,
                start_frame=first.frame_index,
                end_frame=last.frame_index,
                start_timestamp=first.timestamp_seconds,
                end_timestamp=last.timestamp_seconds,
                confidence=None,
                detection_method=DetectionMethod.RULE,
                evidence=EventEvidence(
                    track_ids=(),
                    start_frame=first.frame_index,
                    end_frame=last.frame_index,
                    detector_name=self.name,
                    notes=f"leader={leader.value} region headcount",
                ),
                metadata={
                    "leader": leader.value,
                    "frames": float(len(run)),
                    "min_advantage": float(self.min_advantage),
                },
            )
        ]


class PossessionChangeDetector(TacticalEventDetector):
    """Interface only: proximity-to-ball is not possession evidence, so
    this detector explicitly declines rather than fabricating labels."""

    name = "possession-change-unsupported"
    unsupported_reason = (
        "Ball proximity alone cannot evidence possession; "
        "contact/control observations are unavailable."
    )

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        _frames_of(sequence)
        return []


class BaselineDetectorSuite:
    """Runs the supported RULE baselines; possession stays declined."""

    def __init__(
        self,
        detectors: Sequence[TacticalEventDetector] | None = None,
    ) -> None:
        self.detectors: tuple[TacticalEventDetector, ...] = tuple(
            detectors
            if detectors is not None
            else (
                PlayerMovementDetector(),
                TeamCompactnessDetector(),
                SpatialOverloadDetector(
                    region=OverloadRegion(x_min=0.0, x_max=1.0, y_min=0.0, y_max=1.0)
                ),
                PossessionChangeDetector(),
            )
        )

    def detect(self, sequence: TacticalSequence) -> list[TacticalEvent]:
        events: list[TacticalEvent] = []
        for detector in self.detectors:
            events.extend(detector.detect(sequence))
        events.sort(
            key=lambda e: (
                e.start_frame,
                e.end_frame,
                e.event_type.value,
                e.event_id.hex,
            )
        )
        return events
