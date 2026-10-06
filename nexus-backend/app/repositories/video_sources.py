from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.video_source import VideoSourceRecord


async def get_video_source(
    session: AsyncSession, source_id: UUID
) -> VideoSourceRecord | None:
    return await session.get(VideoSourceRecord, source_id)
