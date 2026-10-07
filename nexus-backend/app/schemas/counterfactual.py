"""Counterfactual tactical scenario contracts.

Separate BASELINE (what actually existed) from COUNTERFACTUAL (hypothetical change).
All inputs are strictly validated; unknown fields are rejected.
"""

from __future__ import annotations

from uuid import UUID

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

    changes: list[CounterfactualPlayerChange]

    @model_validator(mode="after")
    def validate_changes_not_empty(self) -> CounterfactualScenarioCreate:
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