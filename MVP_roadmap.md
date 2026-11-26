# Roadmap: F1 Dry-Race Strategy Simulator MVP

## Goal

Build a reproducible pre-race simulator that compares dry-weather tyre strategies for a single car.

The MVP should answer:

- Which one-stop or two-stop plans are fastest under stated assumptions?
- How large is the predicted time difference between the leading plans?
- Does the ranking remain stable when degradation, compound delta and pit loss vary within their estimated uncertainty, and when tyre parameters are re-estimated under different common-trend assumptions?

The MVP is a strategy-comparison tool, not a race predictor. Its primary outputs are relative time deltas between plans and the robustness of their ranking, not absolute finishing time or position. It does not claim that any recommended plan is the true optimum.

The guiding principle is the simplest scientifically defensible implementation. Complexity is added only when development validation shows it is needed, not to address problems that have not been observed.

## Data and evaluation period

- Source: OpenF1.
- Historical data: 2023–2025 (one regulation era).
- Storage: DuckDB.
- Primary protocol: walk-forward (expanding-window) evaluation. For each evaluated race, parameters are refitted by the frozen procedure on all data available before that race's prediction cutoff.
- Development validation: walk-forward within 2023–2024, including season cold starts (early 2024 races predicted with no 2024 race data).
- Final holdout: 2025, walk-forward with the frozen procedure, evaluated once (see [Holdout protocol](#holdout-protocol)).
- Secondary benchmark: static procedure, fitted once on 2023–2024 and applied unchanged to all of 2025. It measures the benefit of in-season updating and is declared in the frozen evaluation configuration.
- Secondary test: leave-one-circuit-out.
- Prediction cutoff: only information available before the start of the evaluated race may be used for a prediction.

## Common-trend effect

Lap times contain a trend shared by every car and every plan: fuel burn makes the car faster each lap, and track evolution (rubbering-in, track temperature) shifts lap times further. Neither is observed in OpenF1.

Sign convention:

- `observed_net_stint_slope` (s/lap): the within-stint lap-time slope estimated from data; positive means lap times increase with tyre age.
- `common_trend_gain` (s/lap): the per-lap lap-time improvement common to all plans; `common_trend_gain = fuel_gain + track_evolution_gain`. Positive means the car gets faster each lap independent of tyres.
- `inferred_tyre_degradation = observed_net_stint_slope + common_trend_gain`.

When each stint has a free intercept, the common trend and linear tyre degradation are not separately identifiable: only `observed_net_stint_slope` is observed. The common trend is therefore an explicit external assumption, never a fitted coefficient. A trend that is linear in race lap and identical for all plans is a simplifying assumption, not an established physical fact.

In a green-flag single-car comparison without refuelling, every legal plan shares the same trend, so its direct lap-time contribution cancels and is never added to strategy deltas. The assumption still matters: one-stop and two-stop plans accumulate different total tyre age, so the assumed trend changes inferred degradation and can change the ranking. It enters the simulator only through tyre-parameter sets re-estimated under each common-trend scenario.

Common-trend scenarios form a fixed, uniformly spaced grid:

- fuel bounds from cited external sources (lap-time sensitivity to fuel mass × typical fuel burn per lap), with units and limitations documented;
- widened by an explicitly labelled judgement allowance for track evolution (provisionally ±0.02 s/lap);
- provisional step 0.01 s/lap, with a development-only resolution check at 0.005 s/lap.

The grid range is a set of stated assumptions, not a statistical confidence interval. No probability weights are placed on the grid by default.

---

## MVP scope

Included:

- dry races with predominantly green-flag running;
- a single car without explicit rival interactions;
- slick compounds;
- one-stop and two-stop plans;
- tyre degradation, compound pace difference and green-flag pit-stop loss;
- re-estimation of tyre parameters across a common-trend scenario grid;
- uncertainty, sensitivity and data-support analysis;
- historical validation with a frozen holdout.

Excluded from the MVP:

- live race recommendations;
- traffic, overtaking, undercut and pit-exit position models;
- Safety Car and VSC strategy optimisation;
- wet and changing-weather races;
- retirements, damage and mechanical failures;
- team orders and double-stacking;
- exact tyre-set inventory and tyre condition (for example qualifying wear or heat cycles);
- an LLM interface.

Default tyre assumptions, labelled in every output: each stint starts on a new set and inventory is sufficient for every enumerated plan. The user may supply an initial tyre age per stint; no further tyre-condition modelling is done.

Known consequence of the single-car, pace-only scope: at circuits where track position dominates, the simulator will tend to prefer more stops than teams choose. This is reported as a scope limitation, not tuned away.

### Eligibility

Eligibility is defined separately for each use of a race and is applied by pre-declared, mechanical rules:

- **Prediction availability** depends only on information available before the cutoff (event rules, compound nomination, data support). A pre-race prediction can be produced for a race that later turns out to be ineligible for scoring; the share of predicted races that are scoreable is reported.
- **Parameter-level use** is lap-level: clean-lap rules (M3) remove non-green, pit and invalid laps, so a race with heavy neutralisation still contributes its clean laps.
- **Strategy-level scoring** (E2–E4) requires, provisionally, no wet or intermediate tyre use, no red flag after lap 1, and at least 80% green-flag laps (development-only sensitivity analysis at 70% and 90%).
- **Neutralisation overlap**: a driver's executed plan is excluded from strategy-level scoring when an SC/VSC period overlaps the pit-loss measurement window (in-lap and out-lap) of any of its stops. Excluding stops on laps adjacent to a neutralisation is a sensitivity analysis only; a stop before a neutralisation is not assumed to be anticipated.
- **Minimum sample**: E3 comparisons require at least K = 3 eligible drivers per compared plan class. This is a provisional minimum sample requirement, not evidence of statistical reliability.
- **Insufficient support** for a compound excludes the affected plans or comparisons, not the whole race. A compound with no historical data at comparable conditions (for example C6) is not used unless an explicit, documented prior is supplied.

Races or observations excluded from scoring are retained as documented case studies.

---

## Evaluation design

### Evidence hierarchy

No observed race reveals the optimal strategy, and real strategy choices are confounded by traffic, track position, tyre management and other unobserved factors. Evaluation is therefore layered, and each level supports only the claims listed for it.

| Level | Test | Supports | Does not support |
|---|---|---|---|
| E1 | Optimum recovery and parameter recovery on synthetic data with known ground truth | Correctness of estimators and simulator under the generating assumptions | Validity on real races |
| E2 | Prediction of the realised green-flag time cost of the plan each driver actually executed | Predictive accuracy conditional on the executed plan | Causal claims about alternative plans |
| E3 | Pace-adjusted comparison of different plan classes within the same race | Consistency of predicted plan deltas with observed differences | Unconfounded causal effects |
| E4 | Agreement with Pirelli's published pre-race strategy prediction and with the field's modal strategy | Plausibility relative to expert and revealed-preference references | Accuracy or optimality |

Counterfactual statements (a driver would have been faster on another plan) additionally rely on the structural assumption that the same parameters apply regardless of which driver executes a plan. This assumption is documented and not claimed to be tested.

E2 metrics are reported separately for each common-trend scenario. E2 fit is never used to select or weight scenarios; doing so would estimate the common trend indirectly, which the MVP excludes (see Extensions).

E3 controls:

- a placebo test applying the same pace adjustment to drivers on the same plan class; the residual spread defines the minimum plan delta that counts as evidence;
- pre-declared sensitivity analyses (alternative pace baselines, exclusion of traffic-dominated or position-changing races);
- comparisons restricted to plans within data support.

E4: an external reference plan (Pirelli or modal) that is unsupported by the data is marked "not comparable", not counted as disagreement.

### Same-race reference mode

A diagnostic mode in which tyre and pit parameters are cross-fitted on the evaluated race itself, excluding the target driver. It is never used to produce recommendations.

It does not provide ground-truth parameters. It is interpreted only through an error ladder:

`noise floor ≤ same-race reference ≤ history-based prediction ≤ naive baseline`

- Failure with same-race parameters indicates model-form or simulator error, or noise.
- Success with same-race parameters but failure with history-based parameters indicates that parameter prediction is the bottleneck.
- Success with same-race parameters does not validate the simulator by itself.
- Results remain conditional on the common-trend scenario.

The noise floor is estimated by split-half refits (for example odd vs even laps).

### Holdout protocol

- All model selection uses 2023–2024 only: model shape, cleaning rules, support thresholds, shrinkage procedure, common-trend grid, eligibility rules, decision rules and evaluation criteria.
- What is frozen is the procedure (model specification, hyperparameters, feature definitions, cleaning rules, shrinkage, evaluation criteria), not a fixed parameter set. The 2025 walk-forward refits parameters before each race using only data before its cutoff.
- The frozen configuration, including the static secondary benchmark, is tagged in version control before any 2025 data is read by modelling code.
- 2025 data is stored separately and is readable only through the cutoff-gated access layer, and only by the holdout runner: for an evaluated event, earlier races and pre-race sessions may be used for prediction, and that race's data only for scoring. Development code cannot read 2025 data. Both properties are enforced by tests, which are the primary guarantee of holdout isolation.
- The 2025 evaluation, including same-race reference runs and the static benchmark, is executed once from the tagged configuration. No manual tuning occurs between holdout races.
- Any change after the holdout run produces a new version, and the holdout is marked as already consumed for that version.

### Metrics

- Parameter level: stint-level cumulative time-loss error, pit-loss error, interval score and coverage, error by circuit and compound, early-season vs late-season error (season cold starts).
- Plan level (E2/E3): error on predicted vs observed plan deltas, pairwise ranking accuracy, placebo spread.
- Reference level (E4): agreement rates with Pirelli predictions and the modal strategy, with "not comparable" cases reported separately.
- Baselines: the modal strategy at the most recent prior edition of the event; global parameters with circuit pit loss only; always one-stop; Pirelli prediction where available; the static 2023–2024 procedure (holdout only).

Acceptance criteria require metrics to be produced and compared against baselines. They do not impose accuracy thresholds that cannot be justified before seeing the data, with the single exception of the feasibility gate evaluated in M5, whose decision rule is fixed in M0.

### Provisional values and freeze points

Two freeze points apply:

1. **M0 (before any data ingestion):** splits, walk-forward protocol, holdout protocol, the feasibility-gate rule and its threshold, the structure of eligibility, support and decision rules, and the common-trend grid with its sources.
2. **M6 (before 2025 is read):** final values of provisional thresholds, selected on 2023–2024 only.

Values marked provisional (eligibility thresholds, support thresholds, K, track-evolution allowance, grid resolution, decision-rule thresholds) may be adjusted on development data up to the M6 freeze. They are assumptions or decision criteria, not empirically established constants or probabilities. The feasibility-gate thresholds (τ_gate and the 50% pass share) are not adjusted after M0.

### Open definitions

The following must be specified and committed before the milestone that first uses them, and in every case before any development results for the affected evaluation level are computed:

- E2 target: the observed quantity (for example the lap-time profile net of a driver-race intercept) and how the common trend is added back for each scenario.
- E3 pace adjustment and the placebo construction.
- Abstention rules: when the simulator declines to recommend (for example no supported plan), and how abstentions enter each metric.
- Green-flag pit-loss estimator and its counterfactual reference laps, consistent with the in-lap/out-lap window used for eligibility.
- Collection procedure and sources for Pirelli pre-race predictions.
- Source of the forecastable track-temperature input, if used.
- Cutoff-gated access-layer design (M2).

---

## Core milestones

### M0. Evaluation contract and project skeleton

**Objective:** fix scope, splits and evaluation rules before any data is examined.

**Depends on:** nothing.

**Deliverables:**

- `docs/scope.md`: assumptions, exclusions, prediction cutoff, default tyre assumptions, common-trend sign convention.
- `docs/evaluation.md`: evidence hierarchy, metric definitions, baselines, same-race reference mode, walk-forward and holdout protocol, freeze points, open definitions.
- Eligibility rules for prediction, parameter-level use and strategy-level scoring, including the neutralisation-overlap rule and the pit-loss measurement window (in-lap and out-lap).
- Definition of data support (see M1) with provisional thresholds.
- Common-trend grid with cited external sources for the fuel component, units and limitations, and the labelled track-evolution allowance.
- Feasibility-gate decision rule and threshold (evaluated in M5).
- Decision rule and robust/fragile criteria for M5.
- Precise definitions of all outputs listed in M5.
- Package layout, `pyproject.toml`, Ruff, pytest, continuous integration.
- `.gitignore` covering DuckDB files, raw cache, generated reports and tool caches.
- Versioned TOML configuration (read with the standard-library `tomllib`): `config/evaluation.toml` (splits, eligibility, feasibility gate, decision rule), `config/model.toml` (support thresholds, common-trend grid, shrinkage), `config/events/*.toml` (event rules).

**Acceptance criteria:**

- CI runs `ruff` and `pytest` successfully.
- Splits, walk-forward and holdout protocol, eligibility rules, support definition, common-trend grid and feasibility rule are committed before any data ingestion.

---

### M1. Synthetic core

**Objective:** establish the mathematical core and the parameter interface independently of real data.

**Depends on:** M0.

**Deliverables:**

- Model-agnostic parameter interface based on lookup tables:
  - per compound, a pace offset at an explicit reference tyre age;
  - per compound, a per-lap tyre-age effect indexed by integer tyre age, zero at the reference age;
  - pit loss as samples;
  - every parameter set is an array over joint sample IDs, so pace offsets, all compounds' degradation tables and pit-loss samples stay aligned by bootstrap sample;
  - every parameter set is tagged by common-trend scenario, fallback level and provenance.
- Per-lap tyre-age effects are the only stored degradation parameters; cumulative stint losses are derived by summation and never stored or added separately, which prevents double counting.
- Plan representation: starting compound, ordered compound sequence, pit-lap sequence, optional initial tyre age per stint.
- Exhaustive enumeration of legal one-stop and two-stop plans, with event rules loaded from configuration (mandatory compounds, maximum stint length, mandatory stops), not hard-coded.
- Deterministic simulator returning `relative_plan_time = compound effect + tyre-age effect + pit losses` with a breakdown by stint and factor.
- Support labelling of every plan:
  - shape support: a compound at tyre age `a` is supported when clean laps at that age come from at least S distinct stints across at least R distinct races, pooled over circuits (provisionally S = 10, R = 3);
  - support is contiguous from the reference age upward; ages below the reference age, where early-stint laps are excluded by the clean-lap rule, are covered by the reference-age anchor and are not counted as gaps;
  - circuit support: the circuit has clean laps from at least R_c races (provisionally R_c = 1). This records the presence of circuit-level data; the reliability of circuit-specific estimates is expressed separately through shrinkage and parameter uncertainty;
  - `supported`: shape and circuit support hold for every lap of the plan;
  - `extrapolated`: within E laps beyond the longest contiguous supported tyre age (provisionally E = 3), or circuit information only at the global fallback level;
  - `unsupported`: beyond the margin, or a compound without usable data; not enumerated by default.
- Synthetic lap-time generator with known parameters: fuel burn and track evolution (common trend), degradation, noise, driver pace offsets, and a pit policy that ends stints before a degradation cliff (right-censoring).
- Misspecified generator variants: late-stint cliff (non-linear degradation) and tyre-management pace reduction on long stints.
- Identifiability demonstration with least squares and free stint intercepts: the common trend and degradation are not separately recoverable; partial recovery only under added structural assumptions.

**Acceptance criteria:**

- The simulator recovers analytically known optima from true parameters and rejects illegal plans.
- Support labels behave correctly at boundaries, including the reference age and contiguity gaps.
- The identifiability demonstration is reproducible and documented.

---

### M2. OpenF1 ingestion

**Objective:** reproducible, offline-rebuildable storage of the minimal data required by the core.

**Depends on:** M0.

**Deliverables:**

- OpenF1 client with raw JSON cache, rate limiting, retries with exponential backoff and resumable downloads.
- Request manifest: URL, parameters, retrieval time, row count, response hash, status.
- Endpoints: `meetings`, `sessions`, `drivers`, `laps`, `stints`, `pit`, `race_control`.
- `raw_*` tables storing responses unchanged with `_loaded_at`, `_source_url`, `_response_hash`.
- Separate storage for 2025 data.
- Cutoff-gated data-access layer enforcing the prediction cutoff and the holdout protocol for walk-forward evaluation.
- One idempotent command rebuilding DuckDB from the raw cache without network access.

**Acceptance criteria:**

- The database rebuilds offline and deterministically from the cache.
- Interrupted downloads resume; duplicate requests are served from the cache.
- A coverage report lists missing endpoints per session.
- Tests demonstrate that development code paths cannot read 2025 data and that prediction paths cannot read post-cutoff data, including within a walk-forward season.

---

### M3. Canonical race laps and data coverage

**Objective:** a clean, auditable lap table and an early view of data coverage for strategy comparison.

**Depends on:** M2.

**Deliverables:**

- Typed tables for meetings, sessions, drivers, laps, stints, pit stops and race control.
- Reference tables:
  - `ref_tyre_nomination`: relative `SOFT/MEDIUM/HARD` to absolute C0–C6 per event;
  - `ref_event_rules`: scheduled distance, event-specific tyre rules;
  - `ref_circuit`: stable circuit identity, recorded layout versions and significant surface changes. A major layout change may be treated as a separate circuit by a documented decision; resurfacing is recorded but does not automatically discard historical circuit information.
- Separate fields for scheduled and actual race distance; simulation distance is never derived from the winner's lap count.
- Track-status periods (green, yellow, SC, VSC, red flag) derived from timestamped race-control messages.
- `laps_clean`: one row per driver and lap with lap and sector times, relative and absolute compound, stint ID, tyre age, pit-in/pit-out flags, track status, deleted-lap and outlier flags, exclusion reason and source-quality flags.
- Tyre age counts all laps on a set, including neutralised laps. Stints containing SC/VSC laps are flagged.
- Configurable clean-lap rule, initially excluding lap 1, pit-in and pit-out laps, non-green periods, deleted or missing laps and robust outliers. Rows are flagged, never deleted.
- Data tests: duplicate keys, overlapping stints, impossible tyre ages, missing stint assignments, pit/stint inconsistencies.
- Coverage diagnostics on 2023–2024: support profiles by compound, tyre age and circuit, and distribution of observed net stint slopes.

**Acceptance criteria:**

- Every included race has a reproducible clean-lap table and every excluded lap has a reason.
- A quality report shows usable-lap coverage by race, driver and compound.

---

### M4. Parameter estimation

**Objective:** history-based tyre and pit parameters with provenance and joint uncertainty, plus the same-race reference mode.

**Depends on:** M1 (parameter interface and synthetic generator), M3.

**Deliverables:**

- Additive tyre model: absolute compound (C0–C6) as the main effect, plus a circuit effect and a season effect, with driver-race effects. Relative compound labels are used for event rules and presentation. Interactions are introduced only if justified by development validation.
- Degradation shapes compared: linear, piecewise-linear and low-complexity spline.
- Compound delta defined at the common reference tyre age (initially 2–3 laps).
- Green-flag pit loss by circuit from a counterfactual reference built from nearby clean laps, using the in-lap/out-lap window fixed in M0.
- Shrinkage of circuit effects towards global estimates (fallback levels: circuit, global).
- Season effect shrunk towards the previous season by simple regularisation, updating as races accumulate; the procedure is frozen before the holdout.
- Walk-forward fitting: each evaluated race is predicted from data before its cutoff.
- Re-estimation of all tyre parameters for each point of the common-trend grid, stored by scenario.
- Joint uncertainty via cluster bootstrap by race, so parameter samples preserve their correlation across compounds and pit loss.
- Support profiles (clean laps, stints and races by tyre age, compound and circuit) exported with each parameter set.
- Same-race reference mode (cross-fitted, diagnostic only).
- Track temperature used only as a forecastable input; realised race temperature is not used in pre-race predictions.
- Estimator-recovery experiments (E1) on the M1 generator, including both misspecified variants, with documented bias.
- Development-only sensitivity of parameter estimates to excluding stints flagged as neutralised.

**Acceptance criteria:**

- Model shape is selected by walk-forward validation on 2023–2024, not by requiring `soft > medium > hard`.
- Models are compared against simple baselines on held-out clean stints, including season cold starts.
- Estimator-recovery tests exist for each generator variant.
- Every parameter records its fallback level, common-trend scenario and uncertainty.
- Every 2025 event can receive a parameter set produced without its own race data.

---

### M5. Uncertainty, decision outputs and feasibility gate

**Objective:** turn parameter uncertainty into decision-relevant, honestly labelled outputs, and check that they are decision-useful before full evaluation.

**Depends on:** M1, M4.

**Deliverables:**

- Monte Carlo over joint bootstrap parameter samples within each common-trend scenario.
- Per plan and scenario: median relative time, 50% and 90% intervals, `P(fastest | scenario)`, expected regret, 90th-percentile regret (downside risk) relative to the best plan in each sample.
- Across the grid: worst-case scenario-specific expected regret, rank stability, and approximate break-even common-trend values at which each pair of leading plans swaps order (linearly interpolated between grid points and labelled as approximate).
- No probability weights on the grid by default. An aggregated probability is optional, only under an explicit documented prior, and labelled as prior-dependent.
- Support label for every plan; recommendations drawn from supported plans by default; explicit abstention when no supported plan exists.
- `constrained optimum` flag when the best supported plan lies on the support boundary.
- Decision rule: within each scenario, recommend the supported plan with minimum expected regret. Label the recommendation `robust` if it is the minimum-regret plan in at least 80% of grid points and its 90th-percentile regret is at most τ (provisionally 5 s); otherwise `fragile`. Both thresholds are provisional decision criteria, not statistically established thresholds or probabilities.
- Sensitivity of labels to grid resolution and to support thresholds.
- Feasibility gate on 2023–2024 walk-forward outputs, using the rule fixed in M0:
  - for each eligible development race, the 90th-percentile regret of the recommended plan at the central common-trend scenario; the race is decision-useful when it is at most τ_gate = 5 s, fixed in M0 and not changed if the decision-rule τ is later adjusted;
  - the denominator is all eligible development races, including races where the simulator abstains for lack of supported plans; abstentions count as not decision-useful;
  - the gate passes when at least 50% of eligible development races are decision-useful;
  - reported separately: coverage (share of races with a supported recommendation), decision usefulness conditional on coverage, estimation precision (interval widths) and assumption sensitivity (share of races whose recommendation changes across the common-trend grid).
- The gate measures internal decision usefulness under the model assumptions, not empirical strategy correctness, which is assessed by E2–E4.

**Acceptance criteria:**

- Every recommendation reports uncertainty, common-trend stability, support status and its robust/fragile label.
- Outputs are reproducible with documented random seeds.
- The feasibility gate is evaluated with the M0 rule and its outcome is documented. A negative outcome is first diagnosed (coverage, precision or assumption sensitivity) and reported as a finding; any change of direction is a documented, versioned decision, not an automatic fallback.

---

### M6. Development evaluation

**Objective:** evaluate the full pipeline on 2023–2024 and freeze the configuration.

**Depends on:** M4, M5.

**Deliverables:**

- E1–E4 evaluation on walk-forward development splits, including the same-race reference error ladder and the E3 placebo test.
- Leave-one-circuit-out results.
- Development-only sensitivity analyses declared above (eligibility thresholds, adjacent-lap neutralisation exclusion, neutralised stints, grid resolution, support thresholds).
- Failure-case analysis, not only aggregate metrics.
- Final values of provisional thresholds.
- Frozen configuration, including the static benchmark, tagged in version control.

**Acceptance criteria:**

- All metrics and baselines from the evaluation design are reported.
- All open definitions are resolved.
- The configuration tag exists before 2025 data is read.

---

### M7. Holdout evaluation

**Objective:** a single, final evaluation on 2025.

**Depends on:** M6.

**Deliverables:**

- One walk-forward run of the frozen procedure on eligible 2025 races, including same-race reference runs and the static 2023–2024 benchmark.
- Eligibility outcome and exclusion reason for every 2025 race.
- Pirelli pre-race predictions collected for comparison (E4).

**Acceptance criteria:**

- Results are reported once, with baselines, interval coverage, early- vs late-season breakdown and per-race detail.
- Excluded races are documented as case studies.

---

### M8. CLI and reproducible report

**Objective:** a reproducible end-to-end workflow and a readable result.

**Depends on:** M7.

**Deliverables:**

- CLI commands: `ingest`, `build`, `fit`, `simulate`, `evaluate`.
- `simulate` accepts an event, allowed compounds, optional initial tyre ages and a common-trend scenario or grid.
- Readable table and structured JSON output containing data/model version, prediction cutoff, assumptions (including default tyre assumptions), ranked plans, deltas and intervals, conditional fastest-plan probabilities, regret, approximate break-even common-trend values, support labels, factor contributions, warnings and fallback levels.
- One reproducible Markdown or HTML report for a selected 2025 race.

**Acceptance criteria:**

- A clean checkout can rebuild the data, fit parameters, simulate an eligible race and reproduce the same report.

---

## MVP success criteria

1. No post-cutoff information is used in a pre-race prediction, and this is enforced by tests.
2. Legal dry one-stop and two-stop plans are ranked for every eligible event, or an abstention is reported.
3. Outputs are relative times with uncertainty, not unsupported absolute precision.
4. Common-trend assumptions are explicit, varied across a documented grid, and reported through conditional results and approximate break-even values; the common trend is cancelled from strategy comparisons.
5. Every parameter carries provenance, fallback level and uncertainty.
6. Recommendations are restricted to data-supported plans by default, and extrapolation is labelled.
7. Evaluation follows the evidence hierarchy, with baselines, and the 2025 holdout is evaluated once.
8. The system reports when data are insufficient or a race violates MVP assumptions.
9. The full result is reproducible from the raw cache with one documented workflow.

---

## Extensions

Considered only after the core milestones pass their acceptance criteria:

1. Same-weekend pre-race data: Sprint race results, then FP2 long runs.
2. Bayesian hierarchical parameter model with posterior sampling.
3. Partially identified common-trend model using between-stint intercepts with a track-evolution prior.
4. Circuit-group fallback level, if development validation shows structured errors at sparsely observed circuits.
5. Track-position penalty per additional stop.
6. Safety Car / VSC hazard in the Monte Carlo.
7. Traffic filtering from `intervals` and weather effects from `weather`.
8. Schema-drift checks and team/driver identity reference tables.
9. Out-of-distribution test on a later regulation era.
10. Live replay mode and an LLM interface for explaining structured results.
