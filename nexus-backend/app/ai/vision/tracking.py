"""Phase 06E — detection-to-track association.

Converts frame-level :class:`Detection` objects into temporally consistent
:class:`TrackingFrame` outputs without ever assigning club player identity.

Domain separation (never confused here):

- ``Detection.object_class`` — what was observed (PLAYER, BALL, ...).
- ``TrackedObject.tracking_id`` — temporal identity (e.g. ``"player-3"``).
- ``TrackedObject.player_id`` — club identity (always ``None`` here).

Only :class:`DeterministicIoUTracker` is a real implementation. The
ByteTrack/BoT-SORT adapters exist as explicit integration points and fail
with :class:`TrackerUnavailable` until their optional dependency is
installed — the pipeline must never depend on those libraries directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.ai.vision.schemas import (
    BallTrack,
    Detection,
    FrameReference,
    ObjectClass,
    PlayerTrack,
    TrackedObject,
    TrackingFrame,
)

TRACKER_NAME = "nexus-deterministic-iou"
TRACKER_VERSION = "06E.1"

# Hard bound so a corrupt/malicious frame cannot exhaust memory.
MAX_DETECTIONS_PER_FRAME = 256


class TrackLifecycle(StrEnum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    LOST = "LOST"
    TERMINATED = "TERMINATED"


class ObservationKind(StrEnum):
    """Evidence provenance for an emitted track."""

    OBSERVED = "OBSERVED"
    PREDICTED = "PREDICTED"


class TrackerUnavailable(RuntimeError):
    """An optional external tracker backend is not installed/usable."""


class InvalidTrackInput(ValueError):
    """A frame reference or detection sequence cannot be tracked."""


class TrackerLimitExceeded(RuntimeError):
    """Bounded-processing guard: too many detections or live tracks."""


class StreamConfig(BaseModel):
    """Per-stream lifecycle/matching behaviour.

    The ball stream deliberately differs from the player stream: a football
    moves faster (lower IoU overlap frame-to-frame) and is occluded more
    often (longer retention), so sharing player parameters would be wrong.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_missed_frames: int = Field(default=5, ge=0, le=60)
    min_hits: int = Field(default=1, ge=1, le=60)
    iou_threshold: float = Field(default=0.3, ge=0, le=1)
    max_tracks: int = Field(default=32, ge=1, le=256)


class TrackerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player: StreamConfig = StreamConfig()
    ball: StreamConfig = StreamConfig(
        max_missed_frames=10,
        min_hits=1,
        iou_threshold=0.1,
        max_tracks=4,
    )
    tracker_name: str = Field(default=TRACKER_NAME, min_length=1, max_length=100)
    tracker_version: str = Field(default=TRACKER_VERSION, min_length=1, max_length=50)


@dataclass(frozen=True)
class TrackerProvenance:
    """Sidecar metadata — kept out of the schema so contracts stay stable."""

    tracker_name: str
    tracker_version: str
    observation: ObservationKind = ObservationKind.OBSERVED
    detector_name: str | None = None


@dataclass(frozen=True)
class TrackSummary:
    """Evaluation-ready per-track record (no metrics are computed here)."""

    tracking_id: str
    object_class: ObjectClass
    hits: int
    misses: int
    state: TrackLifecycle


@dataclass
class _TrackState:
    tracking_id: str
    object_class: ObjectClass
    bounding_box_coords: tuple[float, float, float, float]
    hits: int = 1
    misses: int = 0
    state: TrackLifecycle = TrackLifecycle.TENTATIVE

    def confirm_if_ready(self, min_hits: int) -> None:
        if self.hits >= min_hits and self.state == TrackLifecycle.TENTATIVE:
            self.state = TrackLifecycle.CONFIRMED


def _iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    inter_x_min = max(left[0], right[0])
    inter_y_min = max(left[1], right[1])
    inter_x_max = min(left[2], right[2])
    inter_y_max = min(left[3], right[3])
    inter_w = max(0.0, inter_x_max - inter_x_min)
    inter_h = max(0.0, inter_y_max - inter_y_min)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - inter
    return inter / union if union > 0 else 0.0


def _coords(detection: Detection) -> tuple[float, float, float, float]:
    box = detection.bounding_box
    return (box.x_min, box.y_min, box.x_max, box.y_max)


def _validate_detections(
    frame: FrameReference, detections: Sequence[Detection]
) -> list[Detection]:
    if not isinstance(frame, FrameReference):
        raise InvalidTrackInput("A valid frame reference is required")
    if detections is None or isinstance(detections, (str, bytes)):
        raise InvalidTrackInput("Detections must be a sequence of Detection objects")
    items = list(detections)
    if len(items) > MAX_DETECTIONS_PER_FRAME:
        raise TrackerLimitExceeded(
            f"Too many detections ({len(items)}); limit is {MAX_DETECTIONS_PER_FRAME}"
        )
    for item in items:
        if not isinstance(item, Detection):
            raise InvalidTrackInput("All detections must be Detection instances")
        if item.frame != frame:
            raise InvalidTrackInput("All detections must reference the tracked frame")
    return items


