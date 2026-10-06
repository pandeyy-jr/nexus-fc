from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.vision.pipeline import ObjectDetector
from app.ai.vision.schemas import (
    BoundingBox,
    Detection,
    FrameReference,
    ObjectClass,
)
from app.ai.vision.types import FramePacket

COCO_PERSON_CLASS_ID = 0
COCO_SPORTS_BALL_CLASS_ID = 32
_CLASS_IDS = {
    ObjectClass.PLAYER: COCO_PERSON_CLASS_ID,
    ObjectClass.BALL: COCO_SPORTS_BALL_CLASS_ID,
}
_CLASS_BY_ID = {class_id: label for label, class_id in _CLASS_IDS.items()}
_EXPECTED_MODEL_NAMES = {
    ObjectClass.PLAYER: "person",
    ObjectClass.BALL: "sports ball",
}


class DetectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    classes: frozenset[Literal[ObjectClass.PLAYER, ObjectClass.BALL]] = frozenset(
        {ObjectClass.PLAYER, ObjectClass.BALL}
    )


class DetectorLoadError(RuntimeError):
    """The local detector model could not be initialized."""


class DetectorInferenceError(RuntimeError):
    """The detector could not process a frame or its model output."""


class InvalidFrameInput(ValueError):
    """A frame packet cannot be passed to the detector."""


class YoloDetector(ObjectDetector[object]):
    """Local YOLO11 nano adapter emitting the existing Detection contract.

    The model file must already exist locally. Ultralytics is imported only when
    no model instance is injected, keeping the rest of the vision package light.
    """

    def __init__(
        self,
        model_path: Path,
        config: DetectorConfig | None = None,
        *,
        device: str = "cpu",
        model: object | None = None,
    ) -> None:
        self.config = config or DetectorConfig()
        self.device = device
        self.model = model if model is not None else self._load_model(model_path)
        self._supported_class_ids = self._find_supported_class_ids(self.model)

    @staticmethod
    def _load_model(model_path: Path) -> object:
        if model_path.suffix.lower() != ".pt" or not model_path.is_file():
            raise DetectorLoadError("A local YOLO model file is required")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorLoadError(
                "Install the optional Ultralytics runtime to load a YOLO model"
            ) from exc
        try:
            return YOLO(str(model_path))
        except Exception as exc:
            raise DetectorLoadError("The local YOLO model could not be loaded") from exc

    def detect(self, frame: FramePacket[object]) -> Sequence[Detection]:
        if not isinstance(frame, FramePacket) or frame.payload is None:
            raise InvalidFrameInput("A frame packet with a payload is required")
        try:
            reference = FrameReference.model_validate(frame.reference)
            image = self._image_payload(frame.payload)
        except (AttributeError, TypeError, ValueError) as exc:
            raise InvalidFrameInput("The frame packet is invalid") from exc

        requested_ids = [
            _CLASS_IDS[label]
            for label in self.config.classes
            if _CLASS_IDS[label] in self._supported_class_ids
        ]
        if not requested_ids:
            return []
        try:
            results = self.model.predict(
                source=image,
                conf=self.config.confidence_threshold,
                classes=requested_ids,
                device=self.device,
                verbose=False,
            )
            return self._detections(reference, results)
        except DetectorInferenceError:
            raise
        except Exception as exc:
            raise DetectorInferenceError("YOLO inference failed") from exc

    @staticmethod
    def _image_payload(payload: object) -> object:
        to_ndarray = getattr(payload, "to_ndarray", None)
        return to_ndarray(format="rgb24") if callable(to_ndarray) else payload

    @staticmethod
    def _find_supported_class_ids(model: object) -> frozenset[int]:
        names = getattr(model, "names", None)
        if names is None:
            # Injected lightweight test doubles can omit model metadata.
            return frozenset(_CLASS_BY_ID)
        entries = names.items() if isinstance(names, dict) else enumerate(names)
        supported: set[int] = set()
        expected = {
            class_id: _EXPECTED_MODEL_NAMES[label]
            for class_id, label in _CLASS_BY_ID.items()
        }
        for class_id, name in entries:
            if (
                int(class_id) in expected
                and str(name).strip().lower() == expected[int(class_id)]
            ):
                supported.add(int(class_id))
        return frozenset(supported)

    def _detections(
        self, reference: FrameReference, results: object
    ) -> list[Detection]:
        detections: list[Detection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            coordinates = self._as_list(boxes.xyxy)
            confidences = self._as_list(boxes.conf)
            class_ids = self._as_list(boxes.cls)
            if not (len(coordinates) == len(confidences) == len(class_ids)):
                raise DetectorInferenceError("YOLO returned inconsistent box data")
            for coordinates_row, confidence, class_id in zip(
                coordinates, confidences, class_ids, strict=True
            ):
                label = _CLASS_BY_ID.get(int(class_id))
                if (
                    label not in self.config.classes
                    or int(class_id) not in self._supported_class_ids
                ):
                    continue
                if float(confidence) < self.config.confidence_threshold:
                    continue
                try:
                    bounding_box = BoundingBox(
                        x_min=float(coordinates_row[0]),
                        y_min=float(coordinates_row[1]),
                        x_max=float(coordinates_row[2]),
                        y_max=float(coordinates_row[3]),
                    )
                    detections.append(
                        Detection(
                            frame=reference,
                            object_class=label,
                            confidence=float(confidence),
                            bounding_box=bounding_box,
                        )
                    )
                except (IndexError, TypeError, ValueError) as exc:
                    raise DetectorInferenceError(
                        "YOLO returned an invalid detection"
                    ) from exc
        return detections

    @staticmethod
    def _as_list(values: object) -> list:
        current = values
        for method_name in ("detach", "cpu"):
            method = getattr(current, method_name, None)
            if callable(method):
                current = method()
        tolist = getattr(current, "tolist", None)
        return tolist() if callable(tolist) else list(current)  # type: ignore[arg-type]
