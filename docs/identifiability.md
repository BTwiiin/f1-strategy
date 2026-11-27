# Identifiability of the common trend and tyre degradation

This document shows on synthetic data that, with a free intercept per stint, the common trend and tyre degradation cannot be estimated separately ([`scope.md`](scope.md#common-trend)). Recovery is possible only under an added structural assumption, and only when the data satisfy that assumption.

## Reproduction

```bash
uv run python -m f1_strategy.synthetic.identifiability
```

Implementation: `f1_strategy.synthetic.identifiability`. Data: `f1_strategy.synthetic.generator` with the default `SyntheticConfig` (seed 0, 8 races × 20 drivers, 57 laps, compounds C1–C3, linear degradation 0.03/0.05/0.08 s/lap, common trend 0.065 s/lap, lap noise sd 0.15 s, driver-race offset sd 0.3 s, reference age 2). Lap 1, in-laps and out-laps are removed. Ordinary least squares (`numpy.linalg.lstsq`). `tests/test_identifiability.py` checks every claim below.

## Models

Tyre age enters as `age − reference_age` per compound. `g` is `common_trend_gain` (positive = faster each lap).

1. **Free stint intercepts:** `lap_time = α_stint + d_c · (age − ref) − g · lap`.
2. **Structural assumption:** `lap_time = δ_driver-race + o_c + d_c · (age − ref) − g · lap`. A compound offset `o_c` is shared by all stints of that compound, replacing the free stint intercepts.

## Results (seed 0)

```
1. Free stint intercepts
   design rank 435 of 436 columns
   estimated net slope [-0.0350, -0.0152, +0.0155]   (true [-0.0350, -0.0150, +0.0150])
   RSS across 12 grid scenarios: min 177.763650, max 177.763650
   g      inferred degradation (= net slope + g)
   0.00   [-0.0350, -0.0152, +0.0155]
   0.06   [+0.0250, +0.0448, +0.0755]
   0.11   [+0.0750, +0.0948, +0.1255]
   (all 12 grid points in the command output)

2. Structural assumption, correct generator
   design rank 166 of 166 columns
   trend +0.0650 (true +0.0650)
   degradation [+0.0299, +0.0498, +0.0804] (true [+0.0300, +0.0500, +0.0800])
   pace offset vs C1 [-0.3018, -0.6081] (true [-0.3000, -0.6000])

3. Structural assumption, tyre-management generator
   design rank 166 of 166 columns
   trend +0.0651 (true +0.0650)
   degradation [+0.0175, +0.0315, +0.0807] (true [+0.0300, +0.0500, +0.0800])
   pace offset vs C1 [-0.3140, -0.7500] (true [-0.3000, -0.6000])
```

## Interpretation

- **Free stint intercepts (1).** Within a stint, `age − lap` is constant, so the design matrix has rank one less than its number of columns. Fixing `g` at any point of the common-trend grid gives identical residuals, and the inferred degradation is exactly `observed_net_stint_slope + g`. The data cannot choose between scenarios, which is why prediction fit is never used to select or weight grid scenarios.
- **Structural assumption (2).** A compound offset shared across stints lets the tyre-age reset at each stop, at a different race lap, separate degradation from the trend. Recovery is exact without noise and accurate with noise here. This holds only because the generator satisfies the assumption and the plans vary enough; the full-rank check is required, and with one driver on a one-stop the design is rank-deficient and the fit is refused (`test_insufficient_variation_is_rejected`). It is not a general guarantee.
- **Misspecification (3).** When drivers manage tyres on long stints (a pace cost plus reduced degradation), the same structural fit still recovers the trend in this configuration, but degradation and compound offsets are biased. Other violations, such as stint-specific tyre-set condition or non-linear track evolution, would act directly on the between-stint comparison that identifies the trend.

## Status after the M0 revision

The project now adopts the structural assumption (shared driver-race intercept, baseline B2 in [`scope.md`](scope.md#pace-model)) and tests it by temporal out-of-sample forecasting ([`forecasting.md`](forecasting.md)). Forecasting can expose violations that change observed laps; it cannot expose a bias that is the same in training and test races, such as consistent tyre management on long stints (case 3). The sensitivity grid is therefore kept for strategy outputs.
