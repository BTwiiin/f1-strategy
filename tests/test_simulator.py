import numpy as np
import pytest

from f1_strategy.simulation.plans import EventRules, IllegalPlanError, Plan, enumerate_plans
from f1_strategy.simulation.simulator import relative_times, simulate


def rules(race_laps, compounds=("C2", "C3"), **kw):
    return EventRules(
        race_laps=race_laps,
        compounds=compounds,
        stop_counts=(1, 2),
        min_distinct_dry_compounds=2,
        **kw,
    )


def linear_stint_cost(offset, slope, laps, ref, first_age=1):
    """Closed-form sum over ages first_age..first_age+laps-1 of offset + slope*(age-ref)."""
    last = first_age + laps - 1
    age_sum = (last * (last + 1) - (first_age - 1) * first_age) / 2
    return offset * laps + slope * (age_sum - ref * laps)


def one_stop_vertex(o1, d1, o2, d2, n, ref):
    """Continuous minimiser of the one-stop total over the first stint length L1."""
    return (o2 - o1 + d2 * (n + 0.5 - ref) - d1 * (0.5 - ref)) / (d1 + d2)


@pytest.mark.parametrize("ref", [2, 3])
def test_one_stop_matches_closed_form(linear_params, ref):
    o = {"C2": 0.4, "C3": 0.0}
    d = {"C2": 0.04, "C3": 0.09}
    n = 50
    params = linear_params(o, d, pit_loss=20.0, reference_age=ref)
    plans = [Plan(("C3", "C2"), (k,)) for k in range(1, n)]
    times = relative_times(plans, params, rules(n))[:, 0]
    expected = [
        linear_stint_cost(o["C3"], d["C3"], k, ref)
        + linear_stint_cost(o["C2"], d["C2"], n - k, ref)
        + 20.0
        for k in range(1, n)
    ]
    np.testing.assert_allclose(times, expected, rtol=0, atol=1e-9)

    vertex = one_stop_vertex(o["C3"], d["C3"], o["C2"], d["C2"], n, ref)
    assert abs(vertex % 1 - 0.5) > 0.05  # no tie between two integers
    assert int(np.argmin(times)) + 1 == round(vertex)


def test_recovers_analytic_optimum_over_all_legal_plans(linear_params):
    # A large pit loss makes every two-stop worse than any one-stop, so the global
    # optimum is the best one-stop of the closed-form cost. A used starting set breaks
    # the symmetry between the two compound orderings.
    o = {"C2": 0.3, "C3": 0.0}
    d = {"C2": 0.05, "C3": 0.11}
    n, ref, pit, start_age = 44, 2, 100.0, 4
    params = linear_params(o, d, pit_loss=pit, reference_age=ref)
    r = rules(n)
    plans = enumerate_plans(r, start_tyre_age=start_age)
    best = plans[int(np.argmin(relative_times(plans, params, r)[:, 0]))]

    analytic = sorted(
        [
            (
                linear_stint_cost(o[a], d[a], k, ref, first_age=start_age + 1)
                + linear_stint_cost(o[b], d[b], n - k, ref),
                Plan((a, b), (k,), (start_age, 0)),
            )
            for a, b in (("C3", "C2"), ("C2", "C3"))
            for k in range(1, n)
        ],
        key=lambda t: t[0],
    )
    assert analytic[1][0] - analytic[0][0] > 1e-6  # unique optimum
    assert best == analytic[0][1]


@pytest.mark.parametrize("delta, expected_stops", [(0.01, 1), (-0.01, 2)])
def test_one_vs_two_stop_break_even_pit_loss(linear_params, delta, expected_stops):
    # Identical compounds: the optimum splits the race equally. With n = 30, d = 0.1, ref = 2:
    # one-stop 2*d*S(15) + P, two-stop 3*d*S(10) + 2P, S(L) = L(L+1)/2 - ref*L,
    # break-even P* = 2*0.1*90 - 3*0.1*35 = 7.5 s.
    params = linear_params({"C2": 0.0, "C3": 0.0}, {"C2": 0.1, "C3": 0.1}, pit_loss=7.5 + delta)
    r = rules(30)
    plans = enumerate_plans(r)
    times = relative_times(plans, params, r)[:, 0]
    best = plans[int(np.argmin(times))]
    assert best.n_stops == expected_stops
    assert [s.n_laps for s in best.stints(30)] == [30 // (expected_stops + 1)] * (
        expected_stops + 1
    )


