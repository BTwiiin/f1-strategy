# Evaluation contract

This document defines how the project is evaluated and how decision outputs are computed.
- Prediction tasks: [`forecasting.md`](forecasting.md).
- Scope and conventions: [`scope.md`](scope.md).
- Values: `config/evaluation.toml` and `config/model.toml`. This document names their keys.

## Status of definitions

| Status | Meaning |
|---|---|
| fixed | Changing it is a versioned contract change. |
| provisional | A decision criterion, not an empirical constant. It may be tuned on 2023–2024 only, until the M7 freeze. |
| dev-only | A development sensitivity analysis; never used for holdout results. |
| deferred | Listed under [Open definitions](#open-definitions). It is committed before the first result that uses it. |

Rules are fixed unless marked otherwise.

## Splits

| Role | Seasons | Use |
|---|---|---|
| Burn-in | 2023 | Training only; never scored. |
| Development | 2024 | Walk-forward scored targets for all model selection. |
| Holdout | 2025 | Walk-forward with the frozen procedure, evaluated once. |

- **Walk-forward (expanding window):** each target is predicted by refitting on all data available before its checkpoint.
- **Season cold starts:**
  - Early 2024 has one prior season and early 2025 has two.
  - Results are reported by position in the season.
- **Secondary checks:**
  - Static benchmark (holdout only): the frozen procedure fitted once on 2023–2024.
  - Leave-one-circuit-out (development only).

## Holdout protocol

- **Model selection on 2023–2024 only.** This covers model specification, features, cleaning, support thresholds, shrinkage, eligibility, decision rules and evaluation criteria.
- **What is frozen is the procedure, not a parameter set.**
- **Access.**
  - The development pipeline cannot read 2025. 2025 data is stored and built separately.
  - The holdout runner reads 2023–2024 history and those 2025 records that are available before each target's checkpoint. A target race is used only for scoring.
  - Both rules are enforced by access-layer tests. Those tests are the primary guarantee of isolation.
- **Binding to the frozen state.** The holdout build and run execute only when `HEAD` is the freeze-tag commit and the working tree is clean (no modified or untracked non-ignored files), so code and configuration are exactly the frozen ones. The run records that commit and the hash of the raw-cache manifests.
- **Run once.** The holdout is evaluated once, including same-race reference runs and the static benchmark. No tuning happens between holdout races.
- **Consumption.** Any later change creates a new version, and the holdout is marked as consumed for that version.

### Holdout exposure log

| Exposure | Handling |
|---|---|
| During the direction review, a data-quality check retrieved one 2025 race (Abu Dhabi). Only its lap count and missing-value count were reported. | No 2025 pace, strategy or lap-time values informed any decision. |
| External findings (e.g. "practice long runs predict race pace poorly") were computed on 2022–2026 data. | Treated as non-binding priors. Feature decisions use 2023–2024 development results only. |
| Public knowledge of 2025 race outcomes cannot be removed. | The guarantee rests on the frozen procedure and code-level isolation, not on ignorance. |

Later exposures, including the sealed 2025 download (M2), are appended here.

## Freeze points

1. **M0, before any data was ingested.** Fixed at this point:
   - the splits and the holdout protocol;
   - the feasibility gate;
   - the structure of the eligibility, support and decision rules;
   - the common-trend grid.
2. **M0 revision, before any data is ingested.**
   - The forecasting tasks, horizons and information-set rules.
   - The model ladder and feature-group order.
   - The roles of the common trend.
3. **After M4, before any development model-comparison result.**
   - `docs/modelling_plan.md` is committed, fixing the model specifications, the T2 normalisation, the feature-selection thresholds and the interval method.
4. **M7, before 2025 is read by modelling code.**
   - Final provisional values.
   - The frozen configuration and the static benchmark, both tagged.

## Eligibility

Each use of a race has its own mechanical rule. Excluded races and observations are kept as case studies.

- **Prediction availability:** decided only from information available before the checkpoint. If no supported plan exists, the output is an abstention. The share of predicted races that turn out to be scoreable is reported.
- **Lap-level use:** clean-lap rules (M3) remove non-green, pit, first, deleted and outlier laps. Every excluded lap has exactly one primary reason.
- **Strategy-level scoring (E2–E4):** the race uses no intermediate or wet tyre, has no red flag after lap 1, and has a green-flag lap share of at least `eligibility.min_green_flag_lap_share` (provisional 0.80; dev-only sensitivity at 0.70 and 0.90).
- **Pit-loss window:** the in-lap and the out-lap (`eligibility.pit_loss_window`).
  - A plan is excluded from strategy scoring when an SC or VSC period overlaps the window of any of its stops.
  - Also excluding stops adjacent to a neutralisation is dev-only.
- **E3 minimum sample:** at least `eligibility.e3_min_drivers_per_plan_class` drivers per plan class (provisional K = 3).
- **Insufficient support:** excludes the affected plans or comparisons, not the race. A compound with no comparable history is used only with a documented prior.

## Data support

Every legal plan is labelled from support profiles computed on its training data. Keys: `support.*` in `config/model.toml`, all provisional.

- **Shape support:** compound `c` at tyre age `a` has clean laps from at least S stints (`min_stints_per_age` = 10) across at least R races (`min_races_per_age` = 3), pooled over circuits.
- **Contiguity:** `A_max(c)` is the last supported age before the first unsupported age at or above the reference age.
- **Circuit support:** the circuit has clean laps from at least R_c races (`min_circuit_races` = 1).
- **Labels:**
  - `supported`: every lap has shape support and the circuit has circuit support.
  - `unsupported`: some stint exceeds `A_max(c) + E` (`extrapolation_margin_laps` = 3), or the plan uses a compound without usable data. Excluded by default.
  - `extrapolated`: neither of the above.

Support is reported separately from parameter uncertainty. For residual models, the supported region is also where they may depart from B2 ([`forecasting.md`](forecasting.md#model-ladder)).

## Decision outputs

**Notation.**

| Symbol | Meaning |
|---|---|
| `G` | the common-trend sensitivity grid; `c ∈ G` a scenario |
| `b = 1..B` | joint bootstrap sample |
| `L` | the legal plans |
| `S ⊆ L` | the supported plans (`decision_rule.comparison_set`) |
| `T(p, b, c)` | relative time of plan `p` |

- Every quantity is computed per race, per scenario and per pace model.
- `S` does not depend on `c`. If `S` is empty, the output is an abstention.
- The scenario dimension applies to tyre parameters refitted with `g` fixed at `c`. Results with the estimated `g` are reported alongside.

### Model-equivalent plans

- **Definition:** two plans are model-equivalent when they have the same multiset of stints (compound, first age, last age). Under models without race-lap terms they have identical `T`.
- **Outputs are computed over equivalence classes:**
  - A class is represented by its member with the smallest plan identifier, and every member is listed.
  - `P(fastest)` and break-even values are computed between classes.
  - E4 is assessed at class level.
- **Phase-aware models:** order differences are reported as model-implied order effects, together with whether the phase term passed the ablation. They are never presented as evidence for an order.
- **Ties:** ties between non-equivalent plans are broken deterministically, and every tied plan is reported.

### Per plan and scenario

- **Regret:** `R(p,b,c) = T(p,b,c) − min_{q∈S} T(q,b,c)`.
- **Expected regret** `ER(p,c)` is the mean of R over `b`. **Downside regret** `QR(p,c)` is its `decision_rule.regret_quantile` (0.90) quantile.
- **`P(fastest | c)`:** the share of samples in which `p` is the minimum; ties share the sample equally.
- **Recommendation:** `p*_c = argmin_{p∈S} ER(p,c)`. Ties are broken by `QR`, then by plan identifier.
- **Delta:** `D(p,b,c) = T(p,b,c) − T(p*_c,b,c)` is reported for every `p ∈ L` as the median and the 50% and 90% intervals. Extrapolated plans are labelled and never recommended.
- **Diagnostics for `p*_c` and `p̂`:**
  - `support_boundary_hit`: a stint reaches `A_max`.
  - `extrapolated_plan_outperforms`: an extrapolated plan has a lower mean `T` than `p*_c`.

### Across the grid

- **Headline:** `p̂ = argmin_{p∈S} max_{c∈G} ER(p,c)` (minimax expected regret). Ties are broken by `ER` at the central scenario, then by identifier. It depends on the grid range, and the scenario recommendations are always reported alongside.
- **Grid stability:** `M(p)` is the share of grid points with `p*_c = p`; ranks are reported per scenario.
- **Break-even values:**
  - **Leading plans:** those with `M > 0`. If only one plan qualifies, add the runner-up at the central scenario.
  - **Difference:** for each pair, `d(c) = mean_b [T(p) − T(q)]`.
  - **Crossings:** every sign change of `d` across adjacent grid points is reported by linear interpolation and labelled approximate. If `d` never changes sign, report "no break-even within the grid".
- **Aggregated probability:** reported only under an explicit, labelled prior over `G`.
- **Reproducibility:** results are reproducible with documented seeds.

### Decision rule

`p̂` is **robust** when both hold:
- `M(p̂) ≥ decision_rule.robust_min_grid_share` (provisional 0.80);
- `max_c QR(p̂,c) ≤ decision_rule.tau_s` (provisional 5 s).

Otherwise it is **fragile**.
- With a single supported plan, regret is zero by construction, and the output says so.
- The sensitivity of the label to grid resolution and to support thresholds is dev-only.

## Feasibility gate

Evaluated once on the 2024 walk-forward outputs of B2 (`feasibility_gate.*`, all fixed at M0):

1. **Denominator:** every 2024 Grand Prix that meets the gate's own eligibility, including abstentions.
   - No intermediate or wet tyre.
   - No red flag after lap 1.
   - Green-flag share ≥ 0.80, independent of `eligibility.*`.
2. **`S_gate`:** the supported plans under the gate's own thresholds (S = 10, R = 3, R_c = 1). It is independent of `support.*`, and extrapolated plans are excluded.
3. **Decision-useful race.** At the central scenario (0.06 s/lap), all three hold:
   - `S_gate` contains both a one-stop and a two-stop plan;
   - `p*_c` exists;
   - `QR(p*_c) ≤ 5 s`.
4. **Pass:** at least 50% of the races in the denominator are decision-useful.

Reported with it:
- coverage;
- usefulness conditional on coverage;
- the width of the 90% interval of `D` for the best supported plan of the other stop-count class;
- the share of races whose `p*_c` changes across the grid.

The gate measures internal decision usefulness of the strategy component under the structural model's assumptions. It does not assess the predictive objectives (P1, P2), which are judged against their baselines, and it is not evidence of predictive or causal validity. A failure is diagnosed and reported, never an automatic fallback.

## Evidence

Each level supports only the claims listed for it.

| Kind | Level | Test | Does not support |
|---|---|---|---|
| Predictive | E1 | Recovery on synthetic data with known truth | Validity on real races |
| Predictive | P1, P2 | Forecast tasks T1 and T2 ([`forecasting.md`](forecasting.md)) | Claims about plans that were not executed |
| Predictive | E2 | Predicting the green-flag time cost of each executed plan | Causal claims about alternative plans |
| Model-implied | — | Decision outputs and model-implied order effects | Any empirical claim |
| Verifiable decision | E3 | Pace-adjusted comparison of plan classes within a race, with a placebo test | Unconfounded causal effects |
| Verifiable decision | E4 | Agreement with Pirelli and with the modal strategy | Accuracy or optimality |

- **Counterfactual statements** also rely on the untested assumption that parameters do not depend on who executes the plan.
- **Prediction fit** (P1, P2, E2) never selects or weights grid scenarios. `g` is estimated only inside B2, as declared in [`scope.md`](scope.md#common-trend).
- **E3** includes:
  - a placebo spread computed on drivers on the same plan class;
  - pre-declared sensitivity analyses;
  - supported plans only.
- **E4:** an external reference plan that is unsupported is marked "not comparable".

## Same-race reference mode

- **What it is:** a diagnostic that cross-fits the evaluated race while excluding the target driver.
- **Restriction:** it is never used for recommendations.
- **How it is read:** through `noise floor ≤ same-race ≤ history ≤ naive baseline`, where the noise floor comes from split-half refits.
- **Interpretation:**
  - Failure with same-race parameters indicates a model-form error.
  - Success with same-race parameters but failure with history indicates the bottleneck is parameter prediction.

## Metrics and baselines

- **Predictive metrics:** as in [`forecasting.md`](forecasting.md#metrics). Baselines: B0, B1, and the lower rungs of the ladder.
- **Parameter level:**
  - cumulative stint-loss error;
  - pit-loss error;
  - interval coverage;
  - error by circuit, compound and position in the season.
- **Plan level (E2/E3):** error in plan deltas, pairwise ranking accuracy, placebo spread.
- **E4:** agreement rates, with "not comparable" cases reported separately.
- **Strategy baselines:**
  - the modal strategy at the previous edition of the event;
  - global parameters with circuit pit loss;
  - always one stop;
  - Pirelli;
  - the static benchmark (holdout only).

No accuracy thresholds are imposed in advance, except the feasibility gate.

## Open definitions

Each is committed before the first result that uses it:

- **Deferred to `modelling_plan.md` (M4):**
  - the GAM and GBM specifications;
  - the T2 normalisation;
  - the feature-selection thresholds;
  - the interval method;
  - the reference tyre age;
  - the shrinkage estimator.
- **E2 target and abstention handling** in E2–E4.
- **E3 pace adjustment and placebo construction.**
- **Green-flag pit-loss estimator.**
- **Pirelli collection procedure.**
- **Green-flag lap definition (before M3 coverage results):**
  - partial overlap with a neutralisation;
  - missing or conflicting statuses;
  - local yellow flags;
  - the denominator of the green-flag share.
