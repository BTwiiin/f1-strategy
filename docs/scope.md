# Scope and modelling assumptions

Where things are defined:
- prediction tasks: [`forecasting.md`](forecasting.md);
- evaluation: [`evaluation.md`](evaluation.md);
- fuel sources and the common-trend grid: [`common_trend.md`](common_trend.md);
- numerical values: `config/`.

## Purpose

The project studies tyre-dependent race pace in dry Formula 1 races on real data. Strategy optimisation is its main application. It produces three kinds of result, and they are never treated as equivalent:

1. **Predictive performance.** Temporal out-of-sample forecasts of stint lap times. These can be checked against observed laps.
2. **Model-implied strategy comparisons.** Plan rankings produced by the simulator from the validated models. They depend on stated assumptions and cannot be checked directly.
3. **Empirically verifiable decision outcomes.** Evidence levels E2–E4. These are partial and confounded.

The project's value does not depend on the data supporting (2). Pit timing and compound choice are endogenous team decisions, so predictive validity does not establish that plan comparisons are causally valid.

## Data

- Source: OpenF1, Grand Prix weekends 2023–2025 (one regulation era).
  - Sessions used: race, qualifying, practice.
  - Excluded: sprint sessions and 2026.
- Raw responses are stored unchanged; derived tables are rebuilt from the raw cache.
- Season roles: [`evaluation.md`](evaluation.md#splits).

## Included and excluded

**Included:**
- dry races with mostly green-flag running;
- a single car;
- slick compounds;
- one-stop and two-stop plans (`plans.stop_counts`);
- compound pace, tyre-age effects, the race-lap trend and pit loss;
- driver, team, circuit, weather, traffic and same-weekend information, as observed at the information checkpoint;
- uncertainty, data support and sensitivity analysis.

**Excluded:**
- live data;
- models of interaction with rivals (undercut, overtaking, pit-exit position);
- SC/VSC strategy optimisation;
- wet or changing-weather races;
- retirements and damage;
- team orders;
- tyre inventory and set condition;
- an LLM interface.

Known consequence: at circuits where track position dominates, the simulator will tend to prefer more stops than teams choose. This is reported as a limitation, not tuned away.

## Information checkpoints

- **Pre-race:** the race start. Usable information: earlier races, earlier sessions of the same event, event rules and tyre nomination.
- **In-race:** the forecast origin `t0` ([`forecasting.md`](forecasting.md)). This is a historical replay only.
- **Availability of a record (`available_at`)** is reconstructed from its on-track timestamp. It approximates what a team could know at that moment; it is not the time the data was published. A record is usable at checkpoint `t` only if `available_at < t`. When availability cannot be reconstructed, the record is excluded rather than given an estimated time.
- Information after the checkpoint is used only for scoring.

## Strategy representation

A plan is a starting compound, an ordered compound sequence, a pit-lap sequence and an optional initial tyre age per stint. Legal plans are enumerated from event rules in `config/events/`; rules are never hard-coded.

- **Compounds:** modelled by absolute designation (C0–C6). Relative labels (`SOFT/MEDIUM/HARD`) are used for event rules and presentation.
- **Tyre age:** counts every lap on a set, including neutralised laps. The first lap on a new set has age 1. The mapping from OpenF1 stint fields to this convention is verified in M3.
- **Pit lap:** the in-lap; the next stint starts with the out-lap. Pit laps are strictly increasing within `[1, race_laps − 1]`.
- **Plan identifier:** for example `C3[0]-C2[0]@20` (compounds with initial ages, then pit laps).
- **Initial age:** only the starting set may have a non-zero initial age.
- **Stint limits:** `max_stint_laps` caps a stint; `max_set_age_laps` caps the age of a set.
- **Default tyre assumptions, labelled in every output:** new sets unless an initial age is supplied; sufficient inventory; no further tyre-condition modelling.

## Pace model

Structural model (baseline B2) for driver `i` in race `r` on lap `l`, compound `c`, tyre age `a`:

```
lap_time = μ_ir + δ_c + f_c(a) − g·l + ε
```

- `μ_ir` is a driver-race intercept shared by all stints. It carries the pace level across pit stops.
- `δ_c` is the compound pace offset at the reference tyre age.
- `f_c` is the tyre-age effect, zero at the reference age.
- `g` is the common trend.
- Circuit and season effects are additive, and shrunk towards the global estimate and the previous season respectively.
- Richer models, which extend B2 rather than replace it, are listed in [`forecasting.md`](forecasting.md#model-ladder).

**Strategy layer (M1 simulator).** For models without race-lap interactions:

```
relative_plan_time = compound_effect + tyre_age_effect + pit_losses
```

- Only per-lap effects are stored; cumulative stint losses are derived.
- A **pit loss** is the incremental time of a stop relative to a normal in-lap and out-lap on the same tyres, added once per stop.
- Models with race-lap terms are evaluated on a lap grid instead.

## Common trend

Sign convention, in s/lap:
- `common_trend_gain = fuel_gain + track_evolution_gain`; positive means the car gets faster each lap.
- `inferred_tyre_degradation = observed_net_stint_slope + common_trend_gain`.

The observed net stint slope is never conflated with degradation.

**Estimation.**
- With free stint intercepts, `g` and degradation are not separable ([`identifiability.md`](identifiability.md)).
- B2 estimates `g` through the shared intercept: the tyre-age reset at each stop happens at a different race lap.
- This identification depends on that assumption. Tyre management biases it, and the bias does not show up in on-policy prediction error.
- The fuel range in [`common_trend.md`](common_trend.md) is a plausibility reference for the fuel component, not a validation criterion for `g`.

**In strategy comparisons.**
- The trend's direct contribution is identical for every plan and cancels.
- It still matters through inferred degradation.
- Strategy outputs therefore also refit tyre parameters with `g` fixed at each point of the sensitivity grid.

## Stint order

- **Without race-lap interactions:** plans that differ only in stint order have identical times. They are reported as model-equivalent ([`evaluation.md`](evaluation.md#model-equivalent-plans)).
- **Phase-aware models** can produce order differences. These are reported as model-implied, together with whether the phase term passed the ablation. They are never presented as evidence that one order is faster ([`stint_order.md`](stint_order.md)).
