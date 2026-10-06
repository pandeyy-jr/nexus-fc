"""Phase 07G evaluation tests. ALL fixtures are SYNTHETIC unit-test
mathematics for verifying matching and metric code. They are NOT
real-world football performance measurements."""

from uuid import UUID

import pytest

from app.ai.tactics.evaluation import (
    GroundTruthEvent,
    evaluate_tactical_events,
    temporal_iou,
)
from app.ai.tactics.events import (
    DetectionMethod,
    EventEvidence,
    EventType,
    TacticalEvent,
)
from app.ai.vision.evaluation import EvaluationError

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def prediction(
    event_type: EventType,
    start: float,
    end: float,
    method: DetectionMethod = DetectionMethod.RULE,
) -> TacticalEvent:
    return TacticalEvent(
        event_type=event_type,
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        start_frame=int(start * 10),
        end_frame=int(end * 10),
        start_timestamp=start,
        end_timestamp=end,
        confidence=None,
        detection_method=method,
        evidence=EventEvidence(
            track_ids=("player-1",),
            start_frame=int(start * 10),
            end_frame=int(end * 10),
            detector_name="test",
        ),
    )


def truth(event_type: EventType, start: float, end: float) -> GroundTruthEvent:
    return GroundTruthEvent(
        event_type=event_type,
        start_frame=int(start * 10),
        end_frame=int(end * 10),
        start_timestamp=start,
        end_timestamp=end,
    )


def test_temporal_iou_known_values() -> None:
    assert temporal_iou((0.0, 1.0), (0.0, 1.0)) == pytest.approx(1.0)
    assert temporal_iou((0.0, 1.0), (2.0, 3.0)) == pytest.approx(0.0)
    assert temporal_iou((0.0, 2.0), (1.0, 3.0)) == pytest.approx(1 / 3)
    assert temporal_iou((1.0, 1.0), (1.0, 1.0)) == pytest.approx(1.0)


# 1. Perfect prediction.
def test_perfect_prediction() -> None:
    result = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
        [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
    )
    metrics = result.per_type[EventType.PLAYER_MOVEMENT]
    assert (
        metrics.true_positives,
        metrics.false_positives,
        metrics.false_negatives,
    ) == (1, 0, 0)
    assert metrics.precision == pytest.approx(1.0)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.f1 == pytest.approx(1.0)
    assert metrics.mean_temporal_iou == pytest.approx(1.0)
    assert metrics.mean_detection_latency == pytest.approx(0.0)
    assert result.micro_f1 == pytest.approx(1.0)


# 2. No predictions: everything is a false negative, no fabrication.
def test_no_predictions() -> None:
    result = evaluate_tactical_events([], [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)])
    metrics = result.per_type[EventType.PLAYER_MOVEMENT]
    assert metrics.recall == pytest.approx(0.0)
    assert metrics.precision == pytest.approx(0.0)
    assert metrics.false_negatives == 1


# 3. No ground truth: explicit error, never fake metrics.
def test_no_ground_truth_errors() -> None:
    with pytest.raises(EvaluationError):
        evaluate_tactical_events([], [])
    with pytest.raises(EvaluationError):
        evaluate_tactical_events([prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)], [])


# 4/5. One false positive / one false negative.
def test_false_positive_and_negative() -> None:
    fp = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 5.0, 6.0)],
        [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
    )
    assert fp.per_type[EventType.PLAYER_MOVEMENT].false_positives == 1
    assert fp.per_type[EventType.PLAYER_MOVEMENT].false_negatives == 1
    assert fp.per_type[EventType.PLAYER_MOVEMENT].precision == pytest.approx(0.0)


# 6/7. Partial vs no overlap at the default threshold.
def test_partial_and_missing_overlap() -> None:
    partial = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 2.0)],
        [truth(EventType.PLAYER_MOVEMENT, 1.0, 3.0)],
    )
    # IoU = 1/3 < 0.5: no match at the default threshold.
    assert partial.per_type[EventType.PLAYER_MOVEMENT].true_positives == 0
    loose = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 2.0)],
        [truth(EventType.PLAYER_MOVEMENT, 1.0, 3.0)],
        temporal_iou_threshold=0.25,
    )
    assert loose.per_type[EventType.PLAYER_MOVEMENT].true_positives == 1
    assert loose.per_type[EventType.PLAYER_MOVEMENT].mean_temporal_iou == pytest.approx(
        1 / 3
    )


