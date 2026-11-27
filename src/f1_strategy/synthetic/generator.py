"""Synthetic lap-time generator with known parameters (E1 ground truth).

Lap time of a driver-race on lap ``l`` at tyre age ``a`` on compound ``c``::

    base + driver_race_offset + pace[c] + tyre_effect(c, a) - common_trend_gain * (l - 1)
    + noise + pit increments

``tyre_effect`` is zero at the reference age. The incremental pit loss of a stop is split
between its in-lap and out-lap, on top of their normal lap time (a lap that is both the
out-lap of one stop and the in-lap of the next carries both shares). Drivers follow a pit
policy that ends every stint at or before a per-compound censoring age, so ages above it
are never observed (right-censoring).

Variants:

- ``correct``: linear degradation, representable by a ``ParameterSet``.
- ``cliff``: extra ``cliff_slope * (a - cliff_age + 1)`` from ``cliff_age`` on. Hidden when
  every censoring age is below the cliff age, observable otherwise.
- ``tyre_management``: on stints longer than ``management_threshold_laps``, the driver
  trades ``management_pace_cost`` s/lap for degradation scaled by ``management_deg_factor``.
  The effect depends on the plan, so it is not representable by a ``ParameterSet``;
  ``truth`` then holds the base (unmanaged) parameters.
"""

from dataclasses import dataclass, field
from itertools import product

import numpy as np

from f1_strategy.parameters import PIT_LOSS_KEY, ParameterSet, check_compounds
from f1_strategy.simulation.plans import EventRules, Plan, load_event_rules, validate_plan

VARIANTS = ("correct", "cliff", "tyre_management")


@dataclass(frozen=True)
class SyntheticConfig:
    seed: int = 0
    n_races: int = 8
    n_drivers: int = 20
    race_laps: int = 57
    compounds: tuple[str, ...] = ("C1", "C2", "C3")
    pace_offset: tuple[float, ...] = (0.6, 0.3, 0.0)  # s/lap at the reference age
    degradation: tuple[float, ...] = (0.03, 0.05, 0.08)  # s/lap per lap of tyre age
    reference_age: int = 2
    fuel_gain: float = 0.055  # s/lap
    track_evolution_gain: float = 0.01  # s/lap
    base_lap_time: float = 90.0
    driver_race_sd: float = 0.3
    noise_sd: float = 0.15
    pit_loss: float = 21.0  # incremental s per stop
    in_lap_share: float = 0.4  # share of the pit loss on the in-lap; the rest on the out-lap
    censoring_age: tuple[int, ...] = (40, 32, 25)  # longest set age the pit policy allows
    variant: str = "correct"
    cliff_age: tuple[int, ...] | None = None
    cliff_slope: float = 0.5
    management_threshold_laps: int = 25
    management_pace_cost: float = 0.2
    management_deg_factor: float = 0.5

    def __post_init__(self) -> None:
        check_compounds(self.compounds)
        n = len(self.compounds)
        for name in ("pace_offset", "degradation", "censoring_age"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name} needs one value per compound")
        if self.variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}")
        if (self.variant == "cliff") != (self.cliff_age is not None):
            raise ValueError("cliff_age is required for, and only for, the cliff variant")
        if self.cliff_age is not None and (
            len(self.cliff_age) != n or min(self.cliff_age) <= self.reference_age
        ):
            raise ValueError("cliff_age needs one value per compound, above the reference age")
        if min(self.n_races, self.n_drivers, self.reference_age, *self.censoring_age) < 1:
            raise ValueError("counts, reference age and censoring ages must be positive")
        if not 0 <= self.in_lap_share <= 1:
            raise ValueError("in_lap_share must be in [0, 1]")
        if min(self.driver_race_sd, self.noise_sd) < 0:
            raise ValueError("standard deviations must be non-negative")

    @property
    def common_trend_gain(self) -> float:
        return self.fuel_gain + self.track_evolution_gain


@dataclass(frozen=True)
class SyntheticRaceData:
    """One row per driver and lap (column arrays), the plan of every driver-race and the
    true parameters."""

    race_id: np.ndarray
    driver_id: np.ndarray
    lap: np.ndarray
    stint_id: np.ndarray  # unique across the data set
    compound: np.ndarray
    tyre_age: np.ndarray
    is_in_lap: np.ndarray
    is_out_lap: np.ndarray
    lap_time: np.ndarray
    plans: dict[tuple[int, int], Plan] = field(repr=False)
    truth: ParameterSet = field(repr=False)


def tyre_effect(cfg: SyntheticConfig, max_age: int) -> np.ndarray:
    """(C, max_age) per-lap effect by tyre age (index ``age - 1``) without tyre management."""
    ages = np.arange(1, max_age + 1)
    effect = np.asarray(cfg.degradation)[:, None] * (ages - cfg.reference_age)
    if cfg.variant == "cliff":
        cliff = np.asarray(cfg.cliff_age)[:, None]
        effect = effect + cfg.cliff_slope * np.maximum(0, ages - cliff + 1)
    return effect


def truth(cfg: SyntheticConfig) -> ParameterSet:
    """True parameters as a single-sample ``ParameterSet`` (scenario = true trend)."""
    return ParameterSet(
        compounds=cfg.compounds,
        reference_age=cfg.reference_age,
        pace_offset=np.asarray(cfg.pace_offset, dtype=float)[None, :],
        age_effect=tyre_effect(cfg, cfg.race_laps)[None, :, :],
        pit_loss=np.array([cfg.pit_loss]),
        sample_ids=np.array([0]),
        scenario=cfg.common_trend_gain,
        fallback_level={**dict.fromkeys(cfg.compounds, "circuit"), PIT_LOSS_KEY: "circuit"},
        provenance=f"synthetic:variant={cfg.variant},seed={cfg.seed}",
    )


