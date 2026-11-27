# Stint order and race-phase interactions: assessment

Status: assessment of a candidate extension. Not part of the evaluation contract and not part of the MVP. The baseline model is stint-order invariant ([`scope.md`](scope.md#stint-order-invariance-limitation)). This document assesses whether a development-data experiment with tyre × race-phase interactions is worth running, and what it would require, before any implementation is proposed.

## Candidate model

Per clean lap, with `a` the tyre age, `l` the race lap and `s` the stint:

```
lap_time = α_s + d_c·a + q_c·a² + γ_c·a·l + β_c·l − g·l − h·l² + ε
```

- `q_c`: curvature of degradation (age-only, order-invariant).
- `γ_c`: tyre-age × race-phase interaction. Degradation rate changes with race lap, for example through fuel mass or track evolution.
- `β_c`: compound × race-phase interaction. Compound pace changes with race lap.
- `g`, `h`: linear and quadratic common trend, shared by all plans. In the baseline, `h = 0` by assumption ([`scope.md`](scope.md#common-trend)).

The baseline is the special case `γ_c = β_c = 0` (and a linear trend). Only `γ_c` and `β_c` make predicted plan times depend on stint order. The common-trend terms add the same amount to every plan and cancel.

## Identifiability

Within a stint, `l = a + m_s`, with `m_s` = start lap − 1 − initial tyre age (constant within the stint). Substituting:

```
lap_time = α'_s + [d_c + β_c − g + (γ_c − 2h)·m_s]·a + (q_c + γ_c − h)·a² + ε
```

With free stint intercepts, the data identify per compound only three quantities:

- `d_c + β_c − g`, the net linear slope;
- `γ_c − 2h`, from how the slope varies with the stint's position `m_s`;
- `q_c + γ_c − h`, the curvature.

Consequences:

1. **`β_c` is not identified at all.** It enters only through the net slope, exactly like the linear common trend. Estimating it requires between-stint information. The structural assumption that provides it is fragile under misspecification ([`identifiability.md`](identifiability.md)).
2. **`γ_c` is identified only up to the trend curvature `h`.** A linear-trend assumption (`h = 0`) yields `γ̂_c = γ_c − 2h`. Only differences `γ_c − γ_c'` between compounds are identified without assumptions about `h`. A numerical check (free stint intercepts, simulated stints at varied race phases) confirmed this: the design with `a, a², a·l, l, l²` is rank-deficient by two, and with true `γ = 2·10⁻⁴` and `h = 10⁻⁴` the fit assuming `h = 0` returned `γ̂ = 0`.
3. **The decision-relevant order effect inherits this dependence.** The order-dependent part of a plan's time is `Σ γ_c·u·l` over its laps (`u = a −` reference age). Writing `γ_c = θ_c + 2h`, with `θ_c` identified, adds `2h·Σ u·l`, which differs between stint orders. For a 60-lap HARD 33 / MEDIUM 27 one-stop, reversing the order changes `Σ u·l` by 2,673. An assumed trend curvature of `h = 10⁻⁴` s/lap² therefore shifts the inferred order delta by about 0.53 s. That curvature changes the trend's slope by only about 0.012 s/lap over the race, about one step of the common-trend grid. In the M1 synthetic demonstration, the best one-stop and two-stop plans differed by 0.06 s.

So an order effect estimated from data would be driven largely by an unidentified assumption about track-evolution curvature, just as degradation is driven by the assumed linear trend. Track evolution is the component most plausibly non-linear (rubbering-in early in the race). A credible interaction model would need its own curvature scenario dimension, adding to the common-trend grid.

## Confounding beyond identifiability

Even with `h` fixed, the variation that identifies `γ_c` (the same compound used at different race phases) is not as-if random:

- **Endogenous stint ends.** Non-final stints end when a team chooses to pit, often as the tyre degrades; final stints end at the flag. Censoring therefore differs systematically between early and late race phase.
- **Compound-phase selection.** Which compound is run in which phase, and for how long, is a team decision correlated with expected degradation and car characteristics. The cells (compound × tyre age × phase) are unbalanced, and some cells will be empty.
- **Phase-dependent driving.** Fuel saving, tyre management on planned long stints and pushing at the end vary with race phase and remaining stint length. This mimics an interaction (compare the tyre-management variant in [`identifiability.md`](identifiability.md)).
- **Traffic and dirty air.** These are concentrated early in the race and raise tyre temperatures. Traffic is out of MVP scope and not filtered.
- **Track temperature.** It changes during the race, is collinear with race phase, and is not used except as a forecastable input.
- **Neutralisations.** SC/VSC laps add tyre age with little wear; flagged stints cluster around incidents.
- **Car heterogeneity.** Driver-race intercepts absorb pace level but not team-specific degradation rates. If teams with different degradation choose different phase patterns, the pooled interaction is biased.

## Data requirements

- **Overlap.** For each compound, stints covering the same tyre-age range at clearly different race phases (a wide spread of `m_s`). This is checked with a phase-extended support profile (compound × age band × phase band, with stint and race thresholds as in [Data support](evaluation.md#data-support)) on 2023–2024 before any model is fitted.
- **Precision (illustrative; the noise level is an assumption to be replaced by the M3 coverage results).** Assume a clean-lap residual standard deviation of 0.4 s. The within-stint slope of a 15-lap stint then has a standard error of about 0.024 s/lap. Regressing slopes on `m_s` with a spread of about 15 laps gives a standard error for `γ` of about `0.024 / (15·√K)` for K stints. That is about 1.1·10⁻⁴ for K = 200 stints per compound, comparable to the curvature ambiguity above. Clustering by race and serial correlation of residuals increase this. Estimates are feasible only pooled over circuits, not per circuit.
- **No 2025 data.** Any such experiment is model selection and uses 2023–2024 only.

## Assessment

The interaction is plausible physically. But the order effect is not identified separately from the common-trend curvature, `β_c` is not identified without the fragile structural assumption, and the identifying variation is confounded by strategy choice, censoring and driving behaviour. An experiment would therefore at best show whether an interaction *improves within-stint prediction* conditional on stated trend assumptions; it could not establish that a particular stint order is faster.

Implementation is not proposed now. If it is reconsidered after M3, the experiment should be pre-declared before fitting:

1. Phase-extended coverage on 2023–2024. Stop if the overlap thresholds are not met for the relevant compounds.
2. Synthetic check (E1): false-positive rate of `θ_c`/`γ_c` estimates under generators with a non-linear trend, with tyre management and with phase-dependent censoring, and no true interaction.
3. Walk-forward comparison on 2024 targets of age-only against age × phase degradation, evaluated on held-out within-stint profiles. Results are reported under a range of assumed trend curvatures `h`, including `h = 0`.
4. Adopt only if the improvement exceeds the split-half noise floor under every declared curvature scenario and the implied order deltas exceed parameter uncertainty. Otherwise the baseline stays, and stint-order invariance remains a documented limitation.

## Status after the M0 revision

The analysis above assumes free stint intercepts. Under the shared driver-race intercept now adopted (B2), compound-relative phase terms are partly identified from variation in when each compound is run; that variation is chosen by teams and therefore confounded. Steps 1–2 move to M4 and steps 3–4 to the M6 ablation, with thresholds fixed in `modelling_plan.md`. Order effects from phase-aware models are reported as model-implied ([`evaluation.md`](evaluation.md#model-equivalent-plans)).
