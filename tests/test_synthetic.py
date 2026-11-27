from dataclasses import replace

import numpy as np
import pytest

from f1_strategy.simulation.plans import EventRules, Plan, enumerate_plans, validate_plan
from f1_strategy.simulation.simulator import relative_times
from f1_strategy.synthetic.generator import SyntheticConfig, generate_laps, plan_laps, truth

SMALL = SyntheticConfig(n_races=3, n_drivers=6, race_laps=40, censoring_age=(30, 25, 20))
NOISE_FREE = replace(SMALL, noise_sd=0.0, driver_race_sd=0.0)


def rules(cfg):
    return EventRules(
        race_laps=cfg.race_laps,
        compounds=cfg.compounds,
        stop_counts=(1, 2),
        min_distinct_dry_compounds=2,
    )


def test_reproducible_from_seed():
    a, b = generate_laps(SMALL), generate_laps(SMALL)
    np.testing.assert_array_equal(a.lap_time, b.lap_time)
    assert a.plans == b.plans
    assert not np.array_equal(a.lap_time, generate_laps(replace(SMALL, seed=1)).lap_time)


def test_plans_legal_and_censored():
    data = generate_laps(SMALL)
    for plan in data.plans.values():
        validate_plan(plan, rules(SMALL))
    for c, cap in zip(SMALL.compounds, SMALL.censoring_age, strict=True):
        assert data.tyre_age[data.compound == c].max() <= cap
    assert len(np.unique(data.stint_id)) == sum(len(p.compounds) for p in data.plans.values())


def test_noise_free_laps_reproduce_truth():
    cfg = NOISE_FREE
    data = generate_laps(cfg)
    t = truth(cfg)
    idx = np.array([t.compound_index(c) for c in data.compound])
    expected = (
        cfg.base_lap_time
        + t.pace_offset[0, idx]
        + t.age_effect[0, idx, data.tyre_age - 1]
        - cfg.common_trend_gain * (data.lap - 1)
        + cfg.pit_loss
        * (cfg.in_lap_share * data.is_in_lap + (1 - cfg.in_lap_share) * data.is_out_lap)
    )
    np.testing.assert_allclose(data.lap_time, expected, atol=1e-9)


def test_pit_loss_is_incremental_once_per_stop():
    """Non-zero offsets and degradation; consecutive stops share a lap that is both an
    out-lap and an in-lap."""
    plan = Plan(("C3", "C2", "C1"), (12, 13))
    laps = plan_laps(SMALL, plan, 40)
    counterfactual = plan_laps(replace(SMALL, pit_loss=0.0), plan, 40)
    extra = laps["lap_time"] - counterfactual["lap_time"]
    assert laps["is_out_lap"][12] and laps["is_in_lap"][12]  # lap 13
    assert extra[12] == pytest.approx(SMALL.pit_loss)
    assert extra.sum() == pytest.approx(2 * SMALL.pit_loss)
    assert np.count_nonzero(extra) == 3  # laps 12, 13, 14
    assert laps["is_out_lap"].sum() == laps["is_in_lap"].sum() == 2
    assert not laps["is_out_lap"][0]  # the race start is not an out-lap


@pytest.mark.parametrize("variant", ["correct", "cliff"])
def test_trend_cancels_in_plan_deltas(variant):
    cfg = replace(SMALL, variant=variant, cliff_age=(28, 22, 18) if variant == "cliff" else None)
    r = rules(cfg)
    plans = enumerate_plans(r)[::97]
    summed = np.array([plan_laps(cfg, p, cfg.race_laps)["lap_time"].sum() for p in plans])
    simulated = relative_times(plans, truth(cfg), r)[:, 0]
    # The trend adds the same constant to every plan; deltas agree exactly.
    np.testing.assert_allclose(summed - summed[0], simulated - simulated[0], atol=1e-9)
    trend_total = -cfg.common_trend_gain * sum(range(cfg.race_laps))
    np.testing.assert_allclose(summed - simulated, trend_total, atol=1e-9)


def test_cliff_hidden_or_observable():
    hidden = replace(SMALL, variant="cliff", cliff_age=(31, 26, 21))  # above every cap
    observable = replace(SMALL, variant="cliff", cliff_age=(20, 15, 10))
    data = generate_laps(hidden)
    for c, cliff in zip(hidden.compounds, hidden.cliff_age, strict=True):
        assert data.tyre_age[data.compound == c].max() < cliff
    data = generate_laps(observable)
    assert any(
        (data.tyre_age[data.compound == c] >= cliff).any()
        for c, cliff in zip(observable.compounds, observable.cliff_age, strict=True)
    )


def test_variants_differ_only_where_intended():
    base = generate_laps(NOISE_FREE)
    cliff_cfg = replace(NOISE_FREE, variant="cliff", cliff_age=(20, 15, 10))
    cliff = generate_laps(cliff_cfg)
    managed = generate_laps(
        replace(NOISE_FREE, variant="tyre_management", management_threshold_laps=15)
    )
    assert base.plans == cliff.plans == managed.plans

    cliff_at = np.array(
        [dict(zip(cliff_cfg.compounds, cliff_cfg.cliff_age, strict=True))[c] for c in base.compound]
    )
    after_cliff = base.tyre_age >= cliff_at
    assert after_cliff.any()
    np.testing.assert_allclose(cliff.lap_time[~after_cliff], base.lap_time[~after_cliff])
    assert np.all(cliff.lap_time[after_cliff] > base.lap_time[after_cliff])

    stint_len = np.bincount(base.stint_id)[base.stint_id]
    long_stint = stint_len > 15
    assert long_stint.any()
    np.testing.assert_allclose(managed.lap_time[~long_stint], base.lap_time[~long_stint])
    assert not np.allclose(managed.lap_time[long_stint], base.lap_time[long_stint])


@pytest.mark.parametrize(
    "changes",
    [
        {"censoring_age": (5, 5, 5)},  # cannot cover 40 laps with at most two stops
        {"variant": "unknown"},
        {"variant": "cliff"},  # cliff_age missing
        {"cliff_age": (30, 30, 30)},  # cliff_age without the cliff variant
        {"variant": "cliff", "cliff_age": (2, 20, 20)},  # cliff at the reference age
        {"pace_offset": (0.0, 0.1)},
        {"compounds": ("C1", "C1", "C3")},
        {"in_lap_share": 1.5},
    ],
)
def test_impossible_or_invalid_config_raises(changes):
    with pytest.raises(ValueError):
        generate_laps(replace(SMALL, **changes))


def test_rules_mismatch_raises():
    with pytest.raises(ValueError, match="race distance"):
        generate_laps(SMALL, replace(rules(SMALL), race_laps=41))
