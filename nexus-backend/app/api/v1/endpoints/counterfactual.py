"""Counterfactual tactical lab — read-only API endpoints.

Provides a minimal read-only surface for counterfactual scenario queries.
All endpoints are governed by existing RBAC; no second authorization system.

See ``app/services/counterfactual.py`` for the simulator boundary.
"""

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDependency
from app.schemas.counterfactual import (
    CounterfactualScenarioCreate,
    CounterfactualScenarioResult,
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

    Args:
        payload: The counterfactual scenario specification separating
            baseline from hypothetical changes.

    Returns:
        A ``CounterfactualScenarioResult`` with the simulation outcome.

    Raises:
        NotImplementedError: If no simulator is configured (11A default).
    """
    service = CounterfactualService.unavailable()
    return service.simulate_scenario(payload)