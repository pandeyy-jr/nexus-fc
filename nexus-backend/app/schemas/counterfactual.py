"""Counterfactual tactical scenario contracts.

Separate BASELINE (what actually existed) from COUNTERFACTUAL (hypothetical change).
All inputs are strictly validated; unknown fields are rejected.
"""

from __future__ import annotations

from uuid import UUID
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Supported formation values for counterfactual configuration.
#: Controlled vocabulary — new formations may be added but unknown
#: values are always rejected by the schema.
CounterfactualFormation = str

FOUR_FOUR_TWO = "4-4-2"
FOUR_THREE_THREE = "4-3-3"
THREE_FIVE_TWO = "3-5-2"
THREE_FOUR_THREE = "3-4-3"
FIVE_THREE_TWO = "5-3-2"
FOUR_TWO_THREE = "4-2-3-1"
FOUR_ONE_THREE_ONE = "4-1-3-1"
TWO_THREE_FIVE = "2-3-5"
TWO_THREE_THREE = "2-3-3-1"
ONE_FOUR_FOUR_ONE = "1-4-4-1"

# Alias for backwards-compatible imports
Formation442 = FOUR_FOUR_TWO
Formation433 = FOUR_THREE_THREE


def _validate_formation(value: str) -> str:
    """Validate that a formation string is from the known vocabulary.

    Raises ValueError if the formation is not in the controlled set.
    """
    valid = {
        FOUR_FOUR_TWO,
        FOUR_THREE_THREE,
        THREE_FIVE_TWO,
        THREE_FOUR_THREE,
        FIVE_THREE_TWO,
        FOUR_TWO_THREE,
        FOUR_ONE_THREE_ONE,
        TWO_THREE_FIVE,
        TWO_THREE_THREE,
        ONE_FOUR_FOUR_ONE,
    }
    if value not in valid:
        raise ValueError(
            f"Invalid formation. Must be one of: "
            f"{', '.join(sorted(valid))}"
        )
    return value


class CounterfactualPlayerChange(BaseModel):
    """A single player substitution in a counterfactual scenario."""

    model_config = ConfigDict(extra="forbid")

    out_player_id: UUID
    in_player_id: UUID

    @model_validator(mode="after")
    def out_must_differ_from_in(self) -> CounterfactualPlayerChange:
        if self.out_player_id == self.in_player_id:
            raise ValueError("out_player_id and in_player_id must differ")
        return self


class CounterfactualScenarioBase(BaseModel):
    """Base shared fields for counterfactual scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: UUID
    match_id: UUID
    baseline_formation: CounterfactualFormation = Field(
        default=FOUR_FOUR_TWO,
        description="The formation that actually existed (baseline)",
    )
    counterfactual_formation: CounterfactualFormation = Field(
        default=FOUR_THREE_THREE,
        description="The hypothetical formation (counterfactual)",
    )
    change_description: str | None = Field(
        default=None,
        max_length=500,
        description="Human-readable description of the hypothetical change",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions underlying the counterfactual scenario",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about limitations and uncertainties",
    )

    @model_validator(mode="after")
    def validate_formations(cls, model) -> CounterfactualScenarioBase:
        """Validate both formations use known vocabulary values."""
        _validate_formation(model.baseline_formation)
        _validate_formation(model.counterfactual_formation)
        return model


class CounterfactualScenarioCreate(CounterfactualScenarioBase):
    """Request contract for creating a counterfactual scenario."""

    model_config = ConfigDict(extra="forbid")

    changes: list[CounterfactualPlayerChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_changes_not_empty_when_required(self) -> CounterfactualScenarioCreate:
        # 11A: require at least one player change for API requests
        # 11B: formation-level counterfactuals may have empty changes
        if not self.changes:
            raise ValueError("At least one player change must be specified")
        return self


class CounterfactualScenarioResult(BaseModel):
    """Result contract preserving scenario data and provenance.

    This is the read-only result model — it never mutates match/player history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: UUID
    match_id: UUID
    baseline_formation: CounterfactualFormation
    counterfactual_formation: CounterfactualFormation
    changes: list[CounterfactualPlayerChange]
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    simulator_status: str = "unavailable"
    analyzed_at: str = Field(
        default_factory=lambda: __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ).isoformat(),
        description="ISO timestamp of when the result was analyzed/generated",
    )
    # 11C: Tactical impact metrics — derived observations, NOT predictions.
    # Computed from existing tactical state; unavailable metrics carry explicit reasons.
    metrics: list["TacticalImpactMetric"] = Field(
        default_factory=list,
        description="Structural impact metrics comparing baseline vs counterfactual",
    )
    unavailable_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons why individual metrics could not be computed",
    )