def plan_laps(cfg: SyntheticConfig, plan: Plan, race_laps: int) -> dict[str, np.ndarray]:
    """Noise-free lap times of one plan (base time and driver offset excluded) with the
    compound, tyre age, stint index and pit flags of every lap."""
    effect = tyre_effect(cfg, max(s.last_age for s in plan.stints(race_laps)))
    lap = np.arange(1, race_laps + 1)
    compound, age, stint_idx = [], [], []
    tyre = np.empty(race_laps)
    for k, s in enumerate(plan.stints(race_laps)):
        i = cfg.compounds.index(s.compound)
        ages = np.arange(s.first_age, s.last_age + 1)
        t = cfg.pace_offset[i] + effect[i, ages - 1]
        if cfg.variant == "tyre_management" and s.n_laps > cfg.management_threshold_laps:
            t = (
                cfg.pace_offset[i]
                + cfg.management_pace_cost
                + cfg.management_deg_factor * (effect[i, ages - 1])
            )
        tyre[s.first_lap - 1 : s.last_lap] = t
        compound += [s.compound] * s.n_laps
        age.append(ages)
        stint_idx += [k] * s.n_laps
    in_lap = np.isin(lap, plan.pit_laps)
    out_lap = np.isin(lap, np.asarray(plan.pit_laps) + 1)
    pit = cfg.pit_loss * (cfg.in_lap_share * in_lap + (1 - cfg.in_lap_share) * out_lap)
    return {
        "lap": lap,
        "compound": np.array(compound),
        "tyre_age": np.concatenate(age),
        "stint": np.array(stint_idx),
        "is_in_lap": in_lap,
        "is_out_lap": out_lap,
        "lap_time": tyre - cfg.common_trend_gain * (lap - 1) + pit,
    }


def _feasible_sequences(
    cfg: SyntheticConfig, rules: EventRules
) -> tuple[list[tuple[str, ...]], dict[str, int]]:
    caps = dict(zip(cfg.compounds, cfg.censoring_age, strict=True))
    for limit in (rules.max_stint_laps, rules.max_set_age_laps):  # new sets: equal here
        if limit is not None:
            caps = {c: min(v, limit) for c, v in caps.items()}
    stop_counts = [n for n in rules.stop_counts if n >= (rules.min_pit_stops or 0)]
    return [
        seq
        for n in sorted(stop_counts)
        for seq in product(cfg.compounds, repeat=n + 1)
        if len(set(seq)) >= rules.min_distinct_dry_compounds
        and len(seq) <= rules.race_laps <= sum(caps[c] for c in seq)
    ], caps


def _sample_plan(rng: np.random.Generator, seqs, caps, race_laps: int) -> Plan:
    """Random feasible plan: stint lengths drawn sequentially within the censoring caps."""
    seq = seqs[rng.integers(len(seqs))]
    remaining, lengths = race_laps, []
    for k, c in enumerate(seq[:-1]):
        later = seq[k + 1 :]
        lo = max(1, remaining - sum(caps[x] for x in later))
        hi = min(caps[c], remaining - len(later))
        lengths.append(int(rng.integers(lo, hi + 1)))
        remaining -= lengths[-1]
    return Plan(seq, tuple(np.cumsum(lengths).tolist()))


def generate_laps(cfg: SyntheticConfig, rules: EventRules | None = None) -> SyntheticRaceData:
    """Generate laps for ``n_races`` races of ``n_drivers`` drivers. Deterministic in
    ``cfg.seed``; plans are drawn before offsets and noise, so variants with the same seed
    share plans, offsets and noise."""
    if rules is None:
        rules = load_event_rules(cfg.race_laps, cfg.compounds)
    if rules.race_laps != cfg.race_laps or not set(cfg.compounds) <= set(rules.compounds):
        raise ValueError("event rules must match the configured race distance and compounds")
    seqs, caps = _feasible_sequences(cfg, rules)
    if not seqs:
        raise ValueError(
            f"no legal plan can cover {cfg.race_laps} laps within censoring ages "
            f"{dict(zip(cfg.compounds, cfg.censoring_age, strict=True))} and the event rules"
        )
    rng = np.random.default_rng(cfg.seed)
    keys = [(r, d) for r in range(cfg.n_races) for d in range(cfg.n_drivers)]
    plans = {k: _sample_plan(rng, seqs, caps, cfg.race_laps) for k in keys}
    offsets = rng.normal(0.0, cfg.driver_race_sd, len(keys))

    cols: dict[str, list[np.ndarray]] = {}
    n_stints = 0
    for (race, driver), offset in zip(keys, offsets, strict=True):
        plan = plans[race, driver]
        validate_plan(plan, rules)
        laps = plan_laps(cfg, plan, cfg.race_laps)
        laps["lap_time"] = laps["lap_time"] + cfg.base_lap_time + offset
        laps["stint_id"] = laps.pop("stint") + n_stints
        laps["race_id"] = np.full(cfg.race_laps, race)
        laps["driver_id"] = np.full(cfg.race_laps, driver)
        n_stints += len(plan.compounds)
        for k, v in laps.items():
            cols.setdefault(k, []).append(v)
    data = {k: np.concatenate(v) for k, v in cols.items()}
    data["lap_time"] = data["lap_time"] + rng.normal(0.0, cfg.noise_sd, len(data["lap_time"]))
    return SyntheticRaceData(**data, plans=plans, truth=truth(cfg))
