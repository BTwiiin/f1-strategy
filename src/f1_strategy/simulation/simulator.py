"""Deterministic single-car simulator.

``relative_plan_time = compound_effect + tyre_age_effect + pit_losses`` (docs/scope.md).
Compound and tyre-age effects apply to every race lap, including in- and out-laps; each
stop adds the incremental pit loss exactly once. The common trend is shared by all plans
and never enters this sum; it reaches the simulator only through the parameter set's
scenario. Results are vectorised over the parameter set's joint samples.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from f1_strategy.parameters import ParameterSet
from f1_strategy.simulation.plans import EventRules, Plan, Stint, validate_plan


@dataclass(frozen=True)
class StintResult:
    stint: Stint
    compound_effect: np.ndarray  # (B,)
    tyre_age_effect: np.ndarray  # (B,)

    @property
    def compound(self) -> str:
        return self.stint.compound


@dataclass(frozen=True)
class PlanResult:
    plan: Plan
    sample_ids: np.ndarray
    stints: tuple[StintResult, ...]
    pit_losses: np.ndarray  # (B,)

    @property
    def compound_effect(self) -> np.ndarray:
        return sum(s.compound_effect for s in self.stints)

    @property
    def tyre_age_effect(self) -> np.ndarray:
        return sum(s.tyre_age_effect for s in self.stints)

    @property
    def total(self) -> np.ndarray:
        return self.compound_effect + self.tyre_age_effect + self.pit_losses


def _cumulative_age_effect(params: ParameterSet) -> np.ndarray:
    """(B, C, A + 1): index ``a`` holds the summed per-lap effect of ages 1..a."""
    b, c, _ = params.age_effect.shape
    return np.concatenate([np.zeros((b, c, 1)), np.cumsum(params.age_effect, axis=2)], axis=2)


def _simulate(plan: Plan, params: ParameterSet, rules: EventRules, cum: np.ndarray) -> PlanResult:
    validate_plan(plan, rules)
    stints = []
    for s in plan.stints(rules.race_laps):
        i = params.compound_index(s.compound)
        if s.last_age > params.max_age:
            raise ValueError(
                f"{plan.id}: tyre age {s.last_age} exceeds tabulated max age {params.max_age}"
            )
        stints.append(
            StintResult(
                stint=s,
                compound_effect=s.n_laps * params.pace_offset[:, i],
                tyre_age_effect=cum[:, i, s.last_age] - cum[:, i, s.first_age - 1],
            )
        )
    return PlanResult(plan, params.sample_ids, tuple(stints), plan.n_stops * params.pit_loss)


def simulate(plan: Plan, params: ParameterSet, rules: EventRules) -> PlanResult:
    """Relative time of one plan per sample, broken down by stint and factor."""
    return _simulate(plan, params, rules, _cumulative_age_effect(params))


def relative_times(plans: Sequence[Plan], params: ParameterSet, rules: EventRules) -> np.ndarray:
    """(n_plans, B) relative plan times; columns aligned with ``params.sample_ids``."""
    cum = _cumulative_age_effect(params)
    if not plans:
        return np.empty((0, params.n_samples))
    return np.stack([_simulate(p, params, rules, cum).total for p in plans])
