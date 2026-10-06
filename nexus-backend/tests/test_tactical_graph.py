"""Phase 07C graph tests: nodes, typed edges, masks by absence,
determinism, provenance. CPU-only, no GNN."""

from uuid import UUID

import pytest

from app.ai.tactics.graph import (
    EdgeType,
    GraphBuilderConfig,
    InvalidGraphInput,
    NodeType,
    TacticalGraphBuilder,
)
from app.ai.tactics.state import TacticalStateBuilder
from app.ai.vision.schemas import (
    BoundingBox,
    FrameReference,
    ImagePoint,
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchCoordinate,
    TeamSide,
    VisionObservation,
)

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)


def frame(number: int) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=0.04 * number,
        width=640,
        height=360,
    )


def observation(
    ref: FrameReference,
    tracking_id: str,
    object_class: ObjectClass,
    pitch: tuple[float, float] | None,
    team_side: TeamSide | None = None,
) -> VisionObservation:
    return VisionObservation(
        match_id=MATCH_ID,
        source_id=SOURCE_ID,
        frame=ref,
        tracking_id=tracking_id,
        object_class=object_class,
        detection_confidence=0.8,
        bounding_box=BoundingBox(x_min=10, y_min=20, x_max=50, y_max=100),
        image_point=ImagePoint(x=30, y=100),
        mapping_point_type=MappingPointType.BOTTOM_CENTER,
        pitch_coordinate=(
            PitchCoordinate(x=pitch[0], y=pitch[1], coordinate_system="PITCH")
            if pitch is not None
            else None
        ),
        mapping_status=(
            MappingStatus.MAPPED if pitch is not None else MappingStatus.FAILED
        ),
        calibration_id="cal-1",
        team_side=team_side,
    )


def player(ref: FrameReference, track_id: str, x: float, y: float) -> VisionObservation:
    return observation(ref, track_id, ObjectClass.PLAYER, (x, y))


def build_state(items: list[VisionObservation], number: int = 0):
    assert {item.frame.frame_number for item in items} == {number}
    return TacticalStateBuilder().build_frame(items)


def build_graph(items: list[VisionObservation], **kwargs: object):
    return TacticalGraphBuilder(
        GraphBuilderConfig(**kwargs) if kwargs else GraphBuilderConfig()  # type: ignore[arg-type]
    ).build(build_state(items))


def edge_types(graph: object) -> list[EdgeType]:
    return [edge.edge_type for edge in graph.edges]  # type: ignore[union-attr]


# 1. Empty frame.
def test_empty_frame_yields_empty_graph() -> None:
    ref = frame(0)
    state = build_state(
        [observation(ref, "player-1", ObjectClass.PLAYER, None)], number=0
    )
    graph = TacticalGraphBuilder().build(state)
    assert len(graph.nodes) == 1
    assert graph.edges == ()
    assert graph.frame_index == 0


def test_frame_with_no_observations_rejected() -> None:
    with pytest.raises(InvalidGraphInput):
        TacticalGraphBuilder().build("nope")  # type: ignore[arg-type]


# 2/3. Single player / multiple players as nodes.
def test_player_nodes() -> None:
    ref = frame(0)
    graph = build_graph(
        [player(ref, "player-2", 0.7, 0.3), player(ref, "player-1", 0.2, 0.3)]
    )
    assert [n.node_id for n in graph.nodes] == ["player-1", "player-2"]
    assert all(n.node_type is NodeType.PLAYER for n in graph.nodes)
    assert graph.nodes[0].pitch_x == pytest.approx(0.2)


# 4/12. Spatial-neighbor edge with distance features.
def test_spatial_neighbor_edge() -> None:
    ref = frame(0)
    graph = build_graph(
        [player(ref, "player-1", 0.2, 0.3), player(ref, "player-2", 0.3, 0.3)]
    )
    spatial = [e for e in graph.edges if e.edge_type is EdgeType.SPATIAL_NEIGHBOR]
    assert len(spatial) == 1
    (edge,) = spatial
    assert (edge.source_id, edge.target_id) == ("player-1", "player-2")
    assert edge.distance == pytest.approx(0.1)
    assert edge.relative_x == pytest.approx(0.1)
    assert edge.relative_y == pytest.approx(0.0)


# 5. Beyond threshold: no spatial edge.
def test_beyond_threshold_not_connected() -> None:
    ref = frame(0)
    graph = build_graph(
        [player(ref, "player-1", 0.0, 0.0), player(ref, "player-2", 0.9, 0.9)]
    )
    assert EdgeType.SPATIAL_NEIGHBOR not in edge_types(graph)


