from uuid import UUID

import pytest
from pydantic import ValidationError

from app.ai.vision.pitch_mapping import (
    CalibrationError,
    DegenerateCalibration,
    HomographyEstimator,
    HomographyMapper,
    InvalidHomography,
    MapperConfig,
    MapperNotCalibrated,
    project,
    representative_point,
    to_metric,
)
from app.ai.vision.schemas import (
    BoundingBox,
    CalibrationCorrespondence,
    CalibrationQuality,
    FrameReference,
    ImagePoint,
    MappingPointType,
    ObjectClass,
    PitchCalibration,
    PitchCoordinate,
    PitchDimensions,
    PitchPosition,
    PitchSpace,
    TrackedObject,
    TrackingFrame,
)
from app.ai.vision.tracking import DeterministicIoUTracker

SOURCE_ID = UUID(int=1)
CAL_ID = "calibration-06F-1"


def frame(width: int = 640, height: int = 360) -> FrameReference:
    return FrameReference(
        source_id=SOURCE_ID,
        frame_number=0,
        timestamp_seconds=0.0,
        width=width,
        height=height,
    )


def rect_calibration(
    calibration_id: str = CAL_ID,
    width: float = 640.0,
    height: float = 360.0,
    origin: str = "top-left corner of the broadcast view",
) -> PitchCalibration:
    return PitchCalibration(
        calibration_id=calibration_id,
        correspondences=[
            CalibrationCorrespondence(
                image=ImagePoint(x=0, y=0),
                pitch=PitchCoordinate(x=0, y=0, coordinate_system="PITCH"),
            ),
            CalibrationCorrespondence(
                image=ImagePoint(x=width, y=0),
                pitch=PitchCoordinate(x=1, y=0, coordinate_system="PITCH"),
            ),
            CalibrationCorrespondence(
                image=ImagePoint(x=width, y=height),
                pitch=PitchCoordinate(x=1, y=1, coordinate_system="PITCH"),
            ),
            CalibrationCorrespondence(
                image=ImagePoint(x=0, y=height),
                pitch=PitchCoordinate(x=0, y=1, coordinate_system="PITCH"),
            ),
        ],
        origin_description=origin,
    )


def track(
    ref: FrameReference,
    object_class: ObjectClass,
    box: tuple[float, float, float, float],
    tracking_id: str,
) -> TrackedObject:
    return TrackedObject(
        frame=ref,
        object_class=object_class,
        confidence=0.9,
        bounding_box=BoundingBox(
            x_min=box[0], y_min=box[1], x_max=box[2], y_max=box[3]
        ),
        tracking_id=tracking_id,
    )


def calibrated_mapper(**kwargs: object) -> HomographyMapper:
    mapper = HomographyMapper(
        MapperConfig(**kwargs) if kwargs else MapperConfig()  # type: ignore[arg-type]
    )
    mapper.calibrate(rect_calibration())
    return mapper


# 1. Valid calibration.
def test_valid_calibration_reports_honest_quality() -> None:
    estimated = HomographyEstimator().estimate(rect_calibration())
    assert estimated.quality.correspondence_count == 4
    assert estimated.quality.inlier_count == 4
    assert estimated.quality.reprojection_rmse == pytest.approx(0.0, abs=1e-9)
    assert estimated.quality.is_valid is True
    assert estimated.inlier_ratio == pytest.approx(1.0)
    assert estimated.calibration_id == CAL_ID
    assert "06F" in estimated.method


# 2/3. Four correspondences map corners exactly.
def test_known_corner_mappings() -> None:
    estimated = HomographyEstimator().estimate(rect_calibration())
    assert project(estimated.matrix, 0, 0) == pytest.approx((0, 0))
    assert project(estimated.matrix, 640, 0) == pytest.approx((1, 0))
    assert project(estimated.matrix, 640, 360) == pytest.approx((1, 1))
    assert project(estimated.matrix, 0, 360) == pytest.approx((0, 1))


