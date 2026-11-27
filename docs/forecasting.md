# Forecasting tasks

This document defines the prediction tasks, the information sets, the model ladder and how features are selected. Values are in `config/evaluation.toml` (`[forecast]`, `[ablation]`). Decisions that depend on data are deferred to `docs/modelling_plan.md`, which is written in M4 and committed before any development model-comparison result.

## T1: next-stint forecast (primary)

- **Origin:** stint `k ≥ 2` of an eligible driver in an eligible race. The prediction timestamp `t0` is the `date_start` of the out-lap. At `t0` the fitted compound is known.
- **Information set:** every record with `available_at < t0` ([`scope.md`](scope.md#information-checkpoints)), plus the fitted set's compound and initial tyre age.
- **Targets:** clean green-flag laps at stint laps 1–15. Stint lap 1 is the out-lap. Neutralised laps count towards tyre age but are never targets.
- **Horizons:** `h ∈ {5, 10, 15}`. The score at horizon `h` uses observed targets at stint laps ≤ `h`. Errors are also reported for each stint lap.
- **Censoring:**
  - A target that does not exist (the stint ended, or the lap is not clean) is missing, not imputed.
  - Every error is reported together with forecast coverage: the share of origins with an observed target, by horizon.
  - Stints that end early are not a random sample. A diagnostic therefore compares stints that reached `h` with those that ended before it.
- **Eligibility:** at least `min_clean_laps_before_origin` clean laps by the driver before `t0`.
- **Pre-stop variant (application):**
  - The origin is the in-lap `date_start`, and every legal compound is evaluated.
  - Only the compound actually fitted can be scored. Forecasts for the others are model-implied.

## T2: pre-race profile

- **Cutoff:** the race start.
- **Target:** the clean-lap profile of each executed stint, including stint 1, relative to the stint's early level. The normalisation is fixed in `modelling_plan.md`.
- **Why it matters:** T2 tests the tyre-age and trend inputs the strategy simulator uses before the race.

## Information-set rules

| Never in a forecast | Reason |
|---|---|
| `lap_end`, length or end reason of a stint ongoing at the origin | future stint length |
| weather, gaps, positions or race-control messages after the origin | future conditions |
| results and classification of the target session | post-session |
| race weather or race laps in a pre-race forecast | after the cutoff |

Field-level availability, implemented and tested in the access layer (M2):

| Record | Available from |
|---|---|
| lap (all fields) | start + duration, else the next lap's start, else never |
| stint compound, initial tyre age | start of the stint's first lap |
| stint `lap_end` | completion of its last lap |
| pit stop with durations | pit entry + longest recorded duration |
| weather, race control, gaps, positions | their own timestamp |
| results, starting grid | the later of the scheduled end, the last lap completion and the last race-control message |

## Metrics

- Lap-time MAE and RMSE, by horizon and by stint lap.
- Post-stop level change: the predicted minus the observed mean of the first clean laps of the new stint, relative to the last clean laps before the stop.
- Degradation: the predicted minus the observed within-stint slope.
- Uncertainty: interval coverage and pinball loss, by horizon.
- Results by circuit, compound and position in the season, and coverage throughout.

## Model ladder

| Model | Definition |
|---|---|
| B0 | Persistence: mean of the driver's last 3 clean laps |
| B1 | B0 plus the historical compound offset and tyre-age reset (circuit or global means) |
| B2 | Structural model ([`scope.md`](scope.md#pace-model)), walk-forward with shrinkage |
| GAM | B2 with smooth tyre-age effects by compound, a smooth race-lap trend and candidate interactions |
| GBM | LightGBM fitted to B2 residuals; outside the supported region it falls back to B2 |

- Each model must beat the models below it out of sample to be retained.
- Specifications for the GAM and GBM are fixed in `modelling_plan.md`.
- Not used: CatBoost and deep learning.

## Feature groups

Groups are added cumulatively in a fixed order (`ablation.group_order`). No group repeats a feature already in B2.

| Group | Content (as observed at the origin or cutoff) |
|---|---|
| F1 tyre | new or used set, initial tyre age |
| F2 context | circuit and season interactions beyond B2 |
| F3 team and driver | team-specific degradation; driver-specific degradation only if it gains |
| F4 weather | track temperature and its recent change |
| F5 traffic | gap to the car ahead, recent position changes |
| F6 same weekend | practice long-run degradation, qualifying gap |

A group is kept on the basis of:
- practical effect size against the B2 noise floor;
- stability across races and both halves of 2024;
- race-clustered uncertainty of the gain;
- added complexity.

Statistical significance alone never decides. The thresholds are fixed in `modelling_plan.md`.

## Interpretation

Forecast accuracy is measured on the plans teams actually executed. It does not validate predictions for plans that were not run, and good predictive performance is not evidence that a strategy ranking is causally correct.
