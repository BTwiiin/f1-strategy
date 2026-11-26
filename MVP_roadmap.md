# Roadmap: F1 Dry-Race Strategy Simulator MVP

## Goal

Build a reproducible pre-race simulator that compares dry-weather tyre strategies for a single car.

The MVP should answer:

- Which one-stop or two-stop plans are fastest under stated assumptions?
- How large is the predicted time difference between the leading plans?
- Does the ranking remain stable when degradation, compound delta and pit loss vary within their estimated uncertainty, and when tyre parameters are re-estimated under different common-trend assumptions?

The MVP is a strategy-comparison tool, not a race predictor. Its primary outputs are relative time deltas between plans and the robustness of their ranking, not absolute finishing time or position. It does not claim that any recommended plan is the true optimum.

The guiding principle is the simplest scientifically defensible implementation. Complexity is added only when development validation shows it is needed, not to address problems that have not been observed.

## Contract documents

The normative project contract is in `docs/`; this roadmap lists milestones, dependencies, deliverables and acceptance criteria only.

- [`docs/scope.md`](docs/scope.md): data, included and excluded scope, prediction cutoff, strategy representation, default tyre assumptions, relative time model, common-trend sign convention and identifiability.
- [`docs/common_trend.md`](docs/common_trend.md): sources and limitations of the fuel component, track-evolution allowance and the common-trend scenario grid.
- [`docs/evaluation.md`](docs/evaluation.md): splits and walk-forward protocol, holdout protocol, freeze points, eligibility, data support, decision outputs and decision rule, feasibility gate, evidence hierarchy, same-race reference mode, metrics, baselines and open definitions.

Numerical values are in the versioned configuration under `config/`, each marked fixed, provisional or development-only.

---

## Core milestones

### M0. Evaluation contract and project skeleton

**Objective:** fix scope, splits and evaluation rules before any data is examined.

**Depends on:** nothing.

**Deliverables:**

- `docs/scope.md`: assumptions, exclusions, prediction cutoff, default tyre assumptions, common-trend sign convention.
- `docs/common_trend.md`: common-trend grid with cited external sources for the fuel component, units and limitations, and the labelled track-evolution allowance.
- `docs/evaluation.md`: splits, walk-forward and holdout protocol, freeze points, eligibility rules (including the neutralisation-overlap rule and the pit-loss measurement window), data-support definition with provisional thresholds, precise definitions of the M5 outputs, decision rule and robust/fragile criteria, feasibility-gate rule and thresholds, evidence hierarchy, metrics, baselines, same-race reference mode, open definitions.
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
- Support labelling of every plan (`supported`, `extrapolated`, `unsupported`) as defined in `docs/evaluation.md` (Data support).
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

- Model shape is selected by walk-forward validation on the development split, not by requiring `soft > medium > hard`.
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
- Decision outputs as defined in `docs/evaluation.md` (Decision outputs): per plan and scenario, intervals, `P(fastest | scenario)`, expected and 90th-percentile regret against supported legal plans; across the grid, a minimax-expected-regret headline recommendation alongside scenario-specific recommendations, grid stability (minimum-regret share, ranks) and approximate break-even values; no probability weights on the grid by default.
- Support label for every plan; recommendations drawn from supported plans; explicit abstention when no supported plan exists; constrained-optimum diagnostics (`support_boundary_hit`, `extrapolated_plan_outperforms`).
- Decision rule and robust/fragile label, with sensitivity of labels to grid resolution and to support thresholds.
- Feasibility gate on the 2024 walk-forward outputs, using the rule, gate eligibility and gate support thresholds fixed in M0 (`docs/evaluation.md`, Feasibility gate). It measures internal decision usefulness under the model assumptions, not empirical strategy correctness, which is assessed by E2–E4.

**Acceptance criteria:**

- Every recommendation reports uncertainty, common-trend stability, support status and its robust/fragile label.
- Outputs are reproducible with documented random seeds.
- The feasibility gate is evaluated with the M0 rule and its outcome is documented. A negative outcome is first diagnosed (coverage, precision or assumption sensitivity) and reported as a finding; any change of direction is a documented, versioned decision, not an automatic fallback.

---

### M6. Development evaluation

**Objective:** evaluate the full pipeline on the development split (2023 burn-in, 2024 scored targets) and freeze the configuration.

**Depends on:** M4, M5.

**Deliverables:**

- E1–E4 evaluation on walk-forward development splits, including the same-race reference error ladder and the E3 placebo test.
- Leave-one-circuit-out results.
- Development-only sensitivity analyses declared in `docs/evaluation.md` (eligibility thresholds, adjacent-lap neutralisation exclusion, neutralised stints, grid resolution, support thresholds).
- Failure-case analysis, not only aggregate metrics.
- Final values of provisional thresholds.
- Frozen configuration, including the static benchmark, tagged in version control.

**Acceptance criteria:**

- All metrics and baselines defined in `docs/evaluation.md` are reported.
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
