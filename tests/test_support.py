import pytest

from f1_strategy import config
from f1_strategy.simulation.plans import EventRules, Plan
from f1_strategy.simulation.support import (
    EXTRAPOLATED,
    SUPPORTED,
    UNSUPPORTED,
    SupportProfile,
    SupportThresholds,
    a_max,
    label_plan,
)

TH = SupportThresholds(
    min_stints_per_age=10, min_races_per_age=3, min_circuit_races=1, extrapolation_margin_laps=3
)
RULES = EventRules(
    race_laps=40, compounds=("C2", "C3"), stop_counts=(1, 2), min_distinct_dry_compounds=2
)


def profile(stints, races, ref=2, circuit_races=1):
    """Same counts for C2 and C3; index = tyre age - 1."""
    return SupportProfile(
        reference_age=ref,
        stints={"C2": stints, "C3": stints},
        races={"C2": races, "C3": races},
        circuit_races=circuit_races,
    )


def ok_ages(n):
    return [10] * n, [3] * n


def test_thresholds_from_config():
    th = SupportThresholds.from_config(config.load("model"))
    assert th == TH


def test_a_max_contiguous_from_reference():
    s, r = ok_ages(30)
    s[19] = 9  # age 20 below S: a gap above the reference
    s[25] = r[25] = 0
    assert a_max(profile(s, r), "C2", TH) == 19


def test_gap_below_reference_is_not_a_gap():
    s, r = ok_ages(30)
    s[0] = r[0] = 0  # age 1 (below reference age 2) unsupported
    assert a_max(profile(s, r), "C2", TH) == 30


@pytest.mark.parametrize("ref", [2, 3])
def test_reference_age_unsupported_means_no_usable_data(ref):
    s, r = ok_ages(30)
    r[ref - 1] = 2  # below R at the reference age
    p = profile(s, r, ref=ref)
    assert a_max(p, "C2", TH) is None
    assert label_plan(Plan(("C3", "C2"), (2,)), RULES, p, TH) == UNSUPPORTED


def test_thresholds_inclusive():
    s, r = ok_ages(30)
    s[24], r[27] = 9, 2  # age 25 one below S; age 28 one below R
    assert a_max(profile(s, r), "C2", TH) == 24
    s[24] = 10
    assert a_max(profile(s, r), "C2", TH) == 27


def test_compound_absent_from_profile():
    s, r = ok_ages(30)
    p = SupportProfile(reference_age=2, stints={"C3": s}, races={"C3": r}, circuit_races=1)
    assert a_max(p, "C2", TH) is None
    assert label_plan(Plan(("C3", "C2"), (20,)), RULES, p, TH) == UNSUPPORTED


# A_max = 20 for both compounds; E = 3. Labels depend on the longest stint's last age.
@pytest.mark.parametrize(
    "pit_lap, initial_age, label",
    [
        (20, 0, SUPPORTED),  # stints 20/20: last age = A_max
        (21, 0, EXTRAPOLATED),  # 21 = A_max + 1
        (23, 0, EXTRAPOLATED),  # 23 = A_max + E
        (24, 0, UNSUPPORTED),  # 24 = A_max + E + 1
        (17, 3, SUPPORTED),  # 37-lap race, used starting set: ages 4..20, then 20 new laps
    ],
)
def test_labels_at_boundaries(pit_lap, initial_age, label):
    s, r = ok_ages(20)  # ages beyond the arrays count as zero
    rules = (
        RULES
        if initial_age == 0
        else EventRules(
            race_laps=37, compounds=("C2", "C3"), stop_counts=(1, 2), min_distinct_dry_compounds=2
        )
    )
    plan = Plan(("C3", "C2"), (pit_lap,), (initial_age, 0))
    assert label_plan(plan, rules, profile(s, r), TH) == label


def test_initial_age_shifts_ages():
    s, r = ok_ages(20)
    # 18 laps on a set with 3 prior laps reach age 21: extrapolated.
    plan = Plan(("C3", "C2"), (18,), (3, 0))
    assert label_plan(plan, RULES, profile(s, r), TH) == EXTRAPOLATED


def test_circuit_support():
    s, r = ok_ages(40)
    plan = Plan(("C3", "C2"), (20,))
    assert label_plan(plan, RULES, profile(s, r, circuit_races=1), TH) == SUPPORTED
    assert label_plan(plan, RULES, profile(s, r, circuit_races=0), TH) == EXTRAPOLATED


def test_invalid_profile_raises():
    with pytest.raises(ValueError):
        SupportProfile(reference_age=2, stints={"C2": [3]}, races={"C2": [4]}, circuit_races=1)
    with pytest.raises(ValueError):
        SupportProfile(reference_age=2, stints={"C2": [3]}, races={"C3": [1]}, circuit_races=1)
    with pytest.raises(ValueError):
        SupportProfile(reference_age=0, stints={"C2": [3]}, races={"C2": [1]}, circuit_races=1)
