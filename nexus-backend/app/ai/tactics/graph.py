"""Phase 07C — player/team graph foundation.

Converts one :class:`TacticalFrameState` into a serializable
:class:`TacticalGraph` for future GNN consumption:

TacticalFrameState -> TacticalGraphBuilder -> TacticalGraph

Rules:

- PLAYER = node; BALL = explicitly typed node, never a player node.
- Edges only from existing evidence: SPATIAL_NEIGHBOR (pitch-space
  distance within a configurable threshold), SAME_TEAM / OPPONENT
  (only when both sides are explicitly known).
- Missing coordinates yield no spatial edges — never ``(0, 0)``.
- ``track_id`` is never a ``player_id``; team stays UNKNOWN unless set.
- Canonical ordering (sorted ids) makes output deterministic. Each
  unordered pair yields at most one edge per type, oriented from the
  smaller to the larger node id; a GNN can symmetrize later.

Plain domain structures only: no NetworkX, no torch, no training.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.tactics.state import (
    MAX_PLAYERS_PER_FRAME,
    PositionValidity,
    TacticalBallState,
    TacticalFrameState,
    TacticalPlayerState,
    TeamAssociation,
    Velocity2D,
)
from app.ai.vision.schemas import ObjectClass, PitchSpace

GRAPH_BUILDER_VERSION = "07C.1"


class GraphContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvalidGraphInput(ValueError):
    """A frame state cannot be converted to a tactical graph."""


class NodeType(StrEnum):
    PLAYER = "PLAYER"
    BALL = "BALL"


class EdgeType(StrEnum):
    SPATIAL_NEIGHBOR = "SPATIAL_NEIGHBOR"
    SAME_TEAM = "SAME_TEAM"
    OPPONENT = "OPPONENT"


class GraphNode(GraphContract):
    node_id: str = Field(min_length=1, max_length=100)
    node_type: NodeType
    track_id: str = Field(min_length=1, max_length=100)
    player_id: UUID | None = None
    identity_verified: bool = False
    team: TeamAssociation = TeamAssociation.UNKNOWN
    object_class: ObjectClass
    pitch_x: float | None = Field(default=None, allow_inf_nan=False)
    pitch_y: float | None = Field(default=None, allow_inf_nan=False)
    validity: PositionValidity
    object_confidence: float = Field(ge=0, le=1)
    velocity: Velocity2D | None = None
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    match_id: UUID
    source_id: UUID
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_identity_association(self) -> GraphNode:
        if self.player_id is not None and not self.identity_verified:
            raise ValueError("Player identity requires a verified association")
        return self

    @model_validator(mode="after")
    def validate_node_kind(self) -> GraphNode:
        if (
            self.node_type is NodeType.BALL
            and self.object_class is not ObjectClass.BALL
        ):
            raise ValueError("BALL nodes must carry the BALL object class")
        if self.node_type is NodeType.PLAYER and self.object_class is ObjectClass.BALL:
            raise ValueError("The ball must never be a PLAYER node")
        return self


class GraphEdge(GraphContract):
    source_id: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=100)
    edge_type: EdgeType
    distance: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    relative_x: float | None = Field(default=None, allow_inf_nan=False)
    relative_y: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_canonical_order(self) -> GraphEdge:
        if self.source_id >= self.target_id:
            raise ValueError("Edges must run from smaller to larger node id")
        return self

    @model_validator(mode="after")
    def validate_spatial_features(self) -> GraphEdge:
        spatial = self.edge_type is EdgeType.SPATIAL_NEIGHBOR
        has_features = (
            self.distance is not None
            and self.relative_x is not None
            and self.relative_y is not None
        )
        if spatial and not has_features:
            raise ValueError("Spatial edges require distance features")
        if not spatial and has_features:
            raise ValueError("Team edges must not carry spatial features")
        return self


class TacticalGraph(GraphContract):
    match_id: UUID
    source_id: UUID
    frame_index: int = Field(ge=0)
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    coordinate_space: PitchSpace = PitchSpace.NORMALIZED
    calibration_id: str | None = Field(default=None, min_length=1, max_length=100)
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    neighbor_threshold: float = Field(gt=0, allow_inf_nan=False)
    builder_version: str = GRAPH_BUILDER_VERSION


class GraphBuilderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    neighbor_threshold: float = Field(default=0.25, gt=0, le=10)
    include_ball_node: bool = True


def _player_node(player: TacticalPlayerState) -> GraphNode:
    return GraphNode(
        node_id=player.track_id,
        node_type=NodeType.PLAYER,
        track_id=player.track_id,
        player_id=player.player_id,
        identity_verified=player.identity_verified,
        team=player.team,
        object_class=player.object_class,
        pitch_x=player.pitch_x,
        pitch_y=player.pitch_y,
        validity=player.validity,
        object_confidence=player.object_confidence,
        velocity=player.velocity,
        frame_index=player.frame_index,
        timestamp_seconds=player.timestamp_seconds,
        match_id=player.match_id,
        source_id=player.source_id,
        calibration_id=player.calibration_id,
    )


def _ball_node(ball: TacticalBallState) -> GraphNode:
    return GraphNode(
        node_id=ball.track_id,
        node_type=NodeType.BALL,
        track_id=ball.track_id,
        team=TeamAssociation.UNKNOWN,
        object_class=ball.object_class,
        pitch_x=ball.pitch_x,
        pitch_y=ball.pitch_y,
        validity=ball.validity,
        object_confidence=ball.object_confidence,
        velocity=ball.velocity,
        frame_index=ball.frame_index,
        timestamp_seconds=ball.timestamp_seconds,
        match_id=ball.match_id,
        source_id=ball.source_id,
        calibration_id=ball.calibration_id,
    )


def _has_position(node: GraphNode) -> bool:
    return (
        node.pitch_x is not None
        and node.pitch_y is not None
        and node.validity is not PositionValidity.MISSING
    )


def _team_known(node: GraphNode) -> bool:
    return node.node_type is NodeType.PLAYER and node.team in (
        TeamAssociation.HOME,
        TeamAssociation.AWAY,
    )


class TacticalGraphBuilder:
    """Stateless builder: frame state in, canonical graph out."""

    version = GRAPH_BUILDER_VERSION

    def __init__(self, config: GraphBuilderConfig | None = None) -> None:
        self.config = config or GraphBuilderConfig()

    def build(self, frame: TacticalFrameState) -> TacticalGraph:
        if not isinstance(frame, TacticalFrameState):
            raise InvalidGraphInput("A TacticalFrameState is required")
        if len(frame.players) > MAX_PLAYERS_PER_FRAME:
            raise InvalidGraphInput("Too many players in one frame")
        nodes = sorted(
            (_player_node(player) for player in frame.players),
            key=lambda node: node.node_id,
        )
        if frame.ball is not None and self.config.include_ball_node:
            nodes.append(_ball_node(frame.ball))
            nodes.sort(key=lambda node: (node.node_type.value, node.node_id))
        edges = self._build_edges(nodes)
        return TacticalGraph(
            match_id=frame.match_id,
            source_id=frame.source_id,
            frame_index=frame.frame_index,
            timestamp_seconds=frame.timestamp_seconds,
            coordinate_space=frame.coordinate_space,
            calibration_id=frame.calibration_id,
            nodes=tuple(nodes),
            edges=tuple(edges),
            neighbor_threshold=self.config.neighbor_threshold,
        )

    def _build_edges(self, nodes: Sequence[GraphNode]) -> list[GraphEdge]:
        ordered = sorted(nodes, key=lambda node: node.node_id)
        edges: list[GraphEdge] = []
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                edges.extend(self._pair_edges(left, right))
        edges.sort(
            key=lambda edge: (edge.edge_type.value, edge.source_id, edge.target_id)
        )
        return edges

    def _pair_edges(self, left: GraphNode, right: GraphNode) -> list[GraphEdge]:
        first, second = (left, right) if left.node_id < right.node_id else (right, left)
        out: list[GraphEdge] = []
        if _has_position(first) and _has_position(second):
            assert first.pitch_x is not None and first.pitch_y is not None
            assert second.pitch_x is not None and second.pitch_y is not None
            rel_x = second.pitch_x - first.pitch_x
            rel_y = second.pitch_y - first.pitch_y
            distance = math.dist(
                (first.pitch_x, first.pitch_y), (second.pitch_x, second.pitch_y)
            )
            if distance <= self.config.neighbor_threshold:
                out.append(
                    GraphEdge(
                        source_id=first.node_id,
                        target_id=second.node_id,
                        edge_type=EdgeType.SPATIAL_NEIGHBOR,
                        distance=distance,
                        relative_x=rel_x,
                        relative_y=rel_y,
                    )
                )
        if _team_known(first) and _team_known(second):
            edge_type = (
                EdgeType.SAME_TEAM if first.team == second.team else EdgeType.OPPONENT
            )
            out.append(
                GraphEdge(
                    source_id=first.node_id,
                    target_id=second.node_id,
                    edge_type=edge_type,
                )
            )
        return out