# 8/9. Multiple types and events score independently.
def test_multiple_types_and_events() -> None:
    result = evaluate_tactical_events(
        [
            prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
            prediction(EventType.PLAYER_MOVEMENT, 2.0, 3.0),
            prediction(EventType.SPATIAL_OVERLOAD, 0.0, 1.0),
        ],
        [
            truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
            truth(EventType.SPATIAL_OVERLOAD, 5.0, 6.0),
        ],
    )
    movement = result.per_type[EventType.PLAYER_MOVEMENT]
    assert (
        movement.true_positives,
        movement.false_positives,
        movement.false_negatives,
    ) == (1, 1, 0)
    overload = result.per_type[EventType.SPATIAL_OVERLOAD]
    assert (
        overload.true_positives,
        overload.false_positives,
        overload.false_negatives,
    ) == (0, 1, 1)
    assert result.micro_precision == pytest.approx(1 / 3)
    assert result.ground_truth_count == 2
    assert result.prediction_count == 3


# 10. Duplicate predictions: one TP, one FP.
def test_duplicate_predictions() -> None:
    result = evaluate_tactical_events(
        [
            prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
            prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
        ],
        [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
    )
    metrics = result.per_type[EventType.PLAYER_MOVEMENT]
    assert (metrics.true_positives, metrics.false_positives) == (1, 1)


# 11. Threshold behavior is explicit and validated.
def test_threshold_behavior() -> None:
    with pytest.raises(EvaluationError):
        evaluate_tactical_events(
            [prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
            [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
            temporal_iou_threshold=1.5,
        )
    strict = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
        [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
        temporal_iou_threshold=1.0,
    )
    assert strict.per_type[EventType.PLAYER_MOVEMENT].true_positives == 1


# 12. Deterministic results.
def test_deterministic_results() -> None:
    preds = [
        prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
        prediction(EventType.SPATIAL_OVERLOAD, 0.5, 1.5),
    ]
    gts = [
        truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0),
        truth(EventType.SPATIAL_OVERLOAD, 0.5, 1.5),
    ]
    first = evaluate_tactical_events(preds, gts)
    second = evaluate_tactical_events(list(reversed(preds)), list(reversed(gts)))
    assert first.micro_f1 == second.micro_f1
    assert first.per_type.keys() == second.per_type.keys()


# 13. Invalid timestamps rejected at the contract boundary.
def test_invalid_timestamps_rejected() -> None:
    with pytest.raises(ValueError):
        GroundTruthEvent(
            event_type=EventType.PLAYER_MOVEMENT,
            start_frame=2,
            end_frame=1,
            start_timestamp=0.0,
            end_timestamp=1.0,
        )
    with pytest.raises(ValueError):
        GroundTruthEvent(
            event_type=EventType.PLAYER_MOVEMENT,
            start_frame=0,
            end_frame=1,
            start_timestamp=float("nan"),
            end_timestamp=1.0,
        )


# 14. Empty predictions list is valid input; wrong types are not.
def test_empty_and_wrong_typed_inputs() -> None:
    result = evaluate_tactical_events(
        [], [truth(EventType.TEAM_COMPACTNESS_CHANGE, 0.0, 1.0)]
    )
    assert EventType.TEAM_COMPACTNESS_CHANGE in result.per_type
    with pytest.raises(EvaluationError):
        evaluate_tactical_events(["nope"], [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)])  # type: ignore[list-item]


# 15. Reports carry counts, threshold, methods; latency present on matches.
def test_reports() -> None:
    result = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
        [truth(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
    )
    reports = result.reports("SYNTHETIC-fixture")
    names = {r.metric_name for r in reports}
    assert {
        "tactical_event_precision",
        "tactical_event_recall",
        "tactical_event_f1",
        "tactical_event_mean_temporal_iou",
        "tactical_event_mean_detection_latency",
        "tactical_event_micro_precision",
        "tactical_event_micro_recall",
        "tactical_event_micro_f1",
    } <= names
    assert all(r.dataset == "SYNTHETIC-fixture" for r in reports)
    assert any("RULE" in r.notes and "tp=1" in r.notes for r in reports)


def test_detection_latency_sign() -> None:
    early = evaluate_tactical_events(
        [prediction(EventType.PLAYER_MOVEMENT, 0.0, 1.0)],
        [truth(EventType.PLAYER_MOVEMENT, 0.5, 1.5)],
        temporal_iou_threshold=0.1,
    )
    assert early.per_type[
        EventType.PLAYER_MOVEMENT
    ].mean_detection_latency == pytest.approx(-0.5)
