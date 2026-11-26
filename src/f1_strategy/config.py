"""Loading and validation of the versioned TOML configuration in ``config/``."""

import math
import tomllib
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Tolerance for comparing decimal configuration values held as binary floats.
_EPS = 1e-9


def load(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Load ``<config_dir>/<name>.toml``; ``name`` may contain a subdirectory."""
    with (config_dir / f"{name}.toml").open("rb") as f:
        return tomllib.load(f)


def common_trend_grid(common_trend: dict[str, Any], step: float | None = None) -> list[float]:
    """Uniform common-trend grid in s/lap.

    Range: fuel bounds widened by the track-evolution allowance, rounded outwards to
    multiples of the primary step. A finer ``step`` (resolution check) spans the same range.
    """
    primary = common_trend["step"]
    allowance = common_trend["track_evolution_allowance"]
    lo = math.floor((common_trend["fuel_gain_min"] - allowance) / primary + _EPS) * primary
    hi = math.ceil((common_trend["fuel_gain_max"] + allowance) / primary - _EPS) * primary
    step = primary if step is None else step
    n = round((hi - lo) / step)
    if not math.isclose(lo + n * step, hi, abs_tol=_EPS):
        raise ValueError(f"step {step} does not divide grid range [{lo}, {hi}]")
    return [round(lo + i * step, 10) for i in range(n + 1)]


def validate(evaluation: dict[str, Any], model: dict[str, Any]) -> None:
    """Check internal consistency of the evaluation contract; raise ``ValueError`` if violated."""
    splits = evaluation["splits"]
    groups = [set(splits[k]) for k in ("burn_in_seasons", "development_seasons", "holdout_seasons")]
    if any(a & b for i, a in enumerate(groups) for b in groups[i + 1 :]):
        raise ValueError("burn-in, development and holdout seasons must be disjoint")
    if max(groups[0] | groups[1]) >= min(groups[2]):
        raise ValueError("holdout seasons must follow all burn-in and development seasons")

    ct = model["common_trend"]
    if not ct["fuel_gain_min"] <= ct["fuel_gain_median"] <= ct["fuel_gain_max"]:
        raise ValueError("fuel_gain_median must lie within the fuel bounds")
    grid = common_trend_grid(ct)
    nearest = min(grid, key=lambda g: abs(g - ct["fuel_gain_median"]))
    if not math.isclose(ct["central_scenario"], nearest, abs_tol=_EPS):
        raise ValueError(f"central_scenario must be the grid point nearest the median ({nearest})")
    common_trend_grid(ct, ct["dev_resolution_step"])

    for section in ("decision_rule", "feasibility_gate"):
        q = evaluation[section]["regret_quantile"]
        if not 0 < q < 1:
            raise ValueError(f"{section}.regret_quantile must be in (0, 1)")
    gate = evaluation["feasibility_gate"]
    for key in ("min_decision_useful_share", "eligibility_min_green_flag_lap_share"):
        if not 0 < gate[key] <= 1:
            raise ValueError(f"feasibility_gate.{key} must be in (0, 1]")
    for key in (
        "support_min_stints_per_age",
        "support_min_races_per_age",
        "support_min_circuit_races",
    ):
        if not (isinstance(gate[key], int) and gate[key] >= 1):
            raise ValueError(f"feasibility_gate.{key} must be a positive integer")