# 4. Identity-like transformation.
def test_identity_like_transformation() -> None:
    calibration = PitchCalibration(
        calibration_id="identity",
        correspondences=[
            CalibrationCorrespondence(
                image=ImagePoint(x=x, y=y),
                pitch=PitchCoordinate(x=x, y=y, coordinate_system="PITCH"),
            )
            for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))
        ],
    )
    estimated = HomographyEstimator().estimate(calibration)
    assert project(estimated.matrix, 0.25, 0.75) == pytest.approx((0.25, 0.75))


# 5. Normalized pitch coordinates carry their space explicitly.
def test_normalized_output_space() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    positions = mapper.map(
        TrackingFrame(
            frame=ref,
            tracks=[track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")],
        )
    )
    assert positions[0].coordinate.space is PitchSpace.NORMALIZED
    assert positions[0].coordinate.coordinate_system == "PITCH"


# 6. Metric pitch coordinates via configurable dimensions.
def test_metric_output_space() -> None:
    mapper = HomographyMapper(
        MapperConfig(
            output_space=PitchSpace.METRIC,
            pitch_dimensions=PitchDimensions(length_metres=105, width_metres=68),
        )
    )
    mapper.calibrate(rect_calibration())
    ref = frame()
    positions = mapper.map(
        TrackingFrame(
            frame=ref,
            tracks=[track(ref, ObjectClass.PLAYER, (0, 0, 640, 360), "player-1")],
        )
    )
    bottom_center = positions[0].coordinate
    assert bottom_center.space is PitchSpace.METRIC
    assert (bottom_center.x, bottom_center.y) == pytest.approx((52.5, 68.0))
    with pytest.raises(ValueError, match="pitch_dimensions"):
        MapperConfig(output_space=PitchSpace.METRIC)


def test_to_metric_rejects_non_normalized_input() -> None:
    metric = PitchCoordinate(
        x=52.5, y=34.0, coordinate_system="PITCH", space=PitchSpace.METRIC
    )
    with pytest.raises(CalibrationError):
        to_metric(metric, PitchDimensions(length_metres=105, width_metres=68))


# 7. Player bottom-center mapping policy.
def test_player_uses_bottom_center() -> None:
    ref = frame()
    player = track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")
    image_point, point_type = representative_point(player)
    assert point_type is MappingPointType.BOTTOM_CENTER
    assert (image_point.x, image_point.y) == (30, 100)
    mapper = calibrated_mapper()
    (position,) = mapper.map(TrackingFrame(frame=ref, tracks=[player]))
    assert position.mapping_point_type is MappingPointType.BOTTOM_CENTER
    assert position.mapping_point == image_point
    assert (position.coordinate.x, position.coordinate.y) == pytest.approx(
        (30 / 640, 100 / 360)
    )


# 8. Ball center mapping policy.
def test_ball_uses_center() -> None:
    ref = frame()
    ball = track(ref, ObjectClass.BALL, (300, 150, 312, 162), "ball-1")
    image_point, point_type = representative_point(ball)
    assert point_type is MappingPointType.CENTER
    assert (image_point.x, image_point.y) == (306, 156)
    mapper = calibrated_mapper()
    (position,) = mapper.map(TrackingFrame(frame=ref, tracks=[ball]))
    assert position.mapping_point_type is MappingPointType.CENTER


# 9. Invalid correspondence count.
def test_too_few_correspondences_rejected() -> None:
    full = rect_calibration()
    with pytest.raises(ValueError):
        PitchCalibration(
            calibration_id="short",
            correspondences=full.correspondences[:3],
        )
    with pytest.raises(ValueError):
        HomographyEstimator().estimate("not-a-calibration")  # type: ignore[arg-type]


# 10. Duplicate / degenerate points.
def test_duplicate_points_rejected() -> None:
    full = rect_calibration()
    duplicated = PitchCalibration(
        calibration_id="dup",
        correspondences=[*full.correspondences[:3], full.correspondences[0]],
    )
    with pytest.raises(DegenerateCalibration):
        HomographyEstimator().estimate(duplicated)


def test_collinear_points_rejected() -> None:
    line = [
        CalibrationCorrespondence(
            image=ImagePoint(x=float(100 * i), y=50.0),
            pitch=PitchCoordinate(x=float(i) / 3, y=0.5, coordinate_system="PITCH"),
        )
        for i in range(4)
    ]
    calibration = PitchCalibration(calibration_id="line", correspondences=line)
    with pytest.raises(DegenerateCalibration):
        HomographyEstimator().estimate(calibration)


# 11. NaN / infinity inputs.
def test_non_finite_inputs_rejected() -> None:
    with pytest.raises(ValidationError):
        ImagePoint(x=float("nan"), y=1.0)
    with pytest.raises(ValidationError):
        ImagePoint(x=1.0, y=float("inf"))
    with pytest.raises(ValidationError):
        PitchCoordinate(x=float("nan"), y=0.0, coordinate_system="PITCH")


def test_calibration_requires_normalized_pitch_points() -> None:
    with pytest.raises(ValidationError):
        CalibrationCorrespondence(
            image=ImagePoint(x=1, y=1),
            pitch=PitchCoordinate(
                x=52.5, y=34.0, coordinate_system="PITCH", space=PitchSpace.METRIC
            ),
        )


# 12. Invalid homography.
def test_invalid_homography_matrix() -> None:
    with pytest.raises(InvalidHomography):
        project((1.0, 0.0), 10.0, 10.0)
    with pytest.raises(InvalidHomography):
        project((0.0,) * 9, 10.0, 10.0)
    with pytest.raises(InvalidHomography):
        project((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, float("nan")), 1.0, 1.0)


# 13. Out-of-bounds mapped coordinates are preserved, flagged, never clamped.
def test_out_of_bounds_preserved_and_flagged() -> None:
    calibration = PitchCalibration(
        calibration_id="sub-region",
        correspondences=[
            CalibrationCorrespondence(
                image=ImagePoint(x=x, y=y),
                pitch=PitchCoordinate(x=xp, y=yp, coordinate_system="PITCH"),
            )
            for (x, y), (xp, yp) in (
                ((100, 100), (0, 0)),
                ((540, 100), (1, 0)),
                ((540, 300), (1, 1)),
                ((100, 300), (0, 1)),
            )
        ],
    )
    mapper = HomographyMapper()
    mapper.calibrate(calibration)
    ref = frame()
    outside = track(ref, ObjectClass.PLAYER, (10, 300, 50, 350), "player-9")
    (position,) = mapper.map(TrackingFrame(frame=ref, tracks=[outside]))
    assert position.in_bounds is False
    raw_x, raw_y = position.coordinate.x, position.coordinate.y
    assert raw_x < 0 or raw_x > 1 or raw_y < 0 or raw_y > 1
    clamped = HomographyMapper(MapperConfig(clamp_to_pitch=True))
    clamped.calibrate(calibration)
    (clamped_position,) = clamped.map(TrackingFrame(frame=ref, tracks=[outside]))
    assert clamped_position.in_bounds is False
    assert 0.0 <= clamped_position.coordinate.x <= 1.0
    assert 0.0 <= clamped_position.coordinate.y <= 1.0


# 14. Calibration metadata / provenance.
def test_calibration_provenance() -> None:
    mapper = calibrated_mapper()
    provenance = mapper.provenance
    assert provenance is not None
    assert provenance.calibration_id == CAL_ID
    assert provenance.estimator_name
    assert provenance.estimator_version
    ref = frame()
    (position,) = mapper.map(
        TrackingFrame(
            frame=ref,
            tracks=[track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")],
        )
    )
    assert position.calibration_id == CAL_ID


# 15/16. Track ID preservation; image evidence unchanged.
def test_track_identity_and_image_evidence_preserved() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    player = track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-7")
    snapshot = player.model_dump()
    (position,) = mapper.map(TrackingFrame(frame=ref, tracks=[player]))
    assert position.tracking_id == "player-7"
    assert position.frame == ref
    assert player.model_dump() == snapshot
    assert position.coordinate.x != player.bounding_box.x_min


# 17. Pitch-space mapping failure is explicit (omitted, never fabricated).
def test_mapping_failure_omits_track_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.ai.vision.pitch_mapping as pitch_mapping

    mapper = calibrated_mapper()
    ref = frame()
    tracks = [
        track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1"),
        track(ref, ObjectClass.PLAYER, (300, 20, 340, 100), "player-2"),
    ]
    real_project = pitch_mapping.project

    def flaky(matrix: object, x: float, y: float) -> tuple[float, float]:
        if x == pytest.approx(30.0):
            raise InvalidHomography("simulated projection failure")
        return real_project(matrix, x, y)  # type: ignore[arg-type]

    monkeypatch.setattr(pitch_mapping, "project", flaky)
    positions = mapper.map(TrackingFrame(frame=ref, tracks=tracks))
    assert [p.tracking_id for p in positions] == ["player-2"]


def test_uncalibrated_mapper_refuses_to_map() -> None:
    mapper = HomographyMapper()
    assert mapper.is_calibrated is False
    assert mapper.provenance is None
    ref = frame()
    with pytest.raises(MapperNotCalibrated):
        mapper.map(TrackingFrame(frame=ref, tracks=[]))


# 18/19. Multiple players; player + ball in the same frame.
def test_multiple_players_and_ball_share_one_frame() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    tracking = TrackingFrame(
        frame=ref,
        tracks=[
            track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1"),
            track(ref, ObjectClass.PLAYER, (300, 20, 340, 100), "player-2"),
            track(ref, ObjectClass.BALL, (300, 150, 312, 162), "ball-1"),
        ],
    )
    positions = mapper.map(tracking)
    assert {p.tracking_id for p in positions} == {"player-1", "player-2", "ball-1"}
    by_id = {p.tracking_id: p for p in positions}
    assert by_id["ball-1"].mapping_point_type is MappingPointType.CENTER
    assert by_id["player-1"].mapping_point_type is MappingPointType.BOTTOM_CENTER


# 20. Deterministic results.
def test_deterministic_mapping() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    tracking = TrackingFrame(
        frame=ref,
        tracks=[
            track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1"),
            track(ref, ObjectClass.BALL, (300, 150, 312, 162), "ball-1"),
        ],
    )
    first = [p.model_dump() for p in mapper.map(tracking)]
    second = [p.model_dump() for p in mapper.map(tracking)]
    assert first == second


# 21. No mutation of source tracking objects.
def test_source_tracking_frame_not_mutated() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    tracking = TrackingFrame(
        frame=ref,
        tracks=[track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")],
    )
    snapshot = tracking.model_dump()
    mapper.map(tracking)
    mapper.map(tracking)
    assert tracking.model_dump() == snapshot


# 22. Reset / recalibration behavior.
def test_reset_and_recalibration() -> None:
    mapper = calibrated_mapper()
    assert mapper.is_calibrated is True
    mapper.reset()
    assert mapper.is_calibrated is False
    ref = frame()
    with pytest.raises(MapperNotCalibrated):
        mapper.map(TrackingFrame(frame=ref, tracks=[]))
    mapper.recalibrate(rect_calibration(calibration_id="calibration-06F-2"))
    assert mapper.is_calibrated is True
    (position,) = mapper.map(
        TrackingFrame(
            frame=ref,
            tracks=[track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")],
        )
    )
    assert position.calibration_id == "calibration-06F-2"


def test_invalid_calibration_estimate_is_rejected_by_mapper() -> None:
    # Four points always fit exactly; inconsistency needs an over-determined set.
    mapper = HomographyMapper(MapperConfig(max_reprojection_rmse=1e-6))
    calibration = PitchCalibration(
        calibration_id="noisy",
        correspondences=[
            *rect_calibration().correspondences,
            CalibrationCorrespondence(
                image=ImagePoint(x=320, y=180),
                pitch=PitchCoordinate(x=0.9, y=0.9, coordinate_system="PITCH"),
            ),
        ],
    )
    with pytest.raises(CalibrationError):
        mapper.calibrate(calibration)
    assert mapper.is_calibrated is False


def test_overdetermined_calibration_with_redundant_point() -> None:
    calibration = PitchCalibration(
        calibration_id="five-point",
        correspondences=[
            *rect_calibration().correspondences,
            CalibrationCorrespondence(
                image=ImagePoint(x=320, y=180),
                pitch=PitchCoordinate(x=0.5, y=0.5, coordinate_system="PITCH"),
            ),
        ],
    )
    estimated = HomographyEstimator().estimate(calibration)
    assert estimated.quality.is_valid is True
    assert estimated.quality.correspondence_count == 5
    assert project(estimated.matrix, 320, 180) == pytest.approx((0.5, 0.5))


def test_end_to_end_pipeline_detection_to_pitch() -> None:
    from collections.abc import Iterable, Sequence
    from datetime import UTC, datetime

    from app.ai.vision.pipeline import VisionPipeline
    from app.ai.vision.schemas import (
        Detection,
        FrameResult,
        VideoProcessingStatus,
        VideoSource,
    )
    from app.ai.vision.types import FramePacket

    ref = frame()
    video = VideoSource(
        source_id=SOURCE_ID,
        match_id=UUID(int=2),
        original_filename="match.mp4",
        media_type="video/mp4",
        file_size_bytes=100,
        ingested_at=datetime(2026, 9, 29, tzinfo=UTC),
        processing_status=VideoProcessingStatus.READY,
        storage_reference=f"{SOURCE_ID.hex}.mp4",
    )

    class Extractor:
        def extract(self, source: VideoSource) -> Iterable[FramePacket[bytes]]:
            yield FramePacket(reference=ref, payload=b"frame")

    class Detector:
        def detect(self, packet: FramePacket[bytes]) -> Sequence[Detection]:
            return [
                Detection(
                    frame=packet.reference,
                    object_class=ObjectClass.PLAYER,
                    confidence=0.9,
                    bounding_box=BoundingBox(x_min=10, y_min=20, x_max=50, y_max=100),
                )
            ]

    tracker = DeterministicIoUTracker()
    mapper = calibrated_mapper()
    [result] = list(VisionPipeline(Extractor(), Detector(), tracker, mapper).run(video))
    assert isinstance(result, FrameResult)
    assert len(result.pitch_positions) == 1
    position = result.pitch_positions[0]
    assert position.tracking_id == result.tracking.tracks[0].tracking_id
    assert position.tracking_id == "player-1"
    assert position.mapping_point_type is MappingPointType.BOTTOM_CENTER
    assert position.calibration_id == CAL_ID


def test_no_player_identity_introduced() -> None:
    mapper = calibrated_mapper()
    ref = frame()
    (position,) = mapper.map(
        TrackingFrame(
            frame=ref,
            tracks=[track(ref, ObjectClass.PLAYER, (10, 20, 50, 100), "player-1")],
        )
    )
    assert isinstance(position, PitchPosition)
    assert "player_id" not in PitchPosition.model_fields
    assert position.tracking_id == "player-1"


def test_quality_model_is_honest() -> None:
    quality = CalibrationQuality(
        reprojection_rmse=0.0,
        max_reprojection_error=0.0,
        inlier_count=4,
        correspondence_count=4,
        is_valid=True,
    )
    assert quality.inlier_count <= quality.correspondence_count
