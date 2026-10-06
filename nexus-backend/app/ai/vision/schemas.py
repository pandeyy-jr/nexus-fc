from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VideoProcessingStatus(StrEnum):
    RECEIVED = "RECEIVED"
    READY = "READY"
    FAILED = "FAILED"


class VideoSource(VisionContract):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    source_id: UUID
    match_id: UUID
    original_filename: str = Field(min_length=1, max_length=180)
    media_type: str = Field(min_length=1, max_length=100)
    file_size_bytes: int = Field(gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    frame_rate: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    ingested_at: datetime
    processing_status: VideoProcessingStatus
    storage_reference: str = Field(min_length=1, max_length=255)


class FrameReference(VisionContract):
    source_id: UUID
    frame_number: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sampling_interval_frames: int | None = Field(default=None, ge=1, le=3000)


class FrameSamplingConfig(VisionContract):
    sample_every_n_frames: int = Field(default=1, ge=1, le=3000)


class ObjectClass(StrEnum):
    PLAYER = "PLAYER"
    BALL = "BALL"
    GOALKEEPER = "GOALKEEPER"
    REFEREE = "REFEREE"
    OTHER = "OTHER"


class BoundingBox(VisionContract):
    x_min: float = Field(ge=0)
    y_min: float = Field(ge=0)
    x_max: float = Field(ge=0)
    y_max: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_bounds_order(self) -> "BoundingBox":
        if self.x_max < self.x_min or self.y_max < self.y_min:
            raise ValueError("Bounding-box maximums must not precede minimums")
        return self


class Detection(VisionContract):
    frame: FrameReference
    object_class: ObjectClass
    confidence: float = Field(ge=0, le=1)
    bounding_box: BoundingBox

    @model_validator(mode="after")
    def validate_box_dimensions(self) -> "Detection":
        if (
            self.bounding_box.x_max > self.frame.width
            or self.bounding_box.y_max > self.frame.height
        ):
            raise ValueError("Bounding box must fit within the frame dimensions")
        return self


class TrackedObject(Detection):
    tracking_id: str = Field(min_length=1, max_length=100)
    player_id: UUID | None = None
    identity_verified: bool = False

    @model_validator(mode="after")
    def validate_identity_association(self) -> "TrackedObject":
        if self.player_id is not None and not self.identity_verified:
            raise ValueError("Player identity requires a verified association")
        return self


class PlayerTrack(TrackedObject):
    object_class: Literal[ObjectClass.PLAYER, ObjectClass.GOALKEEPER] = (
        ObjectClass.PLAYER
    )


class BallTrack(TrackedObject):
    object_class: Literal[ObjectClass.BALL] = ObjectClass.BALL


class PitchSpace(StrEnum):
    """Explicit normalized-vs-metric distinction for pitch coordinates."""

    NORMALIZED = "NORMALIZED"
    METRIC = "METRIC"


class PitchDimensions(VisionContract):
    """Configurable real-world pitch size; pitches vary, never hardcoded."""

    length_metres: float = Field(gt=0, le=200)
    width_metres: float = Field(gt=0, le=200)


class ImagePoint(VisionContract):
    """A point in image pixel coordinates (origin: top-left, y grows down)."""

    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)


class MappingPointType(StrEnum):
    BOTTOM_CENTER = "BOTTOM_CENTER"
    CENTER = "CENTER"


class PitchCoordinate(VisionContract):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    coordinate_system: Literal["PITCH"] = "PITCH"
    space: PitchSpace = PitchSpace.NORMALIZED


class PitchPosition(VisionContract):
    frame: FrameReference
    tracking_id: str = Field(min_length=1, max_length=100)
    coordinate: PitchCoordinate
    mapping_point: ImagePoint | None = None
    mapping_point_type: MappingPointType | None = None
    in_bounds: bool = True
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)


class CalibrationCorrespondence(VisionContract):
    """One observed image point paired with its known pitch location."""

    image: ImagePoint
    pitch: PitchCoordinate

    @model_validator(mode="after")
    def validate_pitch_is_normalized(self) -> "CalibrationCorrespondence":
        if self.pitch.space is not PitchSpace.NORMALIZED:
            raise ValueError("Calibration pitch points must use NORMALIZED space")
        return self


