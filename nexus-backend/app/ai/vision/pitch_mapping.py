"""Phase 06F — image-space to pitch-space homography mapping.

Pipeline position: ``TRACKING -> IMAGE COORDINATES -> PITCH COORDINATES``.

Coordinate convention (explicit and consistent):

- Image space: pixels, origin top-left, x grows right, y grows down.
- Normalized pitch space: unit square. ``x = 0`` is one touchline,
  ``x = 1`` the opposite touchline; ``y = 0`` is one goal line,
  ``y = 1`` the opposite goal line. Which physical corner is the origin
  is fixed by the calibration correspondences and recorded in
  ``PitchCalibration.origin_description``.
- Metric pitch space: metres, ``x_metres = x_norm * length``,
  ``y_metres = y_norm * width`` using configurable ``PitchDimensions``.

Never mixes the two: every ``PitchCoordinate`` carries its ``space``.

Pure standard library (Gaussian elimination, no numpy/OpenCV) so the
unit-test suite stays runnable on a normal CPU machine.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.vision.schemas import (
    BoundingBox,
    CalibrationQuality,
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

ESTIMATOR_NAME = "nexus-dlt-homography"
ESTIMATOR_VERSION = "06F.1"

MAX_TRACKS_PER_FRAME = 256
_SINGULARITY_TOLERANCE = 1e-12
_DEGENERACY_AREA_TOLERANCE = 1e-9


class CalibrationError(ValueError):
    """Calibration data is missing, malformed, or degenerate."""


class DegenerateCalibration(CalibrationError):
    """Correspondences cannot define a valid planar homography."""


class InvalidHomography(ValueError):
    """A homography matrix is malformed or cannot project a point."""


class MapperNotCalibrated(RuntimeError):
    """The mapper was used before a valid calibration was installed."""


@dataclass(frozen=True)
class CalibratedHomography:
    """An estimated transform plus its honestly measured quality."""

    matrix: tuple[float, ...]
    calibration_id: str
    method: str
    quality: CalibrationQuality

    @property
    def inlier_ratio(self) -> float:
        total = self.quality.correspondence_count
        return self.quality.inlier_count / total if total else 0.0


@dataclass(frozen=True)
class MappingProvenance:
    """Sidecar answering 'why does NEXUS FC believe this location?'."""

    calibration_id: str
    estimator_name: str
    estimator_version: str
    mapping_point_type: MappingPointType
    output_space: PitchSpace


class MapperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output_space: PitchSpace = PitchSpace.NORMALIZED
    pitch_dimensions: PitchDimensions | None = None
    clamp_to_pitch: bool = False
    max_reprojection_rmse: float = Field(default=0.05, gt=0, le=1)
    inlier_threshold: float = Field(default=0.02, gt=0, le=1)

    @model_validator(mode="after")
    def validate_metric_needs_dimensions(self) -> MapperConfig:
        if self.output_space is PitchSpace.METRIC and self.pitch_dimensions is None:
            raise ValueError("METRIC output requires pitch_dimensions")
        return self


def representative_point(track: TrackedObject) -> tuple[ImagePoint, MappingPointType]:
    """Policy: players map via ground-contact approximation (bottom-center),
    the ball via its visual center. The original box is always preserved."""
    box: BoundingBox = track.bounding_box
    if track.object_class is ObjectClass.BALL:
        point_type = MappingPointType.CENTER
        point = ImagePoint(x=(box.x_min + box.x_max) / 2, y=(box.y_min + box.y_max) / 2)
    else:
        point_type = MappingPointType.BOTTOM_CENTER
        point = ImagePoint(x=(box.x_min + box.x_max) / 2, y=box.y_max)
    return point, point_type


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for small dense systems."""
    size = len(vector)
    augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < _SINGULARITY_TOLERANCE:
            raise DegenerateCalibration("Correspondence system is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for row in range(column + 1, size):
            factor = augmented[row][column] / divisor
            for cell in range(column, size + 1):
                augmented[row][cell] -= factor * augmented[column][cell]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        residual = augmented[row][size] - sum(
            augmented[row][column] * solution[column] for column in range(row + 1, size)
        )
        if abs(augmented[row][row]) < _SINGULARITY_TOLERANCE:
            raise DegenerateCalibration("Correspondence system is singular")
        solution[row] = residual / augmented[row][row]
    if any(not math.isfinite(value) for value in solution):
        raise DegenerateCalibration("Homography solution is not finite")
    return solution


def _dlt_matrix(
    pairs: Sequence[tuple[float, float, float, float]],
) -> tuple[float, ...]:
    """Direct Linear Transform with h33 fixed to 1 (valid for image->pitch
    quads, where the homogeneous scale is provably non-zero)."""
    rows: list[list[float]] = []
    rhs: list[float] = []
    for x, y, xp, yp in pairs:
        rows.append([x, y, 1, 0, 0, 0, -x * xp, -y * xp])
        rhs.append(xp)
        rows.append([0, 0, 0, x, y, 1, -x * yp, -y * yp])
        rhs.append(yp)
    if len(pairs) == 4:
        solved = _solve_linear_system(rows, rhs)
    else:
        # Over-determined: normal equations A^T A h = A^T b.
        dim = 8
        normal = [[0.0] * dim for _ in range(dim)]
        projected = [0.0] * dim
        for row, target in zip(rows, rhs, strict=True):
            for i in range(dim):
                projected[i] += row[i] * target
                for j in range(dim):
                    normal[i][j] += row[i] * row[j]
        solved = _solve_linear_system(normal, projected)
    matrix = tuple(solved[:6]) + (solved[6], solved[7], 1.0)
    if any(not math.isfinite(value) for value in matrix):
        raise DegenerateCalibration("Estimated homography is not finite")
    return matrix


def project(matrix: Sequence[float], x: float, y: float) -> tuple[float, float]:
    """Apply a row-major 3x3 homography; never silently hides failures."""
    if len(matrix) != 9:
        raise InvalidHomography("Homography matrix must hold 9 values")
    if any(not math.isfinite(v) for v in (*matrix, x, y)):
        raise InvalidHomography("Homography inputs must be finite")
    h11, h12, h13, h21, h22, h23, h31, h32, h33 = matrix
    w = h31 * x + h32 * y + h33
    if abs(w) < _SINGULARITY_TOLERANCE:
        raise InvalidHomography("Homogeneous normalization would divide by zero")
    return (h11 * x + h12 * y + h13) / w, (h21 * x + h22 * y + h23) / w


def to_metric(
    coordinate: PitchCoordinate, dimensions: PitchDimensions
) -> PitchCoordinate:
    """Explicit NORMALIZED -> METRIC conversion; never an implicit reinterpretation."""
    if coordinate.space is not PitchSpace.NORMALIZED:
        raise CalibrationError("Only NORMALIZED coordinates convert to METRIC")
    return PitchCoordinate(
        x=coordinate.x * dimensions.length_metres,
        y=coordinate.y * dimensions.width_metres,
        coordinate_system="PITCH",
        space=PitchSpace.METRIC,
    )


def _max_triangle_area(points: Sequence[tuple[float, float]]) -> float:
    best = 0.0
    count = len(points)
    for i in range(count):
        for j in range(i + 1, count):
            for k in range(j + 1, count):
                (x1, y1), (x2, y2), (x3, y3) = points[i], points[j], points[k]
                area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2
                best = max(best, area)
    return best


class HomographyEstimator:
    """Estimates a homography from calibration correspondences."""

    def __init__(self, config: MapperConfig | None = None) -> None:
        self.config = config or MapperConfig()

    def estimate(self, calibration: PitchCalibration) -> CalibratedHomography:
        if not isinstance(calibration, PitchCalibration):
            raise CalibrationError("A PitchCalibration object is required")
        pairs = [
            (c.image.x, c.image.y, c.pitch.x, c.pitch.y)
            for c in calibration.correspondences
        ]
        self._reject_degenerate(pairs)
        matrix = _dlt_matrix(pairs)
        errors = []
        for x, y, xp, yp in pairs:
            try:
                mapped_x, mapped_y = project(matrix, x, y)
            except InvalidHomography as exc:
                raise DegenerateCalibration(
                    "Estimated homography cannot map its own correspondences"
                ) from exc
            errors.append(math.dist((mapped_x, mapped_y), (xp, yp)))
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        max_error = max(errors)
        inliers = sum(1 for e in errors if e <= self.config.inlier_threshold)
        quality = CalibrationQuality(
            reprojection_rmse=rmse,
            max_reprojection_error=max_error,
            inlier_count=inliers,
            correspondence_count=len(pairs),
            is_valid=bool(
                rmse <= self.config.max_reprojection_rmse and inliers == len(pairs)
            ),
        )
        return CalibratedHomography(
            matrix=matrix,
            calibration_id=calibration.calibration_id,
            method=f"{ESTIMATOR_NAME}/{ESTIMATOR_VERSION}",
            quality=quality,
        )

    @staticmethod
    def _reject_degenerate(pairs: Sequence[tuple[float, float, float, float]]) -> None:
        if len(pairs) < 4:
            raise CalibrationError("At least four correspondences are required")
        for x, y, xp, yp in pairs:
            if not all(math.isfinite(v) for v in (x, y, xp, yp)):
                raise CalibrationError("Correspondences must hold finite values")
        image_points = [(x, y) for x, y, _, _ in pairs]
        pitch_points = [(xp, yp) for _, _, xp, yp in pairs]
        if len(set(image_points)) != len(image_points):
            raise DegenerateCalibration("Duplicate image points are not allowed")
        if len(set(pitch_points)) != len(pitch_points):
            raise DegenerateCalibration("Duplicate pitch points are not allowed")
        if _max_triangle_area(image_points) < _DEGENERACY_AREA_TOLERANCE:
            raise DegenerateCalibration("Image points are collinear or coincident")
        if _max_triangle_area(pitch_points) < _DEGENERACY_AREA_TOLERANCE:
            raise DegenerateCalibration("Pitch points are collinear or coincident")


class HomographyMapper:
    """Pipeline-facing mapper: applies one validated calibration to tracks."""

    def __init__(self, config: MapperConfig | None = None) -> None:
        self.config = config or MapperConfig()
        self._estimator = HomographyEstimator(self.config)
        self._homography: CalibratedHomography | None = None
        self._dimensions: PitchDimensions | None = self.config.pitch_dimensions

    @property
    def is_calibrated(self) -> bool:
        return self._homography is not None

    @property
    def provenance(self) -> MappingProvenance | None:
        if self._homography is None:
            return None
        return MappingProvenance(
            calibration_id=self._homography.calibration_id,
            estimator_name=ESTIMATOR_NAME,
            estimator_version=ESTIMATOR_VERSION,
            mapping_point_type=MappingPointType.BOTTOM_CENTER,
            output_space=self.config.output_space,
        )

    def calibrate(self, calibration: PitchCalibration) -> CalibratedHomography:
        """Install a calibration; replaces any previous one (recalibration)."""
        estimated = self._estimator.estimate(calibration)
        if not estimated.quality.is_valid:
            raise CalibrationError(
                f"Calibration {calibration.calibration_id!r} failed validation: "
                f"rmse={estimated.quality.reprojection_rmse:.6f}"
            )
        self._homography = estimated
        if calibration.pitch_dimensions is not None:
            self._dimensions = calibration.pitch_dimensions
        return estimated

    recalibrate = calibrate

    def reset(self) -> None:
        self._homography = None
        self._dimensions = self.config.pitch_dimensions

    def map(self, tracking: TrackingFrame) -> list[PitchPosition]:
        if self._homography is None:
            raise MapperNotCalibrated("Mapper has no valid calibration installed")
        if not isinstance(tracking, TrackingFrame):
            raise CalibrationError("A TrackingFrame object is required")
        if len(tracking.tracks) > MAX_TRACKS_PER_FRAME:
            raise CalibrationError("Too many tracks in a single frame")
        positions: list[PitchPosition] = []
        for track in tracking.tracks:
            try:
                image_point, point_type = representative_point(track)
                mapped_x, mapped_y = project(
                    self._homography.matrix, image_point.x, image_point.y
                )
            except (InvalidHomography, ValueError):
                # Explicit failure: omit the track rather than fabricate.
                continue
            in_bounds = 0.0 <= mapped_x <= 1.0 and 0.0 <= mapped_y <= 1.0
            if self.config.clamp_to_pitch:
                mapped_x = min(1.0, max(0.0, mapped_x))
                mapped_y = min(1.0, max(0.0, mapped_y))
            coordinate = PitchCoordinate(
                x=mapped_x,
                y=mapped_y,
                coordinate_system="PITCH",
                space=PitchSpace.NORMALIZED,
            )
            if self.config.output_space is PitchSpace.METRIC:
                if self._dimensions is None:
                    raise CalibrationError("METRIC output needs pitch dimensions")
                coordinate = to_metric(coordinate, self._dimensions)
            positions.append(
                PitchPosition(
                    frame=tracking.frame,
                    tracking_id=track.tracking_id,
                    coordinate=coordinate,
                    mapping_point=image_point,
                    mapping_point_type=point_type,
                    in_bounds=in_bounds,
                    calibration_id=self._homography.calibration_id,
                )
            )
        return positions
