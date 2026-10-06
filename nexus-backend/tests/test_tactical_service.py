"""Phase 07I service tests: boundary behavior only. Synthetic data,
no football claims."""

from uuid import UUID

import pytest

from app.ai.tactics.evaluation import GroundTruthEvent
from app.ai.tactics.events import EventType
from app.ai.vision.schemas import (
    BoundingBox,
    FrameReference,
    ImagePoint,
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchCoordinate,
    VisionObservation,
)
from app.services.tactical_intelligence import (
    InvalidTacticalRequest,
    TacticalAnalysisResult,
    TacticalIntelligenceService,
    TacticalServiceUnavailable,
)

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def frame(number: int, timestamp: float) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=timestamp,
        width=640,
        height=360,
    )


def observation(
    ref: FrameReference, tracking_id: str, pitch: tuple[float, float] | None
) -> VisionObservation:
    return VisionObservation(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame=ref,
        tracking_id=tracking_id,
        object_class=ObjectClass.PLAYER,
        detection_confidence=0.8,
        bounding_box=BoundingBox(x_min=10, y_min=20, x_max=50, y_max=100),
        image_point=ImagePoint(x=30, y=100),
        mapping_point_type=MappingPointType.BOTTOM_CENTER,
        pitch_coordinate=(
            PitchCoordinate(x=pitch[0], y=pitch[1], coordinate_system="PITCH")
            if pitch is not None
            else None
        ),
        mapping_status=(
            MappingStatus.MAPPED if pitch is not None else MappingStatus.FAILED
        ),
        calibration_id="cal-1",
        detector_name="det",
        tracker_name="trk",
    )


def observations() -> list[VisionObservation]:
    items: list[VisionObservation] = []
    for number, timestamp in enumerate([0.0, 0.5, 1.0]):
        ref = frame(number, timestamp)
        items.append(observation(ref, "player-1", (0.2 + 0.1 * number, 0.3)))
        items.append(observation(ref, "player-2", (0.7, 0.3)))
    return items


def test_successful_analysis() -> None:
    result = TacticalIntelligenceService.with_defaults().analyze(observations())
    assert isinstance(result, TacticalAnalysisResult)
    assert result.match_id == MATCH_ID
    assert result.source_id == SOURCE_ID
    assert result.frame_range == (0, 2)
    assert result.time_range == (0.0, 1.0)
    assert result.event_count == len(result.events) >= 1
    assert result.evaluated is False
    assert result.service_version


def test_provenance_preservation() -> None:
    result = TacticalIntelligenceService.with_defaults().analyze(observations())
    assert result.provenance["track_ids"] == ("player-1", "player-2")
    assert result.provenance["calibration_ids"] == ("cal-1",)
    assert result.provenance["detector_names"] == ("det",)
    for event in result.events:
        assert event.match_id == MATCH_ID
        assert event.source_id == SOURCE_ID
        assert event.evidence.track_ids


def test_empty_observations_rejected() -> None:
    with pytest.raises(InvalidTacticalRequest):
        TacticalIntelligenceService.with_defaults().analyze([])


def test_partial_observations_accepted() -> None:
    ref = frame(0, 0.0)
    items = [
        observation(ref, "player-1", None),
        observation(ref, "player-2", (0.7, 0.3)),
    ]
    result = TacticalIntelligenceService.with_defaults().analyze(items)
    assert result.frame_range == (0, 0)
    assert result.event_count == 0  # single frame: no movement possible


def test_invalid_items_rejected() -> None:
    with pytest.raises(InvalidTacticalRequest):
        TacticalIntelligenceService.with_defaults().analyze(["nope"])  # type: ignore[list-item]


def test_unavailable_service() -> None:
    service = TacticalIntelligenceService.unavailable()
    assert service.is_available is False
    assert TacticalIntelligenceService.with_defaults().is_available is True
    with pytest.raises(TacticalServiceUnavailable):
        service.analyze(observations())


def test_no_tensor_leakage() -> None:
    result = TacticalIntelligenceService.with_defaults().analyze(observations())
    dumped = result.model_dump()
    assert set(dumped) == {
        "match_id",
        "source_id",
        "frame_range",
        "time_range",
        "events",
        "event_count",
        "representation_metadata",
        "provenance",
        "evaluated",
        "evaluation_summary",
        "analyzed_at",
        "service_version",
    }
    assert "fused_embedding" not in str(dumped["representation_metadata"])
    assert result.representation_metadata["fused_dim"] == 6.0


def test_evaluation_metadata_when_ground_truth() -> None:
    ground_truth = [
        GroundTruthEvent(
            event_type=EventType.PLAYER_MOVEMENT,
            start_frame=0,
            end_frame=2,
            start_timestamp=0.0,
            end_timestamp=1.0,
        )
    ]
    result = TacticalIntelligenceService.with_defaults().analyze(
        observations(), ground_truth
    )
    assert result.evaluated is True
    assert 0.0 <= result.evaluation_summary["micro_f1"] <= 1.0


def test_deterministic_results() -> None:
    service = TacticalIntelligenceService.with_defaults()
    first = service.analyze(observations())
    second = service.analyze(observations())
    assert first.events == second.events
    assert first.frame_range == second.frame_range
