"""Phase 07D GNN tests: shapes, messages, masks, determinism.
CPU-only, tiny dims, untrained — no tactical claims."""

import copy
import math
from uuid import UUID

import pytest

from app.ai.tactics.gnn import (
    EDGE_FEATURE_DIM,
    NODE_FEATURE_DIM,
    GNNConfig,
    GraphEmbedding,
    GraphNeuralEncoder,
    InvalidGNNInput,
    edge_features,
    node_features,
)
from app.ai.tactics.graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    TacticalGraph,
)
from app.ai.tactics.state import PositionValidity, TeamAssociation
from app.ai.vision.schemas import ObjectClass, PitchSpace

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def config(**kwargs: object) -> GNNConfig:
    payload: dict[str, object] = {
        "hidden_dim": 8,
        "output_dim": 4,
        "num_layers": 2,
    }
    payload.update(kwargs)
    return GNNConfig(**payload)  # type: ignore[arg-type]


def player_node(
    node_id: str, x: float | None = 0.2, y: float | None = 0.3
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=NodeType.PLAYER,
        track_id=node_id,
        team=TeamAssociation.UNKNOWN,
        object_class=ObjectClass.PLAYER,
        pitch_x=x,
        pitch_y=y,
        validity=PositionValidity.MISSING if x is None else PositionValidity.VALID,
        object_confidence=0.8,
        frame_index=0,
        timestamp_seconds=0.0,
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
    )


def ball_node() -> GraphNode:
    return GraphNode(
        node_id="ball-1",
        node_type=NodeType.BALL,
        track_id="ball-1",
        team=TeamAssociation.UNKNOWN,
        object_class=ObjectClass.BALL,
        pitch_x=0.5,
        pitch_y=0.5,
        validity=PositionValidity.VALID,
        object_confidence=0.9,
        frame_index=0,
        timestamp_seconds=0.0,
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
    )


def spatial_edge(a: str, b: str, distance: float = 0.1) -> GraphEdge:
    first, second = sorted((a, b))
    return GraphEdge(
        source_id=first,
        target_id=second,
        edge_type=EdgeType.SPATIAL_NEIGHBOR,
        distance=distance,
        relative_x=0.1,
        relative_y=0.0,
    )


def graph(
    nodes: list[GraphNode], edges: list[GraphEdge] | None = None
) -> TacticalGraph:
    ordered_nodes = sorted(nodes, key=lambda n: n.node_id)
    ordered_edges = sorted(
        edges or [],
        key=lambda e: (e.edge_type.value, e.source_id, e.target_id),
    )
    return TacticalGraph(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame_index=0,
        timestamp_seconds=0.0,
        coordinate_space=PitchSpace.NORMALIZED,
        nodes=tuple(ordered_nodes),
        edges=tuple(ordered_edges),
        neighbor_threshold=0.25,
    )


def assert_finite(embedding: GraphEmbedding) -> None:
    for row in embedding.node_embeddings:
        assert all(math.isfinite(v) for v in row)
    assert all(math.isfinite(v) for v in embedding.graph_embedding)


# 1. Model initialization.
def test_initialization() -> None:
    model = GraphNeuralEncoder(config())
    assert model.training is False
    assert model.eval() is model
    assert model.train().training is True
    model.eval()
    with pytest.raises(ValueError):
        GNNConfig(hidden_dim=8, output_dim=4, num_layers=1, node_feature_dim=3)


# 2. Single-node graph.
def test_single_node_graph() -> None:
    output = GraphNeuralEncoder(config()).forward(graph([player_node("player-1")]))
    assert len(output.node_embeddings) == 1
    assert output.node_ids == ("player-1",)
    assert len(output.graph_embedding) == 4
    assert_finite(output)


# 3. Multiple-player graph.
def test_multiple_players() -> None:
    nodes = [player_node(f"player-{i}", 0.1 * i, 0.3) for i in range(1, 4)]
    output = GraphNeuralEncoder(config()).forward(graph(nodes))
    assert output.node_ids == ("player-1", "player-2", "player-3")
    assert len(output.node_embeddings) == 3
    assert_finite(output)


# 4. Player + ball graph keeps ball distinct.
def test_player_plus_ball() -> None:
    output = GraphNeuralEncoder(config()).forward(
        graph(
            [player_node("player-1"), ball_node()],
            [spatial_edge("ball-1", "player-1")],
        )
    )
    assert output.node_ids == ("ball-1", "player-1")
    assert output.node_embeddings[0] != output.node_embeddings[1]
    assert_finite(output)


# 5. Graph with no edges.
def test_edgeless_graph() -> None:
    output = GraphNeuralEncoder(config()).forward(
        graph([player_node("player-1", 0.1, 0.1), player_node("player-2", 0.9, 0.9)])
    )
    assert len(output.node_embeddings) == 2
    assert_finite(output)