class TacticalImpactMetric(BaseModel):
    """A single tactical impact metric with baseline/counterfactual values and delta.

    All values are finite numeric observations derived from existing tactical state.
    Unknown/unavailable values are explicitly marked, never invented.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    baseline_value: float | None = Field(
        default=None,
        description="Metric value from the baseline tactical state",
    )
    counterfactual_value: float | None = Field(
        default=None,
        description="Metric value from the counterfactual tactical state",
    )
    delta: float | None = Field(
        default=None,
        description="Counterfactual minus baseline (baseline to counterfactual)",
    )
    units: str = Field(
        default="",
        description="Units or meaning of the metric (e.g. 'players')",
    )
    available: bool = Field(
        True,
        description="Whether the metric could be computed from available data",
    )
    reason: str | None = Field(
        default=None,
        description="Why the metric is unavailable if available=False",
    )


class TacticalImpactResult(BaseModel):
    """Container for tactical impact metrics computed for a counterfactual scenario.

    This is read-only — it never mutates match/player history or database records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: UUID
    match_id: UUID
    baseline_formation: CounterfactualFormation
    counterfactual_formation: CounterfactualFormation
    metrics: list[TacticalImpactMetric] = Field(
        default_factory=list,
        description="Tactical impact metrics computed for this scenario",
    )
    unavailable_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons why individual metrics could not be computed",
    )
    analyzed_at: str = Field(
        default_factory=lambda: __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ).isoformat(),
        description="ISO timestamp of when the impact analysis was performed",
    )


# 11C: Tactical impact metrics contract


class CounterfactualEvaluationStatus(str, Enum):
    """Status of a counterfactual evaluation."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AVAILABLE = "available"
    UNSUPPORTED = "unsupported"


class CounterfactualEvaluationMetric(BaseModel):
    """A single evaluation metric result.

    Values are finite observations derived from supplied ground truth.
    Unknown/unavailable values are explicitly marked, never invented.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    expected: float | None = Field(
        default=None,
        description="Ground-truth expected value",
    )
    actual: float | None = Field(
        default=None,
        description="Simulated/actual value from counterfactual result",
    )
    error: float | None = Field(
        default=None,
        description="actual - expected (if both available)",
    )
    units: str = Field(
        default="",
        description="Units of the metric",
    )
    available: bool = Field(
        True,
        description="Whether the metric could be computed from available evidence",
    )
    reason: str | None = Field(
        default=None,
        description="Why the metric is unavailable if available=False",
    )


class CounterfactualEvaluationResult(BaseModel):
    """Result contract for counterfactual evaluation.

    This is read-only — it never mutates match/player history or database records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: UUID
    match_id: UUID
    evaluation_status: CounterfactualEvaluationStatus = Field(
        default=CounterfactualEvaluationStatus.INSUFFICIENT_EVIDENCE,
        description="Status of the evaluation",
    )
    evaluation_method: str = Field(
        default="",
        description="Method/version used for evaluation",
    )
    expected_reference: UUID | None = Field(
        default=None,
        description="Reference to ground-truth evidence",
    )
    simulated_reference: UUID | None = Field(
        default=None,
        description="Reference to simulated counterfactual result",
    )
    metrics: list[CounterfactualEvaluationMetric] = Field(
        default_factory=list,
        description="Evaluation metric results where evidence exists",
    )
    sample_count: int = Field(
        default=0,
        ge=0,
        description="Number of samples/observations in the evaluation",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about evaluation limitations",
    )
    provenance: list[str] = Field(
        default_factory=list,
        description="Provenance references for auditability",
    )
    evaluated_at: str = Field(
        default_factory=lambda: __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ).isoformat(),
        description="ISO timestamp of when the evaluation was performed",
    )


# 11D: Evaluation foundation contracts


class CounterfactualEvaluationRequest(BaseModel):
    """Request contract for counterfactual evaluation.

    Takes a scenario ID and optional ground-truth references.
    Evaluation is a separate concern from simulation.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: UUID
    match_id: UUID
    expected_formation: CounterfactualFormation | None = Field(
        default=None,
        description="Ground-truth formation if available",
    )
    actual_formation: CounterfactualFormation | None = Field(
        default=None,
        description="Actual observed formation from real data if available",
    )
    expected_metrics: list[str] | None = Field(
        default=None,
        description="Metric names for which ground truth is provided",
    )
    actual_metrics: dict[str, float] | None = Field(
        default=None,
        description="Actual metric values from real data if available",
    )
    simulator_result_id: UUID | None = Field(
        default=None,
        description="Reference to the counterfactual simulation result",
    )


class CounterfactualScenario(CounterfactualScenarioBase):
    """Full scenario model including database-traced fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    created_at: str
    created_by: UUID | None = None


# Alias for API response
CounterfactualScenarioResponse = CounterfactualScenario


class CounterfactualValidationError(BaseModel):
    """Error response when a counterfactual request fails validation."""

    model_config = ConfigDict(extra="forbid")

    detail: str
    invalid_field: str | None = None
    available_values: list[str] | None = None