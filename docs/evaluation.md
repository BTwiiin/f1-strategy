# Evaluation contract

This document is the normative definition of how the simulator is evaluated and how its decision outputs are computed. Scope and modelling conventions are in [`scope.md`](scope.md); the common-trend grid is in [`common_trend.md`](common_trend.md). Numerical values live in `config/evaluation.toml` and `config/model.toml`; this document names their keys.

## Status of definitions

| Status | Meaning |
|---|---|
| fixed | Set at the M0 freeze point. Changing it is a versioned contract change. |
| provisional | An assumption or decision criterion, not an empirically established constant or probability. May be adjusted on 2023–2024 data only, until the M6 freeze. |
| dev-only | A development sensitivity analysis; never used for the holdout result. |
| deferred | Listed under [Open definitions](#open-definitions); specified and committed before the milestone that first uses it and before any development result for the affected evaluation level is computed. |

Unless marked otherwise, every rule in this document is fixed.

## Splits and walk-forward protocol

| Role | Seasons | Use |
|---|---|---|
| Burn-in | 2023 | Training data only; never scored. |
| Development | 2024 | Walk-forward scored targets for all model selection. |
| Holdout | 2025 | Walk-forward with the frozen procedure, evaluated once. |

Keys: `splits.*`, `walk_forward.*`.

- **Walk-forward (expanding window).** For each target race, parameters are refitted by the frozen procedure on all data available before that race's prediction cutoff ([`scope.md`](scope.md#prediction-cutoff)).
- **Season cold starts.** Early-season targets are predicted with no race data from their own season. Early 2024 targets have one prior season of history; early 2025 targets have two. The protocol is identical; the available history differs, and results are reported by position in the season so the difference stays visible.
- **Static benchmark (secondary, holdout only).** The frozen procedure fitted once on 2023–2024 and applied unchanged to all of 2025. It measures the benefit of in-season updating.
- **Leave-one-circuit-out (secondary).** Each development circuit is predicted with all of its own races removed from the training data.

## Holdout protocol

- All model selection uses 2023–2024 only: model shape, cleaning rules, support thresholds, shrinkage procedure, common-trend grid, eligibility rules, decision rules and evaluation criteria.
- The procedure is frozen (model specification, hyperparameters, feature definitions, cleaning rules, shrinkage, evaluation criteria), not a parameter set. The 2025 walk-forward refits parameters before each race using only data before its cutoff.
- The frozen configuration, including the static benchmark, is tagged in version control before any 2025 data is read by modelling code.
- 2025 data is stored separately and is readable only through the cutoff-gated access layer, and only by the holdout runner. For an evaluated event, earlier races and pre-race sessions may be used for prediction and that race's data only for scoring. Development code cannot read 2025 data. Both properties are enforced by tests, which are the primary guarantee of holdout isolation.
- The 2025 evaluation, including same-race reference runs and the static benchmark, is executed once from the tagged configuration. No manual tuning occurs between holdout races.
- Any change after the holdout run produces a new version, and the holdout is marked as already consumed for that version.

## Freeze points

1. **M0, before any data ingestion:** splits, walk-forward and holdout protocol, feasibility-gate rule, thresholds, gate eligibility and gate support thresholds, structure of eligibility, support and decision rules, and the common-trend grid with its sources.
2. **M6, before 2025 is read:** final values of provisional thresholds, selected on 2023–2024 only.

The feasibility-gate thresholds are not adjusted after M0.

## Eligibility

Eligibility is defined separately for each use of a race and applied by pre-declared, mechanical rules. Races or observations excluded from scoring are retained as documented case studies.

**Prediction availability.** Depends only on information available before the cutoff: event rules, compound nomination and data support. A prediction is produced when at least one legal plan can be enumerated; if no plan is supported, the output is an abstention. A race may be predicted and later turn out to be ineligible for scoring; the share of predicted races that are scoreable is reported.

**Parameter-level use.** Lap-level: clean-lap rules (M3) remove non-green, pit and invalid laps, so a race with heavy neutralisation still contributes its clean laps.

**Strategy-level scoring (E2–E4).** A race is scoreable when all of the following hold:

- no intermediate or wet tyre is used by any driver;
- no red flag after lap 1;
- the share of green-flag laps is at least `eligibility.min_green_flag_lap_share` (provisional 0.80; dev-only sensitivity at 0.70 and 0.90).

The feasibility gate uses its own fixed copy of these rules (see [Feasibility gate](#feasibility-gate-m5)).

**Pit-loss measurement window.** For a stop, the window is the in-lap (the lap ending in the pit lane) and the out-lap (the lap starting from the pit lane). Key: `eligibility.pit_loss_window`.

**Neutralisation overlap.** A driver's executed plan is excluded from strategy-level scoring when an SC or VSC period overlaps the pit-loss measurement window of any of its stops. Excluding stops on laps adjacent to a neutralisation is a dev-only sensitivity analysis; a stop before a neutralisation is not assumed to be anticipated.

**Minimum sample.** E3 comparisons require at least K eligible drivers per compared plan class (`eligibility.e3_min_drivers_per_plan_class`, provisional K = 3). This is a minimum sample requirement, not evidence of statistical reliability.

**Insufficient support.** Insufficient support for a compound excludes the affected plans or comparisons, not the whole race. A compound with no historical data at comparable conditions (for example C6) is not used unless an explicit, documented prior is supplied.

## Data support

Every legal plan is labelled from support profiles computed on the training data of its prediction. Keys: `support.*` in `config/model.toml` (all thresholds provisional).

- **Shape support.** Compound `c` at tyre age `a` is supported when clean laps at that age come from at least S distinct stints across at least R distinct races, pooled over circuits (S = `min_stints_per_age` = 10, R = `min_races_per_age` = 3).
- **Contiguity.** Supported ages are contiguous from the reference tyre age upward; the longest contiguous supported age `A_max(c)` is the last age before the first unsupported age. Ages below the reference age are covered by the reference-age anchor and are not counted as gaps.
- **Circuit support.** The circuit has clean laps from at least R_c races (`min_circuit_races` = 1). This records the presence of circuit-level data; the reliability of circuit-specific estimates is expressed through shrinkage and parameter uncertainty.
- **Labels.**
  - `supported`: every lap of the plan has shape support and the circuit has circuit support.
  - `unsupported`: some stint reaches a tyre age beyond `A_max(c) + E` (E = `extrapolation_margin_laps` = 3), or uses a compound without usable data. Not enumerated by default.
  - `extrapolated`: neither supported nor unsupported, that is, some tyre age lies within E laps beyond `A_max(c)`, or circuit information is available only at the global fallback level.

Support is distinct from parameter uncertainty and is reported separately.

## Decision outputs

### Notation

- `G`: common-trend grid; `c ∈ G` a scenario.
- `b = 1..B`: joint bootstrap sample ID.
- `L`: legal enumerated plans; `S ⊆ L`: supported legal plans (the comparison set, `decision_rule.comparison_set`).
- `T(p, b, c)`: relative plan time of plan `p` under parameter sample `b` estimated in scenario `c` (see [`scope.md`](scope.md#relative-time-model)).

All quantities below are computed per race and per scenario unless stated otherwise. Support labels depend on training-data counts, not on the common-trend scenario, so `S` is the same at every grid point. If `S` is empty, the race is an abstention and no recommendation is made.

### Per plan and scenario

- **Regret:** `R(p, b, c) = T(p, b, c) − min_{q∈S} T(q, b, c)`, for `p ∈ S`.
- **Expected regret:** `ER(p, c) = mean_b R(p, b, c)`.
- **Downside regret:** `QR(p, c)` = the `decision_rule.regret_quantile` (0.90) quantile of `R(p, b, c)` over `b`.
- **Fastest-plan probability:** `P(fastest | c)` = share of samples `b` in which `p` attains `min_{q∈S} T(q, b, c)`; ties share the sample equally.
- **Scenario recommendation:** `p*_c = argmin_{p∈S} ER(p, c)`; ties are broken by lower `QR`, then by plan identifier.
- **Delta to the recommendation:** `D(p, b, c) = T(p, b, c) − T(p*_c, b, c)`, reported for every `p ∈ L` as the median and the central 50% and 90% intervals (quantiles 0.25–0.75 and 0.05–0.95) over `b`. Extrapolated plans are reported with their label and never recommended.
- **Constrained-optimum diagnostics.** Two related but distinct limitations, both reported for `p*_c` and for the headline recommendation `p̂`:
  - `support_boundary_hit` (per plan): some stint of the plan reaches the longest contiguous supported tyre age `A_max` of its compound, so a longer stint would leave the supported region.
  - `extrapolated_plan_outperforms` (per scenario): some extrapolated legal plan has a lower `mean_b T(·, b, c)` than `p*_c`.

### Across the grid

- **Worst-case expected regret:** `W(p) = max_{c∈G} ER(p, c)`.
- **Headline recommendation (minimax expected regret):** `p̂ = argmin_{p∈S} W(p)`; ties are broken by lower `ER` at the central scenario, then by plan identifier. There is no justified probability distribution over the grid, so `p̂` does not weight or count scenarios. It does depend on the grid range, so it is driven by the scenarios at the grid edges, which include the track-evolution judgement allowance. Scenario-specific recommendations `p*_c` are always reported alongside it.
- **Grid stability (reported separately):** the minimum-regret share `M(p)` = share of grid points `c` with `p*_c = p`, and the rank of `p` by `ER(·, c)` at each grid point.
- **Approximate break-even values.** Leading plans are the plans with `M(p) > 0`; if there is only one, the plan with the second-lowest `ER` at the central scenario is added. For each pair `(p, q)` of leading plans, `d(c) = mean_b [T(p, b, c) − T(q, b, c)]` is evaluated at every grid point. Every crossing is reported in grid order, so a pair may have several break-even values: for each pair of adjacent grid points where `d` changes sign, the value is obtained by linear interpolation; where `d = 0` exactly at a grid point, that grid point is reported once. All values are labelled as approximate. If `d` has no crossing, the result is "no break-even within the grid".
- **Aggregated probability:** not reported by default; only under an explicit, documented prior over `G`, labelled as prior-dependent.

Monte Carlo outputs are reproducible with documented random seeds.

### Decision rule (M5)

- Within each scenario the recommendation is `p*_c` (minimum expected regret over supported plans).
- Across the grid the headline recommendation is `p̂` (minimax expected regret).
- `p̂` is labelled **robust** when `M(p̂) ≥ decision_rule.robust_min_grid_share` (provisional 0.80) and `max_{c∈G} QR(p̂, c) ≤ decision_rule.tau_s` (provisional 5 s); otherwise **fragile**.
- When `S` contains a single plan, its regret is zero by construction; the output states this, and the label is not interpreted as robustness of a comparison.
- Both thresholds are decision criteria, not statistically established thresholds or probabilities. Label sensitivity to grid resolution and support thresholds is reported (dev-only).

## Feasibility gate (M5)

Evaluated once, on the 2024 walk-forward outputs, with this fixed rule (`feasibility_gate.*`):

1. **Denominator:** every 2024 Grand Prix race (sprint races excluded) that meets the gate eligibility rules, including races where the simulator abstains. The gate eligibility rules are fixed at M0 and kept separate from the provisional strategy-level eligibility, so the denominator cannot change after M0:
   - no intermediate or wet tyre is used by any driver;
   - no red flag after lap 1;
   - the share of green-flag laps is at least `eligibility_min_green_flag_lap_share` = 0.80. This value does not follow later changes of `eligibility.min_green_flag_lap_share`.
2. **Gate supported-plan set `S_gate`:** the legal plans that are `supported` under the [Data support](#data-support) definition, evaluated with the gate's own fixed thresholds instead of the provisional `support.*` values: S = `support_min_stints_per_age` = 10, R = `support_min_races_per_age` = 3, R_c = `support_min_circuit_races` = 1. Later changes to `model.toml` `support.*` do not affect the gate. The gate recomputes the scenario recommendation `p*_c` and regret `QR` with `S_gate` in place of `S`. Extrapolated plans do not enter `S_gate`, so the extrapolation margin E does not affect the gate.
3. **Decision-useful race:** at the central scenario (`model.common_trend.central_scenario` = 0.06 s/lap), all of the following hold:
   - `S_gate` contains at least one one-stop and at least one two-stop plan (`required_supported_plan_classes`); a race without both is not decision-useful for the intended comparison;
   - a recommendation `p*_c` over `S_gate` exists;
   - `QR(p*_c, c) ≤ tau_gate_s` = 5 s, at quantile `regret_quantile` = 0.90, with regret measured against `S_gate`.

   Abstentions count as not decision-useful. `tau_gate_s` does not follow later changes of `decision_rule.tau_s`.
4. **Pass:** the share of decision-useful races is at least `min_decision_useful_share` = 0.50.

Reported alongside the outcome:

- coverage: share of races with a recommendation, and share with both plan classes supported;
- decision usefulness conditional on coverage;
- estimation precision: width of the 90% interval of `D` for the best supported plan of the other stop-count class;
- assumption sensitivity: share of races whose `p*_c` changes across the grid.

The gate measures internal decision usefulness of the model's outputs on development data, under the model assumptions. It is not evidence of independent predictive validity or of causal validity of plan comparisons; empirical performance is assessed by E2–E4. A negative outcome is diagnosed (coverage, precision or assumption sensitivity) and reported as a finding; any change of direction is a documented, versioned decision, not an automatic fallback.

## Evidence hierarchy

No observed race reveals the optimal strategy, and real strategy choices are confounded by traffic, track position, tyre management and other unobserved factors. Each level supports only the claims listed for it.

| Level | Test | Supports | Does not support |
|---|---|---|---|
| E1 | Optimum recovery and parameter recovery on synthetic data with known ground truth | Correctness of estimators and simulator under the generating assumptions | Validity on real races |
| E2 | Prediction of the realised green-flag time cost of the plan each driver actually executed | Predictive accuracy conditional on the executed plan | Causal claims about alternative plans |
| E3 | Pace-adjusted comparison of different plan classes within the same race | Consistency of predicted plan deltas with observed differences | Unconfounded causal effects |
| E4 | Agreement with Pirelli's published pre-race strategy prediction and with the field's modal strategy | Plausibility relative to expert and revealed-preference references | Accuracy or optimality |

Counterfactual statements (a driver would have been faster on another plan) additionally rely on the structural assumption that the same parameters apply regardless of which driver executes a plan. This assumption is documented and not claimed to be tested.

- **E2** metrics are reported separately for each common-trend scenario. E2 fit is never used to select or weight scenarios; doing so would estimate the common trend indirectly.
- **E3** controls: a placebo test applying the same pace adjustment to drivers on the same plan class, whose residual spread defines the minimum plan delta that counts as evidence; pre-declared sensitivity analyses (alternative pace baselines, exclusion of traffic-dominated or position-changing races); comparisons restricted to supported plans.
- **E4**: an external reference plan that is unsupported by the data is marked "not comparable", not counted as disagreement.

## Same-race reference mode

A diagnostic mode in which tyre and pit parameters are cross-fitted on the evaluated race itself, excluding the target driver. It is never used to produce recommendations and does not provide ground-truth parameters. It is interpreted only through the error ladder

```
noise floor ≤ same-race reference ≤ history-based prediction ≤ naive baseline
```

- Failure with same-race parameters indicates model-form or simulator error, or noise.
- Success with same-race parameters but failure with history-based parameters indicates that parameter prediction is the bottleneck.
- Success with same-race parameters does not validate the simulator by itself.
- Results remain conditional on the common-trend scenario.

The noise floor is estimated by split-half refits (for example odd vs even laps).

## Metrics and baselines

- **Parameter level:** stint-level cumulative time-loss error, pit-loss error, interval score and coverage, error by circuit and compound, early-season vs late-season error.
- **Plan level (E2/E3):** error of predicted vs observed plan deltas, pairwise ranking accuracy, placebo spread.
- **Reference level (E4):** agreement rates with Pirelli predictions and the modal strategy, with "not comparable" cases reported separately.
- **Baselines:** the modal strategy at the most recent prior edition of the event; global parameters with circuit pit loss only; always one-stop; Pirelli prediction where available; the static 2023–2024 procedure (holdout only).

Acceptance criteria require metrics to be produced and compared against baselines. They do not impose accuracy thresholds that cannot be justified before seeing the data, with the single exception of the feasibility gate.

## Open definitions

Deferred definitions (see [Status of definitions](#status-of-definitions)):

- E2 target: the observed quantity (for example the lap-time profile net of a driver-race intercept) and how the common trend is added back for each scenario.
- E3 pace adjustment and placebo construction.
- Abstention handling in each E2–E4 metric (the feasibility gate's handling is fixed above).
- Green-flag pit-loss estimator and its counterfactual reference laps, consistent with the pit-loss measurement window.
- Reference tyre age (initially 2–3 laps; M4).
- Shrinkage estimator and strength (M4).
- Collection procedure and sources for Pirelli pre-race predictions.
- Source of the forecastable track-temperature input, if used.
- Cutoff-gated access-layer design (M2).
- Green-flag lap definition, resolved before any M3 coverage result is computed. It is distinct from a clean modelling lap: a green-flag lap describes race neutralisation and determines the green-flag share used by both eligibility rules, whereas a clean lap is a parameter-level selection that additionally removes pit, first, deleted and outlier laps. The definition must specify:
  - overlap semantics: how a lap that is partly covered by a non-green track-status period is classified;
  - missing or ambiguous track statuses and conflicting race-control messages;
  - whether local (sector) yellow flags make a lap non-green;
  - the denominator of the green-flag share (for example the leader's completed laps or the scheduled race distance).
