"""Phase 07I — tactical intelligence service boundary.

Single application entry point over the completed Phase 07 pipeline so
future API, AI-agent, Club Memory, and frontend layers never import
low-level tactical modules directly:

VisionObservation(s) -> TacticalIntelligenceService.analyze()
  -> TacticalAnalysisResult (events + scalar metadata + provenance)

The result contract exposes NO raw tensors/embeddings: representation
vectors stay inside the pipeline. Events keep full evidence for
traceability. Failures are explicit; nothing is fabricated.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.tactics.events import TacticalEvent
from app.ai.tactics.fusion import FusionConfig, TemporalGraphFusion
from app.ai.tactics.gnn import GNNConfig, GraphNeuralEncoder
from app.ai.tactics.pipeline import (
    InvalidPipelineInput,
    TacticalSmokePipeline,
)
from app.ai.tactics.state import InvalidTacticalInput
from app.ai.tactics.transformer import TemporalTransformer, TransformerConfig
from app.ai.vision.schemas import VisionObservation

SERVICE_VERSION = "07I.1"


class TacticalServiceError(RuntimeError):
    """Base class for explicit tactical-service failures."""


class TacticalServiceUnavailable(TacticalServiceError):
    """The service has no usable model components configured."""


class InvalidTacticalRequest(TacticalServiceError, ValueError):
    """Observations or ground truth cannot be analyzed."""


class TacticalAnalysisResult(BaseModel):
    """Public contract: context, events, scalar metadata, provenance.

    Representation vectors are deliberately absent — see
    ``representation_metadata`` for shapes/versions instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: UUID
    source_id: UUID
    frame_range: tuple[int, int]
    time_range: tuple[float, float]
    events: tuple[TacticalEvent, ...]
    event_count: int = Field(ge=0)
    representation_metadata: dict[str, str | float | bool]
    provenance: dict[str, tuple[str, ...]]
    evaluated: bool = False
    evaluation_summary: dict[str, float] = Field(default_factory=dict)
    analyzed_at: datetime
    service_version: str = SERVICE_VERSION


class TacticalIntelligenceService:
    """Thin boundary over the existing tactical pipeline."""

    def __init__(
        self,
        pipeline: TacticalSmokePipeline | None,
    ) -> None:
        self._pipeline = pipeline

    @classmethod
    def with_defaults(cls) -> TacticalIntelligenceService:
        """Tiny deterministic CPU components; no downloads, no training."""
        transformer = TemporalTransformer(
            TransformerConfig(
                feature_dim=8 * 9,
                model_dim=8,
                num_heads=2,
                num_layers=1,
                feedforward_dim=16,
            )
        ).eval()
        encoder = GraphNeuralEncoder(
            GNNConfig(hidden_dim=8, output_dim=4, num_layers=1)
        ).eval()
        fusion = TemporalGraphFusion(
            FusionConfig(temporal_dim=8, graph_dim=4, fusion_dim=6)
        ).eval()
        return cls(
            TacticalSmokePipeline(transformer, encoder, fusion),
        )

    @classmethod
    def unavailable(cls) -> TacticalIntelligenceService:
        """Explicitly unconfigured service for testing unavailable paths."""
        return cls(None)

    @property
    def is_available(self) -> bool:
        return self._pipeline is not None

    def analyze(
        self,
        observations: Sequence[VisionObservation],
        ground_truth: Sequence[object] | None = None,
    ) -> TacticalAnalysisResult:
        if self._pipeline is None:
            raise TacticalServiceUnavailable("No tactical model components configured")
        items = list(observations)
        if not items:
            raise InvalidTacticalRequest("At least one observation is required")
        if any(not isinstance(item, VisionObservation) for item in items):
            raise InvalidTacticalRequest("All items must be VisionObservation records")
        try:
            result = self._pipeline.run(items, ground_truth)
        except (InvalidTacticalInput, InvalidPipelineInput) as exc:
            raise InvalidTacticalRequest(str(exc)) from exc
        frames = result.sequence.frames
        frame_range = (frames[0].frame_index, frames[-1].frame_index)
        time_range = (frames[0].timestamp_seconds, frames[-1].timestamp_seconds)
        calibration_ids = sorted({o.calibration_id for o in items if o.calibration_id})
        detector_names = sorted({o.detector_name for o in items if o.detector_name})
        tracker_names = sorted({o.tracker_name for o in items if o.tracker_name})
        track_ids = sorted({o.tracking_id for o in items})
        evaluation_summary: dict[str, float] = {}
        evaluated = result.evaluation is not None
        if evaluated:
            evaluation_summary = {
                "micro_f1": result.evaluation.micro_f1,  # type: ignore[union-attr]
                "micro_precision": result.evaluation.micro_precision,  # type: ignore[union-attr]
                "micro_recall": result.evaluation.micro_recall,  # type: ignore[union-attr]
                "ground_truth_count": float(result.evaluation.ground_truth_count),  # type: ignore[union-attr]
                "prediction_count": float(result.evaluation.prediction_count),  # type: ignore[union-attr]
            }
        return TacticalAnalysisResult(
            match_id=result.sequence.frames[0].match_id,
            source_id=result.sequence.frames[0].source_id,
            frame_range=frame_range,
            time_range=time_range,
            events=result.events,
            event_count=len(result.events),
            representation_metadata={
                "encoder_version": "07B-1.1",
                "transformer_version": "07B-2.1",
                "gnn_version": "07D.1",
                "fusion_version": "07E.1",
                "frames": float(len(frames)),
                "fused_dim": float(len(result.fused_frames[0].fused_embedding)),
                "fusion_temporal_available": all(
                    f.temporal_available for f in result.fused_frames
                ),
                "fusion_graph_available": all(
                    f.graph_available for f in result.fused_frames
                ),
            },
            provenance={
                "calibration_ids": tuple(calibration_ids),
                "detector_names": tuple(detector_names),
                "tracker_names": tuple(tracker_names),
                "track_ids": tuple(track_ids),
            },
            evaluated=evaluated,
            evaluation_summary=evaluation_summary,
            analyzed_at=datetime.now(UTC),
        )


__all__ = [
    "InvalidTacticalRequest",
    "TacticalAnalysisResult",
    "TacticalIntelligenceService",
    "TacticalServiceError",
    "TacticalServiceUnavailable",
]
