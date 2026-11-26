# Scope and modelling assumptions

This document defines what the simulator models, what it excludes and the conventions every component follows. The evaluation contract is in [`evaluation.md`](evaluation.md); the common-trend scenario grid and its sources are in [`common_trend.md`](common_trend.md). Numerical values live in the versioned configuration under `config/`.

## Purpose

The simulator compares dry-weather tyre strategies for a single car before a race. Its outputs are relative time differences between plans and the robustness of their ranking under parameter uncertainty and common-trend assumptions. It does not predict absolute race time, finishing position or the true optimal strategy.

## Data

- Source: OpenF1, seasons 2023–2025 (one regulation era), stored in DuckDB.
- Raw responses are stored unchanged; derived tables are rebuilt from the raw cache.
- Season roles (burn-in, development, holdout) are defined in [`evaluation.md`](evaluation.md#splits-and-walk-forward-protocol).

## Included

- Dry races with predominantly green-flag running.
- A single car, without explicit rival interactions.
- Slick compounds.
- One-stop and two-stop plans (`config/model.toml`: `plans.stop_counts`).
- Tyre degradation, compound pace difference and green-flag pit-stop loss.
- Re-estimation of tyre parameters across a common-trend scenario grid.
- Parameter uncertainty, sensitivity and data-support analysis.
- Historical validation with a frozen holdout.

## Excluded

- Live race recommendations.
- Traffic, overtaking, undercut and pit-exit position models.
- Safety Car and VSC strategy optimisation.
- Wet and changing-weather races.
- Retirements, damage and mechanical failures.
- Team orders and double-stacking.
- Exact tyre-set inventory and tyre condition (for example qualifying wear or heat cycles).
- An LLM interface.

Known consequence of the single-car, pace-only scope: at circuits where track position dominates, the simulator will tend to prefer more stops than teams choose. This is reported as a scope limitation, not tuned away.

## Prediction cutoff

A prediction for a race may use only information available before that race's start: earlier races, pre-race sessions of the same event, event rules and the tyre nomination. Information from the race itself is used only for scoring. The MVP models do not use same-weekend session data; it is permitted by the cutoff but listed as an extension.

## Strategy representation

A plan consists of a starting compound, an ordered compound sequence, a pit-lap sequence and an optional initial tyre age per stint. Legal plans are enumerated exhaustively from the event rules in `config/events/` (season defaults in `default.toml`, event-specific overrides with cited sources). Rules are never hard-coded.

Compounds are modelled by their absolute designation (C0–C6). Relative labels (`SOFT`, `MEDIUM`, `HARD`) are used for event rules and presentation.

## Default tyre assumptions

Labelled in every output:

- every stint starts on a new set unless the user supplies an initial tyre age;
- tyre inventory is sufficient for every enumerated plan;
- tyre age counts all laps on a set, including neutralised laps; stints containing SC/VSC laps are flagged;
- no further tyre-condition modelling.

## Relative time model

For a plan `p`:

```
relative_plan_time(p) = compound_effect(p) + tyre_age_effect(p) + pit_losses(p)
```

- `compound_effect`: sum over laps of the compound pace offset at the reference tyre age.
- `tyre_age_effect`: sum over laps of the per-lap tyre-age effect at the lap's tyre age (zero at the reference age). Only per-lap effects are stored; cumulative stint losses are derived by summation and never added separately.
- `pit_losses`: sum of green-flag pit losses.

The shared lap-time trend is not part of this sum (see below).

## Common trend

Lap times contain a trend shared by every car and every plan: fuel burn makes the car faster each lap, and track evolution shifts lap times further. Neither is observed in OpenF1.

Sign convention (all quantities in s/lap):

- `observed_net_stint_slope`: the within-stint lap-time slope estimated from data; positive means lap times increase with tyre age.
- `common_trend_gain = fuel_gain + track_evolution_gain`: the per-lap lap-time improvement common to all plans; positive means the car gets faster each lap independent of tyres.
- `inferred_tyre_degradation = observed_net_stint_slope + common_trend_gain`.

With a free intercept per stint, the common trend and linear tyre degradation are not separately identifiable: only `observed_net_stint_slope` is observed. The common trend is therefore an explicit external assumption, never a fitted coefficient. A trend that is linear in race lap and identical for all plans is a simplifying assumption, not an established physical fact.

In a green-flag single-car comparison without refuelling, every legal plan shares the same trend, so its direct lap-time contribution cancels and is never added to strategy deltas. The assumption still matters: one-stop and two-stop plans accumulate different total tyre age, so the assumed trend changes inferred degradation and can change the ranking. It enters the simulator only through tyre-parameter sets re-estimated under each scenario of the grid defined in [`common_trend.md`](common_trend.md).

## Parameter model

- Tyre model: absolute compound main effect plus circuit effect and season effect, additive, with driver-race effects. Interactions are added only if development validation justifies them.
- Fallback levels: circuit estimates shrunk towards the global estimate; season effect shrunk towards the previous season. No circuit-group level in the MVP.
- Every parameter set is tagged with its common-trend scenario, fallback level and provenance, and is aligned across components by joint bootstrap sample ID.
