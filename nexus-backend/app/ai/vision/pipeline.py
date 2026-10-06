from collections.abc import Iterable, Iterator, Sequence
from typing import Protocol

from app.ai.vision.schemas import (
    Detection,
    FrameReference,
    FrameResult,
    PitchPosition,
    TrackingFrame,
    VideoSource,
)
from app.ai.vision.types import FramePacket


class FrameExtractor[FramePayloadT](Protocol):
    def extract(self, video: VideoSource) -> Iterable[FramePacket[FramePayloadT]]: ...


class ObjectDetector[FramePayloadT](Protocol):
    def detect(self, frame: FramePacket[FramePayloadT]) -> Sequence[Detection]: ...


class ObjectTracker(Protocol):
    def track(
        self, frame: FrameReference, detections: Sequence[Detection]
    ) -> TrackingFrame: ...


class PitchMapper(Protocol):
    def map(self, tracking: TrackingFrame) -> Sequence[PitchPosition]: ...


class VisionPipeline[FramePayloadT]:
    """Lazily compose CV stages without binding to a model or image library."""

    def __init__(
        self,
        frame_extractor: FrameExtractor[FramePayloadT],
        detector: ObjectDetector[FramePayloadT],
        tracker: ObjectTracker,
        pitch_mapper: PitchMapper,
    ) -> None:
        self.frame_extractor = frame_extractor
        self.detector = detector
        self.tracker = tracker
        self.pitch_mapper = pitch_mapper

    def run(self, video: VideoSource) -> Iterator[FrameResult]:
        for frame in self.frame_extractor.extract(video):
            detections = self.detector.detect(frame)
            tracking = self.tracker.track(frame.reference, detections)
            pitch_positions = self.pitch_mapper.map(tracking)
            yield FrameResult(
                frame=frame.reference,
                detections=list(detections),
                tracking=tracking,
                pitch_positions=list(pitch_positions),
            )