def test_pit_loss_counted_once_per_stop_lap_by_lap(linear_params):
    """Independent lap-by-lap sum with non-zero offsets and degradation."""
    o = {"C1": 0.7, "C2": 0.3, "C3": 0.0}
    d = {"C1": 0.02, "C2": 0.05, "C3": 0.12}
    ref, pit, n = 3, 21.5, 40
    params = linear_params(o, d, pit_loss=pit, reference_age=ref)
    r = rules(n, compounds=("C1", "C2", "C3"))

    plan = Plan(("C3", "C2", "C1"), (9, 10), (2, 0, 0))  # consecutive stops: 1-lap stint
    compound_by_lap = ["C3"] * 9 + ["C2"] + ["C1"] * 30
    age_by_lap = list(range(3, 12)) + [1] + list(range(1, 31))
    expected = sum(
        o[c] + d[c] * (a - ref) for c, a in zip(compound_by_lap, age_by_lap, strict=True)
    )
    expected += 2 * pit

    result = simulate(plan, params, r)
    assert result.total[0] == pytest.approx(expected, abs=1e-9)
    assert result.pit_losses[0] == pytest.approx(2 * pit)
    np.testing.assert_allclose(
        result.compound_effect + result.tyre_age_effect + result.pit_losses, result.total
    )

    zero = linear_params(dict.fromkeys(o, 0.0), dict.fromkeys(d, 0.0), pit_loss=pit)
    assert simulate(plan, zero, r).total[0] == pytest.approx(2 * pit)


def test_breakdown_by_stint(linear_params):
    params = linear_params({"C2": 0.3, "C3": 0.0}, {"C2": 0.05, "C3": 0.1}, pit_loss=20.0)
    plan = Plan(("C3", "C2", "C3"), (10, 30))
    result = simulate(plan, params, rules(50))
    assert [s.compound for s in result.stints] == ["C3", "C2", "C3"]
    first = result.stints[0]
    assert first.compound_effect[0] == pytest.approx(0.0)
    assert first.tyre_age_effect[0] == pytest.approx(linear_stint_cost(0.0, 0.1, 10, 2))
    assert result.stints[1].compound_effect[0] == pytest.approx(0.3 * 20)


def test_vectorised_over_samples_keeps_alignment(linear_params):
    params = linear_params(
        {"C2": [0.3, 0.5, 0.1], "C3": 0.0},
        {"C2": [0.05, 0.02, 0.08], "C3": [0.1, 0.12, 0.09]},
        pit_loss=[19.0, 22.0, 25.0],
    )
    r = rules(50)
    plans = enumerate_plans(r)[:200:7]
    times = relative_times(plans, params, r)
    assert times.shape == (len(plans), 3)
    for b in range(3):
        single = relative_times(plans, params.select([b]), r)
        np.testing.assert_allclose(times[:, b], single[:, 0])
    assert np.array_equal(simulate(plans[0], params, r).sample_ids, params.sample_ids)


def test_rejects_illegal_plan(linear_params):
    params = linear_params({"C2": 0.3, "C3": 0.0}, {"C2": 0.05, "C3": 0.1}, pit_loss=20.0)
    with pytest.raises(IllegalPlanError):
        simulate(Plan(("C3", "C3"), (10,)), params, rules(50))
    with pytest.raises(IllegalPlanError):
        relative_times([Plan(("C3", "C2"), (50,))], params, rules(50))


def test_missing_compound_or_short_table_raises(linear_params):
    params = linear_params(
        {"C2": 0.3, "C3": 0.0}, {"C2": 0.05, "C3": 0.1}, pit_loss=20.0, max_age=30
    )
    r = rules(50, compounds=("C1", "C2", "C3"))
    with pytest.raises(ValueError, match="C1"):
        simulate(Plan(("C1", "C2"), (25,)), params, r)
    with pytest.raises(ValueError, match="age"):
        simulate(Plan(("C3", "C2"), (31,)), params, r)