class PitchCalibration(VisionContract):
    """Calibration data only — no transformation logic lives here."""

    calibration_id: str = Field(min_length=1, max_length=100)
    correspondences: list[CalibrationCorrespondence] = Field(
        min_length=4, max_length=64
    )
    pitch_dimensions: PitchDimensions | None = None
    origin_description: str = Field(default="", max_length=500)


class CalibrationQuality(VisionContract):
    """Measured (never fabricated) reprojection statistics."""

    reprojection_rmse: float = Field(ge=0, allow_inf_nan=False)
    max_reprojection_error: float = Field(ge=0, allow_inf_nan=False)
    inlier_count: int = Field(ge=0)
    correspondence_count: int = Field(ge=0)
    is_valid: bool


class TeamSide(StrEnum):
    """Explicit team association — remains unset until verified by a human."""

    HOME = "HOME"
    AWAY = "AWAY"


class MappingStatus(StrEnum):
    MAPPED = "MAPPED"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    FAILED = "FAILED"


class VisionObservation(VisionContract):
    """One match-bound observation: image evidence plus pitch representation.

    Image-space evidence is never replaced by pitch-space output; a failed
    mapping yields ``pitch_coordinate=None`` with ``mapping_status=FAILED``.
    ``player_id``/``team_side`` stay unset — Phase 06 does not solve identity.
    """

    match_id: UUID
    source_id: UUID
    frame: FrameReference
    tracking_id: str = Field(min_length=1, max_length=100)
    object_class: ObjectClass
    bounding_box: BoundingBox
    detection_confidence: float = Field(ge=0, le=1)
    image_point: ImagePoint
    mapping_point_type: MappingPointType
    pitch_coordinate: PitchCoordinate | None = None
    mapping_status: MappingStatus = MappingStatus.MAPPED
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)
    detector_name: str | None = Field(default=None, min_length=1, max_length=100)
    detector_version: str | None = Field(default=None, min_length=1, max_length=50)
    tracker_name: str | None = Field(default=None, min_length=1, max_length=100)
    tracker_version: str | None = Field(default=None, min_length=1, max_length=50)
    player_id: UUID | None = None
    identity_verified: bool = False
    team_side: TeamSide | None = None

    @model_validator(mode="after")
    def validate_identity_association(self) -> "VisionObservation":
        if self.player_id is not None and not self.identity_verified:
            raise ValueError("Player identity requires a verified association")
        return self


class VisionJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VisionProcessingRequest(VisionContract):
    """Bounded processing request — safe to serve synchronously."""

    max_frames: int = Field(default=120, ge=1, le=300)
    sample_every_n_frames: int = Field(default=1, ge=1, le=60)
    detector_confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    calibration: PitchCalibration


class VisionProcessingJob(VisionContract):
    """Service-level job record (in-memory; persistence is future work)."""

    job_id: UUID
    match_id: UUID
    source_id: UUID
    status: VisionJobStatus
    requested_by: UUID
    requested_at: datetime
    completed_at: datetime | None = None
    frames_processed: int = Field(default=0, ge=0)
    max_frames: int = Field(ge=1)
    observations: list[VisionObservation] = Field(default_factory=list)
    detector_name: str | None = Field(default=None, min_length=1, max_length=100)
    tracker_name: str | None = Field(default=None, min_length=1, max_length=100)
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)
    error: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TrackingFrame(VisionContract):
    frame: FrameReference
    tracks: list[TrackedObject]

    @model_validator(mode="after")
    def validate_track_frames(self) -> "TrackingFrame":
        if any(track.frame != self.frame for track in self.tracks):
            raise ValueError("All tracks must reference the tracking frame")
        return self


class FrameResult(VisionContract):
    frame: FrameReference
    detections: list[Detection]
    tracking: TrackingFrame
    pitch_positions: list[PitchPosition]

    @model_validator(mode="after")
    def validate_frame_consistency(self) -> "FrameResult":
        if self.tracking.frame != self.frame:
            raise ValueError("Tracking frame must match the result frame")
        if any(detection.frame != self.frame for detection in self.detections):
            raise ValueError("All detections must reference the result frame")
        if any(position.frame != self.frame for position in self.pitch_positions):
            raise ValueError("All pitch positions must reference the result frame")
        tracking_ids = {track.tracking_id for track in self.tracking.tracks}
        if any(
            position.tracking_id not in tracking_ids
            for position in self.pitch_positions
        ):
            raise ValueError("Pitch positions must reference a track in this frame")
        return self
