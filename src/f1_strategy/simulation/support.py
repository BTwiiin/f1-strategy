"""Data-support labels for plans (docs/evaluation.md, Data support).

Support profiles are counts from the training data of a prediction; building them from
lap tables is part of the data pipeline, not of this module.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from f1_strategy.simulation.plans import EventRules, Plan, validate_plan

SUPPORTED = "supported"
EXTRAPOLATED = "extrapolated"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SupportThresholds:
    min_stints_per_age: int  # S
    min_races_per_age: int  # R
    min_circuit_races: int  # R_c
    extrapolation_margin_laps: int  # E

    @classmethod
    def from_config(cls, model: Mapping[str, Any]) -> SupportThresholds:
        """Provisional model thresholds from ``model.toml`` ``[support]``."""
        return cls(**model["support"])


@dataclass(frozen=True)
class SupportProfile:
    """Per compound, distinct stints and distinct races with clean laps at each tyre age
    (index ``age - 1``; ages beyond a sequence count as zero), pooled over circuits; and
    the number of races with clean laps at the evaluated circuit."""

    reference_age: int
    stints: Mapping[str, Sequence[int]]
    races: Mapping[str, Sequence[int]]
    circuit_races: int

    def __post_init__(self) -> None:
        if not (isinstance(self.reference_age, int) and self.reference_age >= 1):
            raise ValueError("reference_age must be a positive integer")
        if set(self.stints) != set(self.races):
            raise ValueError("stints and races must cover the same compounds")
        for c in self.stints:
            s, r = self.stints[c], self.races[c]
            if len(s) != len(r) or any(x < 0 for x in (*s, *r)):
                raise ValueError(f"{c}: counts must be non-negative and of equal length")
            if any(ri > si for si, ri in zip(s, r, strict=True)):
                raise ValueError(f"{c}: distinct races cannot exceed distinct stints")
        if self.circuit_races < 0:
            raise ValueError("circuit_races must be non-negative")


def _shape_supported(
    profile: SupportProfile, compound: str, age: int, th: SupportThresholds
) -> bool:
    s, r = profile.stints[compound], profile.races[compound]
    i = age - 1
    return i < len(s) and s[i] >= th.min_stints_per_age and r[i] >= th.min_races_per_age


def a_max(profile: SupportProfile, compound: str, th: SupportThresholds) -> int | None:
    """Longest contiguous supported tyre age from the reference age upward; ``None`` when
    the compound has no usable data (the reference age itself is unsupported)."""
    if compound not in profile.stints:
        return None
    age = profile.reference_age
    if not _shape_supported(profile, compound, age, th):
        return None
    while _shape_supported(profile, compound, age + 1, th):
        age += 1
    return age


def label_plan(
    plan: Plan, rules: EventRules, profile: SupportProfile, th: SupportThresholds
) -> str:
    """``supported``, ``extrapolated`` or ``unsupported``.

    Ages below the reference age are covered by the reference-age anchor, so only each
    stint's last tyre age is compared with ``A_max`` of its compound.
    """
    validate_plan(plan, rules)
    label = SUPPORTED if profile.circuit_races >= th.min_circuit_races else EXTRAPOLATED
    for s in plan.stints(rules.race_laps):
        limit = a_max(profile, s.compound, th)
        if limit is None or s.last_age > limit + th.extrapolation_margin_laps:
            return UNSUPPORTED
        if s.last_age > limit:
            label = EXTRAPOLATED
    return label
