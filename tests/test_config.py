import copy

import pytest

from f1_strategy import config


@pytest.fixture
def evaluation():
    return config.load("evaluation")


@pytest.fixture
def model():
    return config.load("model")


def test_committed_config_is_valid(evaluation, model):
    config.validate(evaluation, model)


def test_event_defaults_load():
    assert config.load("events/default")["tyre_rules"]["min_distinct_dry_compounds"] == 2


def test_common_trend_grid(model):
    ct = model["common_trend"]
    grid = config.common_trend_grid(ct)
    assert grid == [round(0.01 * i, 10) for i in range(12)]  # 0.00 ... 0.11 s/lap
    assert grid[0] <= ct["fuel_gain_min"] - ct["track_evolution_allowance"]
    assert grid[-1] >= ct["fuel_gain_max"] + ct["track_evolution_allowance"]
    assert ct["central_scenario"] in grid


def test_resolution_grid_spans_same_range(model):
    ct = model["common_trend"]
    fine = config.common_trend_grid(ct, ct["dev_resolution_step"])
    assert len(fine) == 23
    assert (fine[0], fine[-1]) == (0.0, 0.11)
    assert set(config.common_trend_grid(ct)) <= set(fine)


def test_grid_rejects_step_not_dividing_range(model):
    with pytest.raises(ValueError, match="does not divide"):
        config.common_trend_grid(model["common_trend"], 0.03)


def test_fixed_m0_values(evaluation, model):
    """Values frozen at M0. A failure here is a contract change, not a routine edit."""
    assert evaluation["splits"] == {
        "burn_in_seasons": [2023],
        "development_seasons": [2024],
        "holdout_seasons": [2025],
    }
    assert evaluation["walk_forward"] == {"window": "expanding", "prediction_cutoff": "race_start"}
    assert evaluation["feasibility_gate"] == {
        "eligibility_min_green_flag_lap_share": 0.80,
        "support_min_stints_per_age": 10,
        "support_min_races_per_age": 3,
        "support_min_circuit_races": 1,
        "scenario": "central",
        "regret_quantile": 0.90,
        "tau_gate_s": 5.0,
        "min_decision_useful_share": 0.50,
        "required_supported_plan_classes": ["one_stop", "two_stop"],
    }
    assert evaluation["decision_rule"]["comparison_set"] == "supported"
    ct = model["common_trend"]
    assert (ct["fuel_gain_min"], ct["fuel_gain_max"], ct["fuel_gain_median"]) == (
        0.029,
        0.082,
        0.056,
    )
    assert ct["central_scenario"] == 0.06


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("splits", "development_seasons", [2024, 2025], "disjoint"),
        ("splits", "burn_in_seasons", [2026], "must follow"),
        ("feasibility_gate", "regret_quantile", 1.0, "regret_quantile"),
        ("decision_rule", "regret_quantile", 0.0, "regret_quantile"),
        ("feasibility_gate", "min_decision_useful_share", 0.0, "min_decision_useful_share"),
        (
            "feasibility_gate",
            "eligibility_min_green_flag_lap_share",
            1.5,
            "eligibility_min_green_flag_lap_share",
        ),
        ("feasibility_gate", "support_min_stints_per_age", 0, "support_min_stints_per_age"),
        ("feasibility_gate", "support_min_races_per_age", 2.5, "support_min_races_per_age"),
    ],
)
def test_validate_rejects_invalid_evaluation(evaluation, model, section, key, value, message):
    bad = copy.deepcopy(evaluation)
    bad[section][key] = value
    with pytest.raises(ValueError, match=message):
        config.validate(bad, model)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("central_scenario", 0.05, "central_scenario"),
        ("fuel_gain_median", 0.09, "fuel_gain_median"),
        ("dev_resolution_step", 0.003, "does not divide"),
    ],
)
def test_validate_rejects_invalid_common_trend(evaluation, model, key, value, message):
    bad = copy.deepcopy(model)
    bad["common_trend"][key] = value
    with pytest.raises(ValueError, match=message):
        config.validate(evaluation, bad)
