"""Phase 06H evaluation tests.

All fixtures below are SYNTHETIC unit-test fixtures for verifying
mathematics and contracts. They are NOT evidence of real-world
model performance and must never be quoted as such.
"""

from uuid import UUID

import pytest

from app.ai.vision.evaluation import (
    EvaluationError,
    GroundTruthDetection,
    GroundTruthPitchPoint,
    PredictedPitchPoint,
    evaluate_detections,
    evaluate_pitch_mapping,
    evaluate_tracking,
    iou_boxes,
)
from app.ai.vision.schemas import (
    BoundingBox,
    Detection,
    FrameReference,
    ObjectClass,
    TrackedObject,
)

SOURCE_ID = UUID(int=1)


def frame(number: int) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=0.04 * number,
        width=100,
        height=100,
    )


def box(coords: tuple[float, float, float, float]) -> BoundingBox:
    return BoundingBox(
        x_min=coords[0], y_min=coords[1], x_max=coords[2], y_max=coords[3]
    )


def prediction(
    number: int,
    object_class: ObjectClass,
    coords: tuple[float, float, float, float],
    confidence: float,
) -> Detection:
    return Detection(
        frame=frame(number),
        object_class=object_class,
        confidence=confidence,
        bounding_box=box(coords),
    )


def ground_truth(
    number: int,
    object_class: ObjectClass,
    coords: tuple[float, float, float, float],
    track_id: str | None = None,
) -> GroundTruthDetection:
    return GroundTruthDetection(
        frame_number=number,
        object_class=object_class,
        bounding_box=box(coords),
        track_id=track_id,
    )


def tracked(
    number: int, tracking_id: str, coords: tuple[float, float, float, float]
) -> TrackedObject:
    return TrackedObject(
        frame=frame(number),
        object_class=ObjectClass.PLAYER,
        confidence=0.9,
        bounding_box=box(coords),
        tracking_id=tracking_id,
    )


def test_iou_boxes_known_values() -> None:
    assert iou_boxes((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert iou_boxes((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou_boxes((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25 / 175)


def test_detection_perfect_synthetic_fixture() -> None:
    preds = [
        prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9),
        prediction(0, ObjectClass.BALL, (60, 60, 70, 70), 0.8),
    ]
    truth = [
        ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50)),
        ground_truth(0, ObjectClass.BALL, (60, 60, 70, 70)),
    ]
    result = evaluate_detections(preds, truth)
    for metrics in result.per_class.values():
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)
        assert metrics.f1 == pytest.approx(1.0)
        assert metrics.average_precision == pytest.approx(1.0)
    assert result.mean_average_precision == pytest.approx(1.0)


def test_detection_counts_false_positives_and_negatives() -> None:
    preds = [
        prediction(0, ObjectClass.PLAYER, (12, 12, 48, 48), 0.9),
        prediction(0, ObjectClass.PLAYER, (0, 0, 5, 5), 0.7),
        prediction(0, ObjectClass.BALL, (60, 60, 70, 70), 0.8),
    ]
    truth = [
        ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50)),
        ground_truth(1, ObjectClass.PLAYER, (10, 10, 50, 50)),
        ground_truth(0, ObjectClass.BALL, (60, 60, 70, 70)),
    ]
    result = evaluate_detections(preds, truth)
    player = result.per_class[ObjectClass.PLAYER]
    assert (player.true_positives, player.false_positives, player.false_negatives) == (
        1,
        1,
        1,
    )
    assert player.precision == pytest.approx(0.5)
    assert player.recall == pytest.approx(0.5)
    assert player.f1 == pytest.approx(0.5)
    assert player.average_precision == pytest.approx(0.5)
    assert result.per_class[ObjectClass.BALL].f1 == pytest.approx(1.0)
    assert result.mean_average_precision == pytest.approx(0.75)


def test_detection_class_specificity() -> None:
    preds = [prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9)]
    truth = [ground_truth(0, ObjectClass.BALL, (10, 10, 50, 50))]
    result = evaluate_detections(preds, truth)
    assert result.per_class[ObjectClass.PLAYER].recall == pytest.approx(0.0)
    assert result.per_class[ObjectClass.BALL].precision == pytest.approx(0.0)


def test_detection_requires_ground_truth() -> None:
    with pytest.raises(EvaluationError):
        evaluate_detections([], [])
    with pytest.raises(EvaluationError):
        evaluate_detections(
            [prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9)], []
        )
    with pytest.raises(EvaluationError):
        evaluate_detections(
            [prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9)],
            [ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50))],
            iou_threshold=1.5,
        )


def test_detection_reports_carry_provenance() -> None:
    result = evaluate_detections(
        [prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9)],
        [ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50))],
    )
    reports = result.reports("SYNTHETIC-fixture", model="fake-detector")
    assert reports
    assert all(r.dataset == "SYNTHETIC-fixture" for r in reports)
    assert all(r.model == "fake-detector" for r in reports)
    assert any(r.metric_name == "detection_mAP" for r in reports)
    assert all(r.evaluated_at is not None for r in reports)


