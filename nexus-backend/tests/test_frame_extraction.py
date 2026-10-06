from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.vision.frame_extraction import (
    DecodedFrame,
    ExtractionLimitExceeded,
    MissingStoredVideo,
    VideoDecodeError,
    VideoFrameExtractor,
)
from app.ai.vision.schemas import (
    FrameSamplingConfig,
    VideoProcessingStatus,
    VideoSource,
)
from app.ai.vision.storage import LocalVideoStorage, StorageObjectMissing
from app.services import video_frames


def video_source(source_id: UUID | None = None) -> VideoSource:
    source_id = source_id or UUID(int=1)
    return VideoSource(
        source_id=source_id,
        match_id=UUID(int=2),
        original_filename="test.mp4",
        media_type="video/mp4",
        file_size_bytes=20,
        ingested_at=datetime(2026, 9, 30, tzinfo=UTC),
        processing_status=VideoProcessingStatus.READY,
        storage_reference=f"{source_id.hex}.mp4",
    )


class FakeStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve(self, storage_reference: str) -> Path:
        if not self.path.is_file():
            raise StorageObjectMissing
        return self.path


class FakeDecoder:
    def __init__(self, count: int = 5) -> None:
        self.count = count
        self.decoded = 0

    def decode(self, path: Path) -> Iterator[DecodedFrame]:
        for number in range(self.count):
            self.decoded += 1
            yield DecodedFrame(
                payload=number,
                timestamp_seconds=number / 25,
                width=640,
                height=360,
            )


class BrokenDecoder:
    def decode(self, path: Path) -> Iterator[DecodedFrame]:
        raise RuntimeError("internal decoder details")


def test_frame_extraction_samples_incrementally_with_source_timestamps(
    tmp_path: Path,
) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"synthetic decoder input")
    decoder = FakeDecoder()
    extractor = VideoFrameExtractor(
        FakeStorage(path), decoder, FrameSamplingConfig(sample_every_n_frames=2)
    )
    frames = extractor.extract(video_source())

    first = next(frames)
    assert first.reference.frame_number == 0
    assert first.reference.timestamp_seconds == 0
    assert first.reference.sampling_interval_frames == 2
    assert decoder.decoded == 1

    remaining = list(frames)
    assert [frame.reference.frame_number for frame in remaining] == [2, 4]
    assert [frame.reference.timestamp_seconds for frame in remaining] == [
        2 / 25,
        4 / 25,
    ]
    assert all(frame.reference.width == 640 for frame in [first, *remaining])


def test_frame_extraction_rejects_invalid_sampling_and_missing_storage(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        FrameSamplingConfig(sample_every_n_frames=0)

    extractor = VideoFrameExtractor(
        FakeStorage(tmp_path / "missing.mp4"), FakeDecoder()
    )
    with pytest.raises(MissingStoredVideo):
        next(extractor.extract(video_source()))

    local_storage = LocalVideoStorage(tmp_path / "controlled")
    with pytest.raises(StorageObjectMissing):
        local_storage.resolve("../../outside.mp4")


def test_frame_extraction_handles_empty_video_and_enforces_frame_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"synthetic decoder input")
    empty_decoder = FakeDecoder(count=0)
    with pytest.raises(VideoDecodeError):
        list(
            VideoFrameExtractor(FakeStorage(path), empty_decoder).extract(
                video_source()
            )
        )
    with pytest.raises(VideoDecodeError, match="Video could not be decoded"):
        list(
            VideoFrameExtractor(FakeStorage(path), BrokenDecoder()).extract(
                video_source()
            )
        )

    from app.ai.vision import frame_extraction

    monkeypatch.setattr(frame_extraction, "MAX_FRAMES_PROCESSED", 2)
    decoder = FakeDecoder(count=4)
    with pytest.raises(ExtractionLimitExceeded):
        list(VideoFrameExtractor(FakeStorage(path), decoder).extract(video_source()))
    assert decoder.decoded == 3

    monkeypatch.setattr(frame_extraction, "MAX_FRAMES_PROCESSED", 3000)
    monkeypatch.setattr(frame_extraction, "MAX_EXTRACTION_SECONDS", 0.05)
    with pytest.raises(ExtractionLimitExceeded):
        list(
            VideoFrameExtractor(FakeStorage(path), FakeDecoder()).extract(
                video_source()
            )
        )


@pytest.mark.asyncio
async def test_frame_extraction_service_returns_404_for_missing_video_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing_video_source(session: object, source_id: UUID) -> None:
        return None

    monkeypatch.setattr(
        video_frames.video_sources, "get_video_source", missing_video_source
    )
    with pytest.raises(HTTPException) as error:
        await video_frames.extract_video_frames(
            session=object(),
            storage=object(),
            source_id=UUID(int=1),
            actor=object(),
        )
    assert error.value.status_code == 404
