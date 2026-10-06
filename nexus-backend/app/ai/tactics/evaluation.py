"""Phase 07G — tactical event evaluation.

Compares GROUND TRUTH events against PREDICTED events:

ground truth + predictions -> TacticalEventEvaluation -> reports

Metrics: precision/recall/F1 (per event type + micro overall),
temporal IoU matching, detection latency. Matching is greedy,
deterministic, one-to-one within the same event type at a
configurable temporal-IoU threshold (default 0.5).

No ground truth -> EvaluationError (reused from Phase 06), never
fabricated metrics. Synthetic fixtures in tests are unit-test
mathematics, NOT real-world football performance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.tactics.events import EventType, TacticalEvent
from app.ai.vision.evaluation import EvaluationError, EvaluationReport

MAX_EVAL_EVENTS = 100_000


class GroundTruthEvent(BaseModel):
    """Human- (or otherwise-) annotated event for scoring predictions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    start_timestamp: float = Field(ge=0, allow_inf_nan=False)
    end_timestamp: float = Field(ge=0, allow_inf_nan=False)
    track_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_temporal_order(self) -> GroundTruthEvent:
        if self.end_frame < self.start_frame:
            raise ValueError("Event end frame must not precede start frame")
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("Event end time must not precede start time")
        return self


@dataclass(frozen=True)
class EventTypeMetrics:
    event_type: EventType
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    mean_temporal_iou: float
    mean_detection_latency: float | None


@dataclass(frozen=True)
class TacticalEventEvaluation:
    per_type: dict[EventType, EventTypeMetrics]
    micro_precision: float
    micro_recall: float
    micro_f1: float
    temporal_iou_threshold: float
    ground_truth_count: int
    prediction_count: int
    prediction_methods: tuple[str, ...] = ()

    def reports(
        self,
        dataset: str,
        *,
        frame_range: tuple[int, int] | None = None,
    ) -> list[EvaluationReport]:
        evaluated_at = datetime.now(UTC)
        out: list[EvaluationReport] = []
        for metrics in self.per_type.values():
            context = (
                f"tp={metrics.true_positives} fp={metrics.false_positives} "
                f"fn={metrics.false_negatives} "
                f"gt={self.ground_truth_count} preds={self.prediction_count} "
                f"iou_threshold={self.temporal_iou_threshold} "
                f"methods={','.join(self.prediction_methods)}"
            )
            for name, value in (
                ("precision", metrics.precision),
                ("recall", metrics.recall),
                ("f1", metrics.f1),
                ("mean_temporal_iou", metrics.mean_temporal_iou),
            ):
                out.append(
                    EvaluationReport(
                        metric_name=f"tactical_event_{name}",
                        value=value,
                        dataset=dataset,
                        object_class=metrics.event_type.value,
                        frame_range=frame_range,
                        evaluated_at=evaluated_at,
                        notes=context,
                    )
                )
            if metrics.mean_detection_latency is not None:
                out.append(
                    EvaluationReport(
                        metric_name="tactical_event_mean_detection_latency",
                        value=metrics.mean_detection_latency,
                        dataset=dataset,
                        object_class=metrics.event_type.value,
                        frame_range=frame_range,
                        evaluated_at=evaluated_at,
                        notes=context,
                    )
                )
        for name, value in (
            ("micro_precision", self.micro_precision),
            ("micro_recall", self.micro_recall),
            ("micro_f1", self.micro_f1),
        ):
            out.append(
                EvaluationReport(
                    metric_name=f"tactical_event_{name}",
                    value=value,
                    dataset=dataset,
                    frame_range=frame_range,
                    evaluated_at=evaluated_at,
                    notes=(
                        f"micro over {len(self.per_type)} types; "
                        f"gt={self.ground_truth_count} "
                        f"preds={self.prediction_count}"
                    ),
                )
            )
        return out