def test_tracking_perfect_synthetic_fixture() -> None:
    preds = [tracked(n, "player-1", (10, 10, 50, 50)) for n in range(3)]
    truth = [
        ground_truth(n, ObjectClass.PLAYER, (10, 10, 50, 50), track_id="gt-a")
        for n in range(3)
    ]
    result = evaluate_tracking(preds, truth)
    assert result.idf1 == pytest.approx(1.0)
    assert result.mota == pytest.approx(1.0)
    assert result.id_switches == 0
    assert result.fragmentations == 0
    assert result.ground_truth_tracks == 1
    assert result.predicted_tracks == 1


def test_tracking_counts_id_switch() -> None:
    preds = [
        tracked(0, "player-1", (10, 10, 50, 50)),
        tracked(1, "player-1", (60, 60, 90, 90)),
    ]
    truth = [
        ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50), track_id="gt-a"),
        ground_truth(1, ObjectClass.PLAYER, (60, 60, 90, 90), track_id="gt-b"),
    ]
    result = evaluate_tracking(preds, truth)
    assert result.id_switches == 1
    assert result.idf1 < 1.0


def test_tracking_counts_fragmentation() -> None:
    preds = [
        tracked(0, "player-1", (10, 10, 50, 50)),
        tracked(1, "player-2", (10, 10, 50, 50)),
    ]
    truth = [
        ground_truth(n, ObjectClass.PLAYER, (10, 10, 50, 50), track_id="gt-a")
        for n in range(2)
    ]
    result = evaluate_tracking(preds, truth)
    assert result.fragmentations == 1


def test_tracking_requires_identified_ground_truth() -> None:
    with pytest.raises(EvaluationError):
        evaluate_tracking([], [])
    with pytest.raises(EvaluationError):
        evaluate_tracking(
            [tracked(0, "player-1", (10, 10, 50, 50))],
            [ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50))],
        )
    with pytest.raises(EvaluationError):
        evaluate_tracking(["not-a-track"], [])  # type: ignore[list-item]


def test_tracking_reports_labelled_simplified() -> None:
    result = evaluate_tracking(
        [tracked(0, "player-1", (10, 10, 50, 50))],
        [ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50), track_id="gt-a")],
    )
    reports = result.reports("SYNTHETIC-fixture", tracker="fake-tracker")
    assert {r.metric_name for r in reports} == {
        "tracking_idf1",
        "tracking_mota",
        "tracking_id_switches",
        "tracking_fragmentations",
    }
    assert "simplified" in reports[0].notes.lower() or "CLEAR" in reports[0].notes


def test_pitch_mapping_known_errors() -> None:
    preds = [
        PredictedPitchPoint(frame_number=0, track_id="player-1", x=0.5, y=0.5),
        PredictedPitchPoint(frame_number=1, track_id="player-1", x=0.53, y=0.5),
        PredictedPitchPoint(frame_number=2, track_id="player-1", x=0.54, y=0.5),
    ]
    truth = [
        GroundTruthPitchPoint(frame_number=n, track_id="player-1", x=0.5, y=0.5)
        for n in range(3)
    ]
    result = evaluate_pitch_mapping(preds, truth, tolerance=0.02)
    assert result.count == 3
    assert result.mean_error == pytest.approx(0.07 / 3)
    assert result.median_error == pytest.approx(0.03)
    assert result.max_error == pytest.approx(0.04)
    assert result.inlier_count == 1
    assert result.inlier_ratio == pytest.approx(1 / 3)


def test_pitch_mapping_requires_overlap() -> None:
    with pytest.raises(EvaluationError):
        evaluate_pitch_mapping([], [])
    with pytest.raises(EvaluationError):
        evaluate_pitch_mapping(
            [PredictedPitchPoint(frame_number=9, track_id="x", x=0.1, y=0.1)],
            [GroundTruthPitchPoint(frame_number=0, track_id="y", x=0.1, y=0.1)],
        )


def test_pitch_mapping_reports() -> None:
    result = evaluate_pitch_mapping(
        [PredictedPitchPoint(frame_number=0, track_id="a", x=0.5, y=0.5)],
        [GroundTruthPitchPoint(frame_number=0, track_id="a", x=0.5, y=0.5)],
    )
    reports = result.reports("SYNTHETIC-fixture", calibration="cal-1")
    assert {r.metric_name for r in reports} == {
        "pitch_mean_error",
        "pitch_median_error",
        "pitch_max_error",
        "pitch_inlier_ratio",
    }
    assert all(r.calibration == "cal-1" for r in reports)


def test_ground_truth_never_mutated() -> None:
    truth = [ground_truth(0, ObjectClass.PLAYER, (10, 10, 50, 50), track_id="gt-a")]
    snapshot = [g.model_dump() for g in truth]
    evaluate_tracking([tracked(0, "player-1", (10, 10, 50, 50))], truth)
    evaluate_detections(
        [prediction(0, ObjectClass.PLAYER, (10, 10, 50, 50), 0.9)], truth
    )
    assert [g.model_dump() for g in truth] == snapshot
