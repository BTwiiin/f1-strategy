"""Identifiability of the common trend and tyre degradation (docs/identifiability.md).

Clean synthetic laps (lap 1, in-laps and out-laps removed) are fitted by least squares:

1. **Free stint intercepts**: ``lap_time = alpha_stint + d_c * age - g * lap``. Within a stint
   ``age - lap`` is constant, so the design is rank-deficient: only the net slope
   ``d_c - g`` is identified. Fixing ``g`` at any grid value gives the same residuals and
   ``d_c(g) = net_c + g`` (docs/scope.md sign convention).
2. **Structural assumption**: driver-race intercept plus a compound offset shared by all
   stints of that compound in the race, instead of free stint intercepts. Tyre-age resets
   at stops at different race laps then separate ``d_c`` and ``g``. Recovery holds only
   when the generating process satisfies the assumption and the plans vary enough; under
   the tyre-management variant the same fit is biased.

Run: ``uv run python -m f1_strategy.synthetic.identifiability``.
"""

from dataclasses import replace

import numpy as np

from f1_strategy import config
from f1_strategy.synthetic.generator import SyntheticConfig, SyntheticRaceData, generate_laps

DEFAULT_CONFIG = SyntheticConfig()


def _one_hot(codes: np.ndarray) -> np.ndarray:
    _, inverse = np.unique(codes, return_inverse=True)
    return np.eye(inverse.max() + 1)[inverse]


def _clean(data: SyntheticRaceData) -> np.ndarray:
    return (data.lap > 1) & ~data.is_in_lap & ~data.is_out_lap


def _age_by_compound(data: SyntheticRaceData, m: np.ndarray, compounds, ref: int) -> np.ndarray:
    """Tyre age minus the reference age, one column per compound (zero elsewhere)."""
    age = data.tyre_age[m] - ref
    return np.column_stack([np.where(data.compound[m] == c, age, 0) for c in compounds])


def _fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, int]:
    coef, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    rss = float(np.sum((y - x @ coef) ** 2))
    return coef, rss, int(rank)


def free_intercepts(data: SyntheticRaceData, compounds, ref: int, grid) -> dict:
    """Rank of the full design and per-scenario fits with ``g`` fixed at grid values."""
    m = _clean(data)
    y, lap = data.lap_time[m], data.lap[m].astype(float)
    base = np.hstack([_one_hot(data.stint_id[m]), _age_by_compound(data, m, compounds, ref)])
    full = np.hstack([base, lap[:, None]])
    n_age = len(compounds)
    fits = {}
    for g in grid:
        coef, rss, _ = _fit(base, y + g * lap)
        fits[g] = {"degradation": coef[-n_age:], "rss": rss}
    return {
        "n_columns": full.shape[1],
        "rank": int(np.linalg.matrix_rank(full)),
        "fits": fits,
        "net_slope": fits[grid[0]]["degradation"] - grid[0],
    }


def structural(data: SyntheticRaceData, compounds, ref: int) -> dict:
    """Driver-race intercepts + shared compound offsets (first compound as reference).

    Raises ``ValueError`` when the design is rank-deficient (insufficient variation)."""
    m = _clean(data)
    y, lap = data.lap_time[m], data.lap[m].astype(float)
    driver_race = data.race_id[m] * (data.driver_id.max() + 1) + data.driver_id[m]
    offsets = np.column_stack([data.compound[m] == c for c in compounds[1:]]).astype(float)
    x = np.hstack(
        [_one_hot(driver_race), offsets, _age_by_compound(data, m, compounds, ref), lap[:, None]]
    )
    coef, _, rank = _fit(x, y)
    if rank < x.shape[1]:
        raise ValueError(f"structural design rank {rank} < {x.shape[1]} columns: not identified")
    n = len(compounds)
    return {
        "n_columns": x.shape[1],
        "rank": rank,
        "trend": -coef[-1],
        "degradation": coef[-1 - n : -1],
        "pace_offset_vs_first": coef[-1 - 2 * n + 1 : -1 - n],
    }


def run(cfg: SyntheticConfig = DEFAULT_CONFIG) -> dict:
    grid = config.common_trend_grid(config.load("model")["common_trend"])
    correct = generate_laps(cfg)
    managed = generate_laps(replace(cfg, variant="tyre_management"))
    return {
        "config": cfg,
        "grid": grid,
        "free": free_intercepts(correct, cfg.compounds, cfg.reference_age, grid),
        "structural_correct": structural(correct, cfg.compounds, cfg.reference_age),
        "structural_managed": structural(managed, cfg.compounds, cfg.reference_age),
    }


def _fmt(values) -> str:
    return ", ".join(f"{v:+.4f}" for v in values)


def report(result: dict) -> str:
    cfg, free = result["config"], result["free"]
    rss = [f["rss"] for f in free["fits"].values()]
    true_d = np.asarray(cfg.degradation)
    true_pace = np.asarray(cfg.pace_offset[1:]) - cfg.pace_offset[0]
    lines = [
        f"seed={cfg.seed} races={cfg.n_races} drivers={cfg.n_drivers} laps={cfg.race_laps} "
        f"noise_sd={cfg.noise_sd} compounds={','.join(cfg.compounds)}",
        f"true: trend={cfg.common_trend_gain:.4f} degradation=[{_fmt(true_d)}] "
        f"net slope=[{_fmt(true_d - cfg.common_trend_gain)}]",
        "",
        "1. Free stint intercepts",
        f"   design rank {free['rank']} of {free['n_columns']} columns",
        f"   estimated net slope [{_fmt(free['net_slope'])}]",
        f"   RSS across {len(rss)} grid scenarios: min {min(rss):.6f}, max {max(rss):.6f}",
        "   g      inferred degradation (= net slope + g)",
    ]
    lines += [f"   {g:.2f}   [{_fmt(f['degradation'])}]" for g, f in free["fits"].items()]
    for key, label in (
        ("structural_correct", "2. Structural assumption, correct generator"),
        ("structural_managed", "3. Structural assumption, tyre-management generator"),
    ):
        s = result[key]
        lines += [
            "",
            label,
            f"   design rank {s['rank']} of {s['n_columns']} columns",
            f"   trend {s['trend']:+.4f} (true {cfg.common_trend_gain:+.4f})",
            f"   degradation [{_fmt(s['degradation'])}] (true [{_fmt(true_d)}])",
            f"   pace offset vs {cfg.compounds[0]} [{_fmt(s['pace_offset_vs_first'])}] "
            f"(true [{_fmt(true_pace)}])",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(run()))
