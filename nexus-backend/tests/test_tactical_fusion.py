"""Phase 07E fusion tests: shapes, configs, missing-modality flags,
determinism. CPU-only, untrained — no tactical claims."""

import copy
import math

import pytest

from app.ai.tactics.fusion import (
    FusedTacticalRepresentation,
    FusionConfig,
    InvalidFusionInput,
    TemporalGraphFusion,
)


def module(**kwargs: object) -> TemporalGraphFusion:
    payload: dict[str, object] = {
        "temporal_dim": 8,
        "graph_dim": 4,
        "fusion_dim": 6,
    }
    payload.update(kwargs)
    return TemporalGraphFusion(FusionConfig(**payload))  # type: ignore[arg-type]


def vector(dim: int, start: float = 0.1, step: float = 0.05) -> list[float]:
    return [start + index * step for index in range(dim)]


def assert_finite(output: FusedTacticalRepresentation) -> None:
    assert all(math.isfinite(v) for v in output.fused_embedding)


# 1/2. Valid pair + correct fused shape.
def test_valid_pair_and_shape() -> None:
    output = module().forward(vector(8), vector(4))
    assert len(output.fused_embedding) == 6
    assert output.temporal_available is True
    assert output.graph_available is True
    assert output.fusion_dim == 6
    assert_finite(output)


# 3/4. Different dims + configurable fusion dim.
@pytest.mark.parametrize(
    "temporal_dim,graph_dim,fusion_dim",
    [(8, 4, 6), (4, 4, 4), (16, 8, 12)],
)
def test_dimensions(temporal_dim: int, graph_dim: int, fusion_dim: int) -> None:
    output = module(
        temporal_dim=temporal_dim, graph_dim=graph_dim, fusion_dim=fusion_dim
    ).forward(vector(temporal_dim), vector(graph_dim))
    assert len(output.fused_embedding) == fusion_dim
    assert_finite(output)


# 5. Invalid dimensions rejected, never silently reshaped.
def test_invalid_dimensions_rejected() -> None:
    fusion = module()
    with pytest.raises(InvalidFusionInput):
        fusion.forward(vector(7), vector(4))
    with pytest.raises(InvalidFusionInput):
        fusion.forward(vector(8), vector(5))
    with pytest.raises(InvalidFusionInput):
        fusion.forward([float("nan")] * 8, vector(4))
    with pytest.raises(InvalidFusionInput):
        fusion.forward("nope", vector(4))  # type: ignore[arg-type]


# 6. Batch processing without cross-pair leakage.
def test_batch_processing() -> None:
    fusion = module()
    pairs = [(vector(8, start), vector(4, start)) for start in (0.1, 0.5, 1.0)]
    batched = fusion.forward_batch(pairs)
    assert len(batched) == 3
    for (temporal, graph), output in zip(pairs, batched, strict=True):
        solo = fusion.forward(temporal, graph)
        assert output.fused_embedding == solo.fused_embedding
    with pytest.raises(InvalidFusionInput):
        fusion.forward_batch([])


# 7/8. Missing modalities are explicit, never fabricated.
def test_missing_modalities_flagged() -> None:
    fusion = module()
    temporal_only = fusion.forward(vector(8), None)
    assert temporal_only.temporal_available is True
    assert temporal_only.graph_available is False
    assert temporal_only.graph_embedding is None
    assert_finite(temporal_only)
    graph_only = fusion.forward(None, vector(4))
    assert graph_only.temporal_available is False
    assert graph_only.graph_available is True
    assert graph_only.temporal_embedding is None
    assert_finite(graph_only)
    assert temporal_only.fused_embedding != graph_only.fused_embedding
    with pytest.raises(InvalidFusionInput):
        fusion.forward(None, None)


# 9/10/11. Deterministic eval output on CPU, finite.
def test_eval_determinism() -> None:
    left = module().eval().forward(vector(8), vector(4))
    right = module().eval().forward(vector(8), vector(4))
    assert left.fused_embedding == right.fused_embedding
    assert_finite(left)


# 12. Inputs are not mutated.
def test_inputs_not_mutated() -> None:
    fusion = module()
    temporal, graph = vector(8), vector(4)
    snapshot = (copy.deepcopy(temporal), copy.deepcopy(graph))
    fusion.forward(temporal, graph)
    fusion.forward_batch([(temporal, graph)])
    assert (temporal, graph) == snapshot


# 13/14 covered by regression run; end-to-end interface compatibility.
def test_end_to_end_transformer_gnn_fusion() -> None:
    from app.ai.tactics.gnn import GNNConfig, GraphNeuralEncoder
    from app.ai.tactics.graph import GraphEdge  # noqa: F401
    from app.ai.tactics.transformer import TemporalTransformer, TransformerConfig

    transformer = TemporalTransformer(
        TransformerConfig(
            feature_dim=9,
            model_dim=8,
            num_heads=2,
            num_layers=1,
            feedforward_dim=16,
        )
    ).eval()
    encoder = GraphNeuralEncoder(
        GNNConfig(hidden_dim=8, output_dim=4, num_layers=1)
    ).eval()
    sequence = [
        [[0.1 * (r + c) for c in range(9)] for r in range(3)],
        [[0.2 * (r + c) for c in range(9)] for r in range(3)],
    ]
    temporal = transformer(sequence, valid_lengths=[3, 2]).pooled[0]

    from uuid import UUID

    from app.ai.tactics.graph import GraphNode, NodeType, TacticalGraph
    from app.ai.tactics.state import PositionValidity, TeamAssociation
    from app.ai.vision.schemas import ObjectClass

    node = GraphNode(
        node_id="player-1",
        node_type=NodeType.PLAYER,
        track_id="player-1",
        team=TeamAssociation.UNKNOWN,
        object_class=ObjectClass.PLAYER,
        pitch_x=0.2,
        pitch_y=0.3,
        validity=PositionValidity.VALID,
        object_confidence=0.8,
        frame_index=0,
        timestamp_seconds=0.0,
        match_id=UUID(int=7),
        source_id=UUID(int=8),
    )
    tactical_graph = TacticalGraph(
        match_id=UUID(int=7),
        source_id=UUID(int=8),
        frame_index=0,
        timestamp_seconds=0.0,
        nodes=(node,),
        edges=(),
        neighbor_threshold=0.25,
    )
    graph_vector = encoder.forward(tactical_graph).graph_embedding
    output = module().forward(list(temporal), list(graph_vector))
    assert len(output.fused_embedding) == 6
    assert_finite(output)


def test_metadata() -> None:
    output = module().forward(vector(8), vector(4))
    assert output.model_version
    assert output.metadata["temporal_dim"] == 8
    assert output.metadata["graph_dim"] == 4