# 6. Multiple edges change representations.
def test_edges_influence_embeddings() -> None:
    lonely = GraphNeuralEncoder(config()).forward(
        graph([player_node("player-1", 0.2, 0.3), player_node("player-2", 0.25, 0.3)])
    )
    linked = GraphNeuralEncoder(config()).forward(
        graph(
            [player_node("player-1", 0.2, 0.3), player_node("player-2", 0.25, 0.3)],
            [spatial_edge("player-1", "player-2", distance=0.05)],
        )
    )
    assert lonely.node_embeddings[0] != linked.node_embeddings[0]


# 7/8. Embedding shapes.
def test_embedding_shapes() -> None:
    model = GraphNeuralEncoder(config(output_dim=6, hidden_dim=10))
    output = model.forward(graph([player_node("player-1"), ball_node()]))
    assert all(len(row) == 6 for row in output.node_embeddings)
    assert len(output.graph_embedding) == 6
    assert output.output_dim == 6


# 9. Batch handling without cross-graph leakage.
def test_forward_batch() -> None:
    model = GraphNeuralEncoder(config())
    first = graph([player_node("player-1")])
    second = graph([player_node("player-9", 0.8, 0.8), ball_node()])
    batched = model.forward_batch([first, second])
    assert len(batched) == 2
    solo = model.forward(second)
    assert batched[1].node_embeddings == solo.node_embeddings
    with pytest.raises(InvalidGNNInput):
        model.forward_batch([])


# 10/11. Deterministic eval output on CPU.
def test_eval_determinism() -> None:
    data = graph(
        [player_node("player-1", 0.2, 0.3), player_node("player-2", 0.4, 0.3)],
        [spatial_edge("player-1", "player-2")],
    )
    left = GraphNeuralEncoder(config()).eval().forward(data)
    right = GraphNeuralEncoder(config()).eval().forward(data)
    assert left.node_embeddings == right.node_embeddings
    assert left.graph_embedding == right.graph_embedding


# 12. No NaN/Inf incl. missing positions and deeper stacks.
def test_finite_outputs() -> None:
    model = GraphNeuralEncoder(config(num_layers=4, hidden_dim=12))
    output = model.forward(
        graph(
            [player_node("player-1"), player_node("player-2", None, None), ball_node()],
            [spatial_edge("ball-1", "player-1")],
        )
    )
    assert_finite(output)


# 13/14/15. Invalid inputs rejected.
def test_invalid_inputs_rejected() -> None:
    model = GraphNeuralEncoder(config())
    with pytest.raises(InvalidGNNInput):
        model.forward("nope")  # type: ignore[arg-type]
    with pytest.raises(InvalidGNNInput):
        model.forward(graph([]))
    dangling = graph([player_node("player-1")])
    bad_edge = spatial_edge("player-1", "ghost-9")
    tampered = dangling.model_copy(
        update={"edges": (bad_edge,), "nodes": dangling.nodes}
    )
    with pytest.raises(InvalidGNNInput):
        model.forward(tampered)
    assert len(node_features(player_node("player-1"))) == NODE_FEATURE_DIM
    assert len(edge_features(spatial_edge("a", "b"))) == EDGE_FEATURE_DIM


# 16. Input graph is not mutated.
def test_graph_not_mutated() -> None:
    model = GraphNeuralEncoder(config())
    data = graph(
        [player_node("player-1", 0.2, 0.3), ball_node()],
        [spatial_edge("ball-1", "player-1")],
    )
    snapshot = copy.deepcopy(data.model_dump())
    model.forward(data)
    model.forward_batch([data])
    assert data.model_dump() == snapshot


# 17. Identity metadata preserved, ball never a player.
def test_identity_metadata_untouched() -> None:
    model = GraphNeuralEncoder(config())
    data = graph(
        [player_node("player-1", 0.2, 0.3), ball_node()],
        [spatial_edge("ball-1", "player-1")],
    )
    output = model.forward(data)
    assert output.node_ids == ("ball-1", "player-1")
    ball = [n for n in data.nodes if n.track_id == "ball-1"][0]
    assert ball.player_id is None
    assert output.metadata["model_version"]


def test_pooling_modes() -> None:
    nodes = [player_node("player-1", 0.2, 0.3), player_node("player-2", 0.4, 0.3)]
    mean = GraphNeuralEncoder(config(pooling="mean")).forward(graph(nodes))
    total = GraphNeuralEncoder(config(pooling="sum")).forward(graph(nodes))
    peak = GraphNeuralEncoder(config(pooling="max")).forward(graph(nodes))
    assert mean.pooling == "mean"
    assert all(
        s == pytest.approx(m * 2)
        for s, m in zip(total.graph_embedding, mean.graph_embedding, strict=True)
    )
    assert all(
        p >= m - 1e-9
        for p, m in zip(peak.graph_embedding, mean.graph_embedding, strict=True)
    )
