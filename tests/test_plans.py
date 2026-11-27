from math import comb

import pytest

from f1_strategy.simulation.plans import (
    EventRules,
    IllegalPlanError,
    Plan,
    enumerate_plans,
    load_event_rules,
    validate_plan,
)

COMPOUNDS = ("C1", "C2", "C3")


def rules(**overrides):
    kwargs = {
        "race_laps": 20,
        "compounds": COMPOUNDS,
        "stop_counts": (1, 2),
        "min_distinct_dry_compounds": 2,
    }
    return EventRules(**(kwargs | overrides))


def test_plan_structure_and_id():
    plan = Plan(("C3", "C2", "C2"), (5, 12), (2, 0, 0))
    assert plan.starting_compound == "C3"
    assert plan.n_stops == 2
    assert plan.id == "C3[2]-C2[0]-C2[0]@5,12"
    stints = plan.stints(20)
    assert [(s.first_lap, s.last_lap, s.first_age, s.last_age) for s in stints] == [
        (1, 5, 3, 7),
        (6, 12, 1, 7),
        (13, 20, 1, 8),
    ]
    assert Plan(("C3", "C2"), (5,)).initial_ages == (0, 0)


def test_plan_id_distinguishes_initial_ages():
    assert Plan(("C3", "C2"), (5,)).id != Plan(("C3", "C2"), (5,), (3, 0)).id


@pytest.mark.parametrize(
    "compounds, pit_laps, initial_ages",
    [
        (("C3", "C2"), (5, 9), None),  # stint count mismatch
        (("C3", "C2"), (5,), (0,)),  # initial-age count mismatch
        (("C3", "C2"), (5,), (-1, 0)),  # negative initial age
    ],
)
def test_malformed_plan_raises(compounds, pit_laps, initial_ages):
    with pytest.raises(IllegalPlanError):
        Plan(compounds, pit_laps, initial_ages)


@pytest.mark.parametrize(
    "plan, r",
    [
        (Plan(("C3", "C2"), (0,)), rules()),  # pit before lap 1
        (Plan(("C3", "C2"), (20,)), rules()),  # pit on the final lap
        (Plan(("C3", "C2", "C1"), (9, 9)), rules()),  # zero-length stint
        (Plan(("C3", "C2", "C1"), (9, 5)), rules()),  # decreasing pit laps
        (Plan(("C3", "C3"), (10,)), rules()),  # too few distinct compounds
        (Plan(("C3", "C4"), (10,)), rules()),  # compound not nominated
        (Plan(("C3", "C2", "C1", "C1"), (5, 10, 15)), rules()),  # stop count not allowed
        (Plan(("C3", "C2"), (10,)), rules(min_pit_stops=2)),
        (Plan(("C3", "C2"), (12,)), rules(max_stint_laps=11)),  # first stint 12 laps
        (Plan(("C3", "C2"), (8,), (4, 0)), rules(max_set_age_laps=11)),  # first set age 12
    ],
)
def test_illegal_plans_rejected(plan, r):
    with pytest.raises(IllegalPlanError):
        validate_plan(plan, r)


def test_limits_at_boundary_are_legal():
    validate_plan(Plan(("C3", "C2"), (11,)), rules(max_stint_laps=11))
    validate_plan(Plan(("C3", "C2"), (7,), (4, 0)), rules(race_laps=14, max_set_age_laps=11))
    validate_plan(Plan(("C3", "C2"), (1,)), rules())
    validate_plan(Plan(("C3", "C2", "C1"), (1, 2)), rules())


@pytest.mark.parametrize("n", [2, 3, 20, 57])
def test_enumeration_count_matches_combinatorics(n):
    plans = enumerate_plans(rules(race_laps=n))
    one = 3 * 2 * (n - 1)  # ordered pairs of distinct compounds
    two = (27 - 3) * comb(n - 1, 2)  # sequences with >= 2 distinct compounds
    assert len(plans) == one + two
    assert len({p.id for p in plans}) == len(plans)


def test_enumeration_is_deterministic_and_legal():
    r = rules(min_pit_stops=2, max_stint_laps=9)
    plans = enumerate_plans(r)
    assert plans == enumerate_plans(r)
    assert plans and all(p.n_stops == 2 for p in plans)
    for p in plans:
        validate_plan(p, r)


def test_enumeration_matches_brute_force_filter():
    r = rules(race_laps=12, max_set_age_laps=6)
    plans = enumerate_plans(r, start_tyre_age=2)
    expected = enumerate_plans(rules(race_laps=12), start_tyre_age=2)
    expected = [p for p in expected if all(s.last_age <= 6 for s in p.stints(12))]
    assert plans == expected
    assert all(p.initial_ages[0] == 2 and set(p.initial_ages[1:]) == {0} for p in plans)


def test_no_legal_plan_returns_empty():
    assert enumerate_plans(rules(min_pit_stops=3)) == []


def test_load_event_rules_defaults():
    r = load_event_rules(race_laps=57, compounds=COMPOUNDS)
    assert r.min_distinct_dry_compounds == 2
    assert r.stop_counts == (1, 2)
    assert r.min_pit_stops is r.max_stint_laps is r.max_set_age_laps is None


def test_load_event_rules_override(tmp_path):
    (tmp_path / "events").mkdir()
    (tmp_path / "events" / "default.toml").write_text(
        "[tyre_rules]\nmin_distinct_dry_compounds = 2\n"
    )
    (tmp_path / "events" / "2023_qatar.toml").write_text("[tyre_rules]\nmax_set_age_laps = 18\n")
    (tmp_path / "model.toml").write_text("[plans]\nstop_counts = [1, 2]\n")
    r = load_event_rules(57, COMPOUNDS, event="2023_qatar", config_dir=tmp_path)
    assert (r.max_set_age_laps, r.max_stint_laps) == (18, None)

    (tmp_path / "events" / "bad.toml").write_text("[tyre_rules]\nmax_laps = 18\n")
    with pytest.raises(ValueError, match="unknown"):
        load_event_rules(57, COMPOUNDS, event="bad", config_dir=tmp_path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"race_laps": 1},
        {"compounds": ("C3", "C3")},
        {"compounds": ("C3", "X9")},
        {"stop_counts": (0, 1)},
        {"max_stint_laps": 0},
    ],
)
def test_invalid_event_rules_raise(overrides):
    with pytest.raises(ValueError):
        rules(**overrides)
