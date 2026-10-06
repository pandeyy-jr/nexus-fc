"""Phase 07D — GNN encoder (untrained architecture).

Message-passing encoder over :class:`TacticalGraph`:

TacticalGraph -> GraphNeuralEncoder -> GraphEmbedding

Mechanics (GraphSAGE-mean style, dependency-free pure Python):

- node bridge: GraphNode -> fixed ``NODE_FEATURE_DIM`` vector
  ``[x, y, vx, vy, speed, confidence, is_home, is_away, is_unknown,
  is_ball]`` (missing values zero-pad; masks live in the domain).
- edge bridge: GraphEdge -> ``EDGE_FEATURE_DIM`` vector
  ``[distance, rel_x, rel_y, is_spatial, is_same_team, is_opponent]``.
- per layer: message(j->i) = Linear([h_j, edge_proj(e_ji)]);
  update = LayerNorm(h_i + Linear([h_i, mean(messages)])) with ReLU.
  Mean aggregation is permutation invariant; isolated nodes update
  through the self path. Canonical edges flow both directions, with
  relative features sign-flipped for the reverse direction.
- graph embedding = configurable pooling (mean/sum/max) over nodes.

Untrained architecture only: no datasets, no training, no tactical
predictions. Plain nested lists throughout — tensors never enter.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.tactics.graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    TacticalGraph,
)
from app.ai.tactics.state import PositionValidity, TeamAssociation

MODEL_VERSION = "07D.1"
NODE_FEATURE_DIM = 10
EDGE_FEATURE_DIM = 6


class GNNConfig(BaseModel):
    """All architecture parameters explicit; nothing hardcoded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_feature_dim: int = Field(default=NODE_FEATURE_DIM, ge=1, le=4096)
    hidden_dim: int = Field(ge=1, le=4096)
    output_dim: int = Field(ge=1, le=4096)
    num_layers: int = Field(ge=1, le=48)
    dropout: float = Field(default=0.0, ge=0.0, le=1.0)
    pooling: Literal["mean", "sum", "max"] = "mean"
    seed: int = Field(default=11)

    @model_validator(mode="after")
    def validate_bridge_width(self) -> GNNConfig:
        if self.node_feature_dim != NODE_FEATURE_DIM:
            raise ValueError(
                f"node_feature_dim must match the node bridge ({NODE_FEATURE_DIM})"
            )
        return self


class InvalidGNNInput(ValueError):
    """A graph cannot be encoded by the GNN."""


@dataclass(frozen=True)
class GraphEmbedding:
    """Structured model output; node order aligns with ``node_ids``."""

    node_embeddings: tuple[tuple[float, ...], ...]
    node_ids: tuple[str, ...]
    graph_embedding: tuple[float, ...]
    pooling: str
    output_dim: int
    model_version: str = MODEL_VERSION
    metadata: dict[str, object] = field(default_factory=dict)


def node_features(node: GraphNode) -> tuple[float, ...]:
    """Domain node -> fixed vector. Zeros mark absence, never real zeros
    confused: consumers must consult node validity alongside."""
    has_position = (
        node.pitch_x is not None
        and node.pitch_y is not None
        and node.validity is not PositionValidity.MISSING
    )
    velocity = node.velocity
    has_velocity = has_position and velocity is not None
    return (
        node.pitch_x if has_position and node.pitch_x is not None else 0.0,
        node.pitch_y if has_position and node.pitch_y is not None else 0.0,
        velocity.vx if has_velocity and velocity is not None else 0.0,
        velocity.vy if has_velocity and velocity is not None else 0.0,
        velocity.speed if has_velocity and velocity is not None else 0.0,
        node.object_confidence,
        1.0 if node.team is TeamAssociation.HOME else 0.0,
        1.0 if node.team is TeamAssociation.AWAY else 0.0,
        1.0 if node.team is TeamAssociation.UNKNOWN else 0.0,
        1.0 if node.node_type is NodeType.BALL else 0.0,
    )


def edge_features(edge: GraphEdge) -> tuple[float, ...]:
    return (
        edge.distance if edge.distance is not None else 0.0,
        edge.relative_x if edge.relative_x is not None else 0.0,
        edge.relative_y if edge.relative_y is not None else 0.0,
        1.0 if edge.edge_type is EdgeType.SPATIAL_NEIGHBOR else 0.0,
        1.0 if edge.edge_type is EdgeType.SAME_TEAM else 0.0,
        1.0 if edge.edge_type is EdgeType.OPPONENT else 0.0,
    )


def _check_finite(values: Sequence[float], what: str) -> None:
    if any(not math.isfinite(v) for v in values):
        raise InvalidGNNInput(f"Non-finite values in {what}")


def _layer_norm(vector: list[float], eps: float = 1e-5) -> list[float]:
    mean = sum(vector) / len(vector)
    variance = sum((v - mean) ** 2 for v in vector) / len(vector)
    scale = 1.0 / math.sqrt(variance + eps)
    return [(v - mean) * scale for v in vector]


class _Linear:
    def __init__(self, rng: random.Random, in_dim: int, out_dim: int) -> None:
        bound = 1.0 / math.sqrt(in_dim)
        self.weight = [
            [rng.uniform(-bound, bound) for _ in range(in_dim)] for _ in range(out_dim)
        ]
        self.bias = [0.0] * out_dim

    def __call__(self, vector: Sequence[float]) -> list[float]:
        return [
            sum(w * v for w, v in zip(row, vector, strict=True)) + b
            for row, b in zip(self.weight, self.bias, strict=True)
        ]


