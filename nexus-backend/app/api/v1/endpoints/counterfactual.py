"""Counterfactual tactical lab — read-only API endpoints.

Provides a minimal read-only surface for counterfactual scenario queries.
All endpoints are governed by existing RBAC; no second authorization system.

See ``app/services/counterfactual.py`` for the simulator boundary.

11B: the endpoint now attempts a deterministic structural comparison
via the Phase 07 tactical state representations before falling back to
the 11A unavailable result.
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.counterfactual import (
    CounterfactualScenarioCreate,
    CounterfactualScenarioResult,
    CounterfactualEvaluationRequest,
    CounterfactualEvaluationResult,
)
from app.services.counterfactual import CounterfactualService

router = APIRouter(prefix="/counterfactual", tags=["counterfactual"])


@router.get(
    "/health",
    summary="Counterfactual service health check",
)
async def health_check(
    session: SessionDependency,
    actor: CurrentUser,
) -> dict[str, str]:
    """Verify the counterfactual service is operational.

    Returns the current simulator status. This is a read-only check
    within the authenticated session.
    """
    service = CounterfactualService.unavailable()
    return {"simulator_status": service.is_available and "available" or "unavailable"}


@router.post(
    "/simulate",
    summary="Run a counterfactual tactical simulation",
)
async def simulate_counterfactual(
    payload: CounterfactualScenarioCreate,
    session: SessionDependency,
    actor: CurrentUser,
) -> CounterfactualScenarioResult:
    """Run a counterfactual tactical simulation.

    For 11B, attempts a deterministic structural comparison via the
    Phase 07 tactical state representations. When the scenario is
    supported by the deterministic engine, returns a structural
    comparison result describing what changed (formation, player
    configuration, entities affected). When unsupported, falls back
    to the 11A unavailable result.

    The result is advisory only — it never modifies match/player history,
    never makes substitutions automatically, and never claims certainty.

    Args:
        payload: The counterfactual scenario specification separating
            baseline from hypothetical changes.

    Returns:
        A ``CounterfactualScenarioResult`` with the simulation outcome.

        - If the deterministic engine (11B) supports the scenario,
          returns a result with ``simulator_status = "available"``
          containing structural comparison information.
        - If the scenario is unsupported, falls back to the 11A
          unavailable result with ``simulator_status = "unavailable"``.
    """
    service = CounterfactualService.deterministic()
    try:
        result = service.simulate_scenario(payload)
        if result.simulator_status == "available":
            return result
    except Exception:
        pass

    # Fall back to 11A unavailable result
    service = CounterfactualService.unavailable()
    return service.simulate_scenario(payload)


@router.post(
    "/evaluate",
    summary="Evaluate a counterfactual scenario against ground truth",
    response_model=CounterfactualEvaluationResult,
)
async def evaluate_counterfactual(
    payload: CounterfactualEvaluationRequest,
    session: SessionDependency,
    actor: CurrentUser,
) -> CounterfactualEvaluationResult:
    """Evaluate a counterfactual scenario against optional ground truth.

    11D: evaluation integration.
    - Reuses the Phase 11D evaluation foundation service.
    - Validates scenario and reference compatibility.
    - Returns INSUFFICIENT_EVIDENCE when no ground truth is provided.
    - Computes only deterministic metrics mathematically justified by supplied data.
    - Preserves provenance, warnings, and evaluation version.
    - Evaluation is read-only; never mutates baseline or hypothetical scenarios.
    """
    service = CounterfactualService.deterministic()
    result = service._evaluate(payload)
    return result


