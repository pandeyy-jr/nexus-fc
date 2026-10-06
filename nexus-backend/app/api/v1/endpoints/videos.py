from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.ai.vision.schemas import (
    VideoSource,
    VisionProcessingJob,
    VisionProcessingRequest,
)
from app.ai.vision.storage import LocalVideoStorage, VideoStorage
from app.api.dependencies import SessionDependency
from app.api.match_dependencies import MatchManager, MatchReader
from app.services.matches import get_match_for_actor
from app.services.video_ingestion import ingest_match_video
from app.services.vision_processing import (
    DetectorUnavailableError,
    VisionComponents,
    build_default_components,
    get_vision_job,
    request_vision_processing,
)

router = APIRouter()


def get_video_storage() -> VideoStorage:
    storage_root = Path(__file__).resolve().parents[4] / "var" / "videos"
    return LocalVideoStorage(storage_root)


@router.post(
    "/{match_id}/videos",
    response_model=VideoSource,
    status_code=status.HTTP_201_CREATED,
)
async def post_match_video(
    match_id: UUID,
    request: Request,
    session: SessionDependency,
    actor: MatchManager,
    storage: Annotated[VideoStorage, Depends(get_video_storage)],
    filename: Annotated[str, Header(alias="X-Filename")],
    content_type: Annotated[str, Header(alias="Content-Type")],
    content_length_header: Annotated[str | None, Header(alias="Content-Length")] = None,
) -> VideoSource:
    content_length: int | None = None
    if content_length_header is not None:
        try:
            content_length = int(content_length_header)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Content-Length must be an integer",
            ) from None
    return await ingest_match_video(
        session,
        storage,
        match_id,
        actor,
        filename,
        content_type,
        request.stream(),
        content_length,
    )


def build_vision_components(
    storage: VideoStorage, body: VisionProcessingRequest
) -> VisionComponents:
    """Component wiring seam: monkeypatchable in tests, worker-ready later."""
    return build_default_components(storage, body)


@router.post(
    "/{match_id}/videos/{source_id}/vision-processing",
    response_model=VisionProcessingJob,
)
async def post_video_vision_processing(
    match_id: UUID,
    source_id: UUID,
    body: VisionProcessingRequest,
    session: SessionDependency,
    actor: MatchManager,
    storage: Annotated[VideoStorage, Depends(get_video_storage)],
) -> VisionProcessingJob:
    try:
        components = build_vision_components(storage, body)
    except DetectorUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return await request_vision_processing(
        session,
        storage,
        match_id=match_id,
        source_id=source_id,
        actor=actor,
        request=body,
        components=components,
    )


@router.get(
    "/{match_id}/videos/{source_id}/vision-processing/{job_id}",
    response_model=VisionProcessingJob,
)
async def get_video_vision_processing(
    match_id: UUID,
    source_id: UUID,
    job_id: UUID,
    session: SessionDependency,
    actor: MatchReader,
) -> VisionProcessingJob:
    await get_match_for_actor(session, match_id, actor)
    job = get_vision_job(job_id)
    if job is None or job.match_id != match_id or job.source_id != source_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vision processing job not found",
        )
    return job