class _MessageLayer:
    def __init__(self, rng: random.Random, hidden_dim: int) -> None:
        self.edge_projection = _Linear(rng, EDGE_FEATURE_DIM, hidden_dim)
        self.message = _Linear(rng, 2 * hidden_dim, hidden_dim)
        self.update = _Linear(rng, 2 * hidden_dim, hidden_dim)

    def __call__(
        self,
        states: list[list[float]],
        adjacency: list[list[tuple[int, list[float]]]],
    ) -> list[list[float]]:
        updated: list[list[float]] = []
        for index, own in enumerate(states):
            incoming = adjacency[index]
            if incoming:
                messages = [
                    self.message(states[neighbor] + self.edge_projection(edge))
                    for neighbor, edge in incoming
                ]
                mean = [
                    sum(column) / len(messages)
                    for column in zip(*messages, strict=True)
                ]
            else:
                mean = [0.0] * len(own)
            combined = self.update(own + mean)
            activated = [max(0.0, v) for v in combined]
            updated.append(
                _layer_norm([a + b for a, b in zip(own, activated, strict=True)])
            )
        return updated


class GraphNeuralEncoder:
    """Minimal message-passing encoder (eval-first, CPU-only)."""

    def __init__(self, config: GNNConfig) -> None:
        self.config = config
        rng = random.Random(config.seed)
        self.input_projection = _Linear(rng, config.node_feature_dim, config.hidden_dim)
        self.layers = [
            _MessageLayer(rng, config.hidden_dim) for _ in range(config.num_layers)
        ]
        self.output_projection = _Linear(rng, config.hidden_dim, config.output_dim)
        self._training = False
        self._dropout_rng = random.Random(config.seed + 1)

    def train(self) -> GraphNeuralEncoder:
        self._training = True
        return self

    def eval(self) -> GraphNeuralEncoder:
        self._training = False
        return self

    @property
    def training(self) -> bool:
        return self._training

    def _maybe_dropout(self, vector: list[float]) -> list[float]:
        rate = self.config.dropout
        if not self._training or rate <= 0:
            return list(vector)
        keep = 1.0 - rate
        return [
            (v / keep if self._dropout_rng.random() >= rate else 0.0) for v in vector
        ]

    def _prepare(
        self, graph: TacticalGraph
    ) -> tuple[list[list[float]], list[list[tuple[int, list[float]]]], list[str]]:
        if not isinstance(graph, TacticalGraph):
            raise InvalidGNNInput("A TacticalGraph is required")
        if not graph.nodes:
            raise InvalidGNNInput("Graph holds no nodes")
        index_of = {node.node_id: index for index, node in enumerate(graph.nodes)}
        if len(index_of) != len(graph.nodes):
            raise InvalidGNNInput("Duplicate node ids")
        states: list[list[float]] = []
        for node in graph.nodes:
            features = node_features(node)
            _check_finite(features, "node features")
            projected = self.input_projection(features)
            states.append(self._maybe_dropout(projected))
        adjacency: list[list[tuple[int, list[float]]]] = [[] for _ in graph.nodes]
        for edge in graph.edges:
            if edge.source_id not in index_of or edge.target_id not in index_of:
                raise InvalidGNNInput("Edge references an unknown node")
            source, target = index_of[edge.source_id], index_of[edge.target_id]
            if source == target:
                raise InvalidGNNInput("Self-loop edges are not supported")
            forward = edge_features(edge)
            _check_finite(forward, "edge features")
            backward = (forward[0], -forward[1], -forward[2], *forward[3:])
            adjacency[target].append((source, list(forward)))
            adjacency[source].append((target, list(backward)))
        return states, adjacency, [node.node_id for node in graph.nodes]

    def _pool(self, embeddings: list[list[float]]) -> list[float]:
        pooling = self.config.pooling
        if pooling == "sum":
            return [sum(column) for column in zip(*embeddings, strict=True)]
        if pooling == "max":
            return [max(column) for column in zip(*embeddings, strict=True)]
        count = len(embeddings)
        return [sum(column) / count for column in zip(*embeddings, strict=True)]

    def forward(self, graph: TacticalGraph) -> GraphEmbedding:
        """Encode one graph; the input graph is never mutated."""
        states, adjacency, node_ids = self._prepare(graph)
        hidden = states
        for layer in self.layers:
            hidden = layer(hidden, adjacency)
            if self._training:
                hidden = [self._maybe_dropout(row) for row in hidden]
        node_embeddings = [self.output_projection(row) for row in hidden]
        for row in node_embeddings:
            _check_finite(row, "model output")
        pooled = self._pool(node_embeddings)
        _check_finite(pooled, "model output")
        return GraphEmbedding(
            node_embeddings=tuple(tuple(row) for row in node_embeddings),
            node_ids=tuple(node_ids),
            graph_embedding=tuple(pooled),
            pooling=self.config.pooling,
            output_dim=self.config.output_dim,
            metadata={
                "model_version": MODEL_VERSION,
                "hidden_dim": self.config.hidden_dim,
                "num_layers": self.config.num_layers,
            },
        )

    def forward_batch(
        self, graphs: Sequence[TacticalGraph]
    ) -> tuple[GraphEmbedding, ...]:
        """Independent per-graph encoding; no cross-graph leakage."""
        if not graphs:
            raise InvalidGNNInput("Batch holds no graphs")
        return tuple(self.forward(graph) for graph in graphs)

    __call__ = forward
