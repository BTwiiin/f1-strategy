# Roadmap: F1 tyre-pace forecasting and strategy

## Research questions

1. **Predictive (primary).** How accurately can post-stop stint lap times be forecast 5, 10 and 15 laps ahead for future races? Which model classes and information groups beat persistence and structural baselines under walk-forward evaluation?
2. **Pre-race.** How well can within-stint profiles by compound be predicted before the race?
3. **Model-implied strategy.** How do the strategy rankings implied by the validated models differ from the structural baseline? How robust are they to model class, parameter uncertainty and common-trend sensitivity?
4. **Verifiable outcomes.** What can executed-plan prediction, within-race comparison and reference agreement verify, and what remains unverifiable?

## How the documents divide the work

- **This roadmap:** milestones and acceptance criteria only.
- **Definitions:** [`docs/scope.md`](docs/scope.md), [`docs/forecasting.md`](docs/forecasting.md) and [`docs/evaluation.md`](docs/evaluation.md).
- **Values:** `config/`.

Complexity is added only when development validation shows it is needed.

## Milestones

### M0. Evaluation contract (done; revised before M2)

**Deliverables:**
- Contract documents.
- Versioned TOML configuration.
- Package skeleton.
- CI (ruff, pytest).

**Acceptance:** the contract, including the revision, is committed before any data is ingested.

### M1. Synthetic core (done)

**Deliverables:**
- A lookup-table parameter interface aligned by bootstrap sample.
- Plan enumeration from event rules.
- A deterministic simulator.
- Support labels.
- A synthetic generator with cliff and tyre-management variants.
- The identifiability demonstration.

This is the mathematical baseline. The generator is reused for E1 in M5–M6.

### M2. OpenF1 ingestion

**Deliverables:**
- **Client:** raw JSON cache and request manifest; rate limits, retries, resumable.
- **Endpoints:** for each race, qualifying and practice session of a Grand Prix weekend: `drivers`, `laps`, `stints`, `pit`, `race_control`, `weather`. Races also get `intervals`, `position` and `session_result`. Qualifying also gets `starting_grid` and `session_result`.
- **Rebuild:** an offline, deterministic DuckDB rebuild with `raw_*` tables and typed `stg_*` views that carry `available_at`.
- **Access layer** with two roles:
  - development: 2023–2024 only;
  - holdout: history plus the 2025 records available before each checkpoint, executable only from the frozen commit.
- **Sealed 2025 download:** not parsed, built or inspected before M8.

**Acceptance:**
- The pipeline is validated on one 2024 weekend before the full download.
- The rebuild is offline and deterministic.
- Resume and caching work.
- A coverage report exists per session and endpoint.
- Tests show:
  - development code cannot read 2025;
  - `as_of` hides records after the checkpoint;
  - rewriting future rows does not change earlier views.

### M3. Canonical laps and coverage

**Deliverables:**
- **Typed tables:** for laps, stints, pit stops and track status.
- **Reference tables:** `ref_tyre_nomination`, `ref_event_rules` and `ref_circuit`.
- **`laps_clean`:**
  - per-lap weather, gap ahead and position, as observed;
  - tyre age;
  - flags;
  - one primary exclusion reason.
- **Data tests.**
- **Coverage diagnostics** on 2023–2024.

**Acceptance:**
- Every excluded lap has a reason.
- Coverage is reported by race, driver and compound.

### M4. Exploratory analysis (2023–2024 only)

**Deliverables:**
- **Topics:**
  - race-phase and tyre-age patterns;
  - post-stop level changes;
  - weather;
  - traffic;
  - driver and team effects;
  - practice and qualifying signals;
  - data support;
  - reliability of `tyre_age_at_start`;
  - the stint-order experiment on synthetic data under the shared-intercept model.
- **Notebooks** that call package functions.
- **`docs/modelling_plan.md`:** resolves the definitions deferred to M4 ([`docs/evaluation.md`](docs/evaluation.md#open-definitions)).

**Acceptance:**
- Every deferred decision cites evidence from the analysis.
- `modelling_plan.md` is committed before any model-comparison result is computed.
- All reads go through the development access layer.

### M5. Forecasting harness and baselines

**Deliverables:**
- The T1 origin table with features as of `t0`.
- A walk-forward harness.
- Baselines B0, B1 and B2.
- The pit-loss estimator.
- The estimate of `g`, reported against the fuel reference.
- E1 recovery of B2 on the generator.

**Acceptance:**
- P1 metrics, with coverage and the censoring diagnostic, are reported for 2024.
- Leakage tests cover every feature.

### M6. Model comparison, ablation and uncertainty

**Deliverables:**
- GAM.
- GBM on B2 residuals, with the fallback.
- Feature-group ablation.
- Calibrated intervals by horizon.
- T2.
- Leave-one-circuit-out.

**Acceptance:**
- Every retained model and feature group satisfies the rules in `modelling_plan.md`.
- Failure cases are analysed, not only averages.

### M7. Strategy integration, development evaluation and freeze

**Deliverables:**
- **Strategy inputs:** the retained models feed `ParameterSet`, with an optional race-lap axis.
- **Monte Carlo and decision outputs**, with pace model and trend-grid refits as dimensions.
- **Feasibility gate.**
- **E2–E4.**
- **Final provisional values.**

**Acceptance:**
- Results are reported separately as predictive, model-implied and verifiable outcomes.
- The freeze tag exists before 2025 is read.

### M8. Holdout

**Deliverables:**
- One walk-forward run on 2025 from the frozen commit, including the static benchmark.
- Same-race reference runs.
- The Pirelli comparison.

**Acceptance:**
- Results are reported once, with baselines, coverage, early- and late-season breakdowns, and per-race detail.

### M9. CLI and report

**Deliverables:**
- Commands `ingest`, `build`, `fit`, `forecast`, `simulate` and `evaluate`.
- One reproducible report for a 2025 race.

**Acceptance:** a clean checkout reproduces the report from the raw cache.

## Extensions

Each is considered only after the core milestones:
- a Bayesian hierarchical model;
- an SC/VSC hazard in the Monte Carlo;
- a track-position penalty per stop;
- a circuit-group fallback level;
- schema-drift checks;
- an out-of-distribution test on 2026.
