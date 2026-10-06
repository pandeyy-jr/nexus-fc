from collections.abc import Iterator
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.vision.frame_extraction import PyAVVideoDecoder, VideoFrameExtractor
from app.ai.vision.schemas import (
    FrameSamplingConfig,
    VideoProcessingStatus,
    VideoSource,
)
from app.ai.vision.storage import VideoStorage
from app.ai.vision.types import FramePacket
from app.db.models.user import User
from app.repositories import video_sources
from app.services.matches import get_match_for_actor


async def extract_video_frames(
    session: AsyncSession,
    storage: VideoStorage,
    source_id: UUID,
    actor: User,
    sampling: FrameSamplingConfig | None = None,
) -> Iterator[FramePacket[object]]:
    record = await video_sources.get_video_source(session, source_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video source not found"
        )
    await get_match_for_actor(session, record.match_id, actor)
    if record.processing_status != VideoProcessingStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video source is not ready for extraction",
        )
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
    extractor = VideoFrameExtractor(storage, PyAVVideoDecoder(), sampling)
    return extractor.extract(source)
