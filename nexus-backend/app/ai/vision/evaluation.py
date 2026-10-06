"""Phase 06H — evaluation infrastructure.

Computes real metrics from actual predictions plus actual ground truth.
No ground truth → no metrics (``EvaluationError``), never fabricated.

Kept strictly separate:

- detection metrics (precision/recall/F1/AP/mAP, IoU)
- tracking metrics (IDF1/MOTA-style, ID switches, fragmentation)
- pitch-mapping metrics (mean/median/max error, inliers)

Tracking scores are simplified single-camera CLEAR-MOT-style measures and
are labelled as such in report notes — they are not claimed to equal a
reference MOTChallenge implementation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ai.vision.schemas import BoundingBox, Detection, ObjectClass, TrackedObject

MAX_EVAL_ITEMS = 100_000


class EvaluationError(ValueError):
    """Evaluation input is missing, malformed, or insufficient for metrics."""


class GroundTruthDetection(BaseModel):
    """One annotated object. Prediction data must never be overwritten with this."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_number: int = Field(ge=0)
    object_class: ObjectClass
    bounding_box: BoundingBox
    track_id: str | None = Field(default=None, min_length=1, max_length=100)


class GroundTruthPitchPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_number: int = Field(ge=0)
    track_id: str = Field(min_length=1, max_length=100)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class PredictedPitchPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_number: int = Field(ge=0)
    track_id: str = Field(min_length=1, max_length=100)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class EvaluationReport(BaseModel):
    """Structured backend result — no UI, no charts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_name: str = Field(min_length=1, max_length=100)
    value: float = Field(allow_inf_nan=False)
    dataset: str = Field(min_length=1, max_length=200)
    object_class: str | None = Field(default=None, max_length=50)
    frame_range: tuple[int, int] | None = None
    model: str | None = Field(default=None, max_length=200)
    tracker: str | None = Field(default=None, max_length=200)
    calibration: str | None = Field(default=None, max_length=200)
    evaluated_at: datetime
    notes: str = Field(default="", max_length=1000)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def box_tuple(box: BoundingBox) -> tuple[float, float, float, float]:
    return (box.x_min, box.y_min, box.x_max, box.y_max)


def iou_boxes(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    inter_w = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    inter_h = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - inter
    return inter / union if union > 0 else 0.0


def _check_bounds(name: str, items: Sequence[object]) -> None:
    if len(items) > MAX_EVAL_ITEMS:
        raise EvaluationError(f"Too many {name} items for evaluation")


def _frame_range(numbers: list[int]) -> tuple[int, int] | None:
    return (min(numbers), max(numbers)) if numbers else None


# ---------------------------------------------------------------------------
# Detection evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetectionClassMetrics:
    object_class: ObjectClass
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    mean_iou: float
    average_precision: float


@dataclass(frozen=True)
class DetectionEvaluation:
    per_class: dict[ObjectClass, DetectionClassMetrics]
    mean_average_precision: float
    iou_threshold: float

    def reports(
        self,
        dataset: str,
        *,
        model: str | None = None,
        frame_range: tuple[int, int] | None = None,
    ) -> list[EvaluationReport]:
        evaluated_at = _utcnow()
        out: list[EvaluationReport] = []
        for metrics in self.per_class.values():
            for name, value in (
                ("precision", metrics.precision),
                ("recall", metrics.recall),
                ("f1", metrics.f1),
                ("mean_iou", metrics.mean_iou),
                ("average_precision", metrics.average_precision),
            ):
                out.append(
                    EvaluationReport(
                        metric_name=f"detection_{name}",
                        value=value,
                        dataset=dataset,
                        object_class=metrics.object_class.value,
                        frame_range=frame_range,
                        model=model,
                        evaluated_at=evaluated_at,
                        notes=f"IoU threshold {self.iou_threshold}",
                    )
                )
        out.append(
            EvaluationReport(
                metric_name="detection_mAP",
                value=self.mean_average_precision,
                dataset=dataset,
                frame_range=frame_range,
                model=model,
                evaluated_at=evaluated_at,
                notes=f"Mean over {len(self.per_class)} classes",
            )
        )
        return out


def _average_precision(
    scores: list[tuple[float, bool]], total_ground_truth: int
) -> float:
    """All-points interpolated AP over confidence-ranked predictions."""
    if not scores or total_ground_truth == 0:
        return 0.0
    ranked = sorted(scores, key=lambda item: -item[0])
    points: list[tuple[float, float]] = []
    hits = 0
    for rank, (_, matched) in enumerate(ranked, start=1):
        if matched:
            hits += 1
        points.append((hits / rank, hits / total_ground_truth))
    # All-points interpolation: average max precision at each recall level.
    area = 0.0
    previous_recall = 0.0
    recall_levels = sorted({recall for _, recall in points})
    for recall in recall_levels:
        best = max(p for p, r in points if r >= recall)
        area += best * (recall - previous_recall)
        previous_recall = recall
    return area if points else 0.0


def evaluate_detections(
    predictions: Sequence[Detection],
    ground_truth: Sequence[GroundTruthDetection],
    *,
    iou_threshold: float = 0.5,
) -> DetectionEvaluation:
    _check_bounds("prediction", predictions)
    _check_bounds("ground-truth", ground_truth)
    if not 0 < iou_threshold <= 1:
        raise EvaluationError("IoU threshold must lie in (0, 1]")
    if not ground_truth:
        raise EvaluationError("Detection metrics require ground truth")
    for item in (*predictions, *ground_truth):
        if isinstance(item, Detection):
            box_tuple(item.bounding_box)

    per_class: dict[ObjectClass, DetectionClassMetrics] = {}
    for object_class in ObjectClass:
        gt_boxes = [
            (g.frame_number, box_tuple(g.bounding_box))
            for g in ground_truth
            if g.object_class is object_class
        ]
        preds = [p for p in predictions if p.object_class is object_class]
        if not gt_boxes and not preds:
            continue
        matched_gt: set[int] = set()
        scored: list[tuple[float, bool]] = []
        ious: list[float] = []
        tps = 0
        for pred in sorted(preds, key=lambda p: -p.confidence):
            frame = pred.frame.frame_number
            box = box_tuple(pred.bounding_box)
            best_idx, best_iou = -1, 0.0
            for idx, (gt_frame, gt_box) in enumerate(gt_boxes):
                if idx in matched_gt or gt_frame != frame:
                    continue
                score = iou_boxes(box, gt_box)
                if score > best_iou:
                    best_idx, best_iou = idx, score
            if best_iou >= iou_threshold:
                matched_gt.add(best_idx)
                tps += 1
                scored.append((pred.confidence, True))
                ious.append(best_iou)
            else:
                scored.append((pred.confidence, False))
        fps = len(preds) - tps
        fns = len(gt_boxes) - tps
        precision = tps / (tps + fps) if preds else 0.0
        recall = tps / (tps + fns) if gt_boxes else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall > 0
            else 0.0
        )
        per_class[object_class] = DetectionClassMetrics(
            object_class=object_class,
            true_positives=tps,
            false_positives=fps,
            false_negatives=fns,
            precision=precision,
            recall=recall,
            f1=f1,
            mean_iou=sum(ious) / len(ious) if ious else 0.0,
            average_precision=_average_precision(scored, len(gt_boxes)),
        )
    if not per_class:
        raise EvaluationError("No comparable classes between predictions and truth")
    mean_ap = sum(m.average_precision for m in per_class.values()) / len(per_class)
    return DetectionEvaluation(
        per_class=per_class,
        mean_average_precision=mean_ap,
        iou_threshold=iou_threshold,
    )


# ---------------------------------------------------------------------------
# Tracking evaluation (simplified CLEAR-MOT-style)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackingEvaluation:
    idf1: float
    mota: float
    id_switches: int
    fragmentations: int
    ground_truth_tracks: int
    predicted_tracks: int
    ground_truth_boxes: int
    matched_boxes: int
    frame_range: tuple[int, int] | None = None

    def reports(
        self,
        dataset: str,
        *,
        tracker: str | None = None,
    ) -> list[EvaluationReport]:
        evaluated_at = _utcnow()
        return [
            EvaluationReport(
                metric_name=f"tracking_{name}",
                value=value,
                dataset=dataset,
                tracker=tracker,
                frame_range=self.frame_range,
                evaluated_at=evaluated_at,
                notes="Simplified single-camera CLEAR-MOT-style measure",
            )
            for name, value in (
                ("idf1", self.idf1),
                ("mota", self.mota),
                ("id_switches", float(self.id_switches)),
                ("fragmentations", float(self.fragmentations)),
            )
        ]


@dataclass
class _FrameObservation:
    frame_number: int
    track_id: str
    object_class: ObjectClass
    box: tuple[float, float, float, float]


def _tracked_observations(
    predictions: Sequence[object],
) -> list[_FrameObservation]:
    observations: list[_FrameObservation] = []
    for item in predictions:
        if not isinstance(item, TrackedObject):
            raise EvaluationError("Tracking predictions must be TrackedObject items")
        observations.append(
            _FrameObservation(
                frame_number=item.frame.frame_number,
                track_id=item.tracking_id,
                object_class=item.object_class,
                box=box_tuple(item.bounding_box),
            )
        )
    return observations


def evaluate_tracking(
    predictions: Sequence[object],
    ground_truth: Sequence[GroundTruthDetection],
    *,
    iou_threshold: float = 0.5,
) -> TrackingEvaluation:
    _check_bounds("prediction", predictions)
    _check_bounds("ground-truth", ground_truth)
    if not 0 < iou_threshold <= 1:
        raise EvaluationError("IoU threshold must lie in (0, 1]")
    if not ground_truth:
        raise EvaluationError("Tracking metrics require ground truth")
    gt_with_ids = [g for g in ground_truth if g.track_id is not None]
    if not gt_with_ids:
        raise EvaluationError("Tracking ground truth requires track IDs")
    pred_obs = _tracked_observations(predictions)

    gt_by_frame: dict[int, list[int]] = defaultdict(list)
    for idx, g in enumerate(gt_with_ids):
        gt_by_frame[g.frame_number].append(idx)
    pred_by_frame: dict[int, list[int]] = defaultdict(list)
    for idx, o in enumerate(pred_obs):
        pred_by_frame[o.frame_number].append(idx)

    # Greedy frame-level matching (same class, best IoU).
    matches: list[tuple[int, int]] = []  # (pred_idx, gt_idx)
    unmatched_pred = set(range(len(pred_obs)))
    unmatched_gt = set(range(len(gt_with_ids)))
    for frame in sorted(set(gt_by_frame) | set(pred_by_frame)):
        candidates: list[tuple[float, int, int]] = []
        for pi in pred_by_frame.get(frame, []):
            for gi in gt_by_frame.get(frame, []):
                if pred_obs[pi].object_class is not gt_with_ids[gi].object_class:
                    continue
                score = iou_boxes(
                    pred_obs[pi].box, box_tuple(gt_with_ids[gi].bounding_box)
                )
                if score >= iou_threshold:
                    candidates.append((score, pi, gi))
        candidates.sort(reverse=True)
        used_pi, used_gi = set(), set()
        for _, pi, gi in candidates:
            if pi in used_pi or gi in used_gi:
                continue
            used_pi.add(pi)
            used_gi.add(gi)
            matches.append((pi, gi))
            unmatched_pred.discard(pi)
            unmatched_gt.discard(gi)

    # Majority-vote mappings both directions.
    pred_to_gt: dict[str, str] = {}
    gt_to_pred: dict[str, str] = {}
    pred_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    gt_votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for pi, gi in matches:
        pred_votes[pred_obs[pi].track_id][gt_with_ids[gi].track_id or ""] += 1
        gt_votes[gt_with_ids[gi].track_id or ""][pred_obs[pi].track_id] += 1
    for track_id, votes in pred_votes.items():
        pred_to_gt[track_id] = max(votes, key=lambda k: votes[k])
    for track_id, votes in gt_votes.items():
        gt_to_pred[track_id] = max(votes, key=lambda k: votes[k])

    idtp = idfp = idfn = 0
    for pi, gi in matches:
        pred_id = pred_obs[pi].track_id
        gt_id = gt_with_ids[gi].track_id or ""
        if pred_to_gt.get(pred_id) == gt_id and gt_to_pred.get(gt_id) == pred_id:
            idtp += 1
        else:
            idfp += 1
            idfn += 1
    idfp += len(unmatched_pred)
    idfn += len(unmatched_gt)
    idf1 = 2 * idtp / (2 * idtp + idfp + idfn) if (2 * idtp + idfp + idfn) else 0.0

    # ID switches: one predicted track matched to different GT IDs over time.
    switches = 0
    pred_frames: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for pi, gi in matches:
        pred_frames[pred_obs[pi].track_id].append(
            (pred_obs[pi].frame_number, gt_with_ids[gi].track_id or "")
        )
    for timeline in pred_frames.values():
        ordered = [gt for _, gt in sorted(timeline)]
        switches += sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if a != b)

    # Fragmentation: distinct predicted tracks covering one GT track, minus one.
    gt_cover: dict[str, set[str]] = defaultdict(set)
    for pi, gi in matches:
        gt_cover[gt_with_ids[gi].track_id or ""].add(pred_obs[pi].track_id)
    fragmentations = sum(max(0, len(cover) - 1) for cover in gt_cover.values())

    total_gt = len(gt_with_ids)
    mota = (
        1.0 - (len(unmatched_gt) + len(unmatched_pred) + switches) / total_gt
        if total_gt
        else 0.0
    )
    frames = [g.frame_number for g in gt_with_ids] + [o.frame_number for o in pred_obs]
    return TrackingEvaluation(
        idf1=idf1,
        mota=mota,
        id_switches=switches,
        fragmentations=fragmentations,
        ground_truth_tracks=len({g.track_id for g in gt_with_ids}),
        predicted_tracks=len({o.track_id for o in pred_obs}),
        ground_truth_boxes=total_gt,
        matched_boxes=len(matches),
        frame_range=_frame_range(frames),
    )


# ---------------------------------------------------------------------------
# Pitch-mapping evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PitchEvaluation:
    count: int
    mean_error: float
    median_error: float
    max_error: float
    inlier_count: int
    inlier_ratio: float
    unmatched_predictions: int
    missing_ground_truth: int
    frame_range: tuple[int, int] | None = None

    def reports(
        self,
        dataset: str,
        *,
        calibration: str | None = None,
    ) -> list[EvaluationReport]:
        evaluated_at = _utcnow()
        return [
            EvaluationReport(
                metric_name=f"pitch_{name}",
                value=value,
                dataset=dataset,
                calibration=calibration,
                frame_range=self.frame_range,
                evaluated_at=evaluated_at,
                notes="Normalized pitch-space Euclidean error",
            )
            for name, value in (
                ("mean_error", self.mean_error),
                ("median_error", self.median_error),
                ("max_error", self.max_error),
                ("inlier_ratio", self.inlier_ratio),
            )
        ]


def evaluate_pitch_mapping(
    predictions: Sequence[PredictedPitchPoint],
    ground_truth: Sequence[GroundTruthPitchPoint],
    *,
    tolerance: float = 0.02,
) -> PitchEvaluation:
    _check_bounds("prediction", predictions)
    _check_bounds("ground-truth", ground_truth)
    if tolerance <= 0:
        raise EvaluationError("Tolerance must be positive")
    if not ground_truth:
        raise EvaluationError("Pitch-mapping metrics require ground truth")
    gt_lookup = {(g.frame_number, g.track_id): g for g in ground_truth}
    errors: list[float] = []
    unmatched = 0
    seen: set[tuple[int, str]] = set()
    for pred in predictions:
        key = (pred.frame_number, pred.track_id)
        gt = gt_lookup.get(key)
        if gt is None:
            unmatched += 1
            continue
        seen.add(key)
        errors.append(math.dist((pred.x, pred.y), (gt.x, gt.y)))
    if not errors:
        raise EvaluationError("No overlapping prediction/ground-truth keys")
    ordered = sorted(errors)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    inliers = sum(1 for e in errors if e <= tolerance)
    frames = [g.frame_number for g in ground_truth] + [
        p.frame_number for p in predictions
    ]
    return PitchEvaluation(
        count=len(errors),
        mean_error=sum(errors) / len(errors),
        median_error=median,
        max_error=max(errors),
        inlier_count=inliers,
        inlier_ratio=inliers / len(errors),
        unmatched_predictions=unmatched,
        missing_ground_truth=len(gt_lookup) - len(seen),
        frame_range=_frame_range(frames),
    )


__all__ = [
    "EvaluationError",
    "EvaluationReport",
    "GroundTruthDetection",
    "GroundTruthPitchPoint",
    "PredictedPitchPoint",
    "DetectionClassMetrics",
    "DetectionEvaluation",
    "TrackingEvaluation",
    "PitchEvaluation",
    "evaluate_detections",
    "evaluate_tracking",
    "evaluate_pitch_mapping",
    "iou_boxes",
]
