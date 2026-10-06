"""Phase 07H smoke tests: full VisionObservation -> evaluation chain
on deterministic SYNTHETIC data. Composition only — no football
intelligence claims, no real-world accuracy."""

from uuid import UUID

import pytest

from app.ai.tactics.evaluation import GroundTruthEvent
from app.ai.tactics.events import EventType
from app.ai.tactics.fusion import FusionConfig, TemporalGraphFusion
from app.ai.tactics.gnn import GNNConfig, GraphNeuralEncoder
from app.ai.tactics.pipeline import (
    InvalidPipelineInput,
    SmokePipelineConfig,
    TacticalSmokePipeline,
    pack_frame_row,
)
from app.ai.tactics.state import InvalidTacticalInput
from app.ai.tactics.transformer import TemporalTransformer, TransformerConfig
from app.ai.vision.schemas import (
    BoundingBox,
    FrameReference,
    ImagePoint,
    MappingPointType,
    MappingStatus,
    ObjectClass,
    PitchCoordinate,
    VisionObservation,
)

MATCH_ID = UUID(int=7)
SOURCE_ID = UUID(int=8)
MAX_ENTITIES = 4


def frame(number: int, timestamp: float) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=number,
        timestamp_seconds=timestamp,
        width=640,
        height=360,
    )


def observation(
    ref: FrameReference,
    tracking_id: str,
    object_class: ObjectClass,
    pitch: tuple[float, float] | None,
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
    )


def player(ref: FrameReference, track_id: str, x: float, y: float) -> VisionObservation:
    return observation(ref, track_id, ObjectClass.PLAYER, (x, y))


def pipeline(**kwargs: object) -> TacticalSmokePipeline:
    transformer = TemporalTransformer(
        TransformerConfig(
            feature_dim=MAX_ENTITIES * 9,
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
    return TacticalSmokePipeline(
        transformer,
        encoder,
        fusion,
        config=SmokePipelineConfig(max_entities_per_frame=MAX_ENTITIES),
        **kwargs,  # type: ignore[arg-type]
    )


def observations() -> list[VisionObservation]:
    items: list[VisionObservation] = []
    for number, timestamp in enumerate([0.0, 0.5, 1.0]):
        ref = frame(number, timestamp)
        items.append(player(ref, "player-1", 0.2 + 0.1 * number, 0.3))
        items.append(player(ref, "player-2", 0.7, 0.3))
        items.append(observation(ref, "ball-1", ObjectClass.BALL, (0.5, 0.5)))
    return items


# 1. Full chain produces every stage with compatible dimensions.
def test_full_chain() -> None:
    result = pipeline().run(observations())
    assert len(result.sequence.frames) == 3
    assert len(result.encoded_frames) == 3
    assert len(result.temporal.frames[0]) == 3
    assert len(result.graphs) == 3
    assert len(result.graph_embeddings) == 3
    assert len(result.fused_frames) == 3
    assert all(len(f.fused_embedding) == 6 for f in result.fused_frames)
    assert result.evaluation is None  # no GT supplied -> honestly absent


# 2. Events preserve provenance; evaluation accepts the event format.
def test_events_and_evaluation() -> None:
    ground_truth = [
        GroundTruthEvent(
            event_type=EventType.PLAYER_MOVEMENT,
            start_frame=0,
            end_frame=2,
            start_timestamp=0.0,
            end_timestamp=1.0,
        )
    ]
    result = pipeline().run(observations(), ground_truth)
    assert result.events
    for event in result.events:
        assert event.match_id == MATCH_ID
        assert event.source_id == SOURCE_ID
        assert event.evidence.track_ids
    assert result.evaluation is not None
    assert result.evaluation.ground_truth_count == 1
    assert result.evaluation.prediction_count == len(result.events)
    assert 0.0 <= result.evaluation.micro_f1 <= 1.0


# 3. Unknown team sides flow through without team edges.
def test_unknown_teams_no_team_edges() -> None:
    from app.ai.tactics.graph import EdgeType

    result = pipeline().run(observations())
    for graph in result.graphs:
        kinds = {edge.edge_type for edge in graph.edges}
        assert EdgeType.SAME_TEAM not in kinds
        assert EdgeType.OPPONENT not in kinds
        assert all(n.team.value == "UNKNOWN" for n in graph.nodes)


# 4. Partial observations: missing pitch + ball-only frame.
def test_partial_observations() -> None:
    ref0, ref1 = frame(0, 0.0), frame(1, 0.5)
    items = [
        observation(ref0, "player-1", ObjectClass.PLAYER, None),
        player(ref0, "player-2", 0.7, 0.3),
        observation(ref1, "ball-1", ObjectClass.BALL, (0.5, 0.5)),
    ]
    result = pipeline().run(items)
    assert len(result.fused_frames) == 2
    assert result.graphs[1].nodes[0].node_type.value == "BALL"
    missing = result.sequence.frames[0].players[0]
    assert missing.validity.value == "MISSING"


# 5. Empty observations rejected explicitly.
def test_empty_observations_rejected() -> None:
    with pytest.raises((InvalidPipelineInput, InvalidTacticalInput)):
        pipeline().run([])


# 6. Deterministic repeat runs.
def test_deterministic_pipeline() -> None:
    first = pipeline().run(observations()).fused_frames
    second = pipeline().run(observations()).fused_frames
    assert [f.fused_embedding for f in first] == [f.fused_embedding for f in second]


# 7. Dimension mismatches rejected, packing overflow rejected.
def test_dimension_mismatch_rejected() -> None:
    transformer = TemporalTransformer(
        TransformerConfig(
            feature_dim=MAX_ENTITIES * 9,
            model_dim=8,
            num_heads=2,
            num_layers=1,
            feedforward_dim=16,
        )
    )
    encoder = GraphNeuralEncoder(GNNConfig(hidden_dim=8, output_dim=4, num_layers=1))
    bad_fusion = TemporalGraphFusion(
        FusionConfig(temporal_dim=4, graph_dim=4, fusion_dim=6)
    )
    with pytest.raises(InvalidPipelineInput):
        TacticalSmokePipeline(transformer, encoder, bad_fusion)
    row, mask = pack_frame_row(
        pipeline().feature_encoder.encode_sequence(
            pipeline().builder.build_sequence_from_observations(observations())
        )[0],
        MAX_ENTITIES,
    )
    assert len(row) == MAX_ENTITIES * 9
    assert len(mask) == MAX_ENTITIES
    with pytest.raises(InvalidPipelineInput):
        pack_frame_row(
            pipeline().feature_encoder.encode_sequence(
                pipeline().builder.build_sequence_from_observations(observations())
            )[0],
            1,
        )


def test_packing_entity_mask() -> None:
    ref = frame(0, 0.0)
    pipe = pipeline()
    seq = pipe.builder.build_sequence_from_observations(
        [player(ref, "player-1", 0.2, 0.3)]
    )
    (encoded,) = pipe.feature_encoder.encode_sequence(seq)
    row, mask = pack_frame_row(encoded, MAX_ENTITIES)
    assert mask == (True, False, False, False)
    assert len(row) == MAX_ENTITIES * 9
