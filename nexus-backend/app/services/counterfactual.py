"""Counterfactual tactical simulation interface/protocol.

Defines the boundary between the API layer and a concrete simulator implementation.

For 11A, the default implementation is deterministically unavailable —
it never fabricates predictions or probabilities. Future 11B+ plug-ins
can provide real models without redesigning the contracts.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.tactics.state import (
    MAX_PLAYERS_PER_FRAME,
    TacticalBallState,
    TacticalContract,
    TacticalFrameState,
    TacticalPlayerState,
    TacticalSequence,
    TeamAssociation,
    PositionValidity,
    PitchSpace,
)
from app.schemas.counterfactual import (
    CounterfactualFormation,
    CounterfactualPlayerChange,
    CounterfactualScenarioCreate,
    CounterfactualScenarioResult,
)

# ── Formation vocabulary ────────────────────────────────────────────────

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

VALID_FORMATIONS = {
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


# ── Deterministic counterfactual engine (inline, no sub-package import) ─

class _FormationCounts:
    """Track player counts per team from a TacticalSequence."""

    def __init__(self, sequence: TacticalSequence) -> None:
        self.home = 0
        self.away = 0
        for frame in sequence.frames:
            for p in frame.players:
                if p.team is TeamAssociation.HOME:
                    self.home += 1
                elif p.team is TeamAssociation.AWAY:
                    self.away += 1


class _DeterministicEngine:
    """Deterministic counterfactual analysis engine.

    Reuses Phase 07 TacticalFrameState / TacticalSequence representations.
    Never fabricates predictions, probabilities, or football conclusions.
    Same baseline + same input → same result (deterministic).
    Unknown/unsupported changes return explicit unavailable/unsupported result.
    """

    @staticmethod
    def _sig(frames: TacticalSequence) -> str:
        h = sum(1 for fr in frames.frames for p in fr.players if p.team is TeamAssociation.HOME)
        a = sum(1 for fr in frames.frames for p in fr.players if p.team is TeamAssociation.AWAY)
        return f"[{h}h,{a}a]"

    @staticmethod
    def _valid(fmt: str) -> bool:
        return fmt in VALID_FORMATIONS

    def analyze(self, baseline: TacticalSequence, scenario: CounterfactualScenarioCreate) -> CounterfactualScenarioResult:
        if not self._valid(scenario.baseline_formation):
            return self._unsupported(scenario, "Unknown baseline formation")
        if not self._valid(scenario.counterfactual_formation):
            return self._unsupported(scenario, "Unknown counterfactual formation")

        try:
            bp = scenario.baseline_formation.split("-")
            cp = scenario.counterfactual_formation.split("-")
            bl_h, bl_a = int(bp[0]), int(bp[1]) if len(bp) > 1 else 0
            cf_h, cf_a = int(cp[0]), int(cp[1]) if len(cp) > 1 else 0
        except (ValueError, IndexError):
            return self._unsupported(scenario, "Invalid formation string")

        fc = _FormationCounts(baseline)
        total_bl = fc.home + fc.away
        total_cf = cf_h + cf_a

        if total_bl != total_cf or total_bl == 0:
            return self._unsupported(scenario, f"Player count mismatch: {total_bl} vs {total_cf}")

        assumptions = [
            "Formation reorganization: same player cohort, new formation layout. "
            "Structural comparison only; no tactical evaluation."
        ]
        warnings = []

        notes = []
        if cf_h != bl_h:
            notes.append(f"Home: {bl_h}->{cf_h}")
        if cf_a != bl_a:
            notes.append(f"Away: {bl_a}->{cf_a}")
        if notes:
            warnings.append("; ".join(notes))

        assumptions.append(
            "Same existing player IDs/attributes; no additions/removals. "
            "Structural comparison only. No predictions or probabilities fabricated."
        )

        return CounterfactualScenarioResult(
            scenario_id=scenario.scenario_id,
            match_id=scenario.match_id,
            baseline_formation=scenario.baseline_formation,
            counterfactual_formation=scenario.counterfactual_formation,
            changes=scenario.changes,
            assumptions=assumptions,
            warnings=warnings,
            simulator_status="available",
            analyzed_at="",
        )

    @staticmethod
    def _unsupported(s: CounterfactualScenarioCreate, reason: str) -> CounterfactualScenarioResult:
        return CounterfactualScenarioResult(
            scenario_id=s.scenario_id,
            match_id=s.match_id,
            baseline_formation=s.baseline_formation,
            counterfactual_formation=s.counterfactual_formation,
            changes=s.changes,
            assumptions=["change unsupported by existing tactical state data"],
            warnings=[f"Unsupported: {reason}. No predictions or probabilities fabricated."],
            simulator_status="unsupported",
            analyzed_at="",
        )


# ── CounterfactualSimulator protocol ──────────────────────────────────

class CounterfactualSimulator:
    """Replaceable simulator protocol for counterfactual tactical analysis.

    The `simulate` method takes a baseline description and a hypothetical
    configuration, and returns a ``CounterfactualScenarioResult``.

    Concrete subclasses must implement the `simulate` method. This class
    provides the 11A default (unavailable) and a deterministic 11B
    implementation via CounterfactualService.
    """

    def simulate(
        self,
        scenario_create: CounterfactualScenarioCreate,
    ) -> CounterfactualScenarioResult:
        raise NotImplementedError(
            "Counterfactual simulator not configured — implement or use .unavailable()"
        )

    @classmethod
    def unavailable(cls) -> "CounterfactualSimulator":
        instance = object.__new__(CounterfactualSimulator)
        instance._unavailable = True
        instance.simulate = cls._unavail_sim  # type: ignore[assignment]
        return instance

    _unavail_sim = staticmethod(lambda sc: CounterfactualScenarioResult(
        scenario_id=sc.scenario_id,
        match_id=sc.match_id,
        baseline_formation=sc.baseline_formation,
        counterfactual_formation=sc.counterfactual_formation,
        changes=sc.changes,
        assumptions=sc.assumptions,
        warnings=sc.warnings + [
            "No counterfactual tactical model configured. "
            "This result is deterministically unavailable. "
            "Replace with a configured simulator for 11B+. "
            "No predictions or probabilities are fabricated."
        ] if sc.warnings else [
            "No counterfactual tactical model configured. "
            "This result is deterministically unavailable. "
            "Replace with a configured simulator for 11B+. "
            "No predictions or probabilities are fabricated."
        ],
        simulator_status="unavailable",
    ))


# ── CounterfactualService ─────────────────────────────────────────────

class CounterfactualService:
    """Thin boundary over the replaceable simulator.

    11A default: deterministically unavailable, no fabricated output.
    11B: provides deterministic() using Phase 07 tactical state
    representations with a deterministic transformation engine.
    """

    def __init__(self, simulator: CounterfactualSimulator | None = None) -> None:
        self._simulator = simulator

    @classmethod
    def unavailable(cls) -> CounterfactualService:
        return cls(CounterfactualSimulator.unavailable())

    @classmethod
    def deterministic(cls) -> CounterfactualService:
        return cls(CounterfactualService._det_inner())

    @property
    def is_available(self) -> bool:
        if self._simulator is None:
            return False
        return getattr(self._simulator, "_unavailable", False) is not True

    @classmethod
    def _det_inner(cls) -> CounterfactualSimulator:
        inst = object.__new__(CounterfactualSimulator)
        inst._unavailable = False
        inst.simulate = cls._det_sim  # type: ignore[assignment]
        return inst

    def simulate_scenario(
        self, scenario_create: CounterfactualScenarioCreate
    ) -> CounterfactualScenarioResult:
        # Directly delegate to the simulator to avoid recursion
        return self._simulator.simulate(scenario_create)

    _det_sim = staticmethod(lambda sc: _det_analysis(sc))


def _det_analysis(scenario: CounterfactualScenarioCreate) -> CounterfactualScenarioResult:
    """Perform deterministic analysis using Phase 07 tactical state representations.

    11B real implementation. Reuses TacticalFrameState / TacticalSequence.
    Counts players per team, returns structural comparison result.
    No ML, no probabilities, no fabricated football conclusions.
    """
    engine = _DeterministicEngine()

    # Construct synthetic baseline from formation spec
    parts = scenario.baseline_formation.split("-")
    h = int(parts[0]) if len(parts) > 0 else 0
    a = int(parts[1]) if len(parts) > 1 else 0
    total = h + a

    if total == 0 or total > MAX_PLAYERS_PER_FRAME:
        return _DeterministicEngine._unsupported(scenario, "cannot construct baseline")

    # Build synthetic TacticalSequence
    from uuid import UUID
    from app.ai.tactics.state import (
        TacticalSequence as _TacSeq,
        TacticalFrameState as _TacFrm,
        TeamAssociation as _Tat,
        PositionValidity as _Pvl,
        PitchSpace as _Psp,
    )

    match_id = scenario.match_id
    src_id = UUID(int=1)

    home_p = []
    for i in range(h):
        home_p.append(
            TacticalPlayerState(
                track_id=f"det_h_{i}", player_id=UUID(int=1000 + i),
                identity_verified=True, team=_Tat.HOME, object_class='PLAYER',
                pitch_x=float(i * 0.1) if i < 5 else None, pitch_y=0.5 if i < 5 else None,
                validity=_Pvl.VALID, object_confidence=0.8,
                frame_index=0, timestamp_seconds=0.0,
                match_id=match_id, source_id=src_id,
                velocity=None, mapping_point_type=None,
                coordinate_space=_Psp.NORMALIZED,
                calibration_id="det-cal", detector_name="det-det", tracker_name="det-trk",
            )
        )

    away_p = []
    for i in range(a):
        away_p.append(
            TacticalPlayerState(
                track_id=f"det_a_{i}", player_id=UUID(int=2000 + i),
                identity_verified=True, team=_Tat.AWAY, object_class='PLAYER',
                pitch_x=float(i * 0.1) if i < 5 else None, pitch_y=0.5 if i < 5 else None,
                validity=_Pvl.VALID, object_confidence=0.8,
                frame_index=0, timestamp_seconds=0.0,
                match_id=match_id, source_id=src_id,
                velocity=None, mapping_point_type=None,
                coordinate_space=_Psp.NORMALIZED,
                calibration_id="det-cal", detector_name="det-det", tracker_name="det-trk",
            )
        )

    all_p = home_p + away_p
    ball = None
    if total >= 4:
        ball = TacticalBallState(
            track_id="det_ball", object_class='BALL', pitch_x=0.5, pitch_y=0.5,
            validity=_Pvl.VALID, object_confidence=0.9,
            frame_index=0, timestamp_seconds=0.0,
            match_id=match_id, source_id=src_id,
            velocity=None, mapping_point_type=None,
            coordinate_space=_Psp.NORMALIZED,
            calibration_id="det-cal", detector_name="det-det", tracker_name="det-trk",
        )

    frm = _TacFrm(
        match_id=match_id, source_id=src_id, frame_index=0,
        timestamp_seconds=0.0, players=all_p, ball=ball,
        coordinate_space=_Psp.NORMALIZED, calibration_id="det-cal",
    )
    baseline = _TacSeq(frames=[frm])

    return engine.analyze(baseline, scenario)