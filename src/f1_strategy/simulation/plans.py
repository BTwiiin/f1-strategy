"""Strategy plans, event rules, legality and exhaustive enumeration.

Conventions (docs/scope.md, Strategy representation):

- Tyre age of a lap = laps on the set including that lap; a new set's first lap has age 1,
  and a set with initial age ``k`` starts its stint at age ``k + 1``.
- A pit lap is the in-lap number; the next stint starts on the following lap (its out-lap).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations, product
from pathlib import Path

from f1_strategy import config
from f1_strategy.parameters import check_compounds

# Optional event-rule keys (config/events/*.toml, [tyre_rules]).
_RULE_KEYS = ("min_distinct_dry_compounds", "min_pit_stops", "max_stint_laps", "max_set_age_laps")


class IllegalPlanError(ValueError):
    """A plan is malformed or violates the event rules."""


@dataclass(frozen=True, slots=True)
class Stint:
    compound: str
    first_lap: int
    last_lap: int
    first_age: int
    last_age: int

    @property
    def n_laps(self) -> int:
        return self.last_lap - self.first_lap + 1


@dataclass(frozen=True, slots=True)
class Plan:
    """Ordered compounds (``compounds[0]`` is the starting compound), pit laps and initial
    tyre age per stint (laps already on the set; 0 = new set)."""

    compounds: tuple[str, ...]
    pit_laps: tuple[int, ...]
    initial_ages: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        compounds, pit_laps = tuple(self.compounds), tuple(self.pit_laps)
        ages = (0,) * len(compounds) if self.initial_ages is None else tuple(self.initial_ages)
        if len(compounds) != len(pit_laps) + 1:
            raise IllegalPlanError("a plan needs exactly one more stint than pit stops")
        if len(ages) != len(compounds):
            raise IllegalPlanError("initial_ages needs one entry per stint")
        if any(not isinstance(a, int) or a < 0 for a in ages):
            raise IllegalPlanError("initial tyre ages must be non-negative integers")
        object.__setattr__(self, "compounds", compounds)
        object.__setattr__(self, "pit_laps", pit_laps)
        object.__setattr__(self, "initial_ages", ages)

    @property
    def starting_compound(self) -> str:
        return self.compounds[0]

    @property
    def n_stops(self) -> int:
        return len(self.pit_laps)

    @property
    def id(self) -> str:
        """Unique, deterministic identifier, e.g. ``C3[0]-C2[0]@20``."""
        stints = "-".join(
            f"{c}[{a}]" for c, a in zip(self.compounds, self.initial_ages, strict=True)
        )
        return f"{stints}@{','.join(map(str, self.pit_laps))}"

    def stints(self, race_laps: int) -> tuple[Stint, ...]:
        starts = (1, *(p + 1 for p in self.pit_laps))
        ends = (*self.pit_laps, race_laps)
        return tuple(
            Stint(c, s, e, a + 1, a + e - s + 1)
            for c, s, e, a in zip(self.compounds, starts, ends, self.initial_ages, strict=True)
        )


@dataclass(frozen=True)
class EventRules:
    """Rules for one event. ``compounds`` are the nominated absolute compounds.

    ``max_stint_laps`` limits the laps of one stint; ``max_set_age_laps`` limits the tyre
    age of a set including laps before the stint. They are distinct rules.
    """

    race_laps: int
    compounds: tuple[str, ...]
    stop_counts: tuple[int, ...]
    min_distinct_dry_compounds: int
    min_pit_stops: int | None = None
    max_stint_laps: int | None = None
    max_set_age_laps: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "compounds", tuple(self.compounds))
        object.__setattr__(self, "stop_counts", tuple(self.stop_counts))
        check_compounds(self.compounds)
        if not (isinstance(self.race_laps, int) and self.race_laps >= 2):
            raise ValueError("race_laps must be an integer >= 2")
        if not self.stop_counts or any(n < 1 for n in self.stop_counts):
            raise ValueError("stop_counts must be positive")
        for key in ("min_distinct_dry_compounds", *_RULE_KEYS[1:]):
            v = getattr(self, key)
            if v is not None and not (isinstance(v, int) and v >= 1):
                raise ValueError(f"{key} must be a positive integer")


def load_event_rules(
    race_laps: int,
    compounds: Sequence[str],
    event: str | None = None,
    config_dir: Path = config.CONFIG_DIR,
) -> EventRules:
    """Season defaults from ``events/default.toml``, overridden by ``events/<event>.toml``."""
    rules = dict(config.load("events/default", config_dir)["tyre_rules"])
    if event is not None:
        rules |= config.load(f"events/{event}", config_dir)["tyre_rules"]
    unknown = set(rules) - set(_RULE_KEYS)
    if unknown:
        raise ValueError(f"unknown event rule keys: {sorted(unknown)}")
    stop_counts = config.load("model", config_dir)["plans"]["stop_counts"]
    return EventRules(
        race_laps=race_laps, compounds=tuple(compounds), stop_counts=stop_counts, **rules
    )


def _violation(plan: Plan, rules: EventRules) -> str | None:
    if plan.n_stops not in rules.stop_counts:
        return f"{plan.n_stops} stops not in allowed stop counts {rules.stop_counts}"
    laps = (0, *plan.pit_laps, rules.race_laps)
    if any(b <= a for a, b in zip(laps, laps[1:], strict=False)):
        last = rules.race_laps - 1
        return f"pit laps {plan.pit_laps} must be strictly increasing within [1, {last}]"
    if not set(plan.compounds) <= set(rules.compounds):
        return f"compounds {plan.compounds} not all nominated {rules.compounds}"
    if len(set(plan.compounds)) < rules.min_distinct_dry_compounds:
        return f"fewer than {rules.min_distinct_dry_compounds} distinct compounds"
    if rules.min_pit_stops is not None and plan.n_stops < rules.min_pit_stops:
        return f"fewer than {rules.min_pit_stops} pit stops"
    for s in plan.stints(rules.race_laps):
        if rules.max_stint_laps is not None and s.n_laps > rules.max_stint_laps:
            return f"stint of {s.n_laps} laps exceeds max_stint_laps {rules.max_stint_laps}"
        if rules.max_set_age_laps is not None and s.last_age > rules.max_set_age_laps:
            return f"set age {s.last_age} exceeds max_set_age_laps {rules.max_set_age_laps}"
    return None


def validate_plan(plan: Plan, rules: EventRules) -> None:
    """Raise ``IllegalPlanError`` if ``plan`` violates ``rules``."""
    reason = _violation(plan, rules)
    if reason is not None:
        raise IllegalPlanError(f"{plan.id}: {reason}")


def enumerate_plans(rules: EventRules, start_tyre_age: int = 0) -> list[Plan]:
    """Every legal plan in deterministic order. Only the starting set may be used
    (``start_tyre_age``); later stints start on new sets (inventory is out of scope)."""
    compounds = sorted(rules.compounds)
    plans = []
    for n in sorted(rules.stop_counts):
        ages = (start_tyre_age, *(0,) * n)
        for seq in product(compounds, repeat=n + 1):
            if len(set(seq)) < rules.min_distinct_dry_compounds:
                continue
            for pits in combinations(range(1, rules.race_laps), n):
                plan = Plan(seq, pits, ages)
                if _violation(plan, rules) is None:
                    plans.append(plan)
    return plans
