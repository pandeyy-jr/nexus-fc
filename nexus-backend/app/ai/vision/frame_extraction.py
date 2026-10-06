import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from app.ai.vision.schemas import (
    FrameReference,
    FrameSamplingConfig,
    VideoSource,
)
from app.ai.vision.storage import StorageObjectMissing, VideoStorage
from app.ai.vision.types import FramePacket

MAX_FRAMES_PROCESSED = 3000
MAX_EXTRACTION_SECONDS = 120.0


class FrameExtractionError(Exception):
    """Base class for safe frame-extraction failures."""


class MissingStoredVideo(FrameExtractionError):
    """The video source has no available controlled storage object."""


class DecoderUnavailable(FrameExtractionError):
    """The configured video decoder is unavailable."""


class UnsupportedVideo(FrameExtractionError):
    """The video container has no supported video stream."""


class VideoDecodeError(FrameExtractionError):
    """The video decoder could not read valid frames."""


class ExtractionLimitExceeded(FrameExtractionError):
    """A configured frame or time limit was reached."""


@dataclass(frozen=True)
class DecodedFrame:
    payload: object
    timestamp_seconds: float
    width: int
    height: int


class VideoDecoder(Protocol):
    def decode(self, path: Path) -> Iterator[DecodedFrame]: ...


class PyAVVideoDecoder:
    """Decode video frames incrementally using the optional PyAV dependency."""

    def decode(self, path: Path) -> Iterator[DecodedFrame]:
        try:
            import av
        except ImportError:
            raise DecoderUnavailable("Video decoder is unavailable") from None

        try:
            with av.open(str(path), mode="r") as container:
                if not container.streams.video:
                    raise UnsupportedVideo("Video contains no supported video stream")
                stream = container.streams.video[0]
                for frame in container.decode(stream):
                    timestamp = frame.time
                    if (
                        timestamp is None
                        or not math.isfinite(timestamp)
                        or timestamp < 0
                        or frame.width < 1
                        or frame.height < 1
                    ):
                        raise VideoDecodeError("Video frame metadata is invalid")
                    yield DecodedFrame(
                        payload=frame,
                        timestamp_seconds=timestamp,
                        width=frame.width,
                        height=frame.height,
                    )
        except (UnsupportedVideo, VideoDecodeError):
            raise
        except Exception:
            raise VideoDecodeError("Video could not be decoded") from None


class VideoFrameExtractor:
    def __init__(
        self,
        storage: VideoStorage,
        decoder: VideoDecoder | None = None,
        sampling: FrameSamplingConfig | None = None,
    ) -> None:
        self.storage = storage
        self.decoder = decoder or PyAVVideoDecoder()
        self.sampling = sampling or FrameSamplingConfig()

    def extract(self, video: VideoSource) -> Iterator[FramePacket[object]]:
        if not video.media_type.startswith("video/"):
            raise UnsupportedVideo("Video source media type is not supported")
        if not video.storage_reference.startswith(f"{video.source_id.hex}."):
            raise MissingStoredVideo("Video source storage reference is invalid")
        try:
            path = self.storage.resolve(video.storage_reference)
        except StorageObjectMissing:
            raise MissingStoredVideo("Video source is unavailable") from None
        except Exception:
            raise MissingStoredVideo("Video source is unavailable") from None

        try:
            yield from self._extract_frames(video, path)
        except FrameExtractionError:
            raise
        except Exception:
            raise VideoDecodeError("Video could not be decoded") from None

    def _extract_frames(
        self, video: VideoSource, path: Path
    ) -> Iterator[FramePacket[object]]:
        started_at = time.monotonic()
        first_timestamp: float | None = None
        decoded_count = 0
        for frame_number, decoded in enumerate(self.decoder.decode(path)):
            if frame_number >= MAX_FRAMES_PROCESSED:
                raise ExtractionLimitExceeded("Frame processing limit exceeded")
            decoded_count += 1
            if time.monotonic() - started_at > MAX_EXTRACTION_SECONDS:
                raise ExtractionLimitExceeded("Frame extraction time limit exceeded")
            if (
                not math.isfinite(decoded.timestamp_seconds)
                or decoded.timestamp_seconds < 0
                or decoded.width < 1
                or decoded.height < 1
            ):
                raise VideoDecodeError("Video frame metadata is invalid")
            if first_timestamp is None:
                first_timestamp = decoded.timestamp_seconds
            elif decoded.timestamp_seconds - first_timestamp > MAX_EXTRACTION_SECONDS:
                raise ExtractionLimitExceeded("Video duration limit exceeded")

            if frame_number % self.sampling.sample_every_n_frames:
                continue
            try:
                reference = FrameReference(
                    source_id=video.source_id,
                    frame_number=frame_number,
                    timestamp_seconds=decoded.timestamp_seconds,
                    width=decoded.width,
                    height=decoded.height,
                    sampling_interval_frames=self.sampling.sample_every_n_frames,
                )
            except ValidationError:
                raise VideoDecodeError("Video frame metadata is invalid") from None
            yield FramePacket(reference=reference, payload=decoded.payload)
        if decoded_count == 0:
            raise VideoDecodeError("Video contains no decodable frames")
