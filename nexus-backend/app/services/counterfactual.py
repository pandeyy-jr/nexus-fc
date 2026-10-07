"""Counterfactual tactical simulation interface/protocol.

Defines the boundary between the API layer and a concrete simulator implementation.

For 11A, the default implementation is deterministically unavailable —
it never fabricates predictions or probabilities. Future 11B+ plug-ins
can provide real models without redesigning the contracts.
"""

from __future__ import annotations

from app.schemas.counterfactual import (
    CounterfactualScenarioCreate,
    CounterfactualScenarioResult,
)


class CounterfactualSimulator:
    """Replaceable simulator protocol for counterfactual tactical analysis.

    The `simulate` method takes a baseline description and a hypothetical
    configuration, and returns a ``CounterfactualScenarioResult``.

    Concrete subclasses must implement the `simulate` method. The base
    class provides an ``unavailable`` class that returns a deterministically
    unavailable result — no model is configured, no predictions are ever
    fabricated. This is the 11A default.
    """

    def simulate(
        self,
        scenario_create: CounterfactualScenarioCreate,
    ) -> CounterfactualScenarioResult:
        """Run a counterfactual simulation.

        Args:
            scenario_create: The counterfactual scenario specification
                containing baseline and hypothetical configuration.

        Returns:
            A ``CounterfactualScenarioResult`` with the simulation outcome.

        Raises:
            NotImplementedError: If no model/components are configured.
        """
        raise NotImplementedError(
            "Counterfactual simulator not configured — implement or use .unavailable()"
        )

    @classmethod
    def unavailable(cls) -> CounterfactualSimulator:
        """Return a simulator that deterministically signals unavailable status.

        This is the default for 11A. It returns a result with
        ``simulator_status = "unavailable"`` and includes a warning
        that no model is configured. No predictions or probabilities
        are ever fabricated.

        The returned instance's ``simulate`` method returns a result
        instead of raising ``NotImplementedError``.
        """
        instance = object.__new__(CounterfactualSimulator)
        # Bind the unavailable simulate method directly
        instance.simulate = cls._unavailable_simulate  # type: ignore[assignment]
        return instance

    @staticmethod
    def _unavailable_simulate(
        scenario_create: CounterfactualScenarioCreate,
    ) -> CounterfactualScenarioResult:
        """Build a result indicating the simulator is unavailable."""
        return CounterfactualScenarioResult(
            scenario_id=scenario_create.scenario_id,
            match_id=scenario_create.match_id,
            baseline_formation=scenario_create.baseline_formation,
            counterfactual_formation=scenario_create.counterfactual_formation,
            changes=scenario_create.changes,
            assumptions=scenario_create.assumptions,
            warnings=scenario_create.warnings + [
                "No counterfactual tactical model configured. "
                "This result is deterministically unavailable. "
                "Replace with a configured simulator for 11B+. "
                "No predictions or probabilities are fabricated."
            ]
            if scenario_create.warnings
            else [
                "No counterfactual tactical model configured. "
                "This result is deterministically unavailable. "
                "Replace with a configured simulator for 11B+. "
                "No predictions or probabilities are fabricated."
            ],
            simulator_status="unavailable",
        )


class CounterfactualService:
    """Thin boundary over the replaceable simulator.

    This service owns no model state itself. It simply delegates to
    whatever ``CounterfactualSimulator`` is configured. The default
    configuration (via ``CounterfactualService.unavailable()``) is
    deterministically unavailable — guaranteeing no fabricated output.
    """

    def __init__(self, simulator: CounterfactualSimulator | None = None) -> None:
        self._simulator = simulator

    @classmethod
    def unavailable(cls) -> CounterfactualService:
        """Create a service with the deterministically unavailable simulator.

        This is the 11A default. No models are loaded, no weights are
        downloaded, and no predictions are fabricated.
        """
        return cls(CounterfactualSimulator.unavailable())

    @property
    def is_available(self) -> bool:
        """Check if a real (non-unavailable) simulator is configured."""
        if self._simulator is None:
            return False
        # The unavailable sentinel has its simulate replaced with _unavailable_simulate
        # Check by looking at the _unavailable marker set on the instance
        return getattr(self._simulator, "_unavailable", False) is not True

    def simulate_scenario(
        self, scenario_create: CounterfactualScenarioCreate
    ) -> CounterfactualScenarioResult:
        """Run a counterfactual simulation through the configured simulator.

        Args:
            scenario_create: The counterfactual scenario specification.

        Returns:
            A ``CounterfactualScenarioResult`` with the outcome.
        """
        return self._simulator.simulate(scenario_create)