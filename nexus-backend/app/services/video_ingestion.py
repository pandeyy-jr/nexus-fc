from collections.abc import AsyncIterator
from datetime import UTC, datetime
from http import HTTPStatus
from re import fullmatch
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.vision.schemas import VideoProcessingStatus, VideoSource
from app.ai.vision.storage import (
    StorageConflict,
    StorageSizeLimitExceeded,
    VideoStorage,
)
from app.db.models.user import User
from app.db.models.video_source import VideoSourceRecord
from app.repositories import matches

MAX_VIDEO_SIZE_BYTES = 512 * 1024 * 1024
_ALLOWED_MEDIA_TYPES = {
    ".avi": frozenset({"video/x-msvideo"}),
    ".m4v": frozenset({"video/x-m4v", "video/mp4"}),
    ".mkv": frozenset({"video/x-matroska"}),
    ".mov": frozenset({"video/quicktime"}),
    ".mp4": frozenset({"video/mp4"}),
    ".webm": frozenset({"video/webm"}),
}
_SAFE_FILENAME = r"[A-Za-z0-9][A-Za-z0-9._ ()-]{0,179}"


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail=detail)


def validate_filename(filename: str) -> tuple[str, str]:
    safe_name = filename.strip()
    if (
        not safe_name
        or "/" in safe_name
        or "\\" in safe_name
        or ".." in safe_name
        or not fullmatch(_SAFE_FILENAME, safe_name)
    ):
        raise _invalid("A safe video filename is required")
    suffix = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if suffix not in _ALLOWED_MEDIA_TYPES:
        raise _invalid("Unsupported video file extension")
    return safe_name, suffix


def validate_media_type(media_type: str, suffix: str) -> str:
    normalized = media_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized not in _ALLOWED_MEDIA_TYPES[suffix]:
        raise _invalid("Video content type does not match its extension")
    return normalized


def _validate_signature(header: bytes, suffix: str) -> None:
    valid = {
        ".avi": len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI ",
        ".m4v": len(header) >= 8 and header[4:8] == b"ftyp",
        ".mkv": header.startswith(b"\x1aE\xdf\xa3"),
        ".mov": len(header) >= 8 and header[4:8] == b"ftyp",
        ".mp4": len(header) >= 8 and header[4:8] == b"ftyp",
        ".webm": header.startswith(b"\x1aE\xdf\xa3"),
    }[suffix]
    if not valid:
        raise _invalid("Video content signature is invalid")


async def _validated_video_chunks(
    chunks: AsyncIterator[bytes], suffix: str
) -> AsyncIterator[bytes]:
    required_header_size = {
        ".avi": 12,
        ".m4v": 8,
        ".mkv": 4,
        ".mov": 8,
        ".mp4": 8,
        ".webm": 4,
    }[suffix]
    header = bytearray()
    validated = False
    async for chunk in chunks:
        if not chunk:
            continue
        if not validated:
            needed = required_header_size - len(header)
            header.extend(chunk[:needed])
            remainder = chunk[needed:]
            if len(header) >= required_header_size:
                _validate_signature(bytes(header), suffix)
                validated = True
                yield bytes(header)
                if remainder:
                    yield remainder
            continue
        yield chunk
    if not validated:
        raise _invalid("Video content is empty or incomplete")


async def ingest_match_video(
    session: AsyncSession,
    storage: VideoStorage,
    match_id: UUID,
    actor: User,
    filename: str,
    media_type: str,
    chunks: AsyncIterator[bytes],
    content_length: int | None = None,
) -> VideoSource:
    if await matches.get_match(session, match_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
        )

    original_filename, suffix = validate_filename(filename)
    normalized_media_type = validate_media_type(media_type, suffix)
    if content_length is not None:
        if content_length < 1:
            raise _invalid("Video body cannot be empty")
        if content_length > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Video exceeds the maximum allowed size",
            )

    source_id = uuid4()
    try:
        stored = await storage.store(
            source_id,
            suffix,
            _validated_video_chunks(chunks, suffix),
            MAX_VIDEO_SIZE_BYTES,
        )
    except StorageSizeLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Video exceeds the maximum allowed size",
        ) from exc
    except StorageConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video storage reference already exists",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video could not be stored",
        ) from exc

    if content_length is not None and stored.file_size_bytes != content_length:
        try:
            await storage.delete(stored.storage_reference)
        except OSError:
            pass
        raise _invalid("Content-Length does not match the uploaded video")

    record = VideoSourceRecord(
        id=source_id,
        match_id=match_id,
        original_filename=original_filename,
        media_type=normalized_media_type,
        file_size_bytes=stored.file_size_bytes,
        ingested_at=datetime.now(UTC),
        processing_status=VideoProcessingStatus.READY.value,
        storage_reference=stored.storage_reference,
        created_by=actor.id,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        try:
            await storage.delete(stored.storage_reference)
        except (OSError, ValueError):
            pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video conflicts with existing match data",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        try:
            await storage.delete(stored.storage_reference)
        except (OSError, ValueError):
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Video metadata could not be saved",
        ) from exc
    await session.refresh(record)
    return VideoSource(
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