def _build_tracked_object(detection: Detection, tracking_id: str) -> TrackedObject:
    """Copy (never alias) detection evidence into a tracked object."""
    if detection.object_class == ObjectClass.BALL:
        return BallTrack(
            frame=detection.frame,
            object_class=detection.object_class,
            confidence=detection.confidence,
            bounding_box=detection.bounding_box,
            tracking_id=tracking_id,
            player_id=None,
            identity_verified=False,
        )
    if detection.object_class in (ObjectClass.PLAYER, ObjectClass.GOALKEEPER):
        return PlayerTrack(
            frame=detection.frame,
            object_class=detection.object_class,
            confidence=detection.confidence,
            bounding_box=detection.bounding_box,
            tracking_id=tracking_id,
            player_id=None,
            identity_verified=False,
        )
    return TrackedObject(
        frame=detection.frame,
        object_class=detection.object_class,
        confidence=detection.confidence,
        bounding_box=detection.bounding_box,
        tracking_id=tracking_id,
        player_id=None,
        identity_verified=False,
    )


class DeterministicIoUTracker:
    """Lightweight CPU-only tracker: greedy IoU matching per object class.

    - Matched detection → track continues with the same ``tracking_id``.
    - Unmatched detection → a new ``TENTATIVE`` track (confirmed after
      ``min_hits`` consecutive observations; withheld until then).
    - Unmatched track with ``misses <= max_missed_frames`` → ``LOST``,
      retained internally but **not emitted** (no invented positions).
    - Unmatched track beyond ``max_missed_frames`` → ``TERMINATED``.

    Every emitted track is therefore ``OBSERVED``; this tracker never emits
    ``PREDICTED`` boxes.
    """

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._tracks: dict[str, _TrackState] = {}
        self._counters: dict[ObjectClass, int] = {}
        self._provenance = TrackerProvenance(
            tracker_name=self.config.tracker_name,
            tracker_version=self.config.tracker_version,
            observation=ObservationKind.OBSERVED,
        )

    @property
    def provenance(self) -> TrackerProvenance:
        return self._provenance

    def reset(self) -> None:
        self._tracks.clear()
        self._counters.clear()

    def track(
        self, frame: FrameReference, detections: Sequence[Detection]
    ) -> TrackingFrame:
        """Pipeline-protocol entry point (alias of :meth:`update`)."""
        return self.update(frame, detections)

    def update(
        self, frame: FrameReference, detections: Sequence[Detection]
    ) -> TrackingFrame:
        items = _validate_detections(frame, detections)

        # Group detection indices by exact object class so players, the ball,
        # referees, etc. never share an identity namespace.
        by_class: dict[ObjectClass, list[int]] = {}
        for index, detection in enumerate(items):
            by_class.setdefault(detection.object_class, []).append(index)

        live_by_class: dict[ObjectClass, list[_TrackState]] = {}
        for track in self._tracks.values():
            if track.state is not TrackLifecycle.TERMINATED:
                live_by_class.setdefault(track.object_class, []).append(track)

        matched_detection: set[int] = set()
        emitted: list[tuple[int, TrackedObject]] = []

        for object_class in sorted(
            set(by_class) | set(live_by_class), key=lambda cls: cls.value
        ):
            indices = by_class.get(object_class, [])
            stream = self._stream_for(object_class)
            live = live_by_class.get(object_class, [])
            pairs: list[tuple[float, str, int]] = []
            for track in live:
                for index in indices:
                    score = _iou(track.bounding_box_coords, _coords(items[index]))
                    if score >= stream.iou_threshold:
                        pairs.append((score, track.tracking_id, index))
            # Greedy best-first; track_id / index break ties deterministically.
            pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2]))
            matched_tracks: set[str] = set()
            assignment: dict[int, str] = {}
            for _, tracking_id, index in pairs:
                if tracking_id in matched_tracks or index in matched_detection:
                    continue
                matched_tracks.add(tracking_id)
                matched_detection.add(index)
                assignment[index] = tracking_id

            for track in live:
                if track.tracking_id in matched_tracks:
                    continue
                track.misses += 1
                if track.misses > stream.max_missed_frames:
                    track.state = TrackLifecycle.TERMINATED
                elif track.state is not TrackLifecycle.TENTATIVE:
                    track.state = TrackLifecycle.LOST

            for index in indices:
                detection = items[index]
                if index in assignment:
                    track = self._tracks[assignment[index]]
                    track.bounding_box_coords = _coords(detection)
                    track.hits += 1
                    track.misses = 0
                    track.confirm_if_ready(stream.min_hits)
                    track.state = TrackLifecycle.CONFIRMED
                    emitted.append(
                        (index, _build_tracked_object(detection, track.tracking_id))
                    )
                else:
                    self._assert_capacity(object_class, stream)
                    tracking_id = self._next_id(object_class)
                    state = (
                        TrackLifecycle.CONFIRMED
                        if stream.min_hits <= 1
                        else TrackLifecycle.TENTATIVE
                    )
                    self._tracks[tracking_id] = _TrackState(
                        tracking_id=tracking_id,
                        object_class=object_class,
                        bounding_box_coords=_coords(detection),
                        hits=1,
                        misses=0,
                        state=state,
                    )
                    if state is TrackLifecycle.CONFIRMED:
                        emitted.append(
                            (index, _build_tracked_object(detection, tracking_id))
                        )

        self._purge_terminated()
        emitted.sort(key=lambda pair: pair[0])
        return TrackingFrame(frame=frame, tracks=[track for _, track in emitted])

    def summaries(self) -> list[TrackSummary]:
        """Evaluation-ready records for future IDF1/MOTA-style analysis."""
        return [
            TrackSummary(
                tracking_id=track.tracking_id,
                object_class=track.object_class,
                hits=track.hits,
                misses=track.misses,
                state=track.state,
            )
            for track in sorted(self._tracks.values(), key=lambda t: t.tracking_id)
            if track.state is not TrackLifecycle.TERMINATED
        ]

    def active_track_ids(self) -> list[str]:
        return [summary.tracking_id for summary in self.summaries()]

    def _stream_for(self, object_class: ObjectClass) -> StreamConfig:
        if object_class == ObjectClass.BALL:
            return self.config.ball
        return self.config.player

    def _assert_capacity(self, object_class: ObjectClass, stream: StreamConfig) -> None:
        live = sum(
            1
            for track in self._tracks.values()
            if track.object_class == object_class
            and track.state is not TrackLifecycle.TERMINATED
        )
        if live >= stream.max_tracks:
            raise TrackerLimitExceeded(
                f"Track capacity exceeded for {object_class.value}"
            )

    def _next_id(self, object_class: ObjectClass) -> str:
        self._counters[object_class] = self._counters.get(object_class, 0) + 1
        return f"{object_class.value.lower()}-{self._counters[object_class]}"

    def _purge_terminated(self) -> None:
        terminated = [
            tracking_id
            for tracking_id, track in self._tracks.items()
            if track.state is TrackLifecycle.TERMINATED
        ]
        for tracking_id in terminated:
            del self._tracks[tracking_id]


