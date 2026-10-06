from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.ai.vision.detection import (
    DetectorConfig,
    DetectorInferenceError,
    DetectorLoadError,
    InvalidFrameInput,
    YoloDetector,
)
from app.ai.vision.schemas import (
    FrameReference,
    ObjectClass,
)
from app.ai.vision.types import FramePacket


def packet(payload: object = object()) -> FramePacket[object]:
    return FramePacket(
        reference=FrameReference(
            source_id=UUID(int=1),
            frame_number=4,
            timestamp_seconds=0.16,
            width=640,
            height=360,
        ),
        payload=payload,
    )


class FakeModel:
    def __init__(self, rows: list[list[float]], scores: list[float], ids: list[float]):
        self.rows = rows
        self.scores = scores
        self.ids = ids
        self.kwargs: dict[str, object] = {}

    def predict(self, **kwargs: object) -> list[object]:
        self.kwargs = kwargs
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=self.rows,
                    conf=self.scores,
                    cls=self.ids,
                )
            )
        ]


def test_detector_config_validates_confidence_and_supported_classes() -> None:
    assert DetectorConfig().confidence_threshold == 0.25
    with pytest.raises(ValidationError):
        DetectorConfig(confidence_threshold=1.1)
    with pytest.raises(ValidationError):
        DetectorConfig(classes=frozenset({ObjectClass.REFEREE}))


def test_detector_applies_threshold_and_class_filter() -> None:
    model = FakeModel(
        rows=[[10, 20, 30, 60], [40, 20, 55, 35], [1, 1, 5, 5]],
        scores=[0.8, 0.9, 0.2],
        ids=[0, 32, 0],
    )
    detector = YoloDetector(
        Path("unused.pt"),
        DetectorConfig(
            confidence_threshold=0.5, classes=frozenset({ObjectClass.PLAYER})
        ),
        model=model,
    )

    detections = detector.detect(packet())

    assert len(detections) == 1
    assert detections[0].object_class == ObjectClass.PLAYER
    assert detections[0].confidence == 0.8
    assert detections[0].frame.frame_number == 4
    assert detections[0].bounding_box.x_max == 30
    assert model.kwargs["device"] == "cpu"
    assert model.kwargs["classes"] == [0]


def test_detector_emits_ball_and_rejects_invalid_model_box() -> None:
    ball_model = FakeModel([[2, 3, 8, 9]], [0.7], [32])
    result = YoloDetector(Path("unused.pt"), model=ball_model).detect(packet())
    assert result[0].object_class == ObjectClass.BALL

    bad_model = FakeModel([[2, 3, 700, 9]], [0.7], [32])
    with pytest.raises(DetectorInferenceError, match="invalid detection"):
        YoloDetector(Path("unused.pt"), model=bad_model).detect(packet())


def test_detector_rejects_invalid_frame_packet() -> None:
    detector = YoloDetector(Path("unused.pt"), model=FakeModel([], [], []))
    with pytest.raises(InvalidFrameInput):
        detector.detect(packet(None))
    with pytest.raises(InvalidFrameInput):
        detector.detect(object())  # type: ignore[arg-type]


def test_detector_load_failure_requires_an_existing_local_model(
    tmp_path: Path,
) -> None:
    with pytest.raises(DetectorLoadError, match="local YOLO model file"):
        YoloDetector(tmp_path / "missing.pt")