def temporal_iou(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Interval IoU on [start, end] timestamps; identical points score 1."""
    start = max(first[0], second[0])
    end = min(first[1], second[1])
    overlap = max(0.0, end - start)
    span = max(first[1], second[1]) - min(first[0], second[0])
    if span <= 0:
        return 1.0 if first == second else 0.0
    return overlap / span


def _check_inputs(
    predictions: Sequence[TacticalEvent],
    ground_truth: Sequence[GroundTruthEvent],
    temporal_iou_threshold: float,
) -> None:
    if len(predictions) > MAX_EVAL_EVENTS or len(ground_truth) > MAX_EVAL_EVENTS:
        raise EvaluationError("Too many events for evaluation")
    if not 0 < temporal_iou_threshold <= 1:
        raise EvaluationError("Temporal IoU threshold must lie in (0, 1]")
    if not ground_truth:
        raise EvaluationError("Event metrics require ground truth")
    for item in predictions:
        if not isinstance(item, TacticalEvent):
            raise EvaluationError("Predictions must be TacticalEvent items")
    for item in ground_truth:
        if not isinstance(item, GroundTruthEvent):
            raise EvaluationError("Ground truth must be GroundTruthEvent items")


def evaluate_tactical_events(
    predictions: Sequence[TacticalEvent],
    ground_truth: Sequence[GroundTruthEvent],
    *,
    temporal_iou_threshold: float = 0.5,
) -> TacticalEventEvaluation:
    _check_inputs(predictions, ground_truth, temporal_iou_threshold)
    methods = tuple(sorted({p.detection_method.value for p in predictions}))

    per_type: dict[EventType, EventTypeMetrics] = {}
    for event_type in EventType:
        gt_items = [g for g in ground_truth if g.event_type is event_type]
        pred_items = [p for p in predictions if p.event_type is event_type]
        if not gt_items and not pred_items:
            continue
        candidates: list[tuple[float, int, int]] = []
        for pi, pred in enumerate(pred_items):
            for gi, gt in enumerate(gt_items):
                score = temporal_iou(
                    (pred.start_timestamp, pred.end_timestamp),
                    (gt.start_timestamp, gt.end_timestamp),
                )
                if score >= temporal_iou_threshold:
                    candidates.append((score, pi, gi))
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        matched_pred: set[int] = set()
        matched_gt: set[int] = set()
        ious: list[float] = []
        latencies: list[float] = []
        for score, pi, gi in candidates:
            if pi in matched_pred or gi in matched_gt:
                continue
            matched_pred.add(pi)
            matched_gt.add(gi)
            ious.append(score)
            latencies.append(
                pred_items[pi].start_timestamp - gt_items[gi].start_timestamp
            )
        tps = len(matched_pred)
        fps = len(pred_items) - tps
        fns = len(gt_items) - tps
        precision = tps / (tps + fps) if pred_items else 0.0
        recall = tps / (tps + fns) if gt_items else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall > 0
            else 0.0
        )
        per_type[event_type] = EventTypeMetrics(
            event_type=event_type,
            true_positives=tps,
            false_positives=fps,
            false_negatives=fns,
            precision=precision,
            recall=recall,
            f1=f1,
            mean_temporal_iou=sum(ious) / len(ious) if ious else 0.0,
            mean_detection_latency=(
                sum(latencies) / len(latencies) if latencies else None
            ),
        )
    if not per_type:
        raise EvaluationError("No comparable event types between predictions and truth")
    total_tp = sum(m.true_positives for m in per_type.values())
    total_fp = sum(m.false_positives for m in per_type.values())
    total_fn = sum(m.false_negatives for m in per_type.values())
    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall > 0
        else 0.0
    )
    return TacticalEventEvaluation(
        per_type=per_type,
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=micro_f1,
        temporal_iou_threshold=temporal_iou_threshold,
        ground_truth_count=len(ground_truth),
        prediction_count=len(predictions),
        prediction_methods=methods,
    )


__all__ = [
    "GroundTruthEvent",
    "EventTypeMetrics",
    "TacticalEventEvaluation",
    "evaluate_tactical_events",
    "temporal_iou",
]
