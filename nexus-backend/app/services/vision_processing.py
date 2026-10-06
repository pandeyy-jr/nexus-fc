"""Phase 06G — match/video-bound vision processing service.

Binds the Phase 06 vision pipeline to the Phase 05 match/video domain:

MATCH -> VIDEO SOURCE -> FRAMES -> DETECTION -> TRACKING -> PITCH MAPPING
-> VISION OBSERVATIONS (match_id, source_id, frame, track, image + pitch).

Service-level job abstraction only — no database tables. The in-memory
registry is keyed by an idempotency hash so a repeated identical request
returns the existing job instead of duplicating work; a persistent,
multi-process idempotency store is future work and is documented as such.

``request_vision_processing`` is the synchronous boundary: it runs a bounded
number of frames inline (``max_frames`` <= 300) and is the exact function
to move behind a worker/job queue for full-video asynchronous processing.
No Redis/Celery is introduced here.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.vision.detection import DetectorConfig, YoloDetector
from app.ai.vision.frame_extraction import (
    DecoderUnavailable,
    PyAVVideoDecoder,
    VideoFrameExtractor,
)
from app.ai.vision.pipeline import ObjectDetector, ObjectTracker, PitchMapper
from app.ai.vision.pitch_mapping import HomographyMapper, MapperConfig
from app.ai.vision.schemas import (
    FrameSamplingConfig,
    MappingStatus,
    TrackedObject,
    VideoProcessingStatus,
    VideoSource,
    VisionJobStatus,
    VisionObservation,
    VisionProcessingJob,
    VisionProcessingRequest,
)
from app.ai.vision.storage import VideoStorage
from app.ai.vision.tracking import DeterministicIoUTracker
from app.ai.vision.types import FramePacket
from app.db.models.user import User
from app.repositories import video_sources
from app.services.matches import get_match_for_actor

DEFAULT_MAX_FRAMES = 120
MODEL_PATH_ENV_VAR = "NEXUS_VISION_MODEL_PATH"


class DetectorUnavailableError(RuntimeError):
    """No usable detector backend is configured for this request."""


@dataclass
class VisionComponents:
    """Replaceable pipeline pieces plus honest model metadata."""

    extractor_factory: Callable[[VideoSource], Iterable[FramePacket[object]]]
    detector: ObjectDetector[object]
    tracker: ObjectTracker
    mapper: PitchMapper
    detector_name: str | None = None
    detector_version: str | None = None
    tracker_name: str | None = None
    tracker_version: str | None = None


@dataclass
class _StoredJob:
    job: VisionProcessingJob
    idempotency_key: str = field(repr=False)


_JOBS: dict[UUID, _StoredJob] = {}
_JOBS_BY_KEY: dict[str, UUID] = {}


def clear_vision_jobs() -> None:
    """Test helper — the registry is in-memory by design."""
    _JOBS.clear()
    _JOBS_BY_KEY.clear()


def get_vision_job(job_id: UUID) -> VisionProcessingJob | None:
    stored = _JOBS.get(job_id)
    return stored.job if stored is not None else None


def idempotency_key_for(source_id: UUID, request: VisionProcessingRequest) -> str:
    digest = hashlib.sha256(
        f"{source_id}:{request.model_dump_json()}".encode()
    ).hexdigest()
    return digest


def build_default_components(
    storage: VideoStorage, request: VisionProcessingRequest
) -> VisionComponents:
    """Production component wiring: local video + local YOLO model only."""
    model_path = os.environ.get(MODEL_PATH_ENV_VAR, "").strip()
    if not model_path or not Path(model_path).is_file():
        raise DetectorUnavailableError(
            "Vision model is unavailable: set "
            f"{MODEL_PATH_ENV_VAR} to a local model file"
        )
    try:
        detector = YoloDetector(
            Path(model_path),
            DetectorConfig(confidence_threshold=request.detector_confidence_threshold),
        )
    except Exception as exc:
        raise DetectorUnavailableError("Vision model could not be initialized") from exc
    sampling = FrameSamplingConfig(sample_every_n_frames=request.sample_every_n_frames)

    def extract(source: VideoSource) -> Iterable[FramePacket[object]]:
        return VideoFrameExtractor(storage, PyAVVideoDecoder(), sampling).extract(
            source
        )

    tracker = DeterministicIoUTracker()
    mapper = HomographyMapper(MapperConfig())
    mapper.calibrate(request.calibration)
    return VisionComponents(
        extractor_factory=extract,
        detector=detector,
        tracker=tracker,
        mapper=mapper,
        detector_name="ultralytics-yolo",
        detector_version=None,
        tracker_name=tracker.config.tracker_name,
        tracker_version=tracker.config.tracker_version,
    )


def _observation_for(
    *,
    match_id: UUID,
    source_id: UUID,
    track: TrackedObject,
    positions: dict[str, object],
    components: VisionComponents,
    calibration_id: str | None,
) -> VisionObservation:
    from app.ai.vision.pitch_mapping import representative_point
    from app.ai.vision.schemas import PitchPosition

    image_point, point_type = representative_point(track)
    raw = positions.get(track.tracking_id)
    position = raw if isinstance(raw, PitchPosition) else None
    if position is None:
        status_value = MappingStatus.FAILED
        coordinate = None
    elif position.in_bounds:
        status_value = MappingStatus.MAPPED
        coordinate = position.coordinate
    else:
        status_value = MappingStatus.OUT_OF_BOUNDS
        coordinate = position.coordinate
    return VisionObservation(
        match_id=match_id,
        source_id=source_id,
        frame=track.frame,
        tracking_id=track.tracking_id,
        object_class=track.object_class,
        bounding_box=track.bounding_box,
        detection_confidence=track.confidence,
        image_point=image_point,
        mapping_point_type=point_type,
        pitch_coordinate=coordinate,
        mapping_status=status_value,
        calibration_id=position.calibration_id if position else calibration_id,
        detector_name=components.detector_name,
        detector_version=components.detector_version,
        tracker_name=components.tracker_name,
        tracker_version=components.tracker_version,
        player_id=None,
        identity_verified=False,
        team_side=None,
    )


async def request_vision_processing(
    session: AsyncSession,
    storage: VideoStorage,
    *,
    match_id: UUID,
    source_id: UUID,
    actor: User,
    request: VisionProcessingRequest,
    components: VisionComponents | None = None,
) -> VisionProcessingJob:
    await get_match_for_actor(session, match_id, actor)
    record = await video_sources.get_video_source(session, source_id)
    if record is None or record.match_id != match_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video source not found"
        )
    if record.processing_status != VideoProcessingStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video source is not ready for processing",
        )

    key = idempotency_key_for(source_id, request)
    existing_id = _JOBS_BY_KEY.get(key)
    if existing_id is not None and existing_id in _JOBS:
        return _JOBS[existing_id].job

    resolved = components
    if resolved is None:
        try:
            resolved = build_default_components(storage, request)
        except DetectorUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    source = VideoSource(
        source_id=record.id,
        match_id=record.match_id,
        original_filename=record.original_filename,
        media_type=record.media_type,
        file_size_bytes=record.file_size_bytes,
        duration_seconds=record.duration_seconds,
        frame_rate=record.frame_rate,
        width=record.width,
        height=record.height,
        ingested_at=record.ingested_at,
        processing_status=record.processing_status,
        storage_reference=record.storage_reference,
    )
    job = VisionProcessingJob(
        job_id=uuid4(),
        match_id=match_id,
        source_id=source_id,
        status=VisionJobStatus.RUNNING,
        requested_by=actor.id,
        requested_at=datetime.now(UTC),
        completed_at=None,
        frames_processed=0,
        max_frames=request.max_frames,
        observations=[],
        detector_name=resolved.detector_name,
        tracker_name=resolved.tracker_name,
        calibration_id=request.calibration.calibration_id,
        error=None,
        idempotency_key=key,
    )
    _JOBS[job.job_id] = _StoredJob(job=job, idempotency_key=key)
    _JOBS_BY_KEY[key] = job.job_id

    observations: list[VisionObservation] = []
    frames_processed = 0
    try:
        try:
            frames = resolved.extractor_factory(source)
        except DecoderUnavailable as exc:
            raise _JobFailure("Video decoder is unavailable") from exc
        for packet in frames:
            if frames_processed >= request.max_frames:
                break
            try:
                detections = resolved.detector.detect(packet)
                tracking = resolved.tracker.track(packet.reference, detections)
                positions = {p.tracking_id: p for p in resolved.mapper.map(tracking)}
            except Exception as exc:
                raise _JobFailure(
                    f"Inference failed on frame {packet.reference.frame_number}"
                ) from exc
            for track in tracking.tracks:
                observations.append(
                    _observation_for(
                        match_id=match_id,
                        source_id=source_id,
                        track=track,
                        positions=positions,
                        components=resolved,
                        calibration_id=request.calibration.calibration_id,
                    )
                )
            frames_processed += 1
    except _JobFailure as exc:
        failed = job.model_copy(
            update={
                "status": VisionJobStatus.FAILED,
                "completed_at": datetime.now(UTC),
                "frames_processed": frames_processed,
                "observations": observations,
                "error": str(exc)[:500],
            }
        )
        _JOBS[job.job_id] = _StoredJob(job=failed, idempotency_key=key)
        return failed
    completed = job.model_copy(
        update={
            "status": VisionJobStatus.COMPLETED,
            "completed_at": datetime.now(UTC),
            "frames_processed": frames_processed,
            "observations": observations,
        }
    )
    _JOBS[job.job_id] = _StoredJob(job=completed, idempotency_key=key)
    return completed


class _JobFailure(RuntimeError):
    """Internal control-flow: mark the job FAILED with an explicit error."""


__all__ = [
    "DetectorUnavailableError",
    "VisionComponents",
    "build_default_components",
    "clear_vision_jobs",
    "get_vision_job",
    "idempotency_key_for",
    "request_vision_processing",
]