@dataclass
class _ExternalAdapterBase:
    """Shared unavailable-backend behaviour for optional tracker libraries."""

    backend: str = field(default="external", kw_only=True)
    package: str = field(default="", kw_only=True)

    def reset(self) -> None:
        raise TrackerUnavailable(
            f"{self.backend} backend requires the optional '{self.package}' package"
        )

    def track(
        self, frame: FrameReference, detections: Sequence[Detection]
    ) -> TrackingFrame:
        raise TrackerUnavailable(
            f"{self.backend} backend requires the optional '{self.package}' package"
        )

    def update(
        self, frame: FrameReference, detections: Sequence[Detection]
    ) -> TrackingFrame:
        return self.track(frame, detections)


class ByteTrackAdapter(_ExternalAdapterBase):
    """Integration point for a future ByteTrack backend (optional dep)."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        try:
            import yolox  # noqa: F401
        except ImportError as exc:
            raise TrackerUnavailable(
                "ByteTrack backend requires an optional external package"
            ) from exc
        super().__init__(backend="ByteTrack", package="yolox")


class BoTSORTAdapter(_ExternalAdapterBase):
    """Integration point for a future BoT-SORT backend (optional dep)."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        try:
            import boxmot  # noqa: F401
        except ImportError as exc:
            raise TrackerUnavailable(
                "BoT-SORT backend requires an optional external package"
            ) from exc
        super().__init__(backend="BoT-SORT", package="boxmot")


def build_tracker(
    name: str, config: TrackerConfig | None = None
) -> DeterministicIoUTracker | ByteTrackAdapter | BoTSORTAdapter:
    """Factory keeping the pipeline decoupled from tracker libraries."""
    normalized = name.strip().lower()
    if normalized in {"deterministic", "iou", "deterministic-iou"}:
        return DeterministicIoUTracker(config)
    if normalized in {"bytetrack", "byte-track"}:
        return ByteTrackAdapter(config)
    if normalized in {"botsort", "bot-sort"}:
        return BoTSORTAdapter(config)
    raise InvalidTrackInput(f"Unknown tracker: {name!r}")