# 6/7. Same-team and opponent edges from explicit sides.
def test_team_edges() -> None:
    ref = frame(0)
    graph = build_graph(
        [
            observation(ref, "p-h1", ObjectClass.PLAYER, (0.2, 0.3), TeamSide.HOME),
            observation(ref, "p-h2", ObjectClass.PLAYER, (0.8, 0.8), TeamSide.HOME),
            observation(ref, "p-a1", ObjectClass.PLAYER, (0.5, 0.5), TeamSide.AWAY),
        ]
    )
    same = [e for e in graph.edges if e.edge_type is EdgeType.SAME_TEAM]
    opp = [e for e in graph.edges if e.edge_type is EdgeType.OPPONENT]
    assert [(e.source_id, e.target_id) for e in same] == [("p-h1", "p-h2")]
    assert {(e.source_id, e.target_id) for e in opp} == {
        ("p-a1", "p-h1"),
        ("p-a1", "p-h2"),
    }
    assert all(e.distance is None for e in (*same, *opp))


# 8. Unknown sides create no team edges.
def test_unknown_sides_no_team_edges() -> None:
    ref = frame(0)
    graph = build_graph(
        [player(ref, "player-1", 0.2, 0.3), player(ref, "player-2", 0.25, 0.3)]
    )
    assert EdgeType.SAME_TEAM not in edge_types(graph)
    assert EdgeType.OPPONENT not in edge_types(graph)
    assert EdgeType.SPATIAL_NEIGHBOR in edge_types(graph)


# 9. Ball node handling.
def test_ball_node() -> None:
    ref = frame(0)
    graph = build_graph(
        [
            player(ref, "player-1", 0.2, 0.3),
            observation(ref, "ball-1", ObjectClass.BALL, (0.22, 0.3)),
        ]
    )
    ball = [n for n in graph.nodes if n.node_type is NodeType.BALL]
    assert len(ball) == 1
    assert ball[0].track_id == "ball-1"
    assert all(
        n.node_type is not NodeType.PLAYER or n.track_id != "ball-1"
        for n in graph.nodes
    )
    spatial = [e for e in graph.edges if e.edge_type is EdgeType.SPATIAL_NEIGHBOR]
    assert len(spatial) == 1  # ball connects spatially, never by team
    assert EdgeType.SAME_TEAM not in edge_types(graph)

    without_ball = TacticalGraphBuilder(
        GraphBuilderConfig(include_ball_node=False)
    ).build(build_state([player(ref, "player-1", 0.2, 0.3)]))
    assert without_ball.nodes[0].node_type is NodeType.PLAYER


# 10. Missing coordinates yield no spatial edges.
def test_missing_coordinates_no_spatial_edges() -> None:
    ref = frame(0)
    graph = build_graph(
        [
            observation(ref, "player-1", ObjectClass.PLAYER, None),
            player(ref, "player-2", 0.2, 0.3),
        ]
    )
    assert EdgeType.SPATIAL_NEIGHBOR not in edge_types(graph)
    missing = [n for n in graph.nodes if n.track_id == "player-1"][0]
    assert missing.pitch_x is None


# 11/13/14. Features, track IDs, optional player ID passthrough.
def test_node_provenance_and_identity() -> None:
    ref = frame(0)
    graph = build_graph([player(ref, "player-7", 0.2, 0.3)])
    (node,) = graph.nodes
    assert node.track_id == "player-7"
    assert node.player_id is None
    assert node.object_confidence == pytest.approx(0.8)
    assert node.match_id == MATCH_ID
    assert node.source_id == SOURCE_ID
    assert node.calibration_id == "cal-1"
    assert graph.match_id == MATCH_ID
    assert graph.timestamp_seconds == pytest.approx(0.0)


# 15/16. Deterministic ordering.
def test_deterministic_ordering() -> None:
    ref = frame(0)
    items = [
        player(ref, "player-3", 0.5, 0.5),
        player(ref, "player-1", 0.2, 0.3),
        player(ref, "player-2", 0.25, 0.3),
    ]
    first = build_graph(items).model_dump()
    second = build_graph(list(reversed(items))).model_dump()
    assert first == second
    graph = build_graph(items)
    edge_keys = [(e.edge_type.value, e.source_id, e.target_id) for e in graph.edges]
    assert edge_keys == sorted(edge_keys)


# 17/18. Provenance + no mutation.
def test_provenance_and_no_mutation() -> None:
    ref = frame(0)
    state = build_state([player(ref, "player-1", 0.2, 0.3)])
    snapshot = state.model_dump()
    graph = TacticalGraphBuilder().build(state)
    assert state.model_dump() == snapshot
    assert graph.coordinate_space.value == "NORMALIZED"
    assert graph.builder_version
    assert graph.neighbor_threshold == pytest.approx(0.25)


def test_custom_threshold() -> None:
    ref = frame(0)
    items = [player(ref, "player-1", 0.2, 0.3), player(ref, "player-2", 0.5, 0.3)]
    close = build_graph(items, neighbor_threshold=0.5)
    far = build_graph(items, neighbor_threshold=0.1)
    assert EdgeType.SPATIAL_NEIGHBOR in edge_types(close)
    assert EdgeType.SPATIAL_NEIGHBOR not in edge_types(far)
