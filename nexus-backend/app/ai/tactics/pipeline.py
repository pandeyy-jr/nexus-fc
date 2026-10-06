"""Phase 07H — end-to-end tactical pipeline smoke test module.

Composes the existing Phase 06 -> Phase 07 components without
redesigning any of them:

VisionObservation -> TacticalSequence -> encoded frames
  -> packed rows -> TemporalTransformer -+-> frame reps -+
  -> per-frame TacticalGraph -> GNN -+-> graph reps -----+-> Fusion
  -> baseline events -> (optional) evaluation vs ground truth

Frame packing is explicit and fixed-width: entities per frame
(players sorted by track id, then ball) concatenated up to
``max_entities_per_frame`` with an entity-validity mask; overflow
is rejected, never silently dropped. Deterministic synthetic data
only — no football intelligence claims.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.ai.tactics.encoding import (
    PLAYER_FEATURE_DIM,
    EncodedTacticalFrame,
    TacticalFeatureEncoder,
)
from app.ai.tactics.events import (
    BaselineDetectorSuite,
    TacticalEvent,
    TacticalEventDetector,
)
from app.ai.tactics.fusion import FusedTacticalRepresentation, TemporalGraphFusion
from app.ai.tactics.gnn import GraphEmbedding, GraphNeuralEncoder
from app.ai.tactics.graph import TacticalGraph, TacticalGraphBuilder
from app.ai.tactics.state import (
    TacticalSequence,
    TacticalStateBuilder,
)
from app.ai.tactics.transformer import TemporalRepresentation, TemporalTransformer
from app.ai.vision.schemas import VisionObservation


class InvalidPipelineInput(ValueError):
    """Observations cannot be composed into the smoke pipeline."""


class SmokePipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_entities_per_frame: int = Field(default=8, ge=1, le=33)


@dataclass(frozen=True)
class SmokePipelineResult:
    sequence: TacticalSequence
    encoded_frames: tuple[EncodedTacticalFrame, ...]
    temporal: TemporalRepresentation
    graphs: tuple[TacticalGraph, ...]
    graph_embeddings: tuple[GraphEmbedding, ...]
    fused_frames: tuple[FusedTacticalRepresentation, ...]
    events: tuple[TacticalEvent, ...]
    evaluation: object = None


def pack_frame_row(
    frame: EncodedTacticalFrame, max_entities: int
) -> tuple[tuple[float, ...], tuple[bool, ...]]:
    """Fixed-width row: concatenated entity vectors + validity mask."""
    if not isinstance(frame, EncodedTacticalFrame):
        raise InvalidPipelineInput("An EncodedTacticalFrame is required")
    entities = list(frame.players) + ([frame.ball] if frame.ball is not None else [])
    if len(entities) > max_entities:
        raise InvalidPipelineInput("Frame holds more entities than the packing width")
    row: list[float] = []
    mask: list[bool] = []
    for entity in entities:
        row.extend(entity.features)
        mask.append(entity.has_position)
    padding = max_entities - len(entities)
    row.extend([0.0] * padding * PLAYER_FEATURE_DIM)
    mask.extend([False] * padding)
    return tuple(row), tuple(mask)


class TacticalSmokePipeline:
    """Thin composer over existing components; no new mathematics."""

    def __init__(
        self,
        transformer: TemporalTransformer,
        encoder: GraphNeuralEncoder,
        fusion: TemporalGraphFusion,
        detectors: Sequence[TacticalEventDetector] | None = None,
        config: SmokePipelineConfig | None = None,
    ) -> None:
        expected_width = (
            config or SmokePipelineConfig()
        ).max_entities_per_frame * PLAYER_FEATURE_DIM
        if transformer.config.feature_dim != expected_width:
            raise InvalidPipelineInput(
                "Transformer feature_dim must equal max_entities * 9"
            )
        if fusion.config.temporal_dim != transformer.config.model_dim:
            raise InvalidPipelineInput(
                "Fusion temporal_dim must match transformer output"
            )
        if fusion.config.graph_dim != encoder.config.output_dim:
            raise InvalidPipelineInput("Fusion graph_dim must match GNN output")
        self.transformer = transformer
        self.encoder = encoder
        self.fusion = fusion
        self.detectors = BaselineDetectorSuite(detectors)
        self.config = config or SmokePipelineConfig()
        self.builder = TacticalStateBuilder()
        self.feature_encoder = TacticalFeatureEncoder()
        self.graph_builder = TacticalGraphBuilder()

    def run(
        self,
        observations: Sequence[VisionObservation],
        ground_truth: Sequence[object] | None = None,
    ) -> SmokePipelineResult:
        from app.ai.tactics.evaluation import evaluate_tactical_events

        sequence = self.builder.build_sequence_from_observations(observations)
        encoded = self.feature_encoder.encode_sequence(sequence)
        rows = [
            pack_frame_row(frame, self.config.max_entities_per_frame)[0]
            for frame in encoded
        ]
        temporal = self.transformer([rows], valid_lengths=[len(rows)])
        graphs = tuple(self.graph_builder.build(frame) for frame in sequence.frames)
        graph_embeddings = self.encoder.forward_batch(graphs)
        fused = tuple(
            self.fusion.forward(
                list(temporal.frames[0][index]), list(embedding.graph_embedding)
            )
            for index, embedding in enumerate(graph_embeddings)
        )
        events = tuple(self.detectors.detect(sequence))
        evaluation = None
        if ground_truth:
            evaluation = evaluate_tactical_events(list(events), ground_truth)  # type: ignore[arg-type]
        return SmokePipelineResult(
            sequence=sequence,
            encoded_frames=encoded,
            temporal=temporal,
            graphs=graphs,
            graph_embeddings=graph_embeddings,
            fused_frames=fused,
            events=events,
            evaluation=evaluation,
        )
