from dataclasses import replace

import numpy as np
import pytest

from f1_strategy.simulation.plans import EventRules
from f1_strategy.synthetic.generator import SyntheticConfig, generate_laps
from f1_strategy.synthetic.identifiability import DEFAULT_CONFIG, report, run, structural


@pytest.fixture(scope="module")
def result():
    return run()


def test_free_intercepts_identify_only_the_net_slope(result):
    free = result["free"]
    assert free["rank"] == free["n_columns"] - 1
    rss = [f["rss"] for f in free["fits"].values()]
    assert max(rss) - min(rss) <= 1e-9 * max(rss)
    for g, fit in free["fits"].items():
        np.testing.assert_allclose(fit["degradation"], free["net_slope"] + g, atol=1e-10)
    true_net = np.asarray(DEFAULT_CONFIG.degradation) - DEFAULT_CONFIG.common_trend_gain
    np.testing.assert_allclose(free["net_slope"], true_net, atol=0.002)


def test_structural_assumption_recovers_correct_generator(result):
    s = result["structural_correct"]
    cfg = DEFAULT_CONFIG
    assert s["rank"] == s["n_columns"]
    assert s["trend"] == pytest.approx(cfg.common_trend_gain, abs=0.002)
    np.testing.assert_allclose(s["degradation"], cfg.degradation, atol=0.002)
    true_pace = np.asarray(cfg.pace_offset[1:]) - cfg.pace_offset[0]
    np.testing.assert_allclose(s["pace_offset_vs_first"], true_pace, atol=0.03)


def test_structural_recovery_is_exact_without_noise():
    cfg = replace(DEFAULT_CONFIG, noise_sd=0.0)
    s = structural(generate_laps(cfg), cfg.compounds, cfg.reference_age)
    assert s["trend"] == pytest.approx(cfg.common_trend_gain, abs=1e-8)
    np.testing.assert_allclose(s["degradation"], cfg.degradation, atol=1e-8)


def test_structural_assumption_biased_under_tyre_management(result):
    s = result["structural_managed"]
    bias = np.abs(s["degradation"] - np.asarray(DEFAULT_CONFIG.degradation))
    assert bias.max() > 0.01  # well beyond the 0.002 recovery tolerance above


def test_insufficient_variation_is_rejected():
    # One driver, one stop: per stint only an intercept and a slope are observed, so the
    # five structural coefficients are not identified.
    cfg = SyntheticConfig(
        n_races=1,
        n_drivers=1,
        race_laps=30,
        compounds=("C2", "C3"),
        pace_offset=(0.3, 0.0),
        degradation=(0.05, 0.08),
        censoring_age=(25, 25),
    )
    rules = EventRules(
        race_laps=30, compounds=cfg.compounds, stop_counts=(1,), min_distinct_dry_compounds=2
    )
    with pytest.raises(ValueError, match="not identified"):
        structural(generate_laps(cfg, rules), cfg.compounds, cfg.reference_age)


def test_report_is_reproducible(result):
    assert report(run()) == report(result)
