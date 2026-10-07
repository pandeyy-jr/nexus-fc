"""Phase 11A — Counterfactual Tactical Lab foundation tests.

Tests the contracts, interface, and deterministic unavailable result.
No models are trained, no weights are downloaded, no predictions are fabricated.
"""

from uuid import UUID, uuid4

import pytest

from app.schemas.counterfactual import (
    CounterfactualFormation,
    CounterfactualPlayerChange,
    CounterfactualScenarioCreate,
    CounterfactualScenarioResult,
    FOUR_FOUR_TWO,
    FOUR_THREE_THREE,
    _validate_formation,
)
from app.services.counterfactual import CounterfactualService


# ── Test data ──────────────────────────────────────────────────────────────

MATCH_ID = UUID(int=1)


def make_player_change(out_id: UUID, in_id: UUID) -> CounterfactualPlayerChange:
    return CounterfactualPlayerChange(out_player_id=out_id, in_player_id=in_id)


# ── Contract tests ─────────────────────────────────────────────────────────


def test_counterfactual_player_change_valid():
    """Valid player change contracts."""
    change = make_player_change(uuid4(), uuid4())
    assert change.out_player_id != change.in_player_id


def test_counterfactual_player_change_same_id_rejected():
    """Same out/in player ID is rejected."""
    # Pass the SAME UUID twice to trigger the validation
    same_id = uuid4()
    with pytest.raises(ValueError, match="must differ"):
        make_player_change(same_id, same_id)


def test_validate_formation_known():
    """Known formation values pass validation."""
    assert _validate_formation("4-4-2") == "4-4-2"
    assert _validate_formation("4-3-3") == "4-3-3"


def test_validate_formation_unknown_rejected():
    """Unknown formation values are rejected."""
    with pytest.raises(ValueError, match="Invalid formation"):
        _validate_formation("9-9-9")


def test_counterfactual_scenario_create_valid():
    """Valid scenario create contract."""
    changes = [make_player_change(uuid4(), uuid4())]
    payload = CounterfactualScenarioCreate(
        scenario_id=uuid4(),
        match_id=MATCH_ID,
        baseline_formation=FOUR_FOUR_TWO,
        counterfactual_formation=FOUR_THREE_THREE,
        changes=changes,
        assumptions=["formation change is tactically feasible"],
        warnings=["wind conditions may affect outcome"],
    )
    assert payload.scenario_id is not None
    assert payload.match_id == MATCH_ID
    assert payload.baseline_formation == FOUR_FOUR_TWO
    assert payload.counterfactual_formation == FOUR_THREE_THREE
    assert len(payload.changes) == 1
    assert "formation change is tactically feasible" in payload.assumptions
    assert "wind conditions may affect outcome" in payload.warnings


def test_counterfactual_scenario_create_extra_fields_rejected():
    """Extra fields are rejected (extra='forbid')."""
    from pydantic import ValidationError

    try:
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[],
            extra_field="should fail",  # type: ignore[dict-key]
        )
        # If we get here, extra fields were silently accepted — fail
        assert False, "Extra fields should have been rejected"
    except ValidationError:
        pass  # expected: extra fields forbidden


def test_counterfactual_scenario_create_empty_changes_rejected():
    """Empty changes list is rejected."""
    with pytest.raises(ValueError, match="At least one player change must be specified"):
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[],
        )


# ── Simulation interface tests ─────────────────────────────────────────────


def test_simulator_unavailable_returns_result():
    """The unavailable simulator returns a result with status='unavailable' and warnings."""
    service = CounterfactualService.unavailable()
    result = service.simulate_scenario(
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[make_player_change(uuid4(), uuid4())],
        )
    )
    # The unavailable simulator should return a result, not raise
    assert result.simulator_status == "unavailable"
    assert len(result.warnings) > 0
    # Warning should mention no model configured
    warnings_text = " ".join(result.warnings).lower()
    assert "unavailable" in warnings_text or "not configured" in warnings_text


def test_simulator_unavailable_no_fabrication():
    """No predictions, probabilities, or certainty is fabricated."""
    service = CounterfactualService.unavailable()
    result = service.simulate_scenario(
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[make_player_change(uuid4(), uuid4())],
        )
    )
    assert result.simulator_status == "unavailable"
    # No prediction fields should be present
    assert not hasattr(result, "predicted_winner") or result.predicted_winner is None
    assert not hasattr(result, "win_probability") or result.win_probability is None
    assert not hasattr(result, "expected_goals") or result.expected_goals is None
    # warnings should indicate no model is configured
    warning_text = " ".join(result.warnings).lower()
    assert "no counterfactual tactical model" in warning_text or "deterministically unavailable" in warning_text


# ── API tests ──────────────────────────────────────────────────────────────


def test_baseline_counterfactual_separation():
    """Baseline and counterfactual formation must be conceptually distinct."""
    payload = CounterfactualScenarioCreate(
        scenario_id=uuid4(),
        match_id=MATCH_ID,
        baseline_formation=FOUR_FOUR_TWO,
        counterfactual_formation=FOUR_THREE_THREE,
        changes=[make_player_change(uuid4(), uuid4())],
    )
    assert payload.baseline_formation == FOUR_FOUR_TWO
    assert payload.counterfactual_formation == FOUR_THREE_THREE


def test_result_preserves_provenance_fields():
    """Result contract preserves provenance/evidence fields where applicable."""
    service = CounterfactualService.unavailable()
    result = service.simulate_scenario(
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[make_player_change(uuid4(), uuid4())],
            assumptions=["tactical change is feasible"],
            warnings=["model unavailable"],
        )
    )
    # Verify result contract fields
    assert isinstance(result.scenario_id, UUID)
    assert isinstance(result.match_id, UUID)
    assert result.baseline_formation == FOUR_FOUR_TWO
    assert result.counterfactual_formation == FOUR_THREE_THREE
    # warnings are combined; check that our provided warning is among them
    assert "model unavailable" in result.warnings
    assert len(result.assumptions) == 1
    assert result.assumptions[0] == "tactical change is feasible"


def test_result_unknown_remains_unknown():
    """Unknown fields remain unknown — no fabricated values."""
    service = CounterfactualService.unavailable()
    result = service.simulate_scenario(
        CounterfactualScenarioCreate(
            scenario_id=uuid4(),
            match_id=MATCH_ID,
            baseline_formation=FOUR_FOUR_TWO,
            counterfactual_formation=FOUR_THREE_THREE,
            changes=[make_player_change(uuid4(), uuid4())],
        )
    )
    # No fabricated prediction values
    assert result.simulator_status == "unavailable"
    # assumptions and warnings are preserved as-is
    assert "No counterfactual tactical model" in result.warnings[0]
    assert len(result.assumptions) == 0  # none provided